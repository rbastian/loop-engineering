"""loop/notify.py: Telegram messages to the human about the loop (lpe-2gm).

The notifier polls bd and sends one message per loop state change. These tests
give it a fake bd (a list of bead records, or a bd script on PATH) and a fake
Telegram endpoint: a local HTTP server that records each request and answers
with the replies that a test queues.
"""

import importlib.util
import json
import os
import subprocess
import sys
import threading
from collections import deque
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
START = datetime(2026, 11, 14, 12, 0, tzinfo=UTC).timestamp()
HOUR = 3600


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


def bead(bead_id, state=None, *, round_=None, title="Do a thing", notes="", age=0):
    labels = []
    if state:
        labels.append(f"loop:{state}")
    if round_ is not None:
        labels.append(f"round:{round_}")
    updated = datetime.fromtimestamp(START - age, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "id": bead_id,
        "title": title,
        "labels": labels,
        "notes": notes,
        "updated_at": updated,
    }


class Harness:
    """A notifier wired to a fake bd, a fake clock and a fake process list."""

    def __init__(self, telegram: FakeTelegram, beads: list[dict], logs: list[str]):
        self.beads = beads
        self.clock = START
        self.running = {"Ralph": True, "Alice": True}
        self.bot = notify.Telegram(TOKEN, CHAT, base=telegram.url, log=logs.append)
        self.notifier = notify.Notifier(
            project="demo",
            primary="/p/demo",
            prefix="lpe",
            agents=["Ralph", "Alice"],
            telegram=self.bot,
            list_beads=lambda: list(self.beads),
            running_agents=lambda: {a for a, up in self.running.items() if up},
            now=lambda: self.clock,
            stall_seconds=2 * HOUR,
            log=logs.append,
        )

    def set(self, *new: dict) -> None:
        self.beads[:] = list(new)


@pytest.fixture
def logs():
    return []


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


@pytest.fixture
def make(telegram, logs):
    def build(*beads):
        harness = Harness(telegram, list(beads), logs)
        harness.notifier.start()
        return harness

    return build


# 1. Notifications are off without a token or a chat ID.


