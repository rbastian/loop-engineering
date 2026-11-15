#!/usr/bin/env python3
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""Send short Telegram messages to the human about the loop.

run.sh calls this command around each agent session. It does not poll:

* snapshot FILE: before a session, write the loop state, the round and the
  assignee of each bead of the project to FILE;
* report FILE --agent NAME: after the session, send one message for each bead
  that FILE assigned to NAME and whose loop state changed:
  - escalated or parked: a decision message with the bead ID, the title, the
    last note and a line that asks for a reply, with sound. reply.py reads
    the replies. Each sent decision message is recorded in the shared file
    ~/.local/state/loop-telegram/sent.jsonl, so that reply.py can match a
    reply to its bead. A bead that ends assigned to the human in one of these
    states gets a decision message even when its state did not change;
  - blocked: the bead ID, the title and the last note, with sound;
  - merge: the bead ID, the title and the PR URL, with sound;
  - coding, review, returned or done: the bead ID, the title and the round,
    silently;
* send [--silent] TEXT: send one message;
* check: exit 0 when the variables are set and Telegram knows the bot.

Each message gets up to 3 tries. After the third failure, the command logs
one line and drops the message. Every subcommand except check exits 0, so it
never stops run.sh.

The bot token is part of every request URL, so the command never prints the
token, a URL or a raw exception.

TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID name the bot and the chat. If either
one is unset, every subcommand exits 0 and prints nothing, except check,
which exits 1. TELEGRAM_API_URL replaces https://api.telegram.org, for tests.
--project names the primary checkout; the default is the folder above this
script's folder.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

API_URL = "https://api.telegram.org"
# Telegram accepts 4096 characters. The margin keeps clear of that limit.
MAX_LENGTH = 4000
TRIES = 3
# The wait after a failed send without retry_after, and the longest wait.
RETRY_SECONDS = 5
RETRY_AFTER_MAX = 60

DECISIONS = {"escalated", "parked"}
ESCALATIONS = {"blocked"}
PROGRESS = {"coding", "review", "returned", "done"}
PR_RE = re.compile(r"PR opened: #\d+ (\S+)")


def log_line(text: str) -> None:
    print(f"{time.strftime('%H:%M:%S')}  {text}", flush=True)


def truncate(text: str, limit: int = MAX_LENGTH) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def state_dir() -> Path:
    """The folder that notify.py and reply.py of every repository share."""
    return Path.home() / ".local/state/loop-telegram"


def sent_path() -> Path:
    return state_dir() / "sent.jsonl"


def append_line(path: Path, record: dict) -> None:
    """Append RECORD as one JSON line, in one write with O_APPEND, so that
    two writers never mix their lines."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(fd, (json.dumps(record) + "\n").encode())
    finally:
        os.close(fd)


def read_overlay(path: Path) -> dict[str, str]:
    """The KEY=value lines of .loop/project.md. The first line of a key wins,
    and a {{...}} placeholder counts as no value."""
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return {}
    values: dict[str, str] = {}
    for line in lines:
        match = re.fullmatch(r"([A-Z_]+)=(.*)", line)
        if match and "{{" not in match.group(2):
            values.setdefault(match.group(1), match.group(2))
    return values


class BdError(Exception):
    pass


def read_beads() -> list[dict]:
    """Every bead, closed ones included, so that done beads are seen too."""
    try:
        result = subprocess.run(
            ["bd", "list", "--json", "--all", "--limit", "0"],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as err:
        raise BdError(f"bd list failed: {type(err).__name__}") from None
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        raise BdError(f"bd list failed: {detail[-1] if detail else result.returncode}")
    try:
        return json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        raise BdError("bd list failed: output is not JSON") from None


@dataclass
class Reply:
    ok: bool
    result: object = None
    retry_after: int | None = None
    error: str = ""


class Telegram:
    """The Bot API calls: getMe and sendMessage here, getUpdates in reply.py."""

    def __init__(
        self,
        token: str,
        chat_id: str,
        *,
        base: str = API_URL,
        log: Callable[[str], None] = log_line,
        timeout: float = 20,
    ) -> None:
        self._token = token
        self.chat_id = chat_id
        self.base = base
        self.log = log
        self.timeout = timeout

    def call(self, method: str, payload: dict) -> Reply:
        request = urllib.request.Request(
            f"{self.base}/bot{self._token}/{method}",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                status, raw = response.status, response.read()
        except urllib.error.HTTPError as err:
            status = err.code
            try:
                raw = err.read()
            except Exception:  # noqa: BLE001 - a body that breaks off is no body
                raw = b""
        except Exception as err:  # noqa: BLE001 - its text can hold the URL
            error = f"{method} failed: network error ({type(err).__name__})"
            self.log(error)
            return Reply(ok=False, error=error)
        try:
            body = json.loads(raw)
        except ValueError:
            body = {}
        if not isinstance(body, dict):
            body = {}
        if status == 200 and body.get("ok"):
            return Reply(ok=True, result=body.get("result"))
        error = (
            f"{method} failed: HTTP {status},"
            f" error_code {body.get('error_code', '-')}:"
            f" {body.get('description', 'no description')}"
        )
        self.log(error)
        parameters = body.get("parameters")
        retry = parameters.get("retry_after") if isinstance(parameters, dict) else None
        return Reply(
            ok=False, retry_after=retry if isinstance(retry, int) else None, error=error
        )

    def check(self) -> bool:
        reply = self.call("getMe", {})
        if reply.ok and isinstance(reply.result, dict):
            self.log(f"Telegram bot @{reply.result.get('username', '?')} is ready")
            return True
        return False

    def send(self, message: dict) -> Reply:
        return self.call("sendMessage", {"chat_id": self.chat_id, **message})


def labels_of(bead: dict) -> dict[str, str]:
    """The state dimensions of a bead, from labels such as loop:review and round:2."""
    states = {}
    for label in bead.get("labels") or []:
        key, sep, value = label.partition(":")
        if sep:
            states.setdefault(key, value)
    return states


def last_note(notes: str) -> str:
    """The newest note. run.sh's Session cost notes are not a reason, so skip them."""
    lines = [line for line in (notes or "").splitlines() if line.strip()]
    for line in reversed(lines):
        if not line.startswith("Session cost:"):
            return line
    return ""


