"""loop/run.sh: a killed sleep does not end the loop, but Ctrl+C still does.

run.sh runs under set -e and waits between iterations with sleep. A stray
kill of every "sleep 30" on the machine once stopped four loops at once
(lpe-qi4). These tests run run.sh with a fake bd that reports no beads and a
fake sleep, so run.sh only prints "No beads" and waits.
"""

import os
import signal
import subprocess
import time
from pathlib import Path

RUN_SH = Path(__file__).parents[1] / "run.sh"

NO_BEADS = "No beads for Ralph"


def write_exe(path: Path, body: str) -> None:
    path.write_text("#!/bin/bash\n" + body)
    path.chmod(0o755)


def setup_loop(tmp_path: Path, sleep_body: str) -> dict[str, str]:
    """Write a fake bd with no beads, the given fake sleep and a prompt file.

    Returns the environment for run.sh. The fake sleep counts its calls in
    $SLEEP_COUNT before it runs sleep_body.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    write_exe(bin_dir / "bd", "echo '[]'\n")
    write_exe(
        bin_dir / "sleep",
        'n=$(( $(cat "$SLEEP_COUNT" 2>/dev/null || echo 0) + 1 ))\n'
        'echo "$n" >"$SLEEP_COUNT"\n' + sleep_body,
    )
    (tmp_path / "CODER.md").write_text("code\n")
    return {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "RALPH_OVERLAY": "none",
        "SLEEP_COUNT": str(tmp_path / "sleep.count"),
    }


def sleep_count(tmp_path: Path) -> int:
    try:
        return int((tmp_path / "sleep.count").read_text())
    except (FileNotFoundError, ValueError):
        return 0


def test_a_killed_sleep_does_not_end_the_loop(tmp_path):
    # The first sleep kills itself with SIGKILL, the third stops run.sh.
    env = setup_loop(
        tmp_path,
        'case "$n" in\n  1) kill -9 $$ ;;\n  3) kill -TERM $PPID ;;\nesac\n',
    )
    result = subprocess.run(
        ["bash", str(RUN_SH), "Ralph", "CODER.md"],
        check=False,
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert sleep_count(tmp_path) == 3
    assert result.stdout.count(NO_BEADS) >= 2


def test_ctrl_c_stops_the_loop(tmp_path):
    # The fake shadows sleep on PATH, so the real sleep needs its full path.
    env = setup_loop(tmp_path, "exec /bin/sleep 30\n")
    proc = subprocess.Popen(
        ["bash", str(RUN_SH), "Ralph", "CODER.md"],
        cwd=tmp_path,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 10
        while sleep_count(tmp_path) == 0:
            assert time.monotonic() < deadline, "run.sh never reached its sleep"
            time.sleep(0.05)
        # Ctrl+C sends SIGINT to the whole foreground process group.
        os.killpg(proc.pid, signal.SIGINT)
        proc.wait(timeout=5)
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
