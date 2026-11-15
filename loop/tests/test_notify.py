"""loop/notify.py: the Telegram send command that run.sh calls (lpe-de2).

run.sh calls notify.py around each session: snapshot before it, report after
it, and send for the timeout, failure and stop messages. These tests give it a
fake bd (a script on PATH that prints a JSON file) and a fake Telegram
endpoint: a local HTTP server that records each request and answers with the
replies that a test queues.
"""

import importlib.util
import json
import os
import subprocess
import sys
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NOTIFY = ROOT / "notify.py"

_spec = importlib.util.spec_from_file_location("loop_notify", NOTIFY)
notify = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(notify)

TOKEN = "123456:SECRET-token-value"
CHAT = "4242"
HUMAN = "Rob Bastian"
NOW = datetime(2026, 11, 14, 12, 0, tzinfo=UTC).timestamp()
REPLY_LINE = (
    "Reply to this message to answer. Start with Ralph: or Alice: to choose the agent."
)


class FakeTelegram:
    """A local Bot API endpoint. Each reply is (HTTP status, JSON body)."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, dict]] = []
        self.replies: list[tuple[int, dict]] = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length) or b"{}")
                fake.requests.append((self.path, body))
                status, reply = (
                    fake.replies.pop(0)
                    if fake.replies
                    else (200, {"ok": True, "result": {"username": "loop_bot"}})
                )
                data = json.dumps(reply).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(
            target=self.server.serve_forever, args=(0.05,), daemon=True
        ).start()

    def messages(self) -> list[dict]:
        return [body for path, body in self.requests if path.endswith("/sendMessage")]

    def texts(self) -> list[str]:
        return [body["text"] for body in self.messages()]

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def telegram():
    fake = FakeTelegram()
    yield fake
    fake.close()


def error(status: int, retry_after: int | None = None) -> tuple[int, dict]:
    body = {"ok": False, "error_code": status, "description": f"Error {status}"}
    if retry_after is not None:
        body["parameters"] = {"retry_after": retry_after}
    return status, body


def sent_ok(message_id: int) -> tuple[int, dict]:
    return 200, {"ok": True, "result": {"message_id": message_id, "chat": {"id": 4242}}}


def bead(
    bead_id, state=None, *, assignee="Ralph", round_=None, title="Do a thing", notes=""
):
    labels = []
    if state:
        labels.append(f"loop:{state}")
    if round_ is not None:
        labels.append(f"round:{round_}")
    return {
        "id": bead_id,
        "title": title,
        "labels": labels,
        "notes": notes,
        "assignee": assignee,
    }


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    """A temporary HOME, so that decision messages record into it."""
    path = tmp_path / "home"
    path.mkdir()
    monkeypatch.setenv("HOME", str(path))
    return path


def sent_lines(home: Path) -> list[dict]:
    path = home / ".local/state/loop-telegram/sent.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines()]


PROJECT = notify.Project(
    name="demo",
    primary="/p/demo",
    prefix="lpe",
    human=HUMAN,
    agents=["Ralph", "Alice"],
)


def changes(before: list[dict], after: list[dict], agent: str = "Ralph") -> list:
    """The messages that report sends when the beads go from BEFORE to AFTER."""
    snapshot = notify.snapshot_of(before, PROJECT.prefix)
    return notify.report_messages(PROJECT, snapshot, after, agent)


def texts_of(outgoing) -> list[str]:
    return [message["text"] for message, _ in outgoing]


# Unit level: the messages that report builds.


def test_the_snapshot_keeps_state_round_and_assignee_of_our_beads():
    beads = [
        bead("lpe-a1", "review", round_=2, assignee="Alice"),
        bead("lpe-a2", assignee=""),
        bead("other-x1", "coding"),
    ]
    assert notify.snapshot_of(beads, "lpe") == {
        "lpe-a1": {"loop": "review", "round": "2", "assignee": "Alice"},
        "lpe-a2": {"loop": None, "round": None, "assignee": ""},
    }


@pytest.mark.parametrize(
    ("state", "word"),
    [
        ("escalated", "escalated"),
        ("parked", "parked"),
        ("blocked", "blocked"),
        ("merge", "ready to merge"),
        ("coding", "coding"),
        ("review", "review"),
        ("returned", "returned"),
        ("done", "done"),
    ],
)
def test_each_listed_state_change_sends_one_message(state, word):
    out = changes(
        [bead("lpe-b1", "rebase", title="Add a flag")],
        [bead("lpe-b1", state, title="Add a flag", round_=2, assignee=HUMAN)],
    )
    texts = texts_of(out)
    assert len(texts) == 1
    assert texts[0].startswith("demo: lpe-b1")
    assert "Add a flag" in texts[0]
    assert word in texts[0]


@pytest.mark.parametrize("state", ["accept", "rebase", "rebased", None])
def test_unlisted_states_send_nothing(state):
    assert changes([bead("lpe-c1", "coding")], [bead("lpe-c1", state)]) == []


def test_an_unchanged_bead_sends_nothing():
    assert changes([bead("lpe-c2", "coding")], [bead("lpe-c2", "coding")]) == []


def test_a_bead_of_another_agent_sends_nothing():
    """Alice's change during Ralph's session is Alice's to report."""
    before = [bead("lpe-c3", "review", assignee="Alice")]
    after = [bead("lpe-c3", "merge", assignee=HUMAN)]
    assert changes(before, after, agent="Ralph") == []
    assert len(changes(before, after, agent="Alice")) == 1


