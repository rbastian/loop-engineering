#!/usr/bin/env python3
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""Send short Telegram messages to the human about the loop.

The notifier polls bd for this project's beads and sends one message when a
bead enters a loop state that the human wants to know about:

* escalated or parked: a decision message with the bead ID, the title, the
  last note and a line that asks for a reply, with sound. reply.py reads the
  replies. Each sent decision message is recorded in the shared file
  ~/.local/state/loop-telegram/sent.jsonl, so that reply.py can match a reply
  to its bead;
* blocked: the bead ID, the title and the last note, with sound;
* merge: the bead ID, the title and the PR URL, with sound;
* coding, review, returned or done: the bead ID, the title and the round,
  silently;
* a bead in coding or review with no update for longer than the stall limit,
  or an agent's run.sh that stops: once, with sound.

At start it records the current states and sends nothing, so a restart does
not resend old events. A send that fails stays queued and goes out on a later
poll, in order.

The bot token is part of every request URL, so the notifier never prints the
token, a URL or a raw exception. A failed request logs only the method, the
HTTP status and Telegram's error_code and description.

Usage, from the primary checkout:
    uv run .loop/notify.py
    uv run .loop/notify.py --stall 90m   # a stall limit other than 2h

TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID name the bot and the chat. If either
one is unset, the notifier prints one line and exits 0. TELEGRAM_API_URL
replaces https://api.telegram.org, for tests.
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
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

API_URL = "https://api.telegram.org"
# Telegram accepts 4096 characters. The margin keeps clear of that limit.
MAX_LENGTH = 4000
POLL_SECONDS = 30
# The default stall limit is run.sh's default session timeout.
STALL_DEFAULT = "2h"

DECISIONS = {"escalated", "parked"}
ESCALATIONS = {"blocked"}
PROGRESS = {"coding", "review", "returned", "done"}
STALLS = {"coding", "review"}
PR_RE = re.compile(r"PR opened: #\d+ (\S+)")


def log_line(text: str) -> None:
    print(f"{time.strftime('%H:%M:%S')}  {text}", flush=True)


def truncate(text: str, limit: int = MAX_LENGTH) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def state_dir() -> Path:
    """The folder that every repository's notifier and reply.py share."""
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


def duration_seconds(text: str) -> int:
    """Seconds in a duration such as 90, 90s, 30m, 2h or 1d, as run.sh reads them."""
    match = re.fullmatch(r"(\d+)([smhd]?)", text)
    if not match:
        raise ValueError(f"not a duration: {text}")
    unit = {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}[match.group(2)]
    return int(match.group(1)) * unit


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


def loop_in(lines: Iterable[str], projects: Iterable[str], agent: str) -> bool:
    """True when a process line runs the run.sh of one of PROJECTS for AGENT,
    as layout.sh starts it. PROJECTS holds the path as typed and as resolved."""
    commands = [f"{project}/.loop/run.sh {agent} " for project in projects]
    return any(command in line for line in lines for command in commands)


