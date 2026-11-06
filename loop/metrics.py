#!/usr/bin/env python3
# /// script
# requires-python = ">=3.13"
# dependencies = ["rich"]
# ///
"""What each bead cost the human, and how long the loop took to ship it.

A loop can merge many beads and still leave the human with the specification,
the troubleshooting and the acceptance. Five measurements per bead show
whether the loop takes work away from the human:

1. Human time: the minutes the human spent on the bead, from the notes.
2. Lead time: from the first `loop -> coding` state change to the merge.
3. Review returns: the number of review rounds that failed.
4. Escapes: the bugs that someone found after the merge.
5. Token cost: the sum of the `Session cost:` notes of both agents.

The notes and the state change events already hold these measurements. The
interactive section of `CLAUDE.md` defines the two recording conventions that
the script needs: `Human time: <n>m <activity>` notes, and escaped bug beads
with a `discovered-from` dependency on the bead that shipped the bug.

Usage:
    uv run .loop/metrics.py             # the table, for beads with a merge
    uv run .loop/metrics.py --all       # also beads still in flight
    uv run .loop/metrics.py --json      # the same data as JSON
    uv run .loop/metrics.py --since 2026-11-01
    uv run .loop/metrics.py --by-agent  # the coder's and reviewer's cost apart
"""

import argparse
import json
import os
import re
import statistics
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

from rich.console import Console
from rich.table import Table

CODING_EVENT = "State change: loop → coding"
HUMAN_TIME_RE = re.compile(r"Human time:\s*(\d+)m\b")
REVIEW_FAILED_RE = re.compile(r"Review round \d+ failed:")
PR_OPENED_RE = re.compile(r"PR opened: #(\d+)")
COST_RE = re.compile(r"\$(\d+(?:\.\d+)?)")
SESSION_COST = "Session cost:"


def find_project_file() -> Path | None:
    """The project overlay, found from the script in loop/ or .loop/."""
    base = Path(__file__).resolve().parent
    for folder in (base, *base.parents):
        for candidate in (folder / ".loop/project.md", folder / "project.md"):
            if candidate.is_file():
                return candidate
    return None


def read_overlay(path: Path | None) -> dict[str, str]:
    values: dict[str, str] = {}
    if path is None:
        return values
    for line in path.read_text().splitlines():
        match = re.match(r"^([A-Z][A-Z0-9_]*)=(.*)$", line.strip())
        if match:
            values[match.group(1)] = match.group(2).strip()
    return values


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def warn(message: str) -> None:
    print(f"warning: {message}", file=sys.stderr)