def test_a_bead_that_is_not_in_the_snapshot_sends_nothing():
    assert changes([], [bead("lpe-c4", "coding")]) == []


def test_beads_of_another_prefix_are_ignored():
    assert changes([bead("other-x1", "coding")], [bead("other-x1", "escalated")]) == []


def test_messages_go_out_in_bead_id_order():
    before = [bead("lpe-z9", "coding"), bead("lpe-a1", "coding")]
    after = [bead("lpe-z9", "review"), bead("lpe-a1", "review")]
    texts = texts_of(changes(before, after))
    assert [t.split()[1] for t in texts] == ["lpe-a1", "lpe-z9"]


def test_progress_gives_the_round():
    out = changes(
        [bead("lpe-e1", "coding", round_=1)], [bead("lpe-e1", "review", round_=2)]
    )
    assert "(round 2)" in texts_of(out)[0]


def test_done_and_round_zero_give_no_round():
    out = changes(
        [bead("lpe-e2", "merge", round_=1), bead("lpe-e3", "returned", round_=0)],
        [bead("lpe-e2", "done", round_=1), bead("lpe-e3", "coding", round_=0)],
    )
    assert all("round" not in text for text in texts_of(out))


def test_escalation_gives_the_last_note_and_skips_session_cost():
    notes = (
        "Branch created: feat/x\nReview round 3 failed: tests do not run\n"
        "Session cost: $1.20, 10 turns"
    )
    out = changes([bead("lpe-f1", "review")], [bead("lpe-f1", "blocked", notes=notes)])
    text = texts_of(out)[0]
    assert "Last note: Review round 3 failed: tests do not run" in text
    assert "Session cost" not in text
    assert "Branch created" not in text


def test_merge_gives_the_pr_url():
    notes = (
        "PR opened: #49 https://github.com/o/r/pull/49\n"
        "Review passed, PR #49 awaiting merge approval"
    )
    out = changes([bead("lpe-g1", "review")], [bead("lpe-g1", "merge", notes=notes)])
    assert "https://github.com/o/r/pull/49" in texts_of(out)[0]


@pytest.mark.parametrize("state", ["coding", "review", "returned", "done"])
def test_progress_is_silent(state):
    ((message, _),) = changes([bead("lpe-h1", "parked")], [bead("lpe-h1", state)])
    assert message["disable_notification"] is True