def running_loops(projects: Iterable[str], agents: Iterable[str]) -> set[str] | None:
    """The agents whose run.sh runs, from one ps call, or None when ps fails."""
    try:
        result = subprocess.run(
            ["ps", "-ax", "-o", "command="],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    lines = result.stdout.splitlines()
    return {agent for agent in agents if loop_in(lines, projects, agent)}


@dataclass
class Reply:
    ok: bool
    result: object = None
    retry_after: int | None = None


class Telegram:
    """The two Bot API calls the notifier makes: getMe and sendMessage."""

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
            self.log(f"{method} failed: network error ({type(err).__name__})")
            return Reply(ok=False)
        try:
            body = json.loads(raw)
        except ValueError:
            body = {}
        if not isinstance(body, dict):
            body = {}
        if status == 200 and body.get("ok"):
            return Reply(ok=True, result=body.get("result"))
        self.log(
            f"{method} failed: HTTP {status},"
            f" error_code {body.get('error_code', '-')}:"
            f" {body.get('description', 'no description')}"
        )
        parameters = body.get("parameters")
        retry = parameters.get("retry_after") if isinstance(parameters, dict) else None
        return Reply(ok=False, retry_after=retry if isinstance(retry, int) else None)

    def check(self) -> None:
        reply = self.call("getMe", {})
        if reply.ok and isinstance(reply.result, dict):
            self.log(f"Telegram bot @{reply.result.get('username', '?')} is ready")

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


def updated_at(bead: dict) -> float | None:
    try:
        return datetime.fromisoformat(bead["updated_at"]).timestamp()
    except (KeyError, TypeError, ValueError):
        return None


def age_text(seconds: float) -> str:
    minutes = int(seconds // 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m" if hours else f"{minutes}m"


def bead_text(head: str, bead: dict, detail: str = "") -> str:
    text = f"{head}\n{bead.get('title', '')}"
    return f"{text}\n{detail}" if detail else text


class Notifier:
    def __init__(
        self,
        *,
        project: str,
        prefix: str,
        agents: list[str],
        primary: str = "",
        telegram: Telegram,
        list_beads: Callable[[], list[dict]],
        running_agents: Callable[[], set[str] | None],
        now: Callable[[], float] = time.time,
        stall_seconds: float = duration_seconds(STALL_DEFAULT),
        log: Callable[[str], None] = log_line,
    ) -> None:
        self.project = project
        self.primary = primary
        self.prefix = prefix
        self.agents = agents
        self.telegram = telegram
        self.list_beads = list_beads
        self.running_agents = running_agents
        self.now = now
        self.stall_seconds = stall_seconds
        self.log = log
        self.states: dict[str, str | None] = {}
        self.stalled: set[str] = set()
        self.running: dict[str, bool] = {}
        # Each queued message comes with the sent.jsonl fields of a decision
        # message, or None.
        self.queue: deque[tuple[dict, dict | None]] = deque()
        self.hold_until = 0.0
        # The first bd read only records the states. start makes it, unless
        # bd fails then, and the next poll makes it.
        self.primed = False

    def ours(self, beads: list[dict]) -> list[dict]:
        if not self.prefix:
            return beads
        return [b for b in beads if str(b.get("id", "")).startswith(f"{self.prefix}-")]

    def stall_age(self, bead: dict, state: str | None) -> float | None:
        """How long the bead has had no update, when that is past the limit."""
        stamp = updated_at(bead) if state in STALLS else None
        if stamp is None:
            return None
        age = self.now() - stamp
        return age if age > self.stall_seconds else None

    def start(self) -> None:
        """Record the current states, and send nothing for them."""
        self.read_beads()
        self.check_agents()
        self.log(f"watching {len(self.states)} beads; notifications are on")

    def poll(self) -> None:
        self.read_beads()
        self.check_agents()
        self.flush()

    def read_beads(self) -> None:
        try:
            beads = self.ours(self.list_beads())
        except BdError as err:
            self.log(str(err))
            return
        mark = len(self.queue)
        for bead in beads:
            self.check_bead(bead)
        if not self.primed:
            while len(self.queue) > mark:
                self.queue.pop()
            self.primed = True

    def check_bead(self, bead: dict) -> None:
        bead_id = bead["id"]
        dims = labels_of(bead)
        state = dims.get("loop")
        if state != self.states.get(bead_id):
            self.states[bead_id] = state
            self.stalled.discard(bead_id)
            self.on_change(bead, state, dims.get("round"))
        if bead_id in self.stalled:
            return
        age = self.stall_age(bead, state)
        if age is not None:
            self.stalled.add(bead_id)
            head = f"{bead_id} stalled in {state}: no update for {age_text(age)}"
            self.queue_message(bead_text(head, bead))

    def on_change(self, bead: dict, state: str | None, round_: str | None) -> None:
        bead_id = bead["id"]
        if state in DECISIONS or state in ESCALATIONS:
            note = last_note(bead.get("notes", ""))
            detail = f"Last note: {note}" if note else ""
            text = bead_text(f"{bead_id} {state}", bead, detail)
            if state in DECISIONS:
                self.queue_decision(text, {"bead": bead_id, "state": state})
            else:
                self.queue_message(text)
        elif state == "merge":
            urls = PR_RE.findall(bead.get("notes") or "")
            detail = urls[-1] if urls else ""
            self.queue_message(bead_text(f"{bead_id} ready to merge", bead, detail))
        elif state in PROGRESS:
            head = f"{bead_id} {state}"
            if state != "done" and round_ and round_ != "0":
                head += f" (round {round_})"
            self.queue_message(bead_text(head, bead), silent=True)

    def check_agents(self) -> None:
        """Send one message when an agent's run.sh stops. An agent that is
        not running at start sends nothing."""
        running = self.running_agents()
        if running is None:
            return
        for agent in self.agents:
            if self.running.get(agent) and agent not in running:
                self.queue_message(f"{agent} loop is not running")
            self.running[agent] = agent in running

    def queue_message(self, text: str, *, silent: bool = False) -> None:
        message = {"text": truncate(f"{self.project}: {text}")}
        if silent:
            message["disable_notification"] = True
        self.queue.append((message, None))

    def queue_decision(self, text: str, record: dict) -> None:
        """A message that asks the human for a reply. A long note is cut
        before the reply line, so that the line always goes out."""
        names = " or ".join(f"{agent}:" for agent in self.agents)
        ask = (
            f"Reply to this message to answer. Start with {names} to choose the agent."
        )
        body = truncate(f"{self.project}: {text}", MAX_LENGTH - len(ask) - 1)
        message = {
            "text": f"{body}\n{ask}",
            "reply_markup": {
                "force_reply": True,
                "input_field_placeholder": "Your decision",
            },
        }
        self.queue.append((message, record))

    def flush(self) -> None:
        """Send the queued messages in order. Stop at the first failure."""
        while self.queue and self.now() >= self.hold_until:
            message, record = self.queue[0]
            reply = self.telegram.send(message)
            if not reply.ok:
                if reply.retry_after:
                    self.hold_until = self.now() + reply.retry_after
                return
            self.queue.popleft()
            if record:
                self.record_sent(reply.result, record)

    def record_sent(self, result: object, record: dict) -> None:
        """Append the sent decision message to sent.jsonl for reply.py."""
        sent = result if isinstance(result, dict) else {}
        if not isinstance(sent.get("message_id"), int):
            self.log(f"could not record {record['bead']}: Telegram sent no message_id")
            return
        chat = sent.get("chat") if isinstance(sent.get("chat"), dict) else {}
        line = {
            "message_id": sent.get("message_id"),
            "chat_id": chat.get("id", self.telegram.chat_id),
            "project": self.project,
            "primary": self.primary,
            **record,
            "sent_at": datetime.fromtimestamp(self.now(), UTC).isoformat(),
        }
        try:
            append_line(sent_path(), line)
        except OSError as err:
            self.log(f"could not record {record['bead']} in sent.jsonl: {err.strerror}")


def project_path(arg: str) -> Path:
    """ARG as an absolute path. For ".", the shell's PWD keeps the path as
    typed, where os.getcwd gives the resolved path."""
    path = Path(arg).absolute()
    pwd = os.environ.get("PWD")
    if arg == "." and pwd and Path(pwd).resolve() == path.resolve():
        return Path(pwd)
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project", default=".", help="the primary checkout")
    parser.add_argument(
        "--stall",
        default=STALL_DEFAULT,
        help="the stall limit, such as 90m or 2h (default: %(default)s)",
    )
    parser.add_argument("--interval", type=float, default=POLL_SECONDS)
    parser.add_argument("--polls", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        print(
            "notify: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is not set;"
            " notifications are off"
        )
        return 0
    try:
        stall_seconds = duration_seconds(args.stall)
    except ValueError as err:
        print(f"notify: {err}")
        return 2

    project = project_path(args.project)
    overlay = read_overlay(project / ".loop/project.md")
    agents = [overlay[k] for k in ("CODER", "REVIEWER") if overlay.get(k)]
    # layout.sh starts run.sh with the project path as typed, which can differ
    # from the resolved path when the path goes through a symbolic link.
    projects = {str(project), str(project.resolve())}
    os.chdir(project)
    telegram = Telegram(
        token, chat_id, base=os.environ.get("TELEGRAM_API_URL", API_URL)
    )
    telegram.check()
    notifier = Notifier(
        project=project.name,
        primary=overlay.get("PRIMARY") or str(project),
        prefix=overlay.get("BEAD_PREFIX", ""),
        agents=agents,
        telegram=telegram,
        list_beads=read_beads,
        running_agents=lambda: running_loops(projects, agents),
        stall_seconds=stall_seconds,
    )
    notifier.start()
    polls = 0
    try:
        while args.polls is None or polls < args.polls:
            time.sleep(args.interval)
            notifier.poll()
            polls += 1
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
