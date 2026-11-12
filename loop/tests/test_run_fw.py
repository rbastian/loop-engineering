"""loop/run.sh: LOOP_ENGINE=fw runs Claude Code on a Fireworks model (lpe-6v6.1).

fw (~/.local/bin/fw) starts one Claude Code process against the Fireworks
endpoint. Usage: fw --model MODEL [--check] [-- CLAUDE_ARGUMENTS...]. These
tests reuse the fakes from test_run_watchdog.py and add a fake fw that records
its arguments, one per line, in fw.args and fw.checks.
"""

import json
import time

import pytest
from test_run_watchdog import alive, claude_pid, run_loop, setup_loop, write_exe

FW_MODEL = "deepseek-flash-latest[1m]"
FW_ERROR = "fw: FIREWORKS_API_KEY is not set"
STREAM_FLAGS = ["--verbose", "--output-format", "stream-json"]
DISALLOWED_TOOL_ARGS = ["--disallowedTools", "ScheduleWakeup", "CronCreate"]


def setup_fw(tmp_path, session_body: str = "exit 0\n") -> dict[str, str]:
    """The watchdog fakes plus a fake fw, and the environment for LOOP_ENGINE=fw.

    The fake fw records the arguments of each call, one per line: a --check
    call in fw.checks, a session in fw.args. It answers --check with a line on
    stdout, or with FW_ERROR on stderr and exit 2 when FW_CHECK_FAIL is set.
    A session writes claude.pid, so the watchdog helpers find it.
    """
    env = setup_loop(tmp_path, "exit 0\n")
    write_exe(
        tmp_path / "bin" / "fw",
        'if [ "${3:-}" = --check ]; then\n'
        '  printf \'%s\\n\' "$@" >"$WORK/fw.checks"\n'
        '  if [ -n "${FW_CHECK_FAIL:-}" ]; then echo "'
        + FW_ERROR
        + '" >&2; exit 2; fi\n'
        '  echo "fw check passed"\n'
        "  exit 0\n"
        "fi\n"
        'echo $$ >"$WORK/claude.pid"\n'
        'printf \'%s\\n\' "$@" >"$WORK/fw.args"\n' + session_body,
    )
    env["LOOP_ENGINE"] = "fw"
    env["LOOP_MODEL"] = FW_MODEL
    return env


def lines_of(path) -> list[str]:
    return path.read_text().splitlines()


@pytest.mark.parametrize("stream_log", [True, False])
def test_an_fw_session_runs_claude_code_through_fw(tmp_path, stream_log):
    env = setup_fw(tmp_path)
    if stream_log:
        env["LOOP_STREAM_LOG"] = "1"
        env["LOOP_LOG_DIR"] = str(tmp_path / "logs")

    result = run_loop(tmp_path, env)

    assert "fw exited with 0" in result.stdout, result.stdout
    assert lines_of(tmp_path / "fw.args") == [
        "--model",
        FW_MODEL,
        "--",
        "-p",
        "code",
        "--dangerously-skip-permissions",
        *DISALLOWED_TOOL_ARGS,
        *(STREAM_FLAGS if stream_log else []),
    ]
    assert lines_of(tmp_path / "fw.checks") == ["--model", FW_MODEL, "--check"]
    assert "fw check passed" not in result.stdout, "the check output was not discarded"
    if stream_log:
        first = json.loads(lines_of(tmp_path / "logs" / "current.jsonl")[0])
        assert first["type"] == "loop.session"
        assert first["engine"] == "fw"
        assert first["model"] == FW_MODEL


def test_fw_without_a_model_stops_the_loop_at_start(tmp_path):
    env = setup_fw(tmp_path)
    del env["LOOP_MODEL"]

    result = run_loop(tmp_path, env)

    assert result.returncode == 1
    assert (
        "ERROR: LOOP_ENGINE=fw needs LOOP_MODEL, for example deepseek-flash-latest[1m]"
        in result.stdout
    )
    assert not (tmp_path / "claude.pid").exists()


def test_fw_not_on_path_stops_the_loop_before_any_session(tmp_path):
    env = setup_fw(tmp_path)
    (tmp_path / "bin" / "fw").unlink()

    result = run_loop(tmp_path, env)

    assert result.returncode == 1
    assert "ERROR: LOOP_ENGINE=fw needs fw on PATH" in result.stdout
    assert "Starting" not in result.stdout
    assert not (tmp_path / "claude.pid").exists()


def test_a_failed_fw_check_stops_the_loop_and_prints_its_error(tmp_path):
    env = setup_fw(tmp_path)
    env["FW_CHECK_FAIL"] = "1"

    result = run_loop(tmp_path, env)

    assert result.returncode == 1
    assert FW_ERROR in result.stdout + result.stderr
    assert "Starting" not in result.stdout
    assert not (tmp_path / "claude.pid").exists()


def test_the_watchdog_stops_an_fw_session_that_runs_too_long(tmp_path):
    env = setup_fw(tmp_path, "exec /bin/sleep 300\n")
    env["LOOP_SESSION_TIMEOUT"] = "2s"
    start = time.monotonic()

    result = run_loop(tmp_path, env)

    assert "fw session timed out after 2s" in result.stdout
    assert time.monotonic() - start < 8
    assert not alive(claude_pid(tmp_path))


def test_an_unknown_engine_names_all_three(tmp_path):
    env = setup_loop(tmp_path, "exit 0\n")
    env["LOOP_ENGINE"] = "pi"

    result = run_loop(tmp_path, env)

    assert result.returncode == 1
    assert "LOOP_ENGINE must be claude, codex or fw (got: pi)" in result.stdout