@pytest.mark.parametrize("state", ["escalated", "parked", "blocked", "merge"])
def test_escalation_and_merge_make_a_sound(state):
    ((message, _),) = changes([bead("lpe-i1", "review")], [bead("lpe-i1", state)])
    assert "disable_notification" not in message


@pytest.mark.parametrize("state", ["escalated", "parked"])
def test_a_decision_message_asks_for_a_reply(state):
    ((message, record),) = changes(
        [bead("lpe-u1", "review")],
        [bead("lpe-u1", state, title="Pick one", notes="Which way?", assignee=HUMAN)],
    )
    lines = message["text"].splitlines()
    assert lines[0] == f"demo: lpe-u1 {state}"
    assert "Pick one" in lines
    assert "Last note: Which way?" in lines
    assert lines[-1] == REPLY_LINE
    assert message["reply_markup"] == {
        "force_reply": True,
        "input_field_placeholder": "Your decision",
    }
    assert record == {"bead": "lpe-u1", "state": state}


@pytest.mark.parametrize("state", ["blocked", "merge", "coding"])
def test_other_messages_ask_for_no_reply(state):
    ((message, record),) = changes([bead("lpe-u2", "review")], [bead("lpe-u2", state)])
    assert "reply_markup" not in message
    assert "Reply to this message" not in message["text"]
    assert record is None


@pytest.mark.parametrize("state", ["escalated", "parked"])
def test_a_re_escalation_with_the_same_state_sends_a_decision_message(state):
    """The reviewer escalates again after a decision: the state stays the same."""
    out = changes(
        [bead("lpe-r1", state, assignee="Alice")],
        [bead("lpe-r1", state, assignee=HUMAN, notes="Still stuck")],
        agent="Alice",
    )
    assert len(out) == 1
    message, record = out[0]
    assert message["text"].splitlines()[-1] == REPLY_LINE
    assert record == {"bead": "lpe-r1", "state": state}


def test_an_unchanged_decision_state_that_stays_with_the_agent_sends_nothing():
    out = changes(
        [bead("lpe-r2", "escalated", assignee="Alice")],
        [bead("lpe-r2", "escalated", assignee="Alice")],
        agent="Alice",
    )
    assert out == []


def test_a_bead_that_waits_for_the_human_already_sends_nothing():
    out = changes(
        [bead("lpe-r3", "escalated", assignee=HUMAN)],
        [bead("lpe-r3", "escalated", assignee=HUMAN)],
        agent="Alice",
    )
    assert out == []


def test_a_new_escalation_sends_one_message_only():
    out = changes(
        [bead("lpe-r4", "review", assignee="Alice")],
        [bead("lpe-r4", "escalated", assignee=HUMAN)],
        agent="Alice",
    )
    assert len(out) == 1


def test_a_long_message_is_truncated():
    text = notify.truncate("x" * 5000)
    assert len(text) <= 4000
    assert text.endswith("...")
    assert notify.truncate("short") == "short"


def test_a_long_escalation_goes_out_truncated():
    out = changes(
        [bead("lpe-r5", "review")], [bead("lpe-r5", "blocked", notes="y" * 5000)]
    )
    text = texts_of(out)[0]
    assert len(text) <= 4000
    assert text.endswith("...")


def test_a_long_decision_message_keeps_the_reply_line():
    out = changes(
        [bead("lpe-w4", "review")],
        [bead("lpe-w4", "parked", notes="z" * 5000, assignee=HUMAN)],
    )
    text = texts_of(out)[0]
    assert len(text) <= 4000
    assert text.endswith("to choose the agent.")
    assert "..." in text


def test_a_send_message_has_the_project_first_and_a_sound():
    message = notify.plain_message(PROJECT, "Ralph loop stopped (exit 130)")
    assert message == {"text": "demo: Ralph loop stopped (exit 130)"}
    silent = notify.plain_message(PROJECT, "x" * 5000, silent=True)
    assert silent["disable_notification"] is True
    assert len(silent["text"]) <= 4000


