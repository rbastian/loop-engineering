"""queue.sh renders one agent's beads from bd text and JSON output."""

import json
import os
import subprocess
from pathlib import Path

QUEUE = Path(__file__).parents[2] / "skills/dev-env-setup/scripts/queue.sh"

FAKE_BD = r"""#!/usr/bin/python3
import json
import os
import sys
from pathlib import Path

root = Path(os.environ["FAKE_QUEUE"])
args = sys.argv[1:]
with (root / "calls.jsonl").open("a") as calls:
    calls.write(json.dumps({"args": args, "color": os.environ.get("CLICOLOR_FORCE", "unset")}) + "\n")

if args and args[0] == "list":
    key = "in_progress" if "--status=in_progress" in args else "assigned"
elif args and args[0] in ("ready", "blocked"):
    key = args[0]
else:
    print("unexpected bd arguments: " + " ".join(args), file=sys.stderr)
    sys.exit(9)

scenario = json.loads((root / "scenario.json").read_text())
entry = scenario.get(key, {"data": []} if key != "ready" else {"stdout": ""})
responses = entry.get("responses")
if responses is not None:
    counter = root / (key + ".counter")
    index = int(counter.read_text()) if counter.exists() else 0
    counter.write_text(str(index + 1))
    response = responses[min(index, len(responses) - 1)]
else:
    response = entry

if "data" in response:
    sys.stdout.write(json.dumps(response["data"]))
else:
    sys.stdout.write(response.get("stdout", ""))
sys.stderr.write(response.get("stderr", ""))
sys.exit(response.get("exit", 0))
"""

READY_OLD = "○ ready-2 P2 Second\n○ ready-1 P1 First"


def install_commands(tmp_path: Path) -> None:
    bd = tmp_path / "bd"
    bd.write_text(FAKE_BD)
    bd.chmod(0o755)

    sleep = tmp_path / "sleep"
    sleep.write_text(
        """#!/bin/sh
printf '%s\n' "${CLICOLOR_FORCE-unset}" >>"$FAKE_QUEUE/shell-colors"
count=0
if [ -f "$FAKE_QUEUE/sleep.counter" ]; then count="$(cat "$FAKE_QUEUE/sleep.counter")"; fi
count=$((count + 1))
printf '%s' "$count" >"$FAKE_QUEUE/sleep.counter"
if [ "$count" -ge "${WATCH_SLEEP_LIMIT:-2}" ]; then exit 42; fi
"""
    )
    sleep.chmod(0o755)

    clear = tmp_path / "clear"
    clear.write_text(
        '#!/bin/sh\nprintf "clear\\n" >>"$FAKE_QUEUE/clears"\nprintf "CLEAR\\n"\n'
    )
    clear.chmod(0o755)

    date = tmp_path / "date"
    date.write_text('#!/bin/sh\nprintf "updated 12:34:56\\n"\n')
    date.chmod(0o755)


def run_queue(tmp_path: Path, scenario: dict, *args: str, sleep_limit: int = 2):
    install_commands(tmp_path)
    (tmp_path / "scenario.json").write_text(json.dumps(scenario))
    env = {
        "PATH": f"{tmp_path}:/usr/bin:/bin",
        "FAKE_QUEUE": str(tmp_path),
        "WATCH_SLEEP_LIMIT": str(sleep_limit),
    }
    return subprocess.run(
        [str(QUEUE), *args],
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )


def calls(tmp_path: Path) -> list[dict]:
    return [
        json.loads(line) for line in (tmp_path / "calls.jsonl").read_text().splitlines()
    ]


def bead(number: str, **extra) -> dict:
    return {"id": number, "title": f"Title {number}", "labels": [], **extra}


