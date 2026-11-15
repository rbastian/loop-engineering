"""loop/run.sh sends the Telegram messages through notify.py (lpe-de2).

run.sh takes a snapshot of the bead states before each session and reports
the changes after it. It sends one message when a session times out, one when
three sessions in a row fail, and one when the loop stops. These tests copy
run.sh into a fake .loop/ folder beside a fake notify.py, which logs each call.
A fake uv runs the script it gets, and a fake direnv logs its folder. A fake
claude takes its exit codes from a file, and a fake sleep stops run.sh after
a set number of 30-second pauses.
"""

import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

from test_run_watchdog import RUN_SH, wait_for, write_exe

ROOT = Path(__file__).parents[2]
TOKEN = "123456:SECRET-token-value"


def setup(tmp_path: Path, codes: list[str], stop_after: int = 1) -> dict[str, str]:
    """Write the fakes. Returns the environment for run.sh.

    codes holds one exit code per session; "sleep" makes a session that runs
    until the watchdog stops it.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    harness = tmp_path / "primary/.loop"
    harness.mkdir(parents=True)
    shutil.copy(RUN_SH, harness / "run.sh")
    write_exe(
        harness / "notify.py",
        'echo "$*" >>"$WORK/notify.log"\n'
        'env | grep "^TELEGRAM_" | sort >"$WORK/notify.env"\n'
        'if [ "$1" = check ]; then exit "$(cat "$WORK/check-exit" 2>/dev/null || echo 0)"; fi\n'
        'exit "$(cat "$WORK/notify-exit" 2>/dev/null || echo 0)"\n',
    )
    write_exe(
        bin_dir / "uv",
        '[ "$1" = run ] && shift\n[ "$1" = --quiet ] && shift\nexec "$@"\n',
    )
    write_exe(
        bin_dir / "bd",
        'case "$*" in\n'
        '  *--status=in_progress*--json*) echo \'[{"id":"lpe-x"}]\' ;;\n'
        "  *--json*) echo '[]' ;;\n"
        "esac\n",
    )
    write_exe(
        bin_dir / "claude",
        'echo $$ >"$WORK/claude.pid"\n'
        'env | grep "^TELEGRAM_" >>"$WORK/claude.env"\n'
        'echo session >>"$WORK/notify.log"\n'
        'code=$(head -1 "$WORK/codes")\n'
        'tail -n +2 "$WORK/codes" >"$WORK/codes.tmp"\n'
        'mv "$WORK/codes.tmp" "$WORK/codes"\n'
        'if [ "$code" = sleep ]; then exec /bin/sleep 300; fi\n'
        'exit "${code:-0}"\n',
    )
    write_exe(
        bin_dir / "sleep",
        'if [ "$1" = 30 ]; then\n'
        '  n=$(( $(cat "$WORK/pauses" 2>/dev/null || echo 0) + 1 ))\n'
        '  echo "$n" >"$WORK/pauses"\n'
        '  [ "$n" -lt "$STOP_AFTER" ] || kill -TERM $PPID\n'
        "  exit 0\n"
        "fi\n"
        'exec /bin/sleep "$@"\n',
    )
    (bin_dir / "jq").symlink_to(shutil.which("jq") or "/usr/bin/jq")
    (tmp_path / "codes").write_text("".join(f"{c}\n" for c in codes))
    work = tmp_path / "work"
    work.mkdir()
    (work / "CODER.md").write_text("code\n")
    return {
        "PATH": f"{bin_dir}:/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": str(tmp_path),
        "WORK": str(tmp_path),
        "TMPDIR": str(tmp_path),
        "LOOP_OVERLAY": "none",
        "STOP_AFTER": str(stop_after),
    }


def command(tmp_path: Path) -> list[str]:
    return ["bash", str(tmp_path / "primary/.loop/run.sh"), "Ralph", "CODER.md"]


def run(tmp_path: Path, env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        command(tmp_path),
        check=False,
        cwd=tmp_path / "work",
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def calls(tmp_path: Path) -> list[str]:
    log = tmp_path / "notify.log"
    return log.read_text().splitlines() if log.exists() else []


def sends(tmp_path: Path) -> list[str]:
    return [c for c in calls(tmp_path) if c.startswith("send ")]


def test_snapshot_before_and_report_after_each_session(tmp_path):
    env = setup(tmp_path, ["0", "0"], stop_after=2)
    result = run(tmp_path, env)
    log = calls(tmp_path)
    assert log[0] == "check", result.stdout
    snapshot = log[1].split(" ", 1)[1]
    assert log[1:] == [
        f"snapshot {snapshot}",
        "session",
        f"report {snapshot} --agent Ralph",
        f"snapshot {snapshot}",
        "session",
        f"report {snapshot} --agent Ralph",
        "send Ralph loop stopped (exit 143)",
    ]
    assert Path(snapshot).parent == tmp_path


def test_the_snapshot_goes_in_the_session_log_folder(tmp_path):
    env = setup(tmp_path, ["0"])
    env["LOOP_STREAM_LOG"] = "1"
    env["LOOP_LOG_DIR"] = str(tmp_path / "logs")
    run(tmp_path, env)
    snapshot = calls(tmp_path)[1].split(" ", 1)[1]
    assert Path(snapshot).parent == tmp_path / "logs"


def test_a_timeout_sends_one_message(tmp_path):
    env = setup(tmp_path, ["sleep"])
    env["LOOP_SESSION_TIMEOUT"] = "1s"
    result = run(tmp_path, env)
    assert "claude session timed out after 1s" in result.stdout
    assert sends(tmp_path) == [
        "send Ralph session timed out after 1s on lpe-x",
        "send Ralph loop stopped (exit 143)",
    ]


def test_three_failed_sessions_in_a_row_send_one_message(tmp_path):
    env = setup(tmp_path, ["1", "2", "3", "4", "0", "5", "6", "7"], stop_after=8)
    run(tmp_path, env)
    assert sends(tmp_path) == [
        "send Ralph: 3 sessions in a row failed, last exit 3",
        "send Ralph: 3 sessions in a row failed, last exit 7",
        "send Ralph loop stopped (exit 143)",
    ]


def test_a_success_resets_the_failure_count(tmp_path):
    env = setup(tmp_path, ["1", "1", "0", "1", "1"], stop_after=5)
    run(tmp_path, env)
    assert sends(tmp_path) == ["send Ralph loop stopped (exit 143)"]


def test_a_timeout_is_not_a_failed_session(tmp_path):
    env = setup(tmp_path, ["1", "1", "sleep"], stop_after=3)
    env["LOOP_SESSION_TIMEOUT"] = "1s"
    run(tmp_path, env)
    assert not any("in a row failed" in s for s in sends(tmp_path))


def test_ctrl_c_sends_one_loop_stopped_message(tmp_path):
    env = setup(tmp_path, ["sleep"])
    proc = subprocess.Popen(
        command(tmp_path),
        cwd=tmp_path / "work",
        env=env,
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        wait_for(tmp_path / "claude.pid")
        os.killpg(proc.pid, signal.SIGINT)
        assert proc.wait(timeout=20) == 130
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
    deadline = time.monotonic() + 5
    while not sends(tmp_path) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert sends(tmp_path) == ["send Ralph loop stopped (exit 130)"]


def test_failing_notify_calls_change_no_exit_code(tmp_path):
    env = setup(tmp_path, ["0", "4"], stop_after=2)
    (tmp_path / "notify-exit").write_text("7\n")
    result = run(tmp_path, env)
    assert "claude exited with 0" in result.stdout
    assert "claude exited with 4" in result.stdout
    assert calls(tmp_path).count("session") == 2
    assert result.returncode == 143


def test_notify_runs_without_direnv_when_direnv_is_missing(tmp_path):
    env = setup(tmp_path, ["0"])
    run(tmp_path, env)
    assert calls(tmp_path)
    assert not (tmp_path / "direnv.log").exists()


def test_notify_runs_through_direnv_in_the_primary_checkout(tmp_path):
    env = setup(tmp_path, ["0"])
    write_exe(
        tmp_path / "bin/direnv",
        'echo "$1 $2" >>"$WORK/direnv.log"\nshift 2\nexec "$@"\n',
    )
    run(tmp_path, env)
    primary = tmp_path / "primary"
    direnv = (tmp_path / "direnv.log").read_text().splitlines()
    assert len(direnv) == len(calls(tmp_path)) - calls(tmp_path).count("session")
    assert set(direnv) == {f"exec {primary}"}


def test_telegram_variables_reach_notify_but_not_the_agent(tmp_path):
    env = setup(tmp_path, ["0"])
    env.update(
        {
            "TELEGRAM_BOT_TOKEN": TOKEN,
            "TELEGRAM_CHAT_ID": "4242",
            "TELEGRAM_API_URL": "http://127.0.0.1:9",
        }
    )
    result = run(tmp_path, env)
    assert (tmp_path / "claude.env").read_text() == ""
    assert (tmp_path / "notify.env").read_text().splitlines() == [
        "TELEGRAM_API_URL=http://127.0.0.1:9",
        f"TELEGRAM_BOT_TOKEN={TOKEN}",
        "TELEGRAM_CHAT_ID=4242",
    ]
    assert TOKEN not in result.stdout + result.stderr


def test_the_startup_block_says_notifications_on(tmp_path):
    env = setup(tmp_path, ["0"])
    result = run(tmp_path, env)
    block = result.stdout.split("\n\n", 1)[0]
    assert "notifications on" in block.splitlines()


def test_the_startup_block_says_notifications_off_when_the_check_fails(tmp_path):
    env = setup(tmp_path, ["0"])
    (tmp_path / "check-exit").write_text("1\n")
    result = run(tmp_path, env)
    block = result.stdout.split("\n\n", 1)[0]
    assert "notifications off" in block.splitlines()
    assert calls(tmp_path) == ["check", "session"]


def test_without_uv_notifications_are_off(tmp_path):
    env = setup(tmp_path, ["0"])
    (tmp_path / "bin/uv").unlink()
    result = run(tmp_path, env)
    assert "notifications off" in result.stdout.split("\n\n", 1)[0].splitlines()
    assert calls(tmp_path) == ["session"]
    assert "claude exited with 0" in result.stdout


def test_the_docs_say_that_run_sh_sends_the_messages():
    readme = (ROOT / "loop/README.md").read_text()
    skill = (ROOT / "skills/dev-env-setup/SKILL.md").read_text()
    for text in (readme, skill):
        assert "`run.sh` sends" in text
        assert "TELEGRAM_BOT_TOKEN" in text
        assert ".envrc" in text
        assert "BotFather" in text
        assert "notifier pane" not in text.lower()
        assert "| notifier |" not in text
        assert "`notifier`" not in text
    for event in ("timed out", "in a row failed", "loop stopped"):
        assert event in readme