def bead_text(head: str, bead: dict, detail: str = "") -> str:
    text = f"{head}\n{bead.get('title', '')}"
    return f"{text}\n{detail}" if detail else text


@dataclass
class Project:
    """The facts about the project that the messages need."""

    name: str
    primary: str
    prefix: str = ""
    human: str = ""
    agents: list[str] = field(default_factory=list)


def default_project() -> Path:
    """The primary checkout: the folder above the harness folder of this script."""
    return Path(__file__).absolute().parent.parent


def load_project(path: Path) -> Project:
    overlay = read_overlay(path / ".loop/project.md")
    return Project(
        name=path.name,
        primary=overlay.get("PRIMARY") or str(path),
        prefix=overlay.get("BEAD_PREFIX", ""),
        human=overlay.get("HUMAN", ""),
        agents=[overlay[k] for k in ("CODER", "REVIEWER") if overlay.get(k)],
    )


def ours(beads: list[dict], prefix: str) -> list[dict]:
    if not prefix:
        return beads
    return [b for b in beads if str(b.get("id", "")).startswith(f"{prefix}-")]


def snapshot_of(beads: list[dict], prefix: str) -> dict[str, dict]:
    """The loop state, the round and the assignee of each bead of the project."""
    snapshot = {}
    for bead in ours(beads, prefix):
        dims = labels_of(bead)
        snapshot[bead["id"]] = {
            "loop": dims.get("loop"),
            "round": dims.get("round"),
            "assignee": bead.get("assignee") or "",
        }
    return snapshot


def plain_message(project: Project, text: str, *, silent: bool = False) -> dict:
    message = {"text": truncate(f"{project.name}: {text}")}
    if silent:
        message["disable_notification"] = True
    return message


def decision_message(project: Project, text: str) -> dict:
    """A message that asks the human for a reply. A long note is cut before
    the reply line, so that the line always goes out."""
    names = " or ".join(f"{agent}:" for agent in project.agents)
    ask = f"Reply to this message to answer. Start with {names} to choose the agent."
    body = truncate(f"{project.name}: {text}", MAX_LENGTH - len(ask) - 1)
    return {
        "text": f"{body}\n{ask}",
        "reply_markup": {
            "force_reply": True,
            "input_field_placeholder": "Your decision",
        },
    }


# A message to send, with the sent.jsonl fields of a decision message or None.
Outgoing = tuple[dict, dict | None]


def change_message(project: Project, bead: dict, state: str | None) -> Outgoing | None:
    """The message for a bead that entered STATE, or None for an unlisted state."""
    bead_id = bead["id"]
    if state in DECISIONS or state in ESCALATIONS:
        note = last_note(bead.get("notes", ""))
        text = bead_text(
            f"{bead_id} {state}", bead, f"Last note: {note}" if note else ""
        )
        if state in DECISIONS:
            return decision_message(project, text), {"bead": bead_id, "state": state}
        return plain_message(project, text), None
    if state == "merge":
        urls = PR_RE.findall(bead.get("notes") or "")
        text = bead_text(f"{bead_id} ready to merge", bead, urls[-1] if urls else "")
        return plain_message(project, text), None
    if state in PROGRESS:
        head = f"{bead_id} {state}"
        round_ = labels_of(bead).get("round")
        if state != "done" and round_ and round_ != "0":
            head += f" (round {round_})"
        return plain_message(project, bead_text(head, bead), silent=True), None
    return None


