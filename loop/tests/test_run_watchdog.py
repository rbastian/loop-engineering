"""loop/run.sh: a wall-clock watchdog limits each session (lpe-k08).

GNU timeout counted only awake time on macOS, so a session that started before
the Mac slept ran 12h52m against a 2h limit. run.sh now starts each session in
its own process group and compares `date +%s` with the start every 5 seconds.
These tests run run.sh with a fake bd that reports one bead in progress, a
fake claude, and a fake sleep that stops run.sh at its first 30-second pause.
A fake date adds an offset from a file to the real time, to simulate a sleep.
"""

import os
import shutil
import signal
import subprocess
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

RUN_SH = Path(__file__).parents[1] / "run.sh"


def write_exe(path: Path, body: str) -> None:
    path.write_text("#!/bin/bash\n" + body)
    path.chmod(0o755)


def setup_loop(tmp_path: Path, claude_body: str) -> dict[str, str]:
    """Write the fakes and a prompt file. Returns the environment for run.sh.

    The fake claude writes its PID to claude.pid before it runs claude_body.
    The fake sleep passes every call through to the real sleep, except the
    loop's 30-second pause: there it lists run.sh's other children in
    children.txt and stops run.sh.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    write_exe(
        bin_dir / "bd",
        'case "$*" in\n'
        '  *--status=in_progress*--json*) echo \'[{"id":"lpe-x"}]\' ;;\n'
        "  *--json*) echo '[]' ;;\n"
        "esac\n",
    )
    write_exe(bin_dir / "claude", 'echo $$ >"$WORK/claude.pid"\n' + claude_body)
    write_exe(
        bin_dir / "sleep",
        'if [ "$1" = 30 ]; then\n'
        '  ps -A -o ppid= -o pid= -o command= | awk -v p="$PPID" -v me=$$ \\\n'
        "    '$1 == p && $2 != me' >\"$WORK/children.txt\"\n"
        "  kill -TERM $PPID\n"
        "  exit 0\n"
        "fi\n"
        'exec /bin/sleep "$@"\n',
    )
    write_exe(
        bin_dir / "date",
        'if [ "$1" = +%s ]; then\n'
        '  echo $(( $(/bin/date +%s) + $(cat "$WORK/offset" 2>/dev/null || echo 0) ))\n'
        "else\n"
        '  exec /bin/date "$@"\n'
        "fi\n",
    )
    # jq may sit in a folder that a test leaves off PATH.
    (bin_dir / "jq").symlink_to(shutil.which("jq") or "/usr/bin/jq")
    (tmp_path / "CODER.md").write_text("code\n")
    return {
        "PATH": f"{bin_dir}:/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": str(tmp_path),
        "WORK": str(tmp_path),
        "LOOP_OVERLAY": "none",
    }


LOOP = ["bash", str(RUN_SH), "Ralph", "CODER.md"]


def run_loop(tmp_path: Path, env: dict[str, str], timeout: float = 30):
    return subprocess.run(
        LOOP,
        check=False,
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


@contextmanager
def start_loop(tmp_path: Path, env: dict[str, str], **kw) -> Iterator[subprocess.Popen]:
    """Start run.sh in its own process group, and kill the group at the end."""
    proc = subprocess.Popen(
        LOOP, cwd=tmp_path, env=env, start_new_session=True, text=True, **kw
    )
    try:
        yield proc
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def claude_pid(tmp_path: Path) -> int:
    return int((tmp_path / "claude.pid").read_text())


def wait_for(path: Path, seconds: float = 10) -> None:
    deadline = time.monotonic() + seconds
    while not path.exists():
        assert time.monotonic() < deadline, f"{path.name} never appeared"
        time.sleep(0.05)


def test_the_watchdog_stops_a_session_that_runs_too_long(tmp_path):
    env = setup_loop(tmp_path, "exec /bin/sleep 300\n")
    env["LOOP_SESSION_TIMEOUT"] = "2s"
    start = time.monotonic()
    result = run_loop(tmp_path, env)
    assert "claude session timed out after 2s" in result.stdout
    assert time.monotonic() - start < 8, (
        "the watchdog sleeps no longer than the time left"
    )
    assert not alive(claude_pid(tmp_path))


def test_the_watchdog_counts_time_the_clock_jumped(tmp_path):
    """After a sleep, the first check sees the real elapsed time."""
    env = setup_loop(tmp_path, "exec /bin/sleep 300\n")
    env["LOOP_SESSION_TIMEOUT"] = "1h"
    with start_loop(
        tmp_path, env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    ) as proc:
        wait_for(tmp_path / "claude.pid")
        (tmp_path / "offset").write_text("3700\n")
        jumped = time.monotonic()
        out, _ = proc.communicate(timeout=20)
        assert time.monotonic() - jumped < 10
    assert "claude session timed out after 1h" in out
    assert not alive(claude_pid(tmp_path))


def test_a_normal_session_leaves_no_watchdog_running(tmp_path):
    env = setup_loop(tmp_path, "/bin/sleep 1\nexit 0\n")
    result = run_loop(tmp_path, env)
    assert "claude exited with 0" in result.stdout
    assert "timed out" not in result.stdout
    children = (tmp_path / "children.txt").read_text()
    assert children.strip() == "", f"left running: {children}"


def test_a_failed_session_reports_its_exit_code(tmp_path):
    env = setup_loop(tmp_path, "exit 3\n")
    result = run_loop(tmp_path, env)
    assert "claude exited with 3" in result.stdout


def test_ctrl_c_stops_the_session_and_the_watchdog(tmp_path):
    env = setup_loop(tmp_path, "exec /bin/sleep 300\n")
    with start_loop(
        tmp_path, env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    ) as proc:
        wait_for(tmp_path / "claude.pid")
        # Ctrl+C sends SIGINT to the terminal's foreground process group,
        # which holds run.sh but not the session's own group.
        os.killpg(proc.pid, signal.SIGINT)
        proc.wait(timeout=15)
    assert not alive(claude_pid(tmp_path))
    out = subprocess.run(
        ["ps", "-A", "-o", "command="], check=True, capture_output=True, text=True
    ).stdout
    assert str(RUN_SH) not in out, "run.sh or its watchdog is still running"


@pytest.mark.parametrize("value", ["2x", "h", "1.5h", "-1h", "2 h", "1hm"])
def test_an_invalid_timeout_stops_the_loop_at_start(tmp_path, value):
    env = setup_loop(tmp_path, "exit 0\n")
    env["LOOP_SESSION_TIMEOUT"] = value
    result = run_loop(tmp_path, env)
    assert result.returncode == 1
    assert "LOOP_SESSION_TIMEOUT" in result.stdout
    assert not (tmp_path / "claude.pid").exists()


@pytest.mark.parametrize("value", ["90", "90s", "30m", "2h", "1d", "0"])
def test_a_valid_timeout_is_accepted(tmp_path, value):
    env = setup_loop(tmp_path, "exit 0\n")
    env["LOOP_SESSION_TIMEOUT"] = value
    env["LOOP_PRINT_PROMPT"] = "1"
    result = run_loop(tmp_path, env)
    assert result.returncode == 0, result.stdout


def test_an_old_ralph_variable_is_ignored(tmp_path):
    """run.sh reads only the LOOP_ names (lpe-wh5): an old RALPH_ variable
    gets the default, with no fallback and no warning."""
    env = setup_loop(tmp_path, "exit 0\n")
    env["RALPH_SESSION_TIMEOUT"] = "bogus"
    env["LOOP_PRINT_PROMPT"] = "1"
    result = run_loop(tmp_path, env)
    assert result.returncode == 0, result.stdout
    assert "RALPH_" not in result.stdout


def test_keep_awake_runs_the_session_under_caffeinate(tmp_path):
    env = setup_loop(tmp_path, "exit 0\n")
    write_exe(
        tmp_path / "bin" / "caffeinate",
        'echo "$@" >"$WORK/caffeinate.args"\nshift\nexec "$@"\n',
    )
    env["LOOP_KEEP_AWAKE"] = "1"
    result = run_loop(tmp_path, env)
    assert "claude exited with 0" in result.stdout
    args = (tmp_path / "caffeinate.args").read_text().split()
    assert args[:2] == ["-i", "claude"]


def test_keep_awake_without_caffeinate_warns_and_continues(tmp_path):
    env = setup_loop(tmp_path, "exit 0\n")
    # /usr/bin holds caffeinate, so link every other tool it holds.
    usr_bin = tmp_path / "usr-bin"
    usr_bin.mkdir()
    for tool in Path("/usr/bin").iterdir():
        if tool.name != "caffeinate":
            (usr_bin / tool.name).symlink_to(tool)
    env["PATH"] = f"{tmp_path / 'bin'}:{usr_bin}:/bin"
    if shutil.which("caffeinate", path=env["PATH"]):
        pytest.skip("caffeinate is on the reduced PATH on this machine")
    env["LOOP_KEEP_AWAKE"] = "1"
    result = run_loop(tmp_path, env)
    assert result.stdout.count("WARNING: caffeinate not found") == 1
    assert "claude exited with 0" in result.stdout


def test_keep_awake_is_off_by_default(tmp_path):
    env = setup_loop(tmp_path, "exit 0\n")
    write_exe(tmp_path / "bin" / "caffeinate", 'touch "$WORK/caffeinate.args"\n')
    result = run_loop(tmp_path, env)
    assert "claude exited with 0" in result.stdout
    assert not (tmp_path / "caffeinate.args").exists()


def test_a_session_that_ends_before_the_watchdog_fires_is_not_a_timeout(tmp_path):
    """The clock passes the limit, but the session ends before the next check."""
    env = setup_loop(tmp_path, 'echo 3700 >"$WORK/offset"\n/bin/sleep 1\nexit 0\n')
    env["LOOP_SESSION_TIMEOUT"] = "1h"
    result = run_loop(tmp_path, env)
    assert "claude exited with 0" in result.stdout
    assert "timed out" not in result.stdout