def read_beads() -> list[dict]:
    try:
        result = subprocess.run(
            ["bd", "list", "--all", "--json", "-n", "0"],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        warn(f"bd list failed: {error}")
        return []
    if result.returncode != 0:
        warn(f"bd list failed: {result.stderr.strip()}")
        return []
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        warn(f"bd list returned invalid JSON: {error}")
        return []


class Github:
    """The PR merge data, read as the project's GitHub account."""

    def __init__(self, account: str) -> None:
        self.token = self._token(account)
        self.merged: dict[int, datetime | None] = {}
        self.warned: set[int] = set()

    def _token(self, account: str) -> str | None:
        if not account:
            return None
        try:
            result = subprocess.run(
                ["gh", "auth", "token", "--user", account],
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            warn(f"gh auth token --user {account} failed: {error}")
            return None
        if result.returncode != 0:
            warn(f"gh auth token --user {account} failed: {result.stderr.strip()}")
            return None
        return result.stdout.strip() or None

    def merged_at(self, number: int) -> datetime | None:
        if number in self.merged:
            return self.merged[number]
        env = os.environ.copy()
        if self.token:
            env["GH_TOKEN"] = self.token
        try:
            result = subprocess.run(
                ["gh", "pr", "view", str(number), "--json", "mergedAt"],
                check=False,
                capture_output=True,
                text=True,
                env=env,
                timeout=60,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            self._warn_once(number, f"gh pr view #{number} failed: {error}")
            self.merged[number] = None
            return None
        if result.returncode != 0:
            self._warn_once(
                number, f"gh pr view #{number} failed: {result.stderr.strip()}"
            )
            self.merged[number] = None
            return None
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            self._warn_once(
                number, f"gh pr view #{number} returned invalid JSON: {error}"
            )
            self.merged[number] = None
            return None
        merged = parse_time(payload.get("mergedAt"))
        self.merged[number] = merged
        return merged

    def _warn_once(self, number: int, message: str) -> None:
        if number not in self.warned:
            self.warned.add(number)
            warn(message)


def loop_events(rows: list[dict]) -> dict[str, list[dict]]:
    """The state change events of each bead, keyed by the bead ID."""
    events: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        if row.get("issue_type") != "event":
            continue
        title = row.get("title", "")
        if not title.startswith("State change: loop"):
            continue
        parent = row.get("parent")
        if not parent:
            for dependency in row.get("dependencies") or []:
                if dependency.get("type") == "parent-child":
                    parent = dependency.get("depends_on_id")
                    break
        if parent:
            events[parent].append(row)
    return events


def escape_counts(rows: list[dict]) -> Counter:
    """How many escaped bugs each bead shipped, by discovered-from edge."""
    escapes: Counter = Counter()
    for row in rows:
        if "escaped" not in (row.get("labels") or []):
            continue
        for dependency in row.get("dependencies") or []:
            if dependency.get("type") == "discovered-from":
                original = dependency.get("depends_on_id")
                if original:
                    escapes[original] += 1
    return escapes


def parse_cost(notes: str) -> tuple[float, int, dict[str, float]]:
    """The known dollar sum, the unknown sessions, and the sum per agent."""
    total = 0.0
    unknown = 0
    by_agent: dict[str, float] = {}
    for line in notes.splitlines():
        if not line.startswith(SESSION_COST):
            continue
        body = line[len(SESSION_COST) :].strip()
        agent = body.split(",", 1)[0].strip()
        match = COST_RE.search(body)
        if match:
            amount = float(match.group(1))
            total += amount
            by_agent[agent] = by_agent.get(agent, 0.0) + amount
        else:
            unknown += 1
            by_agent.setdefault(agent, 0.0)
    return total, unknown, by_agent


def first_coding_event(events: list[dict]) -> datetime | None:
    times = [
        parse_time(event.get("created_at"))
        for event in events
        if event.get("title") == CODING_EVENT
    ]
    times = [time for time in times if time is not None]
    return min(times) if times else None


def build_row(row: dict, events: list[dict], escapes: Counter, github: Github) -> dict:
    notes = row.get("notes") or ""
    human_times = [int(value) for value in HUMAN_TIME_RE.findall(notes)]
    human = sum(human_times) if human_times else None
    cost, unknown, cost_by_agent = parse_cost(notes)

    pr_match = PR_OPENED_RE.search(notes)
    pr_number = int(pr_match.group(1)) if pr_match else None
    estimated = False
    merged = None
    if pr_number is not None:
        merged = github.merged_at(pr_number)
    elif row.get("status") == "closed" and row.get("closed_at"):
        merged = parse_time(row.get("closed_at"))
        estimated = merged is not None

    coding = first_coding_event(events)
    lead = None
    if coding is not None and merged is not None:
        lead = round((merged - coding).total_seconds() / 60)

    result = {
        "id": row.get("id", ""),
        "title": row.get("title", ""),
        "human_minutes": human,
        "lead_time_minutes": lead,
        "lead_time_estimated": estimated,
        "review_returns": len(REVIEW_FAILED_RE.findall(notes)),
        "escapes": escapes.get(row.get("id", ""), 0),
        "cost": round(cost, 2),
        "unknown_cost_sessions": unknown,
    }
    result["_merged"] = merged
    result["_cost_by_agent"] = cost_by_agent
    return result


def median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def summarise(rows: list[dict], agents: list[str]) -> tuple[dict, dict]:
    humans = [row["human_minutes"] for row in rows if row["human_minutes"] is not None]
    leads = [
        row["lead_time_minutes"] for row in rows if row["lead_time_minutes"] is not None
    ]
    costs = [row["cost"] for row in rows]
    totals = {
        "human_minutes": sum(humans) if humans else None,
        "beads_without_human_time": len(rows) - len(humans),
        "lead_time_minutes": sum(leads) if leads else None,
        "review_returns": sum(row["review_returns"] for row in rows),
        "escapes": sum(row["escapes"] for row in rows),
        "cost": round(sum(costs), 2),
        "unknown_cost_sessions": sum(row["unknown_cost_sessions"] for row in rows),
    }
    medians = {
        "human_minutes": median(humans),
        "lead_time_minutes": median(leads),
        "review_returns": median([row["review_returns"] for row in rows]),
        "escapes": median([row["escapes"] for row in rows]),
        "cost": round(median(costs), 2) if costs else None,
    }
    if agents:
        totals["cost_by_agent"] = {
            agent: round(sum(row["_cost_by_agent"].get(agent, 0.0) for row in rows), 2)
            for agent in agents
        }
        medians["cost_by_agent"] = {
            agent: round(
                median(
                    [
                        row["_cost_by_agent"].get(agent)
                        for row in rows
                        if row["_cost_by_agent"].get(agent) is not None
                    ]
                )
                or 0.0,
                2,
            )
            for agent in agents
        }
    return totals, medians


def fmt_minutes(minutes: float | None) -> str:
    if minutes is None:
        return ""
    whole = round(minutes)
    hours, rest = divmod(whole, 60)
    if hours and rest:
        return f"{hours}h {rest}m"
    if hours:
        return f"{hours}h"
    return f"{rest}m"


def fmt_lead(minutes: float | None, estimated: bool) -> str:
    text = fmt_minutes(minutes)
    if text and estimated:
        return text + "*"
    return text


def fmt_cost(cost: float | None, unknown: int = 0) -> str:
    if cost is None:
        return ""
    return f"${cost:.2f}" + ("+" if unknown else "")


def fmt_number(value: float | None) -> str:
    if value is None:
        return ""
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.1f}"


def print_table(
    rows: list[dict], totals: dict, medians: dict, agents: list[str]
) -> None:
    table = Table(title="Workload metrics")
    table.add_column("Bead", no_wrap=True)
    table.add_column("Title")
    table.add_column("Human", justify="right")
    table.add_column("Lead", justify="right")
    table.add_column("Returns", justify="right")
    table.add_column("Escapes", justify="right")
    table.add_column("Cost", justify="right")
    for agent in agents:
        table.add_column(f"{agent} $", justify="right")

    for row in rows:
        cells = [
            row["id"],
            row["title"][:40],
            fmt_minutes(row["human_minutes"]),
            fmt_lead(row["lead_time_minutes"], row["lead_time_estimated"]),
            str(row["review_returns"]),
            str(row["escapes"]),
            fmt_cost(row["cost"], row["unknown_cost_sessions"]),
        ]
        cells += [fmt_cost(row["_cost_by_agent"].get(agent, 0.0)) for agent in agents]
        table.add_row(*cells)

    human_total = fmt_minutes(totals["human_minutes"])
    missing = totals["beads_without_human_time"]
    if missing:
        human_total = f"{human_total} ({missing} without)".strip()
    total_cells = [
        "Total",
        "",
        human_total,
        fmt_minutes(totals["lead_time_minutes"]),
        str(totals["review_returns"]),
        str(totals["escapes"]),
        fmt_cost(totals["cost"], totals["unknown_cost_sessions"]),
    ]
    total_cells += [
        fmt_cost(totals["cost_by_agent"].get(agent, 0.0)) if agents else ""
        for agent in agents
    ]
    table.add_row(*total_cells, style="bold")

    median_cells = [
        "Median",
        "",
        fmt_minutes(medians["human_minutes"]),
        fmt_minutes(medians["lead_time_minutes"]),
        fmt_number(medians["review_returns"]),
        fmt_number(medians["escapes"]),
        fmt_cost(medians["cost"]),
    ]
    median_cells += [
        fmt_cost(medians["cost_by_agent"].get(agent, 0.0)) if agents else ""
        for agent in agents
    ]
    table.add_row(*median_cells)

    Console().print(table)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Report the workload of each bead.")
    parser.add_argument("--all", action="store_true", help="also show unmerged beads")
    parser.add_argument("--json", action="store_true", help="print JSON, not a table")
    parser.add_argument("--since", metavar="YYYY-MM-DD", help="only beads merged since")
    parser.add_argument(
        "--by-agent", action="store_true", help="show the coder's and reviewer's cost"
    )
    args = parser.parse_args(argv)

    since = None
    if args.since:
        try:
            since = date.fromisoformat(args.since)
        except ValueError:
            parser.error(f"--since must be YYYY-MM-DD: {args.since}")

    overlay = read_overlay(find_project_file())
    account = overlay.get("GITHUB_ACCOUNT", "")
    agents = [overlay.get("CODER", "Ralph"), overlay.get("REVIEWER", "Alice")]
    agents = agents if args.by_agent else []

    rows = read_beads()
    events = loop_events(rows)
    escapes = escape_counts(rows)
    github = Github(account)

    results = []
    for row in rows:
        if row.get("issue_type") == "event":
            continue
        bead_id = row.get("id", "")
        if bead_id not in events:
            continue
        result = build_row(row, events[bead_id], escapes, github)
        merged = result.pop("_merged")
        if not args.all and merged is None:
            continue
        if since is not None and (merged is None or merged.date() < since):
            continue
        if agents:
            result["cost_by_agent"] = {
                agent: round(result["_cost_by_agent"].get(agent, 0.0), 2)
                for agent in agents
            }
        results.append(result)

    totals, medians = summarise(results, agents)
    if args.json:
        public = [
            {key: value for key, value in row.items() if not key.startswith("_")}
            for row in results
        ]
        print(
            json.dumps(
                {"beads": public, "totals": totals, "medians": medians}, indent=2
            )
        )
        return 0
    print_table(results, totals, medians, agents)
    return 0


if __name__ == "__main__":
    sys.exit(main())
