"""Run layout.sh with a fake herdr and inspect its pane operations."""

import json
import re
import shlex
import shutil
import subprocess
from itertools import takewhile
from pathlib import Path

LAYOUT = Path(__file__).parents[2] / "skills/dev-env-setup/scripts/layout.sh"

FAKE_HERDR = """#!/bin/bash
record() {
  printf '%s' "$1" >>"$HERDR_OPS_LOG"
  shift
  printf '\\t%s' "$@" >>"$HERDR_OPS_LOG"
  printf '\\n' >>"$HERDR_OPS_LOG"
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
  "pane run")
    printf '%s\n' "$4" >>"$HERDR_LOG"
    record run "$3" "$4"
    ;;
esac
"""

BASE_LINES = [
    "CODER=Bob",
    "REVIEWER=Carol",
    "BEAD_PREFIX=demo",
]


def operation_records(tmp_path: Path) -> list[list[str]]:
    log = tmp_path / "herdr-ops.log"
    if not log.exists():
        return []
    return [line.split("\t") for line in log.read_text().splitlines()]


def run_layout(
    tmp_path: Path,
    lines: list[str],
    env: dict[str, str] | None = None,
    *,
    fw: bool = True,
    panes: list[dict] | None = None,
) -> tuple[subprocess.CompletedProcess, dict[str, dict[str, str]]]:
    """Run layout.sh and return the result and run.sh variables per agent."""
    project = tmp_path / "proj"
    (project / ".loop").mkdir(parents=True)
    trees = {}
    for agent in ("bob", "carol"):
        tree = tmp_path / f"proj-{agent}"
        tree.mkdir()
        (tree / ".git").write_text("gitdir: x\n")
        trees[agent] = tree
    overlay = BASE_LINES + [
        f"CODER_WORKTREE={trees['bob']}",
        f"REVIEWER_WORKTREE={trees['carol']}",
        *lines,
    ]
    (project / ".loop" / "project.md").write_text("\n".join(overlay) + "\n")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    herdr = bin_dir / "herdr"
    herdr.write_text(FAKE_HERDR)
    herdr.chmod(0o755)
    (bin_dir / "jq").symlink_to(shutil.which("jq"))
    if fw:
        stub = bin_dir / "fw"
        stub.write_text("#!/bin/sh\n")
        stub.chmod(0o755)

    log = tmp_path / "herdr.log"
    panes_file = tmp_path / "panes.json"
    panes_file.write_text(json.dumps({"result": {"panes": panes or []}}))
    full_env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "HERDR_ENV": "1",
        "HERDR_WORKSPACE_ID": "w1",
        "HERDR_TAB_ID": "t1",
        "HERDR_PANE_ID": "caller",
        "HERDR_LOG": str(log),
        "HERDR_OPS_LOG": str(tmp_path / "herdr-ops.log"),
        "HERDR_PANES": str(panes_file),
    }
    full_env.update(env or {})
    result = subprocess.run(
        ["bash", str(LAYOUT), str(project)],
        env=full_env,
        capture_output=True,
        text=True,
        check=False,
    )
    commands = {}
    if log.exists():
        for command in log.read_text().splitlines():
            if "/.loop/run.sh" not in command:
                continue
            words = shlex.split(command)
            prefix = takewhile(lambda w: re.match(r"\w+=", w), words)
            assigns = dict(w.split("=", 1) for w in prefix)
            role = "coder" if words[-1].endswith("CODER.md") else "reviewer"
            commands[role] = assigns
    return result, commands