# Delivery: up to 3 tries, then drop.


@pytest.fixture
def logs():
    return []


def deliver(telegram, logs, message, record=None, sleeps=None):
    bot = notify.Telegram(TOKEN, CHAT, base=telegram.url, log=lambda _: None)
    return notify.deliver(
        bot,
        PROJECT,
        message,
        record,
        sleep=(sleeps if sleeps is not None else []).append,
        log=logs.append,
        now=lambda: NOW,
    )


def test_a_send_that_works_sends_once(telegram, logs):
    sleeps = []
    assert deliver(telegram, logs, {"text": "demo: hi"}, sleeps=sleeps) is True
    assert telegram.texts() == ["demo: hi"]
    assert sleeps == []
    assert logs == []


def test_a_failed_send_is_tried_three_times_then_dropped(telegram, logs):
    telegram.replies = [error(500), error(502), error(500)]
    sleeps = []
    assert deliver(telegram, logs, {"text": "demo: hi"}, sleeps=sleeps) is False
    assert len(telegram.messages()) == 3
    assert sleeps == [5, 5]
    assert len(logs) == 1
    assert "3 tries" in logs[0]
    assert "500" in logs[0]


def test_a_send_that_works_on_the_second_try_logs_nothing(telegram, logs):
    telegram.replies = [error(500), sent_ok(1)]
    sleeps = []
    assert deliver(telegram, logs, {"text": "demo: hi"}, sleeps=sleeps) is True
    assert len(telegram.messages()) == 2
    assert sleeps == [5]
    assert logs == []


def test_retry_after_sets_the_wait(telegram, logs):
    telegram.replies = [error(429, retry_after=30), sent_ok(1)]
    sleeps = []
    assert deliver(telegram, logs, {"text": "demo: hi"}, sleeps=sleeps) is True
    assert sleeps == [30]


def test_retry_after_waits_60_seconds_at_most(telegram, logs):
    telegram.replies = [error(429, retry_after=600)] * 3
    sleeps = []
    assert deliver(telegram, logs, {"text": "demo: hi"}, sleeps=sleeps) is False
    assert sleeps == [60, 60]
    assert len(logs) == 1


def test_a_sent_decision_message_is_recorded(telegram, logs, home):
    telegram.replies = [sent_ok(77)]
    deliver(
        telegram, logs, {"text": "demo: x"}, {"bead": "lpe-v1", "state": "escalated"}
    )
    assert sent_lines(home) == [
        {
            "message_id": 77,
            "chat_id": 4242,
            "project": "demo",
            "primary": "/p/demo",
            "bead": "lpe-v1",
            "state": "escalated",
            "sent_at": "2026-11-14T12:00:00+00:00",
        }
    ]
    mode = (home / ".local/state/loop-telegram/sent.jsonl").stat().st_mode
    assert mode & 0o077 == 0


def test_a_dropped_decision_message_is_not_recorded(telegram, logs, home):
    telegram.replies = [error(500)] * 3
    deliver(telegram, logs, {"text": "demo: x"}, {"bead": "lpe-v2", "state": "parked"})
    assert sent_lines(home) == []


def test_a_decision_message_that_works_on_a_retry_is_recorded_once(
    telegram, logs, home
):
    telegram.replies = [error(500), sent_ok(9)]
    deliver(telegram, logs, {"text": "demo: x"}, {"bead": "lpe-v3", "state": "parked"})
    assert [(line["message_id"], line["bead"]) for line in sent_lines(home)] == [
        (9, "lpe-v3")
    ]


def test_a_failed_record_logs_one_line(telegram, logs, home):
    (home / ".local").write_text("not a folder")
    telegram.replies = [sent_ok(3)]
    assert deliver(
        telegram, logs, {"text": "demo: x"}, {"bead": "lpe-w3", "state": "escalated"}
    )
    assert len(telegram.messages()) == 1
    assert any("sent.jsonl" in line for line in logs)


