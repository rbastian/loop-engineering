"""loop/run.sh keeps scheduled wakeups out of Claude Code sessions (lpe-9lp).

A scheduled wakeup can keep claude -p alive after its final result. The claude
and fw engines block ScheduleWakeup and CronCreate. codex has neither tool.
Each engine runs against a stub that records its arguments, one per line.
"""

import pytest
from test_run_fw import DISALLOWED_TOOL_ARGS, lines_of, setup_fw
from test_run_watchdog import run_loop, setup_loop, write_exe


@pytest.mark.parametrize("engine", ["claude", "fw", "codex"])
def test_engine_tool_restrictions(tmp_path, engine):
    if engine == "fw":
        env = setup_fw(tmp_path)
        args_path = tmp_path / "fw.args"
    else:
        env = setup_loop(tmp_path, "exit 0\n")
        env["LOOP_ENGINE"] = engine
        write_exe(
            tmp_path / "bin" / engine,
            'printf \'%s\\n\' "$@" >"$WORK/agent.args"\n',
        )
        args_path = tmp_path / "agent.args"

    result = run_loop(tmp_path, env)

    assert f"{engine} exited with 0" in result.stdout, result.stdout + result.stderr
    args = lines_of(args_path)
    if engine == "codex":
        assert "--disallowedTools" not in args
        return

    flag = args.index("--disallowedTools")
    assert args[flag : flag + len(DISALLOWED_TOOL_ARGS)] == DISALLOWED_TOOL_ARGS
    if engine == "claude":
        assert args[flag - 1] == "--dangerously-skip-permissions"
    else:
        assert args.index("--") < flag
