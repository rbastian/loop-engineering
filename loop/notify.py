#!/usr/bin/env python3
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""Send short Telegram messages to the human about the loop.

The notifier polls bd for this project's beads and sends one message when a
bead enters a loop state that the human wants to know about:

* escalated or blocked: the bead ID, the title and the last note, with sound;
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

Usage:
    uv run loop/notify.py --project DIR   # DIR holds .loop/project.md

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
from datetime import datetime
from pathlib import Path

API_URL = "https://api.telegram.org"
# Telegram accepts 4096 characters. The margin keeps clear of that limit.
MAX_LENGTH = 4000
POLL_SECONDS = 30
# The default stall limit is run.sh's default session timeout.
STALL_DEFAULT = "2h"

ESCALATIONS = {"escalated", "blocked"}
PROGRESS = {"coding", "review", "returned", "done"}
STALLS = {"coding", "review"}
PR_RE = re.compile(r"PR opened: #\d+ (\S+)")


def log_line(text: str) -> None:
    print(f"{time.strftime('%H:%M:%S')}  {text}", flush=True)


def truncate(text: str) -> str:
    if len(text) <= MAX_LENGTH:
        return text
    return text[: MAX_LENGTH - 3] + "..."


def duration_seconds(text: str) -> int:
    """Seconds in a duration such as 90, 90s, 30m, 2h or 1d, as run.sh reads them."""
    match = re.fullmatch(r"(\d+)([smhd]?)", text)
    if not match:
        raise ValueError(f"not a duration: {text}")
    unit = {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}[match.group(2)]
    return int(match.group(1)) * unit


def overlay_value(path: Path, key: str) -> str:
    """The value of the first KEY=value line in .loop/project.md, or ""."""
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return ""
    prefix = f"{key}="
    return next((line[len(prefix) :] for line in lines if line.startswith(prefix)), "")


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


def loop_in(lines: Iterable[str], project: str, agent: str) -> bool:
    """True when a process line runs PROJECT's run.sh for AGENT, as layout.sh starts it."""
    command = f"{project}/.loop/run.sh {agent} "
    return any(command in line for line in lines)


def run_sh_running(project: str, agent: str) -> bool | None:
    """Whether AGENT's run.sh runs, or None when ps fails."""
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
    return loop_in(result.stdout.splitlines(), project, agent)


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


class Notifier:
    def __init__(
        self,
        *,
        project: str,
        prefix: str,
        agents: list[str],
        telegram: Telegram,
        list_beads: Callable[[], list[dict]],
        agent_running: Callable[[str], bool | None],
        now: Callable[[], float] = time.time,
        stall_seconds: float = duration_seconds(STALL_DEFAULT),
        log: Callable[[str], None] = log_line,
    ) -> None:
        self.project = project
        self.prefix = prefix
        self.agents = agents
        self.telegram = telegram
        self.list_beads = list_beads
        self.agent_running = agent_running
        self.now = now
        self.stall_seconds = stall_seconds
        self.log = log
        self.states: dict[str, str | None] = {}
        self.stalled: set[str] = set()
        self.running: dict[str, bool | None] = {}
        self.queue: deque[dict] = deque()
        self.hold_until = 0.0

    def ours(self, beads: list[dict]) -> list[dict]:
        if not self.prefix:
            return beads
        return [b for b in beads if str(b.get("id", "")).startswith(f"{self.prefix}-")]

    def stalls(self, bead: dict, state: str | None) -> bool:
        if state not in STALLS:
            return False
        stamp = updated_at(bead)
        return stamp is not None and self.now() - stamp > self.stall_seconds

    def start(self) -> None:
        """Record the current states, and send nothing for them."""
        try:
            beads = self.ours(self.list_beads())
        except BdError as err:
            self.log(str(err))
            beads = []
        for bead in beads:
            state = labels_of(bead).get("loop")
            self.states[bead["id"]] = state
            if self.stalls(bead, state):
                self.stalled.add(bead["id"])
        for agent in self.agents:
            self.running[agent] = self.agent_running(agent)
        self.log(f"watching {len(self.states)} beads; notifications are on")

    def poll(self) -> None:
        try:
            beads = self.ours(self.list_beads())
        except BdError as err:
            self.log(str(err))
        else:
            for bead in beads:
                self.check_bead(bead)
        for agent in self.agents:
            self.check_agent(agent)
        self.flush()

    def check_bead(self, bead: dict) -> None:
        bead_id = bead["id"]
        dims = labels_of(bead)
        state = dims.get("loop")
        if state != self.states.get(bead_id):
            self.states[bead_id] = state
            self.stalled.discard(bead_id)
            self.on_change(bead, state, dims.get("round"))
        if bead_id not in self.stalled and self.stalls(bead, state):
            self.stalled.add(bead_id)
            age = self.now() - (updated_at(bead) or self.now())
            self.queue_message(
                f"{bead_id} stalled in {state}: no update for {age_text(age)}",
                bead,
            )

    def on_change(self, bead: dict, state: str | None, round_: str | None) -> None:
        bead_id = bead["id"]
        if state in ESCALATIONS:
            note = last_note(bead.get("notes", ""))
            self.queue_message(
                f"{bead_id} {state}", bead, f"Last note: {note}" if note else ""
            )
        elif state == "merge":
            match = PR_RE.findall(bead.get("notes") or "")
            self.queue_message(
                f"{bead_id} ready to merge", bead, match[-1] if match else ""
            )
        elif state in PROGRESS:
            head = f"{bead_id} {state}"
            if state != "done" and round_ and round_ != "0":
                head += f" (round {round_})"
            self.queue_message(head, bead, silent=True)

    def check_agent(self, agent: str) -> None:
        running = self.agent_running(agent)
        if running is None:
            return
        if self.running.get(agent) and not running:
            self.queue.append(
                {"text": truncate(f"{self.project}: {agent} loop is not running")}
            )
        self.running[agent] = running

    def queue_message(
        self, head: str, bead: dict, detail: str = "", *, silent: bool = False
    ) -> None:
        text = f"{self.project}: {head}\n{bead.get('title', '')}"
        if detail:
            text += f"\n{detail}"
        message = {"text": truncate(text)}
        if silent:
            message["disable_notification"] = True
        self.queue.append(message)

    def flush(self) -> None:
        """Send the queued messages in order. Stop at the first failure."""
        while self.queue and self.now() >= self.hold_until:
            reply = self.telegram.send(self.queue[0])
            if not reply.ok:
                if reply.retry_after:
                    self.hold_until = self.now() + reply.retry_after
                return
            self.queue.popleft()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project", default=".", help="the primary checkout")
    parser.add_argument(
        "--stall",
        default=STALL_DEFAULT,
        help="the stall limit, such as 90m or 2h (default: 2h)",
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

    project = Path(args.project).absolute()
    overlay = project / ".loop/project.md"
    agents = [
        name
        for name in (
            overlay_value(overlay, "CODER"),
            overlay_value(overlay, "REVIEWER"),
        )
        if name and "{{" not in name
    ]
    os.chdir(project)
    telegram = Telegram(
        token, chat_id, base=os.environ.get("TELEGRAM_API_URL", API_URL)
    )
    telegram.check()
    notifier = Notifier(
        project=project.name,
        prefix=overlay_value(overlay, "BEAD_PREFIX"),
        agents=agents,
        telegram=telegram,
        list_beads=read_beads,
        agent_running=lambda agent: run_sh_running(str(project), agent),
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
