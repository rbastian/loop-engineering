"""loop/reply.py: the human answers a decision message from Telegram (lpe-kri).

The reader long-polls getUpdates, matches each reply to a decision message in
the shared sent.jsonl, writes a note from the human in the bead and assigns the
bead to the right agent. These tests give it a temporary HOME, a fake bd on
PATH that keeps its beads in a JSON file, and a fake Telegram endpoint that
honors the getUpdates offset.
"""

import fcntl
import importlib.util
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REPLY = ROOT / "reply.py"

_spec = importlib.util.spec_from_file_location("loop_reply", REPLY)
reply = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(reply)

TOKEN = "123456:SECRET-token-value"
CHAT = 4242
HUMAN = "Rob Bastian"
ASK = "Reply to a decision message to answer a bead."

FAKE_BD = f"""#!{sys.executable}
import json, os, sys

state_path = os.environ["FAKE_BD_STATE"]
with open(state_path) as f:
    state = json.load(f)
args = sys.argv[1:]
with open(os.environ["FAKE_BD_LOG"], "a") as f:
    f.write(json.dumps({{"cwd": os.getcwd(), "args": args}}) + "\\n")


def fail(text):
    print(text, file=sys.stderr)
    sys.exit(1)


def save():
    with open(state_path, "w") as f:
        json.dump(state, f)


command, bead_id = args[0], args[1] if len(args) > 1 else ""
if command in state.get("raw", {{}}):
    print(state["raw"][command])
    sys.exit(0)
if command == "list" and command in state.get("fail", {{}}):
    fail(state["fail"][command])
if command == "list" and "--parent" in args:
    parent = args[args.index("--parent") + 1]
    print(json.dumps(state.get("events", {{}}).get(parent, [])))
    sys.exit(0)
bead = state["beads"].get(bead_id)
if bead is None:
    fail(f"Error: no issue found matching {{bead_id!r}}")
if command in state.get("fail", {{}}):
    fail(state["fail"][command])
if command == "show":
    print(json.dumps([{{"id": bead_id, **bead}}]))
elif command == "note":
    bead.setdefault("notes", []).append(args[2])
    save()
elif command == "update":
    expected = [a.split("=", 1)[1] for a in args if a.startswith("--if-assignee=")]
    if expected and expected[0] != bead.get("assignee"):
        fail("Error: assignee does not match")
    bead["assignee"] = [a.split("=", 1)[1] for a in args if a.startswith("--assignee=")][0]
    save()
else:
    fail(f"unknown command {{args}}")
"""


