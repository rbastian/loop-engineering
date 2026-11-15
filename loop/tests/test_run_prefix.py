"""loop/run.sh passes project.bead_prefix to watch.py --summary (lpe-7fn).

watch.py matches only the project's prefix when --prefix names it, and falls
back to a greedy pattern without it. loop.toml requires the prefix, so run.sh
always passes it. This test runs one session of run.sh with
LOOP_STREAM_LOG=1 and a stub uv that records its arguments, so the cost note
step calls the stub instead of watch.py.
"""

import subprocess
from pathlib import Path

from _loop_toml import install_run_sh, uv_body
from test_run_github_account import write_exe


def summary_args(tmp_path: Path, prefix: str) -> list[str]:
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
    # run.sh also calls notify.py through uv; record only the watch.py call.
    write_exe(
        bin_dir / "uv",
        uv_body(
            f'case "$*" in *watch.py*) printf "%s\\n" "$@" >"{calls}" ;; esac\n'
            'echo "{}"\n'
        ),
    )
    write_exe(
        bin_dir / "sleep",
        '[ "$1" = 30 ] || exec /bin/sleep "$@"\nkill -TERM $PPID\n',
    )
    prompt_dir = repo / ".loop"
    run_sh = install_run_sh(prompt_dir, {"project.bead_prefix": prefix})
    (prompt_dir / "CODER.md").write_text("code\n")
    (prompt_dir / "project.md").write_text("# Project\n")
    result = subprocess.run(
        ["bash", str(run_sh), "Ralph", ".loop/CODER.md"],
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


def test_the_prefix_is_passed_to_the_summary(tmp_path):
    args = summary_args(tmp_path, "my-app")
    assert "--summary" in args
    assert args[args.index("--prefix") + 1] == "my-app"