@pytest.mark.parametrize("missing", ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"])
def test_missing_variable_turns_notifications_off(tmp_path, missing):
    env = {k: v for k, v in os.environ.items() if not k.startswith("TELEGRAM_")}
    env.update({"TELEGRAM_BOT_TOKEN": TOKEN, "TELEGRAM_CHAT_ID": CHAT})
    del env[missing]
    result = subprocess.run(
        [sys.executable, str(NOTIFY)],
        check=False,
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    out = result.stdout + result.stderr
    assert "notifications are off" in out
    assert len(out.strip().splitlines()) == 1
    assert TOKEN not in out


# 2. One message per state change, none for the states seen at start.


def test_states_seen_at_start_send_nothing(make, telegram):
    harness = make(
        bead("lpe-a1", "escalated", notes="Why"),
        bead("lpe-a2", "merge"),
        bead("lpe-a3", "coding", age=5 * HOUR),
        bead("lpe-a4", "blocked"),
    )
    harness.notifier.poll()
    assert telegram.messages() == []


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
def test_each_listed_state_change_sends_one_message(make, telegram, state, word):
    harness = make(bead("lpe-b1", "rebase", title="Add a flag"))
    harness.set(bead("lpe-b1", state, title="Add a flag", round_=2))
    harness.notifier.poll()
    harness.notifier.poll()

    texts = telegram.texts()
    assert len(texts) == 1
    assert texts[0].startswith("demo")
    assert "lpe-b1" in texts[0]
    assert "Add a flag" in texts[0]
    assert word in texts[0]


@pytest.mark.parametrize("state", ["accept", "rebase", "rebased"])
def test_unlisted_states_send_nothing(make, telegram, state):
    harness = make(bead("lpe-c1", "coding"))
    harness.set(bead("lpe-c1", state))
    harness.notifier.poll()
    assert telegram.messages() == []


def test_a_new_bead_that_enters_a_listed_state_sends_a_message(make, telegram):
    harness = make()
    harness.set(bead("lpe-d1", "coding"))
    harness.notifier.poll()
    assert len(telegram.messages()) == 1


def test_beads_of_another_prefix_are_ignored(make, telegram):
    harness = make(bead("other-x1", "coding"))
    harness.set(bead("other-x1", "escalated"))
    harness.notifier.poll()
    assert telegram.messages() == []


def test_progress_gives_the_round(make, telegram):
    harness = make(bead("lpe-e1", "coding", round_=1))
    harness.set(bead("lpe-e1", "review", round_=2))
    harness.notifier.poll()
    assert "round 2" in telegram.texts()[0]


def test_escalation_gives_the_last_note(make, telegram):
    harness = make(bead("lpe-f1", "review"))
    notes = "Branch created: feat/x\nReview round 3 failed: tests do not run"
    harness.set(bead("lpe-f1", "escalated", notes=notes))
    harness.notifier.poll()
    text = telegram.texts()[0]
    assert "Review round 3 failed: tests do not run" in text
    assert "Branch created" not in text


def test_merge_gives_the_pr_url(make, telegram):
    harness = make(bead("lpe-g1", "review"))
    notes = (
        "PR opened: #49 https://github.com/o/r/pull/49\n"
        "Review passed, PR #49 awaiting merge approval"
    )
    harness.set(bead("lpe-g1", "merge", notes=notes))
    harness.notifier.poll()
    assert "https://github.com/o/r/pull/49" in telegram.texts()[0]


# 3. Progress is silent. Escalation, merge and stall messages make a sound.


@pytest.mark.parametrize("state", ["coding", "review", "returned", "done"])
def test_progress_is_silent(make, telegram, state):
    harness = make(bead("lpe-h1", "parked"))
    harness.set(bead("lpe-h1", state))
    harness.notifier.poll()
    assert telegram.messages()[0]["disable_notification"] is True


@pytest.mark.parametrize("state", ["escalated", "parked", "blocked", "merge"])
def test_escalation_and_merge_make_a_sound(make, telegram, state):
    harness = make(bead("lpe-i1", "review"))
    harness.set(bead("lpe-i1", state))
    harness.notifier.poll()
    assert "disable_notification" not in telegram.messages()[0]


def test_stall_makes_a_sound(make, telegram):
    harness = make(bead("lpe-j1", "coding"))
    harness.clock += 3 * HOUR
    harness.notifier.poll()
    assert "disable_notification" not in telegram.messages()[0]


def test_a_stopped_agent_makes_a_sound(make, telegram):
    harness = make()
    harness.running["Alice"] = False
    harness.notifier.poll()
    harness.notifier.poll()
    messages = telegram.messages()
    assert len(messages) == 1
    assert "Alice" in messages[0]["text"]
    assert "not running" in messages[0]["text"]
    assert "disable_notification" not in messages[0]


def test_an_agent_that_is_down_at_start_sends_nothing(make, telegram):
    harness = Harness(telegram, [], [])
    harness.running["Ralph"] = False
    harness.notifier.start()
    harness.notifier.poll()
    assert telegram.messages() == []
    harness.running["Ralph"] = True
    harness.notifier.poll()
    harness.running["Ralph"] = False
    harness.notifier.poll()
    assert len(telegram.messages()) == 1


# 4. One stall message, no repeat until the state changes.


@pytest.mark.parametrize("state", ["coding", "review"])
def test_one_stall_message_until_the_state_changes(make, telegram, state):
    harness = make(bead("lpe-k1", state, title="Slow one"))
    harness.clock += HOUR
    harness.notifier.poll()
    assert telegram.messages() == []

    harness.clock += 1.5 * HOUR
    harness.notifier.poll()
    harness.clock += HOUR
    harness.notifier.poll()
    stalls = [t for t in telegram.texts() if "stalled" in t]
    assert len(stalls) == 1
    assert "lpe-k1" in stalls[0]

    # bd sets updated_at when the state changes.
    other = "review" if state == "coding" else "coding"
    fresh = START - harness.clock
    harness.set(bead("lpe-k1", other, title="Slow one", age=fresh))
    harness.notifier.poll()
    harness.set(bead("lpe-k1", state, title="Slow one", age=fresh))
    harness.notifier.poll()
    assert len([t for t in telegram.texts() if "stalled" in t]) == 1

    harness.clock += 3 * HOUR
    harness.notifier.poll()
    assert len([t for t in telegram.texts() if "stalled" in t]) == 2


def test_a_bead_stalled_at_start_sends_nothing(make, telegram):
    harness = make(bead("lpe-l1", "review", age=3 * HOUR))
    harness.clock += HOUR
    harness.notifier.poll()
    assert telegram.messages() == []


def test_other_states_never_stall(make, telegram):
    harness = make(bead("lpe-m1", "merge"))
    harness.clock += 10 * HOUR
    harness.notifier.poll()
    assert telegram.messages() == []


# 5. A failed send does not stop the notifier, and the message goes out later.


def test_a_failed_send_is_sent_again_on_the_next_poll(make, telegram, logs):
    harness = make(bead("lpe-n1", "review"), bead("lpe-n2", "review"))
    telegram.replies = [(500, {"ok": False, "error_code": 500, "description": "Boom"})]
    harness.set(bead("lpe-n1", "merge"), bead("lpe-n2", "escalated"))
    harness.notifier.poll()
    assert len(telegram.messages()) == 1
    assert any("sendMessage" in line and "500" in line for line in logs)

    harness.notifier.poll()
    texts = telegram.texts()
    assert len(texts) == 3
    assert "lpe-n1" in texts[1]
    assert "lpe-n2" in texts[2]


def test_a_network_error_does_not_stop_the_notifier(telegram, logs):
    harness = Harness(telegram, [bead("lpe-o1", "review")], logs)
    harness.notifier.start()
    harness.bot.base = "http://127.0.0.1:9"
    harness.set(bead("lpe-o1", "merge"))
    harness.notifier.poll()
    assert telegram.messages() == []

    harness.bot.base = telegram.url
    harness.notifier.poll()
    assert len(telegram.messages()) == 1


def test_a_failed_bd_call_does_not_stop_the_notifier(make, telegram, logs):
    harness = make(bead("lpe-p1", "coding"))

    def broken():
        raise notify.BdError("bd list failed")

    harness.notifier.list_beads = broken
    harness.notifier.poll()
    assert any("bd list failed" in line for line in logs)
    harness.notifier.list_beads = lambda: [bead("lpe-p1", "review")]
    harness.notifier.poll()
    assert len(telegram.messages()) == 1


def test_a_failed_bd_call_at_start_sends_nothing_for_old_states(telegram, logs):
    harness = Harness(telegram, [], logs)

    def broken():
        raise notify.BdError("bd list failed")

    harness.notifier.list_beads = broken
    harness.notifier.start()
    harness.notifier.list_beads = lambda: list(harness.beads)
    harness.set(bead("lpe-p2", "escalated"), bead("lpe-p3", "merge"))
    harness.notifier.poll()
    assert telegram.messages() == []

    harness.set(bead("lpe-p2", "coding"), bead("lpe-p3", "merge"))
    harness.notifier.poll()
    assert len(telegram.messages()) == 1


# 6. After a 429 with retry_after, nothing goes out until that time passes.


def test_retry_after_holds_every_send(make, telegram):
    harness = make(bead("lpe-q1", "review"))
    telegram.replies = [
        (
            429,
            {
                "ok": False,
                "error_code": 429,
                "description": "Too Many Requests: retry after 30",
                "parameters": {"retry_after": 30},
            },
        )
    ]
    harness.set(bead("lpe-q1", "merge"))
    harness.notifier.poll()
    assert len(telegram.messages()) == 1

    harness.clock += 29
    harness.set(bead("lpe-q1", "done"))
    harness.notifier.poll()
    assert len(telegram.messages()) == 1

    harness.clock += 1
    harness.notifier.poll()
    texts = telegram.texts()
    assert len(texts) == 3
    assert "ready to merge" in texts[1]
    assert "done" in texts[2]


# 7. Long messages are truncated.


def test_a_long_message_is_truncated():
    text = notify.truncate("x" * 5000)
    assert len(text) <= 4000
    assert text.endswith("...")
    assert notify.truncate("short") == "short"


def test_a_long_escalation_goes_out_truncated(make, telegram):
    harness = make(bead("lpe-r1", "review"))
    harness.set(bead("lpe-r1", "blocked", notes="y" * 5000))
    harness.notifier.poll()
    text = telegram.texts()[0]
    assert len(text) <= 4000
    assert text.endswith("...")


# 8. The token never appears in output or logs.


def test_get_me_logs_the_bot_username(telegram, logs):
    bot = notify.Telegram(TOKEN, CHAT, base=telegram.url, log=logs.append)
    bot.check()
    assert telegram.requests[0][0] == f"/bot{TOKEN}/getMe"
    assert any("loop_bot" in line for line in logs)


def test_http_errors_log_no_token(telegram, logs, capsys):
    telegram.replies = [
        (401, {"ok": False, "error_code": 401, "description": "Unauthorized"}),
        (404, {"ok": False, "error_code": 404, "description": "Not Found"}),
    ]
    bot = notify.Telegram(TOKEN, CHAT, base=telegram.url, log=logs.append)
    bot.check()
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
    bot.check()
    assert bot.send({"text": "hi"}).ok is False
    out = capsys.readouterr()
    text = "\n".join(logs) + out.out + out.err
    assert "getMe" in text and "sendMessage" in text
    assert TOKEN not in text
    assert "SECRET" not in text
    assert "127.0.0.1" not in text


def test_main_logs_no_token_when_telegram_is_down(tmp_path):
    (tmp_path / ".loop").mkdir()
    (tmp_path / ".loop/project.md").write_text(
        "CODER=Ralph\nREVIEWER=Alice\nBEAD_PREFIX=lpe\n"
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_bd = bin_dir / "bd"
    fake_bd.write_text("#!/bin/sh\necho '[]'\n")
    fake_bd.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if not k.startswith("TELEGRAM_")}
    env.update(
        {
            "TELEGRAM_BOT_TOKEN": TOKEN,
            "TELEGRAM_CHAT_ID": CHAT,
            "TELEGRAM_API_URL": "http://127.0.0.1:9",
            "PATH": f"{bin_dir}:{env['PATH']}",
        }
    )
    result = subprocess.run(
        [sys.executable, str(NOTIFY), "--polls", "1", "--interval", "0"],
        check=False,
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    out = result.stdout + result.stderr
    assert result.returncode == 0, out
    assert "getMe" in out
    assert TOKEN not in out
    assert "SECRET" not in out


# 9. No parse_mode.


def test_requests_use_no_parse_mode(make, telegram):
    harness = make(bead("lpe-s1", "review"))
    harness.set(bead("lpe-s1", "escalated", notes="*bold* <b>x</b> _y_"))
    harness.notifier.poll()
    message = telegram.messages()[0]
    assert "parse_mode" not in message
    assert message["chat_id"] == CHAT
    assert "*bold* <b>x</b> _y_" in message["text"]


# The default bd reader and the project overlay.


def test_read_beads_calls_bd_list_for_every_bead(tmp_path, monkeypatch):
    args_file = tmp_path / "args"
    fake_bd = tmp_path / "bd"
    fake_bd.write_text(
        f'#!/bin/sh\nprintf "%s " "$@" > "{args_file}"\n'
        """echo '[{"id": "lpe-t1", "labels": ["loop:done"]}]'\n"""
    )
    fake_bd.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")
    assert notify.read_beads() == [{"id": "lpe-t1", "labels": ["loop:done"]}]
    args = args_file.read_text().split()
    assert args[:2] == ["list", "--json"]
    assert "--all" in args
    assert "--limit" in args and args[args.index("--limit") + 1] == "0"


def test_read_beads_raises_when_bd_fails(tmp_path, monkeypatch):
    fake_bd = tmp_path / "bd"
    fake_bd.write_text("#!/bin/sh\necho 'database is locked' >&2\nexit 1\n")
    fake_bd.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")
    with pytest.raises(notify.BdError):
        notify.read_beads()


def test_overlay_values_come_from_project_md(tmp_path):
    overlay = tmp_path / "project.md"
    overlay.write_text(
        "# Project\n\n```bash\nCODER=Bob\nREVIEWER=Carol\nCODER=Dan\n"
        "BEAD_PREFIX={{BEAD_PREFIX}}\n```\n"
    )
    assert notify.read_overlay(overlay) == {"CODER": "Bob", "REVIEWER": "Carol"}
    assert notify.read_overlay(tmp_path / "missing.md") == {}


def test_the_project_path_keeps_the_typed_path(tmp_path, monkeypatch):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    monkeypatch.chdir(link)
    monkeypatch.setenv("PWD", str(link))
    assert notify.project_path(".") == link
    monkeypatch.setenv("PWD", str(tmp_path))
    assert notify.project_path(".").resolve() == real.resolve()


def test_run_sh_process_is_matched_by_project_and_agent():
    lines = [
        "/bin/zsh",
        "bash /p/proj/.loop/run.sh Ralph /p/proj/.loop/CODER.md",
        "bash /p/other/.loop/run.sh Alice /p/other/.loop/REVIEWER.md",
    ]
    assert notify.loop_in(lines, ["/p/proj"], "Ralph") is True
    assert notify.loop_in(lines, ["/p/proj"], "Alice") is False
    assert notify.loop_in(lines, ["/x/link", "/p/other"], "Alice") is True


@pytest.mark.parametrize(
    ("text", "seconds"), [("2h", 7200), ("90", 90), ("30m", 1800), ("1d", 86400)]
)
def test_stall_limit_takes_run_sh_durations(text, seconds):
    assert notify.duration_seconds(text) == seconds


# Decision messages (lpe-kri): escalated and parked beads ask for a reply, and
# each sent decision message is recorded in the shared sent.jsonl.


@pytest.mark.parametrize("state", ["escalated", "parked"])
def test_a_decision_message_asks_for_a_reply(make, telegram, state):
    harness = make(bead("lpe-u1", "review"))
    harness.set(bead("lpe-u1", state, title="Pick one", notes="Which way?"))
    harness.notifier.poll()
    message = telegram.messages()[0]
    lines = message["text"].splitlines()
    assert lines[0] == f"demo: lpe-u1 {state}"
    assert "Pick one" in lines
    assert "Last note: Which way?" in lines
    assert lines[-1] == (
        "Reply to this message to answer. Start with Ralph: or Alice:"
        " to choose the agent."
    )
    assert message["reply_markup"] == {
        "force_reply": True,
        "input_field_placeholder": "Your decision",
    }
    assert "disable_notification" not in message


@pytest.mark.parametrize("state", ["blocked", "merge", "coding"])
def test_other_messages_ask_for_no_reply(make, telegram, home, state):
    harness = make(bead("lpe-u2", "review"))
    harness.set(bead("lpe-u2", state))
    harness.notifier.poll()
    message = telegram.messages()[0]
    assert "reply_markup" not in message
    assert "Reply to this message" not in message["text"]
    assert sent_lines(home) == []


def test_a_sent_decision_message_is_recorded(make, telegram, home):
    harness = make(bead("lpe-v1", "review"))
    telegram.replies = [
        (200, {"ok": True, "result": {"message_id": 77, "chat": {"id": 4242}}})
    ]
    harness.set(bead("lpe-v1", "escalated"))
    harness.notifier.poll()
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


def test_a_failed_decision_message_is_recorded_when_it_goes_out(make, telegram, home):
    harness = make(bead("lpe-v2", "coding"))
    telegram.replies = [
        (500, {"ok": False, "error_code": 500, "description": "Boom"}),
        (200, {"ok": True, "result": {"message_id": 9, "chat": {"id": 4242}}}),
    ]
    harness.set(bead("lpe-v2", "parked"))
    harness.notifier.poll()
    assert sent_lines(home) == []
    harness.notifier.poll()
    assert [(line["message_id"], line["bead"]) for line in sent_lines(home)] == [
        (9, "lpe-v2")
    ]


def test_every_notifier_appends_to_the_same_file(telegram, home, logs):
    one = Harness(telegram, [bead("lpe-w1", "review")], logs)
    two = Harness(telegram, [bead("lpe-w2", "review")], logs)
    one.notifier.start()
    two.notifier.start()
    telegram.replies = [
        (200, {"ok": True, "result": {"message_id": 1, "chat": {"id": 4242}}}),
        (200, {"ok": True, "result": {"message_id": 2, "chat": {"id": 4242}}}),
    ]
    one.set(bead("lpe-w1", "escalated"))
    two.set(bead("lpe-w2", "parked"))
    one.notifier.poll()
    two.notifier.poll()
    assert [line["bead"] for line in sent_lines(home)] == ["lpe-w1", "lpe-w2"]


def test_a_failed_record_does_not_stop_the_notifier(make, telegram, home, logs):
    harness = make(bead("lpe-w3", "review"))
    (home / ".local").write_text("not a folder")
    telegram.replies = [
        (200, {"ok": True, "result": {"message_id": 3, "chat": {"id": 4242}}})
    ]
    harness.set(bead("lpe-w3", "escalated"))
    harness.notifier.poll()
    assert len(telegram.messages()) == 1
    assert harness.notifier.queue == deque()
    assert any("sent.jsonl" in line for line in logs)


def test_a_long_decision_message_keeps_the_reply_line(make, telegram):
    harness = make(bead("lpe-w4", "review"))
    harness.set(bead("lpe-w4", "parked", notes="z" * 5000))
    harness.notifier.poll()
    text = telegram.texts()[0]
    assert len(text) <= 4000
    assert text.endswith("to choose the agent.")
    assert "..." in text