def test_requests_use_no_parse_mode(telegram, logs):
    deliver(telegram, logs, {"text": "demo: *bold* <b>x</b> _y_"})
    message = telegram.messages()[0]
    assert "parse_mode" not in message
    assert message["chat_id"] == CHAT
    assert message["text"] == "demo: *bold* <b>x</b> _y_"


# Token safety at the Telegram level.


def test_http_errors_log_no_token(telegram, logs, capsys):
    telegram.replies = [
        (401, {"ok": False, "error_code": 401, "description": "Unauthorized"}),
        (404, {"ok": False, "error_code": 404, "description": "Not Found"}),
    ]
    bot = notify.Telegram(TOKEN, CHAT, base=telegram.url, log=logs.append)
    assert bot.check() is False
    assert bot.send({"text": "hi"}).ok is False
    out = capsys.readouterr()
    text = "\n".join(logs) + out.out + out.err
    assert "getMe" in text and "401" in text and "Unauthorized" in text
    assert "sendMessage" in text and "404" in text and "Not Found" in text
    assert TOKEN not in text
    assert "SECRET" not in text


def test_a_body_that_is_not_json_logs_no_token(logs, capsys):
    class Plain(BaseHTTPRequestHandler):
        def do_POST(self):
            self.send_response(502)
            self.end_headers()
            self.wfile.write(f"bad gateway for /bot{TOKEN}/x".encode())

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Plain)
    threading.Thread(target=server.serve_forever, args=(0.05,), daemon=True).start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}"
        bot = notify.Telegram(TOKEN, CHAT, base=url, log=logs.append)
        assert bot.send({"text": "hi"}).ok is False
    finally:
        server.shutdown()
        server.server_close()
    out = capsys.readouterr()
    text = "\n".join(logs) + out.out + out.err
    assert "502" in text
    assert TOKEN not in text


def test_network_errors_log_no_token(logs, capsys):
    bot = notify.Telegram(TOKEN, CHAT, base="http://127.0.0.1:9", log=logs.append)
    assert bot.check() is False
    assert bot.send({"text": "hi"}).ok is False
    out = capsys.readouterr()
    text = "\n".join(logs) + out.out + out.err
    assert "getMe" in text and "sendMessage" in text
    assert TOKEN not in text
    assert "SECRET" not in text
    assert "127.0.0.1" not in text


# The command line: run main in process, with a fake bd on PATH.


@pytest.fixture
def project_dir(tmp_path):
    path = tmp_path / "demo"
    (path / ".loop").mkdir(parents=True)
    (path / ".loop/project.md").write_text(
        "# Project\n\n```bash\nCODER=Ralph\nREVIEWER=Alice\n"
        f"HUMAN={HUMAN}\nBEAD_PREFIX=lpe\n```\n"
    )
    return path


class FakeBd:
    """A bd script on PATH that prints the beads in a JSON file."""

    def __init__(self, tmp_path: Path) -> None:
        self.bin = tmp_path / "bin"
        self.bin.mkdir()
        self.data = tmp_path / "beads.json"
        self.args = tmp_path / "bd-args"
        script = self.bin / "bd"
        script.write_text(
            "#!/bin/sh\n"
            f'printf "%s " "$@" >>"{self.args}"\necho >>"{self.args}"\n'
            f'if [ -f "{tmp_path}/bd-fails" ]; then echo "database is locked" >&2; exit 1; fi\n'
            f'cat "{self.data}"\n'
        )
        script.chmod(0o755)
        self.set()

    def set(self, *beads: dict) -> None:
        self.data.write_text(json.dumps(list(beads)))


@pytest.fixture
def fake_bd(tmp_path, monkeypatch):
    bd = FakeBd(tmp_path)
    monkeypatch.setenv("PATH", f"{bd.bin}:{os.environ['PATH']}")
    return bd


