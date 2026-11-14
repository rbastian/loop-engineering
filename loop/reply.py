#!/usr/bin/env python3
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""Read the human's Telegram replies to decision messages and route the beads.

notify.py sends a decision message when a bead enters loop=escalated or
loop=parked, and records it in ~/.local/state/loop-telegram/sent.jsonl. The
human replies to that message. This reader long-polls getUpdates, finds the
message that the reply answers, and in the primary checkout that the record
names:

* adds the note "Decision from <HUMAN> (Telegram): <text>" to the bead;
* assigns the bead to the agent: the one that the reply names with a
  "<CODER>:" or "<REVIEWER>:" prefix, else the coder for loop=escalated, and
  for loop=parked the reviewer when it parked the bead with "Review not run"
  and the coder otherwise.

One reader serves every repository that uses the same bot, because Telegram
lets only one getUpdates reader confirm updates. A lock file keeps a second
reader from starting. The reader saves the next update offset after each
update, so a restart does not apply a reply twice. Telegram keeps unread
updates for 24 hours, so a reply sent while the reader is down for longer is
lost.

The bot token is part of every request URL, so the reader never prints the
token, a URL or a raw exception.

Usage, from the primary checkout of any project that has the harness:
    uv run .loop/reply.py

TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID name the bot and the chat, as for
notify.py. If either one is unset, the reader prints one line and exits 0.
TELEGRAM_API_URL replaces https://api.telegram.org, for tests.
"""

import argparse
import fcntl
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import IO

# The sibling notify.py, in loop/ or .loop/.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import notify

POLL_TIMEOUT = 30
# The HTTP timeout must be longer than the long-poll timeout.
HTTP_TIMEOUT = 40
RETRY_SECONDS = 5
ASK = "Reply to a decision message to answer a bead."
EVENT_TITLE = "State change: loop → parked"
REASON_RE = re.compile(r"^Reason: (.*)$", re.MULTILINE)


def take_lock() -> IO | None:
    """An exclusive lock on reply.lock, or None when another reader holds it.
    The lock lasts as long as the returned file stays open."""
    path = notify.state_dir() / "reply.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = open(path, "w")  # noqa: SIM115 - held open for the life of the reader
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        return None
    return lock


def find_record(message_id: object, chat_id: str) -> dict | None:
    """The newest line of sent.jsonl for MESSAGE_ID in CHAT_ID."""
    try:
        lines = notify.sent_path().read_text().splitlines()
    except OSError:
        return None
    found = None
    for line in lines:
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if (
            isinstance(record, dict)
            and record.get("message_id") == message_id
            and str(record.get("chat_id")) == chat_id
        ):
            found = record
    return found


class BdFailed(Exception):
    pass


def run_bd(args: list[str], cwd: str) -> str:
    """The output of bd ARGS, run in CWD. A failure raises BdFailed with
    the last line that bd printed."""
    try:
        result = subprocess.run(
            ["bd", *args],
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as err:
        raise BdFailed(type(err).__name__) from None
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        raise BdFailed(detail[-1] if detail else f"exit {result.returncode}")
    return result.stdout


def parked_reason(bead_id: str, cwd: str) -> str:
    """The reason of the newest loop=parked state change of the bead."""
    events = json.loads(
        run_bd(
            ["list", "--parent", bead_id, "--all", "--type", "event"]
            + ["--limit", "0", "--json"],
            cwd,
        )
        or "[]"
    )
    parked = [e for e in events if e.get("title") == EVENT_TITLE]
    if not parked:
        return ""
    newest = max(parked, key=lambda e: (e.get("created_at", ""), e.get("id", "")))
    match = REASON_RE.search(newest.get("description", ""))
    return match.group(1).strip() if match else ""


def choose_agent(
    text: str, names: dict[str, str], state: str, reason: Callable[[], str]
) -> tuple[str, str]:
    """The agent that gets the bead, and the note text without a name prefix."""
    for key in ("CODER", "REVIEWER"):
        match = re.match(rf"\s*{re.escape(names[key])}:\s*", text, re.IGNORECASE)
        if match:
            return names[key], text[match.end() :]
    if state == "parked" and reason() == "Review not run":
        return names["REVIEWER"], text
    return names["CODER"], text


class Reader:
    def __init__(
        self,
        telegram: notify.Telegram,
        chat_id: str,
        *,
        poll_timeout: int = POLL_TIMEOUT,
        log: Callable[[str], None] = notify.log_line,
    ) -> None:
        self.telegram = telegram
        self.chat_id = chat_id
        self.poll_timeout = poll_timeout
        self.log = log
        self.offset_path = notify.state_dir() / "offset"
        self.offset_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.offset: int | None = int(self.offset_path.read_text().strip())
        except (OSError, ValueError):
            self.offset = None

    def save_offset(self, offset: int) -> None:
        self.offset = offset
        self.offset_path.write_text(f"{offset}\n")

    def updates_request(self) -> dict:
        request = {"timeout": self.poll_timeout, "allowed_updates": ["message"]}
        if self.offset is not None:
            request["offset"] = self.offset
        return request

    def poll(self) -> bool:
        """One getUpdates call. Handle each update, then save the next offset.
        False when the call failed."""
        result = self.telegram.call("getUpdates", self.updates_request())
        if not result.ok:
            return False
        for update in result.result if isinstance(result.result, list) else []:
            uid = update.get("update_id") if isinstance(update, dict) else None
            if not isinstance(uid, int):
                continue
            try:
                self.handle(update.get("message"))
            except Exception as err:  # noqa: BLE001 - one bad update must not stop the reader
                self.log(f"update {uid} failed: {type(err).__name__}")
            self.save_offset(uid + 1)
        return True

    def answer(self, message: dict, text: str) -> None:
        self.telegram.send(
            {"text": text, "reply_parameters": {"message_id": message["message_id"]}}
        )

    def handle(self, message: object) -> None:
        if not isinstance(message, dict):
            return
        chat = (message.get("chat") or {}).get("id")
        sender = (message.get("from") or {}).get("id")
        if str(chat) != self.chat_id or str(sender) != self.chat_id:
            self.log(f"ignored a message from chat {chat}, user {sender}")
            return
        original = message.get("reply_to_message") or {}
        record = find_record(original.get("message_id"), self.chat_id)
        if record is None:
            self.answer(message, ASK)
            return
        text = message.get("text") or ""
        if not text.strip():
            self.answer(message, "Reply with text to answer a bead.")
            return
        self.answer(message, self.decide(record, text))

    def decide(self, record: dict, text: str) -> str:
        """Write the decision into the bead. The answer to send back."""
        bead_id, primary = record.get("bead", ""), record.get("primary", "")
        head = f"{record.get('project', '?')} {bead_id}"
        names = notify.read_overlay(Path(primary) / ".loop/project.md")
        missing = [k for k in ("CODER", "REVIEWER", "HUMAN") if not names.get(k)]
        if missing:
            return (
                f"{head}: .loop/project.md in {primary} has no"
                f" {', '.join(missing)}. Nothing changed."
            )
        human = names["HUMAN"]
        try:
            (bead,) = json.loads(run_bd(["show", bead_id, "--json"], primary))
        except BdFailed as err:
            return f"{head}: bd show failed: {err}. Nothing changed."
        state = notify.labels_of(bead).get("loop")
        assignee = bead.get("assignee") or ""
        if state not in notify.DECISIONS or assignee != human:
            return (
                f"{head}: not waiting for a decision (state {state},"
                f" assignee {assignee}). Nothing changed."
            )
        agent, note = choose_agent(
            text, names, state, lambda: parked_reason(bead_id, primary)
        )
        try:
            run_bd(
                ["note", bead_id, f"Decision from {human} (Telegram): {note}"],
                primary,
            )
        except BdFailed as err:
            return f"{head}: the note failed: {err}. Nothing changed."
        try:
            run_bd(
                ["update", bead_id, f"--if-assignee={human}", f"--assignee={agent}"],
                primary,
            )
        except BdFailed as err:
            return (
                f"{head}: note added, but the assignment failed: {err}."
                f" The bead is still assigned to {human}."
            )
        self.log(f"{head}: note added, assigned to {agent}")
        return f"{head}: note added, assigned to {agent}."


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--polls", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        print(
            "reply: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is not set; replies are off"
        )
        return 0
    lock = take_lock()
    if lock is None:
        print("reply: a reader already runs for this bot; exiting")
        return 1
    telegram = notify.Telegram(
        token,
        chat_id,
        base=os.environ.get("TELEGRAM_API_URL", notify.API_URL),
        timeout=HTTP_TIMEOUT,
    )
    telegram.check()
    reader = Reader(telegram, chat_id)
    notify.log_line("reading replies to decision messages")
    polls = 0
    try:
        while args.polls is None or polls < args.polls:
            polls += 1
            if not reader.poll() and (args.polls is None or polls < args.polls):
                time.sleep(RETRY_SECONDS)
    except KeyboardInterrupt:
        pass
    finally:
        lock.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
