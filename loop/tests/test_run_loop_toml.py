"""loop/run.sh reads its values from .loop/loop.toml through config.py (lpe-umq.2).

At start, run.sh checks loop.toml beside it and stops with the key-path errors
of config.py when the file is not valid, before any session starts. The prompt
is the role prompt, then the prose of project.md, then the "Roles and paths"
block that config.py roles prints. These tests copy run.sh and config.py into
a scratch .loop/ folder, with a fake uv, bd, gh and claude on PATH.
"""

import subprocess
from pathlib import Path

from _loop_toml import install_run_sh, write_uv

STARTED = "session starts ==="
PROSE = "# Project\n\nThe prose that the team shares.\n"
NAMES = (
    "PRIMARY",
    "BEAD_PREFIX",
    "HUMAN",
    "SHIP_MODE",
    "GITHUB_ACCOUNT",
    "CODER",
    "CODER_ENGINE",
    "CODER_MODEL",
    "CODER_WORKTREE",
    "REVIEWER",
    "REVIEWER_ENGINE",
    "REVIEWER_MODEL",
    "REVIEWER_WORKTREE",
)


def write_exe(path: Path, body: str) -> None:
    path.write_text("#!/bin/bash\n" + body)
    path.chmod(0o755)


def setup(tmp_path: Path, toml: dict | None = None) -> tuple[Path, dict[str, str]]:
    harness = tmp_path / "primary/.loop"
    run_sh = install_run_sh(harness, toml)
    (harness / "CODER.md").write_text("The coder prompt.\n")
    (harness / "project.md").write_text(PROSE)
    bin_dir = tmp_path / "bin"
    write_uv(bin_dir)
    calls = tmp_path / "calls.log"
    write_exe(
        bin_dir / "bd",
        f'echo "bd $*" >>"{calls}"\n'
        'case "$*" in\n'
        "  *--status=in_progress*--json*) echo '[]' ;;\n"
        '  ready*--json*) echo \'[{"id":"lpe-y"}]\' ;;\n'
        "esac\n",
    )
    write_exe(bin_dir / "gh", f'echo "gh $*" >>"{calls}"\necho stub-token\n')
    write_exe(
        bin_dir / "claude",
        f'echo "claude" >>"{calls}"\nprintf "%s" "$2" >"{tmp_path / "prompt"}"\n',
    )
    write_exe(
        bin_dir / "sleep",
        '[ "$1" = 30 ] || exec /bin/sleep "$@"\nkill -TERM $PPID\n',
    )
    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "HOME": str(tmp_path),
    }
    return run_sh, env


def run(tmp_path: Path, run_sh: Path, env: dict[str, str]):
    return subprocess.run(
        ["bash", str(run_sh), "Ralph", str(run_sh.parent / "CODER.md")],
        check=False,
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def calls(tmp_path: Path) -> list[str]:
    log = tmp_path / "calls.log"
    return log.read_text().splitlines() if log.exists() else []


def roles_block(text: str) -> dict[str, str]:
    """The NAME=value lines of the Roles and paths block at the end of TEXT."""
    head, _, block = text.rpartition("## Roles and paths\n")
    assert head, text
    lines = block.split("```bash\n", 1)[1].split("```", 1)[0].splitlines()
    return dict(line.split("=", 1) for line in lines)


def test_an_invalid_loop_toml_stops_before_anything_runs(tmp_path):
    run_sh, env = setup(tmp_path, {"coder.engine": "codex", "ship.mode": "pr"})
    result = run(tmp_path, run_sh, env)
    out = result.stdout + result.stderr
    assert result.returncode == 1
    assert "loop.toml: coder.engine: must be claude or fw (got: codex)" in out
    assert "loop.toml: ship.github_account: must be set in pr mode" in out
    assert STARTED not in out
    assert calls(tmp_path) == []


def test_a_missing_loop_toml_stops_with_its_name(tmp_path):
    run_sh, env = setup(tmp_path)
    (run_sh.parent / "loop.toml").unlink()
    result = run(tmp_path, run_sh, env)
    out = result.stdout + result.stderr
    assert result.returncode == 1
    assert "loop.toml: cannot read the file" in out
    assert calls(tmp_path) == []


def test_the_print_shows_the_prompt_then_the_prose_then_the_roles(tmp_path):
    run_sh, env = setup(tmp_path, {"coder.model": "claude-opus-5-5"})
    env["LOOP_PRINT_PROMPT"] = "1"
    result = run(tmp_path, run_sh, env)
    assert result.returncode == 0, result.stderr
    text = result.stdout
    assert text.startswith("The coder prompt.\n\n\n" + PROSE)
    assert text.index(PROSE) < text.index("## Roles and paths")
    roles = roles_block(text)
    assert tuple(roles) == NAMES
    assert roles["CODER"] == "Ralph"
    assert roles["CODER_MODEL"] == "claude-opus-5-5"
    assert roles["SHIP_MODE"] == "local"
    assert calls(tmp_path) == []


def test_without_the_overlay_the_roles_follow_the_prompt(tmp_path):
    run_sh, env = setup(tmp_path)
    env["LOOP_PRINT_PROMPT"] = "1"
    env["LOOP_OVERLAY"] = "none"
    result = run(tmp_path, run_sh, env)
    assert result.stdout.startswith("The coder prompt.\n\n## Roles and paths\n")
    assert "prose" not in result.stdout


def test_each_session_gets_the_roles_block(tmp_path):
    run_sh, env = setup(tmp_path)
    result = run(tmp_path, run_sh, env)
    assert STARTED in result.stdout, result.stdout + result.stderr
    prompt = (tmp_path / "prompt").read_text()
    assert prompt.startswith("The coder prompt.\n\n" + PROSE)
    assert roles_block(prompt)["REVIEWER"] == "Alice"