class FakeTelegram:
    """A Bot API endpoint for the reader: getUpdates honors the offset, and
    sendMessage answers with a new message_id unless a test queues a failure."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, dict]] = []
        self.updates: list[dict] = []
        self.send_failures: list[tuple[int, dict]] = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length) or b"{}")
                fake.requests.append((self.path, body))
                status, data = fake.answer(self.path.rsplit("/", 1)[-1], body)
                raw = json.dumps(data).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(
            target=self.server.serve_forever, args=(0.05,), daemon=True
        ).start()

    def answer(self, method: str, body: dict) -> tuple[int, dict]:
        if method == "getUpdates":
            offset = body.get("offset", 0)
            result = [u for u in self.updates if u["update_id"] >= offset]
            return 200, {"ok": True, "result": result}
        if method == "sendMessage" and self.send_failures:
            return self.send_failures.pop(0)
        return 200, {
            "ok": True,
            "result": {"message_id": 1000 + len(self.requests), "chat": {"id": CHAT}},
        }

    def messages(self) -> list[dict]:
        return [body for path, body in self.requests if path.endswith("/sendMessage")]

    def get_updates(self) -> list[dict]:
        return [body for path, body in self.requests if path.endswith("/getUpdates")]

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def telegram():
    fake = FakeTelegram()
    yield fake
    fake.close()


@pytest.fixture
def home(tmp_path, monkeypatch):
    path = tmp_path / "home"
    path.mkdir()
    monkeypatch.setenv("HOME", str(path))
    return path


class Bd:
    """The fake bd's beads, events and command log."""

    def __init__(self, tmp_path: Path, monkeypatch) -> None:
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        script = bin_dir / "bd"
        script.write_text(FAKE_BD)
        script.chmod(0o755)
        self.state_path = tmp_path / "bd-state.json"
        self.log_path = tmp_path / "bd-log.jsonl"
        self.log_path.write_text("")
        self.state = {"beads": {}, "events": {}, "fail": {}, "raw": {}}
        self.save()
        monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
        monkeypatch.setenv("FAKE_BD_STATE", str(self.state_path))
        monkeypatch.setenv("FAKE_BD_LOG", str(self.log_path))

    def save(self) -> None:
        self.state_path.write_text(json.dumps(self.state))

    def add(self, bead_id, state, *, assignee=HUMAN, events=()):
        self.state["beads"][bead_id] = {
            "assignee": assignee,
            "labels": [f"loop:{state}", "round:2"],
        }
        self.state["events"][bead_id] = [
            {
                "id": f"{bead_id}.{n}",
                "title": f"State change: loop → {value}",
                "description": f"Set loop to {value}\n\nReason: {reason}",
                "created_at": f"2026-11-14T12:0{n}:00Z",
                "issue_type": "event",
            }
            for n, (value, reason) in enumerate(events, start=1)
        ]
        self.save()

    def fail(self, command: str, text: str) -> None:
        self.state["fail"][command] = text
        self.save()

    def print_raw(self, command: str, text: str) -> None:
        self.state["raw"][command] = text
        self.save()

    def bead(self, bead_id) -> dict:
        return json.loads(self.state_path.read_text())["beads"][bead_id]

    def calls(self) -> list[dict]:
        return [json.loads(line) for line in self.log_path.read_text().splitlines()]

    def writes(self) -> list[list[str]]:
        return [c["args"] for c in self.calls() if c["args"][0] in ("note", "update")]


@pytest.fixture
def bd(tmp_path, monkeypatch):
    return Bd(tmp_path, monkeypatch)


@pytest.fixture
def project(tmp_path):
    path = tmp_path / "demo"
    (path / ".loop").mkdir(parents=True)
    (path / ".loop/project.md").write_text(
        f"```bash\nCODER=Ralph\nREVIEWER=Alice\nHUMAN={HUMAN}\nBEAD_PREFIX=lpe\n```\n"
    )
    return path


def record(home: Path, message_id: int, bead_id: str, primary: Path, state: str):
    reply.notify.append_line(
        home / ".local/state/loop-telegram/sent.jsonl",
        {
            "message_id": message_id,
            "chat_id": CHAT,
            "project": "demo",
            "primary": str(primary),
            "bead": bead_id,
            "state": state,
            "sent_at": "2026-11-14T12:00:00+00:00",
        },
    )


def update(update_id, text, *, reply_to=None, chat=CHAT, sender=CHAT):
    message = {
        "message_id": 500 + update_id,
        "chat": {"id": chat, "type": "private"},
        "from": {"id": sender, "is_bot": False},
        "text": text,
    }
    if reply_to is not None:
        message["reply_to_message"] = {"message_id": reply_to}
    return {"update_id": update_id, "message": message}


@pytest.fixture
def logs():
    return []


@pytest.fixture
def reader(telegram, home, logs):
    def build():
        bot = reply.notify.Telegram(
            TOKEN, str(CHAT), base=telegram.url, log=logs.append
        )
        return reply.Reader(bot, str(CHAT), poll_timeout=0, log=logs.append)

    return build


def answers(telegram) -> list[tuple[str, int | None]]:
    return [
        (m["text"], m.get("reply_parameters", {}).get("message_id"))
        for m in telegram.messages()
    ]


# 2. Replies are off without a token or a chat ID.


def clean_env(home: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("TELEGRAM_")}
    env.update(
        {"HOME": str(home), "TELEGRAM_BOT_TOKEN": TOKEN, "TELEGRAM_CHAT_ID": str(CHAT)}
    )
    return env