@pytest.fixture
def env_on(telegram, monkeypatch):
    for name in list(os.environ):
        if name.startswith("TELEGRAM_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", CHAT)
    monkeypatch.setenv("TELEGRAM_API_URL", telegram.url)
    monkeypatch.setattr(notify.time, "sleep", lambda _: None)


def run_main(project_dir: Path, *args: str) -> int:
    return notify.main(["--project", str(project_dir), *args])


def test_snapshot_writes_the_states_of_our_beads(
    tmp_path, project_dir, fake_bd, env_on, telegram, capsys
):
    fake_bd.set(
        bead("lpe-a1", "review", round_=1, assignee="Alice"), bead("x-1", "coding")
    )
    snap = tmp_path / "snap.json"
    assert run_main(project_dir, "snapshot", str(snap)) == 0
    assert json.loads(snap.read_text()) == {
        "lpe-a1": {"loop": "review", "round": "1", "assignee": "Alice"}
    }
    args = fake_bd.args.read_text().split()
    assert args[:2] == ["list", "--json"]
    assert "--all" in args
    assert args[args.index("--limit") + 1] == "0"
    assert telegram.requests == []
    assert capsys.readouterr().out == ""


def test_report_sends_the_changes_of_the_session(
    tmp_path, project_dir, fake_bd, env_on, telegram
):
    fake_bd.set(
        bead("lpe-a1", "coding", round_=1),
        bead("lpe-a2", "review", assignee="Alice"),
        bead("lpe-a3", "coding"),
    )
    snap = tmp_path / "snap.json"
    run_main(project_dir, "snapshot", str(snap))
    fake_bd.set(
        bead("lpe-a1", "review", round_=1, assignee="Alice"),
        bead("lpe-a2", "merge", assignee=HUMAN),
        bead("lpe-a3", "coding"),
    )
    assert run_main(project_dir, "report", str(snap), "--agent", "Ralph") == 0
    assert telegram.texts() == ["demo: lpe-a1 review (round 1)\nDo a thing"]


def test_report_without_a_snapshot_logs_one_line_and_exits_0(
    tmp_path, project_dir, fake_bd, env_on, telegram, capsys
):
    assert (
        run_main(project_dir, "report", str(tmp_path / "none"), "--agent", "Ralph") == 0
    )
    assert len(capsys.readouterr().out.strip().splitlines()) == 1
    assert telegram.messages() == []


def test_a_failed_bd_call_logs_and_exits_0(
    tmp_path, project_dir, fake_bd, env_on, telegram, capsys
):
    snap = tmp_path / "snap.json"
    snap.write_text("{}")
    (tmp_path / "bd-fails").write_text("")
    assert run_main(project_dir, "snapshot", str(tmp_path / "s2.json")) == 0
    assert run_main(project_dir, "report", str(snap), "--agent", "Ralph") == 0
    out = capsys.readouterr().out
    assert "bd list failed" in out
    assert telegram.messages() == []


def test_send_sends_one_message(project_dir, env_on, telegram):
    assert run_main(project_dir, "send", "Ralph loop stopped (exit 130)") == 0
    assert telegram.messages() == [
        {"chat_id": CHAT, "text": "demo: Ralph loop stopped (exit 130)"}
    ]


def test_send_silent_sends_no_sound(project_dir, env_on, telegram):
    assert run_main(project_dir, "send", "--silent", "quiet") == 0
    assert telegram.messages()[0]["disable_notification"] is True


def test_send_drops_after_three_tries_logs_one_line_and_exits_0(
    project_dir, env_on, telegram, capsys
):
    telegram.replies = [error(500)] * 3
    assert run_main(project_dir, "send", "hi") == 0
    assert len(telegram.messages()) == 3
    out = capsys.readouterr()
    assert len(out.out.strip().splitlines()) == 1
    assert out.err == ""


