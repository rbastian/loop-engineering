"""loop/run.sh passes the overlay's BEAD_PREFIX to watch.py --summary (lpe-7fn).

watch.py matches only the project's prefix when --prefix names it, and falls
back to a greedy pattern without it. These tests run one session of run.sh with
LOOP_STREAM_LOG=1 and a stub uv that records its arguments, so the cost note
step calls the stub instead of watch.py.
"""

import subprocess
from pathlib import Path

import pytest
from test_run_github_account import RUN_SH, write_exe


def summary_args(tmp_path: Path, overlay_lines: str) -> list[str]:
    """Run one session and return the arguments that run.sh gave uv."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(repo)], check=True, capture_output=True
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "uv.args"
    write_exe(
        bin_dir / "bd",
        'case "$*" in\n'
        "  *--status=in_progress*--json*) echo '[]' ;;\n"
        '  ready*--json*) echo \'[{"id":"my-app-abc"}]\' ;;\n'
        "esac\n",
    )
    write_exe(bin_dir / "claude", "")
    write_exe(bin_dir / "uv", f'printf "%s\\n" "$@" >"{calls}"\necho "{{}}"\n')
    write_exe(
        bin_dir / "sleep",
        '[ "$1" = 30 ] || exec /bin/sleep "$@"\nkill -TERM $PPID\n',
    )
    prompt_dir = repo / ".loop"
    prompt_dir.mkdir()
    (prompt_dir / "CODER.md").write_text("code\n")
    (prompt_dir / "project.md").write_text(
        "# Project\n\n```bash\nCODER=Ralph\nREVIEWER=Alice\n"
        f"{overlay_lines}```\n\n```bash\nSHIP_MODE=local\nGITHUB_ACCOUNT=\n```\n"
    )
    result = subprocess.run(
        ["bash", str(RUN_SH), "Ralph", ".loop/CODER.md"],
        check=False,
        cwd=repo,
        env={
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "HOME": str(tmp_path),
            "LOOP_STREAM_LOG": "1",
            "LOOP_LOG_DIR": str(tmp_path / "logs"),
        },
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert calls.exists(), result.stdout + result.stderr
    return calls.read_text().splitlines()


def test_a_set_prefix_is_passed_to_the_summary(tmp_path):
    args = summary_args(tmp_path, "BEAD_PREFIX=my-app\n")
    assert "--summary" in args
    assert args[args.index("--prefix") + 1] == "my-app"


@pytest.mark.parametrize("overlay_lines", ["BEAD_PREFIX=\n", ""])
def test_an_empty_or_missing_prefix_passes_nothing(tmp_path, overlay_lines):
    args = summary_args(tmp_path, overlay_lines)
    assert "--summary" in args
    assert "--prefix" not in args
