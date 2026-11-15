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
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import IO

# The sibling notify.py, in loop/ or .loop/.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import notify

POLL_TIMEOUT = 30
# The HTTP timeout must be longer than the long-poll timeout.
HTTP_TIMEOUT = 40
# The wait after a failed getUpdates without retry_after. Repeated HTTP 409
# answers double it up to notify.RETRY_AFTER_MAX.
RETRY_SECONDS = 5
# The size of each read when sent.jsonl is read from the end.
BLOCK_SIZE = 65536
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


def lines_from_end(path: Path) -> Iterator[bytes]:
    """The lines of PATH, the last line first, read in blocks from the end."""
    with open(path, "rb") as file:
        position = file.seek(0, os.SEEK_END)
        rest = b""
        while position > 0:
            size = min(BLOCK_SIZE, position)
            position -= size
            file.seek(position)
            lines = (file.read(size) + rest).split(b"\n")
            rest = lines.pop(0)
            yield from reversed(lines)
        yield rest


def find_record(message_id: object, chat_id: str) -> tuple[dict | None, bool]:
    """The newest line of sent.jsonl for MESSAGE_ID in CHAT_ID, and whether it
    is still the newest line for its project and bead. The file is read from
    the end, and the read stops at the first match."""
    later = set()
    try:
        for line in lines_from_end(notify.sent_path()):
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if not isinstance(record, dict):
                continue
            key = (record.get("project"), record.get("bead"))
            if (
                record.get("message_id") == message_id
                and str(record.get("chat_id")) == chat_id
            ):
                return record, key not in later
            later.add(key)
    except OSError:
        pass
    return None, False


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


def record_head(record: dict) -> str:
    """The "<project> <bead>" start of each answer about RECORD."""
    return f"{record.get('project', '?')} {record.get('bead', '')}"


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
        self.conflicts = 0
        self.offset_path = notify.state_dir() / "offset"
        self.offset_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.offset: int | None = int(self.offset_path.read_text().strip())
        except (OSError, ValueError):
            self.offset = None

    def save_offset(self, offset: int) -> None:
        """Keep OFFSET, and write it to a temporary file that a rename puts
        in place, so that a crash never leaves a half-written file. A failed
        write logs one line and keeps the reader going."""
        self.offset = offset
        temporary = self.offset_path.with_name(f"{self.offset_path.name}.tmp")
        try:
            temporary.write_text(f"{offset}\n")
            os.replace(temporary, self.offset_path)
        except OSError as err:
            self.log(f"could not save the offset: {err.strerror}")

    def updates_request(self) -> dict:
        request = {"timeout": self.poll_timeout, "allowed_updates": ["message"]}
        if self.offset is not None:
            request["offset"] = self.offset
        return request

    def poll(self) -> float:
        """One getUpdates call. Handle each update, then save the next offset.
        The seconds to wait before the next call: 0 after a success."""
        result = self.telegram.call("getUpdates", self.updates_request(), quiet=True)
        if not result.ok:
            return self.wait_after(result)
        self.conflicts = 0
        for update in result.result if isinstance(result.result, list) else []:
            uid = update.get("update_id") if isinstance(update, dict) else None
            if not isinstance(uid, int):
                continue
            try:
                self.handle(update.get("message"))
            except Exception as err:  # noqa: BLE001 - one bad update must not stop the reader
                self.log(f"update {uid} failed: {type(err).__name__}")
            self.save_offset(uid + 1)
        return 0

    def wait_after(self, result: notify.Reply) -> float:
        """The wait after a failed getUpdates: retry_after when Telegram gives
        it, else a back-off for HTTP 409, else RETRY_SECONDS. A run of 409
        answers logs one line."""
        backoff = RETRY_SECONDS
        if result.status == 409:
            self.conflicts += 1
            if self.conflicts == 1:
                self.log(
                    f"{result.error}. Another reader or a webhook takes the"
                    f" updates; trying again after up to {notify.RETRY_AFTER_MAX}"
                    " seconds"
                )
            backoff = min(
                RETRY_SECONDS * 2 ** (self.conflicts - 1), notify.RETRY_AFTER_MAX
            )
        else:
            self.log(result.error)
        if result.retry_after is not None:
            return max(result.retry_after, 0)
        return backoff

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
        original = message.get("reply_to_message")
        if not isinstance(original, dict):
            self.answer(message, ASK)
            return
        record, newest = find_record(original.get("message_id"), self.chat_id)
        if record is None:
            self.answer(message, ASK)
            return
        if not newest:
            self.answer(
                message,
                f"{record_head(record)}: this message"
                " is out of date; reply to the newest message for this bead.",
            )
            return
        self.answer(message, self.decide(record, message.get("text") or ""))

    def decide(self, record: dict, text: str) -> str:
        """Write the decision into the bead. The answer to send back."""
        bead_id, primary = record.get("bead", ""), record.get("primary", "")
        head = record_head(record)
        names = notify.read_overlay(Path(primary) / ".loop/project.md")
        missing = [k for k in ("CODER", "REVIEWER", "HUMAN") if not names.get(k)]
        if missing:
            return (
                f"{head}: .loop/project.md in {primary} has no"
                f" {', '.join(missing)}. Nothing changed."
            )
        if not choose_agent(text, names, "", str)[1].strip():
            return f"{head}: reply with text."
        human = names["HUMAN"]
        try:
            records = json.loads(run_bd(["show", bead_id, "--json"], primary))
        except (BdFailed, ValueError) as err:
            return f"{head}: bd show failed: {err}. Nothing changed."
        if not isinstance(records, list):
            return f"{head}: bd show failed: output is not a list. Nothing changed."
        if len(records) != 1:
            found = f"{len(records)} records" if records else "no record"
            return f"{head}: bd show {bead_id} returned {found}. Nothing changed."
        (bead,) = records
        state = notify.labels_of(bead).get("loop")
        assignee = bead.get("assignee") or ""
        if state not in notify.DECISIONS or assignee != human:
            return (
                f"{head}: not waiting for a decision (state {state},"
                f" assignee {assignee}). Nothing changed."
            )
        try:
            agent, note = choose_agent(
                text, names, state, lambda: parked_reason(bead_id, primary)
            )
        except (BdFailed, ValueError) as err:
            return f"{head}: bd list failed: {err}. Nothing changed."
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
            wait = reader.poll()
            if wait and (args.polls is None or polls < args.polls):
                time.sleep(wait)
    except KeyboardInterrupt:
        pass
    finally:
        lock.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