def test_check_exits_0_when_get_me_works(project_dir, env_on, telegram, capsys):
    assert run_main(project_dir, "check") == 0
    assert telegram.requests[0][0] == f"/bot{TOKEN}/getMe"
    assert capsys.readouterr().out == ""


def test_check_exits_1_when_get_me_fails(project_dir, env_on, telegram, capsys):
    telegram.replies = [error(401)]
    assert run_main(project_dir, "check") == 1
    out = capsys.readouterr()
    assert TOKEN not in out.out + out.err


def test_main_logs_no_token_when_telegram_is_down(
    tmp_path, project_dir, fake_bd, env_on, monkeypatch, capsys
):
    monkeypatch.setenv("TELEGRAM_API_URL", "http://127.0.0.1:9")
    snap = tmp_path / "snap.json"
    fake_bd.set(bead("lpe-n1", "review"))
    run_main(project_dir, "snapshot", str(snap))
    fake_bd.set(bead("lpe-n1", "escalated", assignee=HUMAN))
    assert run_main(project_dir, "report", str(snap), "--agent", "Ralph") == 0
    assert run_main(project_dir, "send", "hi") == 0
    assert run_main(project_dir, "check") == 1
    out = capsys.readouterr()
    text = out.out + out.err
    assert "3 tries" in text
    assert TOKEN not in text
    assert "SECRET" not in text
    assert "127.0.0.1" not in text


def test_main_logs_no_token_on_http_errors(
    tmp_path, project_dir, fake_bd, env_on, telegram, capsys
):
    telegram.replies = [error(401)] * 3
    assert run_main(project_dir, "send", "hi") == 0
    out = capsys.readouterr()
    text = out.out + out.err
    assert "401" in text
    assert TOKEN not in text
    assert "SECRET" not in text


def test_the_project_comes_from_the_overlay(project_dir):
    project = notify.load_project(project_dir)
    assert project == notify.Project(
        name="demo",
        primary=str(project_dir),
        prefix="lpe",
        human=HUMAN,
        agents=["Ralph", "Alice"],
    )


def test_the_overlay_ignores_placeholders_and_later_lines(tmp_path):
    overlay = tmp_path / "project.md"
    overlay.write_text(
        "# Project\n\n```bash\nCODER=Bob\nREVIEWER=Carol\nCODER=Dan\n"
        "BEAD_PREFIX={{BEAD_PREFIX}}\n```\n"
    )
    assert notify.read_overlay(overlay) == {"CODER": "Bob", "REVIEWER": "Carol"}
    assert notify.read_overlay(tmp_path / "missing.md") == {}


def test_the_default_project_is_the_parent_of_the_harness_folder():
    assert notify.default_project() == NOTIFY.parent.parent


# The command line as a process: usage and the off switch.


def clean_env(home: Path, **extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("TELEGRAM_")}
    env.update({"HOME": str(home), **extra})
    return env