def test_sections_states_ready_order_and_waiting_limit(tmp_path):
    waiting = [bead(f"w-{number}") for number in range(1, 5)]
    scenario = {
        "in_progress": {
            "data": [
                bead("progress-1", labels=["loop:returned", "round:2"]),
                bead("progress-2", labels=["loop:review"]),
            ]
        },
        "ready": {"stdout": READY_OLD},
        "assigned": {"data": [bead("not-blocked"), *waiting]},
        "blocked": {
            "data": [
                {
                    "id": "other-agent",
                    "title": "Not mine",
                    "blocked_by": ["other-blocker"],
                },
                *[
                    {
                        "id": item["id"],
                        "title": item["title"],
                        "blocked_by": [f"blocker-{index}", "shared"],
                    }
                    for index, item in enumerate(waiting, start=1)
                ],
            ]
        },
    }

    result = run_queue(tmp_path, scenario, "Ralph")

    assert result.returncode == 0, result.stderr
    headings = ["In progress", "Ready next", "Waiting"]
    positions = [result.stdout.index(heading) for heading in headings]
    assert positions == sorted(positions)
    assert "progress-1 [loop:returned] Title progress-1" in result.stdout
    assert "progress-2 [loop:review] Title progress-2" in result.stdout
    assert "round:2" not in result.stdout
    assert result.stdout.index("ready-2") < result.stdout.index("ready-1")
    assert "4 beads" in result.stdout
    for number in range(1, 4):
        assert f"w-{number} (blocked by: blocker-{number}, shared)" in result.stdout
    assert "w-4" not in result.stdout
    assert "other-agent" not in result.stdout
    assert "... and 1 more" in result.stdout

    assert calls(tmp_path) == [
        {
            "args": ["list", "--assignee=Ralph", "--status=in_progress", "--json"],
            "color": "1",
        },
        {"args": ["ready", "--assignee=Ralph"], "color": "1"},
        {"args": ["list", "--assignee=Ralph", "--json"], "color": "1"},
        {"args": ["blocked", "--json"], "color": "1"},
    ]


def test_empty_sections_print_none(tmp_path):
    result = run_queue(tmp_path, {}, "Alice")

    assert result.returncode == 0
    assert result.stdout.count("(none)") == 3


def test_bd_no_work_messages_count_as_empty(tmp_path):
    result = run_queue(
        tmp_path,
        {
            "ready": {
                "stdout": "✨ No ready work found (all issues have blocking dependencies)"
            }
        },
        "Alice",
    )

    assert result.returncode == 0
    assert result.stdout.count("(none)") == 3


def test_errors_stay_in_their_sections_and_do_not_stop_the_report(tmp_path):
    scenario = {
        "in_progress": {"exit": 1, "stderr": "progress database error\n"},
        "ready": {"stdout": "○ ready-1 P1 Still shown"},
        "assigned": {"exit": 1, "stderr": "assigned database error\n"},
        "blocked": {"data": [{"id": "foreign", "blocked_by": ["x"]}]},
    }

    result = run_queue(tmp_path, scenario, "Ralph")

    assert result.returncode == 0
    progress = result.stdout.split("Ready next", 1)[0]
    ready = result.stdout.split("Ready next", 1)[1].split("Waiting", 1)[0]
    waiting = result.stdout.split("Waiting", 1)[1]
    assert "progress database error" in progress
    assert "Still shown" in ready
    assert "assigned database error" in waiting
    assert "foreign" not in result.stdout


def test_watch_colors_bd_only_and_redraws_only_on_change(tmp_path):
    scenario = {
        "ready": {
            "responses": [
                {"stdout": READY_OLD},
                {"stdout": READY_OLD},
                {"stdout": "○ ready-3 P0 Changed"},
            ]
        }
    }

    result = run_queue(tmp_path, scenario, "--watch", "Ralph", sleep_limit=3)

    assert result.returncode == 42  # The fake sleep stops the otherwise endless watch.
    assert result.stdout.count("CLEAR") == 2
    assert result.stdout.count("updated 12:34:56") == 2
    assert result.stdout.count(READY_OLD) == 1
    assert result.stdout.count("ready-3") == 1
    assert (tmp_path / "clears").read_text().splitlines() == ["clear", "clear"]
    bd_calls = calls(tmp_path)
    assert len(bd_calls) == 12
    assert {call["color"] for call in bd_calls} == {"1"}
    assert (tmp_path / "shell-colors").read_text().splitlines() == ["unset"] * 3


def test_watch_continues_after_a_bd_failure(tmp_path):
    scenario = {
        "in_progress": {
            "responses": [
                {"exit": 1, "stderr": "temporary error\n"},
                {"data": [bead("recovered", labels=["loop:coding"])]},
            ]
        }
    }

    result = run_queue(tmp_path, scenario, "--watch", "Ralph")

    assert result.returncode == 42
    assert "temporary error" in result.stdout
    assert "recovered [loop:coding]" in result.stdout
    assert result.stdout.count("CLEAR") == 2


def test_missing_agent_prints_usage_and_fails(tmp_path):
    result = run_queue(tmp_path, {})

    assert result.returncode != 0
    assert "Usage: queue.sh [--watch] AGENT" in result.stderr


def test_queue_is_executable():
    assert os.access(QUEUE, os.X_OK)
