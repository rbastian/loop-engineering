"""Write .loop/loop.toml and a fake uv for the tests of the scripts that read it.

run.sh, layout.sh, worktrees.sh, bootstrap.sh and update.sh read loop.toml
through `uv run --quiet .../config.py`. The tests put a fake uv first on PATH.
It runs config.py with the Python that runs pytest, so that no test needs the
real uv, and passes every other script to a body that the test chooses.
"""

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).parents[2]
RUN_SH = ROOT / "loop/run.sh"
CONFIG_PY = ROOT / "loop/config.py"

# A valid file in local mode, so that run.sh needs no gh. Each value is
# "table.key": value. A value of None leaves the key out.
DEFAULTS = {
    "project.primary": "/tmp/primary",
    "project.bead_prefix": "lpe",
    "project.human": "Rob",
    "ship.mode": "local",
    "ship.github_account": "",
    "coder.name": "Ralph",
    "coder.worktree": "/tmp/primary-ralph",
    "reviewer.name": "Alice",
    "reviewer.worktree": "/tmp/primary-alice",
}


# The shell name of each key path, as config.py export prints them.
SHELL_NAMES = {
    "PRIMARY": "project.primary",
    "BEAD_PREFIX": "project.bead_prefix",
    "HUMAN": "project.human",
    "SHIP_MODE": "ship.mode",
    "GITHUB_ACCOUNT": "ship.github_account",
    "CODER": "coder.name",
    "CODER_ENGINE": "coder.engine",
    "CODER_MODEL": "coder.model",
    "CODER_WORKTREE": "coder.worktree",
    "REVIEWER": "reviewer.name",
    "REVIEWER_ENGINE": "reviewer.engine",
    "REVIEWER_MODEL": "reviewer.model",
    "REVIEWER_WORKTREE": "reviewer.worktree",
}


def values_of(lines: list[str]) -> dict[str, str]:
    """The key path values of KEY=value lines, for example CODER_MODEL=x."""
    pairs = (line.split("=", 1) for line in lines)
    return {SHELL_NAMES[key]: value for key, value in pairs}


def toml_text(values: dict[str, str | None] | None = None) -> str:
    """The text of a loop.toml: DEFAULTS with VALUES on top."""
    merged = {**DEFAULTS, **(values or {})}
    tables: dict[str, list[str]] = {}
    for path, value in merged.items():
        table, key = path.split(".")
        lines = tables.setdefault(table, [])
        if value is not None:
            # A JSON string is a valid TOML basic string.
            lines.append(f"{key} = {json.dumps(value)}")
    return "\n".join(f"[{t}]\n" + "\n".join(lines) + "\n" for t, lines in tables.items())


def write_loop_toml(path: Path, values: dict[str, str | None] | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(toml_text(values))
    return path


def install_run_sh(harness: Path, values: dict[str, str | None] | None = None) -> Path:
    """Copy run.sh and config.py into HARNESS, write loop.toml beside them,
    and return the path of the copied run.sh."""
    harness.mkdir(parents=True, exist_ok=True)
    shutil.copy(RUN_SH, harness / "run.sh")
    shutil.copy(CONFIG_PY, harness / "config.py")
    write_loop_toml(harness / "loop.toml", values)
    return harness / "run.sh"


def uv_body(other: str = "exit 1\n") -> str:
    """The body of a fake uv. OTHER runs every script but config.py, with the
    script and its arguments in $@. By default every other script fails, so
    that notify.py check turns the notifications off."""
    return (
        '[ "$1" = run ] && shift\n'
        '[ "$1" = --quiet ] && shift\n'
        f'case "$1" in *config.py) exec "{sys.executable}" "$@" ;; esac\n' + other
    )


def write_uv(bin_dir: Path, other: str = "exit 1\n") -> Path:
    bin_dir.mkdir(parents=True, exist_ok=True)
    uv = bin_dir / "uv"
    uv.write_text("#!/bin/bash\n" + uv_body(other))
    uv.chmod(0o755)
    return uv