def run_notify(args: list[str], env: dict[str, str], cwd: Path):
    return subprocess.run(
        [sys.executable, str(NOTIFY), *args],
        check=False,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_no_subcommand_prints_usage_and_exits_2(tmp_path, home):
    result = run_notify([], clean_env(home), tmp_path)
    assert result.returncode == 2
    assert "usage" in (result.stdout + result.stderr).lower()


def test_the_notifier_has_no_poll_loop():
    text = NOTIFY.read_text()
    assert "class Notifier" not in text
    assert "--interval" not in text
    assert "--polls" not in text


@pytest.mark.parametrize("missing", ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"])
@pytest.mark.parametrize(
    ("args", "code"),
    [
        (["snapshot", "snap.json"], 0),
        (["report", "snap.json", "--agent", "Ralph"], 0),
        (["send", "hi"], 0),
        (["send", "--silent", "hi"], 0),
        (["check"], 1),
    ],
)
def test_a_missing_variable_turns_every_subcommand_off(
    tmp_path, home, project_dir, missing, args, code
):
    env = clean_env(
        home,
        TELEGRAM_BOT_TOKEN=TOKEN,
        TELEGRAM_CHAT_ID=CHAT,
        TELEGRAM_API_URL="http://127.0.0.1:9",
    )
    del env[missing]
    (tmp_path / "snap.json").write_text("{}")
    result = run_notify(["--project", str(project_dir), *args], env, tmp_path)
    assert result.returncode == code
    assert result.stdout == ""
    assert result.stderr == ""
    assert json.loads((tmp_path / "snap.json").read_text()) == {}


# lpe-qqv 7. Without agent names, the decision message names no agent.


def test_a_decision_message_without_agent_names_leaves_out_start_with():
    project = notify.Project(name="demo", primary="/p/demo", prefix="lpe", human=HUMAN)
    message = notify.decision_message(project, "lpe-u9 escalated")
    assert message["text"] == "demo: lpe-u9 escalated\nReply to this message to answer."
    assert "Start with" not in message["text"]


def test_the_project_without_agent_names_has_no_agents(tmp_path):
    (tmp_path / ".loop").mkdir()
    (tmp_path / ".loop/project.md").write_text(f"HUMAN={HUMAN}\nCODER=\n")
    assert notify.load_project(tmp_path).agents == []


# lpe-qqv 8. A bad bd record is skipped with one log line.

BAD_RECORDS = [
    ({"title": "no id", "labels": ["loop:review"]}, "without an id"),
    ({"id": "", "labels": []}, "without an id"),
    ({"id": 7, "labels": []}, "without an id"),
    ("lpe-not-a-dict", "without an id"),
    ({"id": "lpe-bad1", "labels": "loop:review"}, "lpe-bad1: malformed labels"),
    ({"id": "lpe-bad2", "labels": [1, "loop:review"]}, "lpe-bad2: malformed labels"),
]


@pytest.mark.parametrize(("bad", "said"), BAD_RECORDS)
def test_a_bad_record_is_skipped_by_the_snapshot_with_one_log_line(bad, said, capsys):
    good = bead("lpe-ok1", "review", assignee="Alice")
    assert notify.snapshot_of([bad, good], "lpe") == {
        "lpe-ok1": {"loop": "review", "round": None, "assignee": "Alice"}
    }
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 1
    assert said in lines[0]


@pytest.mark.parametrize(("bad", "said"), BAD_RECORDS)
def test_a_bad_record_is_skipped_by_the_report_with_one_log_line(bad, said, capsys):
    snapshot = {"lpe-ok1": {"loop": "coding", "round": None, "assignee": "Ralph"}}
    if isinstance(bad, dict) and isinstance(bad.get("id"), str) and bad["id"]:
        snapshot[bad["id"]] = {"loop": "coding", "round": None, "assignee": "Ralph"}
    after = [bad, bead("lpe-ok1", "review", assignee="Alice")]
    out = notify.report_messages(PROJECT, snapshot, after, "Ralph")
    assert texts_of(out) == ["demo: lpe-ok1 review\nDo a thing"]
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 1
    assert said in lines[0]


def test_a_bad_record_does_not_end_the_report_command(
    tmp_path, project_dir, fake_bd, env_on, telegram, capsys
):
    fake_bd.set({"title": "no id"}, bead("lpe-a1", "coding", round_=1))
    snap = tmp_path / "snap.json"
    assert run_main(project_dir, "snapshot", str(snap)) == 0
    fake_bd.set(
        {"id": "lpe-x9", "labels": "oops"},
        bead("lpe-a1", "review", round_=1, assignee="Alice"),
    )
    assert run_main(project_dir, "report", str(snap), "--agent", "Ralph") == 0
    assert telegram.texts() == ["demo: lpe-a1 review (round 1)\nDo a thing"]
    out = capsys.readouterr().out
    assert "without an id" in out
    assert "lpe-x9: malformed labels" in out
