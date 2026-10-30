"""loop/run.sh: the reviewer waits for a clean primary checkout in local mode.

In local mode the reviewer merges into the primary checkout, and REVIEWER.md
exits without a merge when the primary is busy. run.sh restarted the reviewer
every 30 seconds into the same busy primary (lpe-47h). These tests run run.sh
against a scratch git repository with a fake bd, a fake agent and a fake sleep.
The fake sleep stops run.sh with SIGTERM after a set number of iterations, and
it can run a shell command on each call to change the primary between
iterations.
"""

import subprocess
from pathlib import Path

RUN_SH = Path(__file__).parents[1] / "run.sh"

BUSY_BRANCH = "primary checkout busy: on feature"
BUSY_MODIFIED = "primary checkout busy: modified tracked files"
STARTED = "Starting claude session"


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def make_primary(tmp_path: Path) -> Path:
    primary = tmp_path / "primary"
    primary.mkdir()
    git(primary, "init", "-q", "-b", "main")
    git(primary, "config", "user.email", "test@example.com")
    git(primary, "config", "user.name", "Test")
    (primary / "README.md").write_text("hello\n")
    (primary / ".beads").mkdir()
    (primary / ".beads" / "issues.jsonl").write_text("{}\n")
    git(primary, "add", "-A")
    git(primary, "commit", "-q", "-m", "init")
    return primary


def write_exe(path: Path, body: str) -> None:
    path.write_text("#!/bin/bash\n" + body)
    path.chmod(0o755)


def run_loop(
    tmp_path: Path,
    primary: Path,
    *,
    agent: str = "Alice",
    ship_mode: str = "local",
    in_progress: int = 1,
    ready: int = 0,
    iterations: int = 3,
    on_sleep: dict[int, str] | None = None,
    overlay: bool = True,
) -> str:
    """Run run.sh until the fake sleep has been called `iterations` times.

    on_sleep maps a sleep call number (1-based) to a shell command that runs
    in that call, before the next iteration starts.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    beads = ",".join('{"id":"lpe-x"}' for _ in range(in_progress))
    ready_beads = ",".join('{"id":"lpe-y"}' for _ in range(ready))
    write_exe(
        bin_dir / "bd",
        'case "$*" in\n'
        f"  *--status=in_progress*--json*) echo '[{beads}]' ;;\n"
        f"  ready*--json*) echo '[{ready_beads}]' ;;\n"
        "esac\n",
    )
    write_exe(bin_dir / "claude", 'echo "agent ran" >>"$AGENT_LOG"\n')
    hooks = "".join(f"  {n}) {cmd} ;;\n" for n, cmd in (on_sleep or {}).items())
    write_exe(
        bin_dir / "sleep",
        'n=$(( $(cat "$SLEEP_COUNT" 2>/dev/null || echo 0) + 1 ))\n'
        'echo "$n" >"$SLEEP_COUNT"\n'
        f'case "$n" in\n{hooks}esac\n'
        f'[ "$n" -lt {iterations} ] || kill -TERM $PPID\n',
    )

    prompt_dir = tmp_path / "ralph"
    prompt_dir.mkdir()
    (prompt_dir / "REVIEWER.md").write_text("review\n")
    if overlay:
        (prompt_dir / "project.md").write_text(
            "# Project\n\n```bash\nCODER=Ralph\nREVIEWER=Alice\n```\n\n"
            f"```bash\nSHIP_MODE={ship_mode}\n```\n\n"
            f"```bash\nPRIMARY={primary}\n```\n"
        )

    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "AGENT_LOG": str(tmp_path / "agent.log"),
        "SLEEP_COUNT": str(tmp_path / "sleep.count"),
    }
    if not overlay:
        env["RALPH_OVERLAY"] = "none"
    # The fake sleep stops run.sh with SIGTERM, so run.sh never exits 0.
    result = subprocess.run(
        ["bash", str(RUN_SH), agent, "ralph/REVIEWER.md"],
        check=False,
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.stdout


def test_primary_on_a_branch_blocks_the_reviewer_and_prints_once(tmp_path):
    primary = make_primary(tmp_path)
    git(primary, "checkout", "-q", "-b", "feature")
    out = run_loop(tmp_path, primary)
    assert STARTED not in out
    assert out.count(BUSY_BRANCH) == 1


def test_modified_tracked_files_block_the_reviewer_with_a_ready_bead(tmp_path):
    primary = make_primary(tmp_path)
    (primary / "README.md").write_text("changed\n")
    out = run_loop(tmp_path, primary, in_progress=0, ready=1)
    assert STARTED not in out
    assert out.count(BUSY_MODIFIED) == 1


def test_staged_files_block_the_reviewer(tmp_path):
    primary = make_primary(tmp_path)
    (primary / "new.txt").write_text("staged\n")
    git(primary, "add", "new.txt")
    out = run_loop(tmp_path, primary)
    assert STARTED not in out
    assert out.count(BUSY_MODIFIED) == 1


def test_session_starts_once_the_primary_is_clean(tmp_path):
    primary = make_primary(tmp_path)
    git(primary, "checkout", "-q", "-b", "feature")
    out = run_loop(
        tmp_path,
        primary,
        iterations=2,
        on_sleep={1: f'git -C "{primary}" checkout -q main'},
    )
    assert out.count(BUSY_BRANCH) == 1
    assert out.count(STARTED) == 1
    assert (tmp_path / "agent.log").read_text() == "agent ran\n"


def test_untracked_files_and_beads_changes_do_not_count_as_busy(tmp_path):
    primary = make_primary(tmp_path)
    (primary / "scratch.txt").write_text("untracked\n")
    (primary / ".beads" / "issues.jsonl").write_text('{"changed":1}\n')
    out = run_loop(tmp_path, primary, iterations=1)
    assert "busy" not in out
    assert STARTED in out


def test_pr_mode_ignores_a_busy_primary(tmp_path):
    primary = make_primary(tmp_path)
    git(primary, "checkout", "-q", "-b", "feature")
    out = run_loop(tmp_path, primary, ship_mode="pr", iterations=1)
    assert "busy" not in out
    assert STARTED in out


def test_coder_ignores_a_busy_primary(tmp_path):
    primary = make_primary(tmp_path)
    git(primary, "checkout", "-q", "-b", "feature")
    out = run_loop(tmp_path, primary, agent="Ralph", iterations=1)
    assert "busy" not in out
    assert STARTED in out


def test_no_overlay_skips_the_check(tmp_path):
    primary = make_primary(tmp_path)
    git(primary, "checkout", "-q", "-b", "feature")
    out = run_loop(tmp_path, primary, overlay=False, iterations=1)
    assert "busy" not in out
    assert STARTED in out


def test_no_beads_still_prints_no_beads(tmp_path):
    primary = make_primary(tmp_path)
    git(primary, "checkout", "-q", "-b", "feature")
    out = run_loop(tmp_path, primary, in_progress=0, ready=0, iterations=1)
    assert "No beads for Alice" in out
    assert "busy" not in out