@pytest.mark.parametrize("missing", ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"])
def test_missing_variable_turns_replies_off(tmp_path, home, missing):
    env = clean_env(home)
    del env[missing]
    result = subprocess.run(
        [sys.executable, str(REPLY)],
        check=False,
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    out = result.stdout + result.stderr
    assert result.returncode == 0, out
    assert "replies are off" in out
    assert TOKEN not in out


# 3. Only one reader runs.


def test_a_second_reader_exits_while_the_lock_is_held(tmp_path, home):
    state = home / ".local/state/loop-telegram"
    state.mkdir(parents=True)
    with open(state / "reply.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        env = clean_env(home)
        env["TELEGRAM_API_URL"] = "http://127.0.0.1:9"
        result = subprocess.run(
            [sys.executable, str(REPLY), "--polls", "1"],
            check=False,
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
    out = result.stdout + result.stderr
    assert result.returncode == 1, out
    assert "already runs" in out
    assert "getUpdates" not in out


def test_the_reader_takes_the_lock(home):
    lock = reply.take_lock()
    assert lock is not None
    assert reply.take_lock() is None
    lock.close()
    again = reply.take_lock()
    assert again is not None
    again.close()


# 4. Routing by the loop state, 11. the assignment uses --if-assignee.


def test_a_reply_to_an_escalated_bead_goes_to_the_coder(
    telegram, home, bd, project, reader
):
    bd.add("lpe-a1", "escalated", events=[("escalated", "Review round 2 failed")])
    record(home, 77, "lpe-a1", project, "escalated")
    telegram.updates = [update(1, "Accept the finding as non-blocking", reply_to=77)]
    reader().poll()

    assert bd.writes() == [
        [
            "note",
            "lpe-a1",
            f"Decision from {HUMAN} (Telegram): Accept the finding as non-blocking",
        ],
        ["update", "lpe-a1", f"--if-assignee={HUMAN}", "--assignee=Ralph"],
    ]
    assert all(c["cwd"] == str(project) for c in bd.calls())
    assert bd.bead("lpe-a1")["assignee"] == "Ralph"
    assert answers(telegram) == [("demo lpe-a1: note added, assigned to Ralph.", 501)]


def test_a_reply_to_a_bead_parked_by_review_not_run_goes_to_the_reviewer(
    telegram, home, bd, project, reader
):
    bd.add(
        "lpe-a2",
        "parked",
        events=[
            ("parked", "Gate fails twice"),
            ("review", "Handed to Alice"),
            ("parked", "Review not run"),
        ],
    )
    record(home, 78, "lpe-a2", project, "parked")
    telegram.updates = [update(1, "codex is back on PATH", reply_to=78)]
    reader().poll()
    assert bd.bead("lpe-a2")["assignee"] == "Alice"
    assert answers(telegram) == [("demo lpe-a2: note added, assigned to Alice.", 501)]


def test_a_reply_to_a_bead_parked_for_another_reason_goes_to_the_coder(
    telegram, home, bd, project, reader
):
    bd.add(
        "lpe-a3",
        "parked",
        events=[("parked", "Review not run"), ("parked", "Gate fails twice")],
    )
    record(home, 79, "lpe-a3", project, "parked")
    telegram.updates = [update(1, "Skip the flaky test", reply_to=79)]
    reader().poll()
    assert bd.bead("lpe-a3")["assignee"] == "Ralph"


# 5. A name prefix chooses the agent and is removed from the note.


@pytest.mark.parametrize(
    ("text", "agent", "note"),
    [
        (
            "Alice: pass it, the finding is style",
            "Alice",
            "pass it, the finding is style",
        ),
        ("alice:pass it", "Alice", "pass it"),
        ("RALPH: fix the test", "Ralph", "fix the test"),
        ("Ralphie: hello", "Ralph", "Ralphie: hello"),
    ],
)
def test_a_name_prefix_chooses_the_agent(
    telegram, home, bd, project, reader, text, agent, note
):
    bd.add("lpe-b1", "escalated")
    record(home, 80, "lpe-b1", project, "escalated")
    telegram.updates = [update(1, text, reply_to=80)]
    reader().poll()
    assert bd.writes()[0] == [
        "note",
        "lpe-b1",
        f"Decision from {HUMAN} (Telegram): {note}",
    ]
    assert bd.bead("lpe-b1")["assignee"] == agent


# 6. A bead that no longer waits for a decision changes nothing.


@pytest.mark.parametrize(
    ("state", "assignee"),
    [("coding", "Ralph"), ("escalated", "Ralph"), ("parked", "Alice")],
)
def test_a_bead_that_no_longer_waits_changes_nothing(
    telegram, home, bd, project, reader, state, assignee
):
    bd.add("lpe-c1", state, assignee=assignee)
    record(home, 81, "lpe-c1", project, "escalated")
    telegram.updates = [update(1, "go on", reply_to=81)]
    reader().poll()
    assert bd.writes() == []
    assert answers(telegram) == [
        (
            (
                f"demo lpe-c1: not waiting for a decision (state {state},"
                f" assignee {assignee}). Nothing changed."
            ),
            501,
        )
    ]


# 7. A message that is not a reply to a decision message changes nothing.


def test_a_message_that_is_not_a_reply_changes_nothing(telegram, home, bd, reader):
    telegram.updates = [update(1, "hello")]
    reader().poll()
    assert bd.calls() == []
    assert answers(telegram) == [(ASK, 501)]


def test_a_reply_to_an_unknown_message_changes_nothing(
    telegram, home, bd, project, reader
):
    bd.add("lpe-d1", "escalated")
    record(home, 82, "lpe-d1", project, "escalated")
    telegram.updates = [update(1, "hello", reply_to=999)]
    reader().poll()
    assert bd.calls() == []
    assert answers(telegram) == [(ASK, 501)]


def test_the_newest_record_of_a_message_wins(telegram, home, bd, project, reader):
    bd.add("lpe-d2", "escalated")
    bd.add("lpe-d3", "escalated")
    record(home, 83, "lpe-d2", project, "escalated")
    record(home, 83, "lpe-d3", project, "escalated")
    telegram.updates = [update(1, "go", reply_to=83)]
    reader().poll()
    assert bd.bead("lpe-d2")["assignee"] == HUMAN
    assert bd.bead("lpe-d3")["assignee"] == "Ralph"


def test_a_reply_without_text_changes_nothing(telegram, home, bd, project, reader):
    bd.add("lpe-d4", "escalated")
    record(home, 84, "lpe-d4", project, "escalated")
    sticker = update(1, "", reply_to=84)
    del sticker["message"]["text"]
    telegram.updates = [sticker]
    reader().poll()
    assert bd.writes() == []
    assert answers(telegram) == [("Reply with text to answer a bead.", 501)]


# 8. A message from another chat or sender gets no answer.


@pytest.mark.parametrize(("chat", "sender"), [(999, CHAT), (CHAT, 999), (999, 999)])
def test_a_message_from_someone_else_is_ignored(
    telegram, home, bd, project, reader, logs, chat, sender
):
    bd.add("lpe-e1", "escalated")
    record(home, 85, "lpe-e1", project, "escalated")
    telegram.updates = [
        update(1, "Ralph: merge it", reply_to=85, chat=chat, sender=sender)
    ]
    reader().poll()
    assert bd.calls() == []
    assert telegram.messages() == []
    assert any("ignored" in line for line in logs)


# 9. Confirmation, and a failed assignment after a note.


def test_a_failed_assignment_after_a_note_says_so(telegram, home, bd, project, reader):
    bd.add("lpe-f1", "escalated")
    bd.fail("update", "Error: database is locked")
    record(home, 86, "lpe-f1", project, "escalated")
    telegram.updates = [update(1, "go", reply_to=86)]
    reader().poll()
    assert [w[0] for w in bd.writes()] == ["note", "update"]
    ((text, reply_to),) = answers(telegram)
    assert reply_to == 501
    assert text.startswith("demo lpe-f1: note added, but the assignment failed:")
    assert "database is locked" in text
    assert f"still assigned to {HUMAN}" in text


def test_a_failed_note_assigns_nothing(telegram, home, bd, project, reader):
    bd.add("lpe-f2", "escalated")
    bd.fail("note", "Error: database is locked")
    record(home, 87, "lpe-f2", project, "escalated")
    telegram.updates = [update(1, "go", reply_to=87)]
    reader().poll()
    assert [w[0] for w in bd.writes()] == ["note"]
    assert bd.bead("lpe-f2")["assignee"] == HUMAN
    ((text, _),) = answers(telegram)
    assert text.startswith("demo lpe-f2: the note failed:")
    assert "Nothing changed." in text


@pytest.mark.parametrize(
    ("command", "output", "error"),
    [
        ("list", None, "Error: database is locked"),
        ("list", "not json", None),
        ("show", "not json", None),
        ("show", "[]", None),
    ],
)
def test_a_failed_bead_read_answers_and_changes_nothing(
    telegram, home, bd, project, reader, command, output, error
):
    bd.add("lpe-f4", "parked", events=[("parked", "Review not run")])
    if error:
        bd.fail(command, error)
    else:
        bd.print_raw(command, output)
    record(home, 89, "lpe-f4", project, "parked")
    telegram.updates = [update(1, "go", reply_to=89)]
    reader().poll()
    assert bd.writes() == []
    assert bd.bead("lpe-f4")["assignee"] == HUMAN
    ((text, reply_to),) = answers(telegram)
    assert reply_to == 501
    assert text.startswith(f"demo lpe-f4: bd {command} failed:")
    assert text.endswith("Nothing changed.")
    if error:
        assert error in text


def test_answers_use_no_parse_mode(telegram, home, bd, project, reader):
    bd.add("lpe-f3", "escalated")
    record(home, 88, "lpe-f3", project, "escalated")
    telegram.updates = [update(1, "*go*", reply_to=88), update(2, "hi")]
    reader().poll()
    messages = telegram.messages()
    assert len(messages) == 2
    for message in messages:
        assert "parse_mode" not in message
        assert message["chat_id"] == str(CHAT)


# 10. The saved offset stops a restarted reader from applying an update twice.


def test_a_restarted_reader_does_not_apply_an_update_twice(
    telegram, home, bd, project, reader
):
    bd.add("lpe-g1", "escalated")
    record(home, 89, "lpe-g1", project, "escalated")
    telegram.updates = [update(7, "go", reply_to=89)]
    reader().poll()
    assert (home / ".local/state/loop-telegram/offset").read_text().strip() == "8"

    bd.add("lpe-g1", "escalated")
    reader().poll()
    assert len([w for w in bd.writes() if w[0] == "note"]) == 1
    assert telegram.get_updates()[-1]["offset"] == 8


def test_get_updates_long_polls_for_messages(telegram, home, logs):
    bot = reply.notify.Telegram(TOKEN, str(CHAT), base=telegram.url, log=logs.append)
    request = reply.Reader(bot, str(CHAT), log=logs.append).updates_request()
    assert request == {"timeout": 30, "allowed_updates": ["message"]}
    assert reply.HTTP_TIMEOUT == 40


# 12. The token never appears in output or logs.


def test_http_and_network_errors_log_no_token(telegram, home, logs, capsys):
    bot = reply.notify.Telegram(
        TOKEN, str(CHAT), base="http://127.0.0.1:9", log=logs.append
    )
    reply.Reader(bot, str(CHAT), poll_timeout=0, log=logs.append).poll()
    bot.base = telegram.url
    telegram.send_failures = [
        (401, {"ok": False, "error_code": 401, "description": "Unauthorized"})
    ]
    telegram.updates = [update(1, "hi")]
    reply.Reader(bot, str(CHAT), poll_timeout=0, log=logs.append).poll()
    out = capsys.readouterr()
    text = "\n".join(logs) + out.out + out.err
    assert "getUpdates" in text and "sendMessage" in text and "401" in text
    assert TOKEN not in text
    assert "SECRET" not in text
    assert "127.0.0.1" not in text


def test_main_logs_no_token_when_telegram_is_down(tmp_path, home):
    env = clean_env(home)
    env["TELEGRAM_API_URL"] = "http://127.0.0.1:9"
    result = subprocess.run(
        [sys.executable, str(REPLY), "--polls", "1"],
        check=False,
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    out = result.stdout + result.stderr
    assert result.returncode == 0, out
    assert "getUpdates" in out
    assert TOKEN not in out
    assert "SECRET" not in out
