"""layout.sh opens one queue pane above each agent's loop pane (lpe-4h9.3)."""

import json
import shutil
import subprocess
from pathlib import Path

LAYOUT = Path(__file__).parents[2] / "skills/dev-env-setup/scripts/layout.sh"

FAKE_HERDR = """#!/bin/bash
record() {
  printf '%s' "$1" >>"$HERDR_LOG"
  shift
  printf '\\t%s' "$@" >>"$HERDR_LOG"
  printf '\\n' >>"$HERDR_LOG"
}
case "$1 $2" in
  "tab list") echo '{"result":{"tabs":[]}}' ;;
  "pane list") cat "$HERDR_PANES" ;;
  "tab create")
    record tab create
    echo '{"result":{"root_pane":{"pane_id":"p0"}}}'
    ;;
  "pane split")
    n=$(cat "$HERDR_LOG.n" 2>/dev/null || echo 0); n=$((n + 1)); echo "$n" >"$HERDR_LOG.n"
    record split "$3" "$5" "$7" "$9"
    echo "{\\"result\\":{\\"pane\\":{\\"pane_id\\":\\"p$n\\"}}}"
    ;;
  "pane swap") record swap "$4" "$6" ;;
  "pane rename") record rename "$3" "$4" ;;
  "pane run") record run "$3" "$4" ;;
esac
"""


def run_layout(tmp_path: Path, panes: list[dict] | None = None):
    project = tmp_path / "proj"
    (project / ".loop").mkdir(parents=True)
    trees = {}
    for agent in ("bob", "carol"):
        tree = tmp_path / f"proj-{agent}"
        tree.mkdir()
        (tree / ".git").write_text("gitdir: x\n")
        trees[agent] = tree
    (project / ".loop" / "project.md").write_text(
        "\n".join(
            [
                "CODER=Bob",
                "REVIEWER=Carol",
                "BEAD_PREFIX=demo",
                f"CODER_WORKTREE={trees['bob']}",
                f"REVIEWER_WORKTREE={trees['carol']}",
            ]
        )
        + "\n"
    )

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    herdr = bin_dir / "herdr"
    herdr.write_text(FAKE_HERDR)
    herdr.chmod(0o755)
    (bin_dir / "jq").symlink_to(shutil.which("jq"))

    log = tmp_path / "herdr.log"
    panes_file = tmp_path / "panes.json"
    panes_file.write_text(json.dumps({"result": {"panes": panes or []}}))
    result = subprocess.run(
        ["bash", str(LAYOUT), str(project)],
        env={
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "HOME": str(tmp_path),
            "HERDR_ENV": "1",
            "HERDR_WORKSPACE_ID": "w1",
            "HERDR_TAB_ID": "t1",
            "HERDR_PANE_ID": "caller",
            "HERDR_LOG": str(log),
            "HERDR_PANES": str(panes_file),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    records = []
    if log.exists():
        records = [line.split("\t") for line in log.read_text().splitlines()]
    return result, records, project


def test_queue_panes_sit_above_unchanged_loop_panes(tmp_path):
    result, records, project = run_layout(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert ["split", "p0", "down", "0.67", str(project)] in records
    assert ["split", "p1", "down", "0.67", str(project)] in records
    assert ["swap", "p2", "p0"] in records
    assert ["swap", "p3", "p1"] in records
    assert ["rename", "p0", "Bob"] in records
    assert ["rename", "p1", "Carol"] in records
    assert ["rename", "p2", "Bob queue"] in records
    assert ["rename", "p3", "Carol queue"] in records


def test_queue_commands_start_before_the_loops(tmp_path):
    result, records, project = run_layout(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    queue = LAYOUT.parent / "queue.sh"
    runs = [record for record in records if record[0] == "run"]
    agent_runs = [
        record
        for record in runs
        if "queue.sh" in record[2] or "/.loop/run.sh" in record[2]
    ]
    assert agent_runs == [
        ["run", "p2", f"'{queue}' --watch Bob"],
        ["run", "p3", f"'{queue}' --watch Carol"],
        [
            "run",
            "p0",
            f"LOOP_ENGINE=claude LOOP_MODEL='claude-opus-5-5' LOOP_STREAM_LOG=1 LOOP_SHOW_BEAD=1 LOOP_LOG_DIR=/tmp/proj-bob-sessions {project}/.loop/run.sh Bob {project}/.loop/CODER.md",
        ],
        [
            "run",
            "p1",
            f"LOOP_ENGINE=claude LOOP_MODEL='claude-sonnet-5-5' LOOP_STREAM_LOG=1 LOOP_SHOW_BEAD=1 LOOP_LOG_DIR=/tmp/proj-carol-sessions {project}/.loop/run.sh Carol {project}/.loop/REVIEWER.md",
        ],
    ]


def test_a_queue_pane_anywhere_in_the_workspace_stops_the_layout(tmp_path):
    result, records, _ = run_layout(
        tmp_path,
        [{"pane_id": "old", "tab_id": "another-tab", "label": "Old queue"}],
    )

    assert result.returncode == 1
    assert "Old queue" in result.stdout + result.stderr
    assert "close it first" in result.stdout + result.stderr
    assert not any(record[0] in ("tab", "split") for record in records)