def report_messages(
    project: Project, snapshot: dict[str, dict], beads: list[dict], agent: str
) -> list[Outgoing]:
    """One message per bead that SNAPSHOT assigned to AGENT and whose loop state
    changed, in bead ID order. A bead that ends with the human in a decision
    state gets a decision message even when its state did not change, because
    the reviewer can escalate a bead again with the same state."""
    out = []
    for bead in sorted(ours(beads, project.prefix), key=lambda b: str(b["id"])):
        before = snapshot.get(bead["id"])
        if not isinstance(before, dict) or before.get("assignee") != agent:
            continue
        state = labels_of(bead).get("loop")
        returned = (
            state in DECISIONS
            and bool(project.human)
            and bead.get("assignee") == project.human
        )
        if state != before.get("loop") or returned:
            message = change_message(project, bead, state)
            if message:
                out.append(message)
    return out


def record_sent(
    project: Project,
    telegram: Telegram,
    result: object,
    record: dict,
    *,
    log: Callable[[str], None],
    now: Callable[[], float],
) -> None:
    """Append the sent decision message to sent.jsonl for reply.py."""
    sent = result if isinstance(result, dict) else {}
    if not isinstance(sent.get("message_id"), int):
        log(f"could not record {record['bead']}: Telegram sent no message_id")
        return
    chat = sent.get("chat") if isinstance(sent.get("chat"), dict) else {}
    line = {
        "message_id": sent.get("message_id"),
        "chat_id": chat.get("id", telegram.chat_id),
        "project": project.name,
        "primary": project.primary,
        **record,
        "sent_at": datetime.fromtimestamp(now(), UTC).isoformat(),
    }
    try:
        append_line(sent_path(), line)
    except OSError as err:
        log(f"could not record {record['bead']} in sent.jsonl: {err.strerror}")


def deliver(
    telegram: Telegram,
    project: Project,
    message: dict,
    record: dict | None = None,
    *,
    sleep: Callable[[float], None] | None = None,
    log: Callable[[str], None] = log_line,
    now: Callable[[], float] = time.time,
) -> bool:
    """Send MESSAGE with up to TRIES tries. After the last failure, log one
    line and drop it. True when it went out."""
    sleep = sleep or time.sleep
    for attempt in range(1, TRIES + 1):
        reply = telegram.send(message)
        if reply.ok:
            if record:
                record_sent(project, telegram, reply.result, record, log=log, now=now)
            return True
        if attempt < TRIES:
            wait = RETRY_SECONDS
            if reply.retry_after is not None:
                wait = min(max(reply.retry_after, 0), RETRY_AFTER_MAX)
            sleep(wait)
    log(f"dropped a message after {TRIES} tries: {reply.error or 'send failed'}")
    return False


def write_snapshot(path: Path, project: Project) -> None:
    try:
        snapshot = snapshot_of(read_beads(), project.prefix)
    except BdError as err:
        log_line(str(err))
        return
    try:
        path.write_text(json.dumps(snapshot))
    except OSError as err:
        log_line(f"could not write the snapshot: {err.strerror}")


def report(path: Path, agent: str, project: Project, telegram: Telegram) -> None:
    try:
        snapshot = json.loads(path.read_text())
    except (OSError, ValueError):
        snapshot = None
    if not isinstance(snapshot, dict):
        log_line(f"no snapshot in {path}; nothing to report")
        return
    try:
        beads = read_beads()
    except BdError as err:
        log_line(str(err))
        return
    for message, record in report_messages(project, snapshot, beads, agent):
        deliver(telegram, project, message, record)


def parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--project", type=Path, help="the primary checkout (default: %(default)s)"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    snapshot = commands.add_parser("snapshot", help="record the bead states")
    snapshot.add_argument("file", type=Path)
    report = commands.add_parser("report", help="send the changes since a snapshot")
    report.add_argument("file", type=Path)
    report.add_argument("--agent", required=True)
    send = commands.add_parser("send", help="send one message")
    send.add_argument("--silent", action="store_true", help="send without a sound")
    send.add_argument("text")
    commands.add_parser("check", help="exit 0 when Telegram knows the bot")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return 1 if args.command == "check" else 0
    # Telegram's own error lines stay quiet: deliver logs one line per drop.
    telegram = Telegram(
        token,
        chat_id,
        base=os.environ.get("TELEGRAM_API_URL", API_URL),
        log=lambda _: None,
    )
    if args.command == "check":
        return 0 if telegram.check() else 1
    project = load_project(args.project or default_project())
    if args.command == "snapshot":
        write_snapshot(args.file, project)
    elif args.command == "report":
        report(args.file, args.agent, project, telegram)
    else:
        deliver(
            telegram, project, plain_message(project, args.text, silent=args.silent)
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
