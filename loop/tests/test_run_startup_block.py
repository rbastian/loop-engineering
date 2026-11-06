"""loop/run.sh prints its configuration at startup and its identity per session (lpe-a2h).

After every startup check passes, run.sh prints one block: the agent and its
role, the harness label, the ship mode, the prompt, the logs, the time limit
and the harness version. Each session start line names the agent, the role
and the same label. These tests reuse the fakes from test_run_watchdog.py and
test_run_fw.py and write a project overlay beside the prompt.
"""

import importlib.util
import subprocess
from pathlib import Path

import pytest
from test_run_fw import FW_MODEL, setup_fw
from test_run_watchdog import RUN_SH, setup_loop, write_exe

WATCH = importlib.util.spec_from_file_location(
    "startup_watch", RUN_SH.parent / "watch.py"
)
watch = importlib.util.module_from_spec(WATCH)
WATCH.loader.exec_module(watch)

TOKEN = "gho_secrettoken987"
API_KEY = "fw_secretkey654"


def write_overlay(tmp_path: Path, ship: str = "pr", primary: Path | None = None):
    lines = ["CODER=Ralph", "REVIEWER=Alice", f"SHIP_MODE={ship}"]
    if ship == "pr":
        lines.append("GITHUB_ACCOUNT=rbastian")
    if primary is not None:
        lines.append(f"PRIMARY={primary}")
    (tmp_path / "project.md").write_text(
        "# Project\n\n```bash\n" + "\n".join(lines) + "\n```\n"
    )
    write_exe(tmp_path / "bin" / "gh", f"echo {TOKEN}\n")


def run_as(tmp_path: Path, env: dict[str, str], agent: str = "Alice"):
    env = {k: v for k, v in env.items() if k != "LOOP_OVERLAY"}
    return subprocess.run(
        ["bash", str(RUN_SH), agent, "CODER.md"],
        check=False,
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def block_of(stdout: str) -> list[str]:
    """The startup block: from its === title to the first blank line."""
    lines = stdout.splitlines()
    start = next(i for i, line in enumerate(lines) if line.endswith(") ==="))
    end = lines.index("", start) if "" in lines[start:] else len(lines)
    return lines[start:end]


def test_the_reviewer_on_fw_prints_the_startup_block(tmp_path):
    env = setup_fw(tmp_path)
    write_overlay(tmp_path, primary=tmp_path)
    env["LOOP_STREAM_LOG"] = "1"
    env["LOOP_LOG_DIR"] = str(tmp_path / "alice-logs")
    env["LOOP_SESSION_TIMEOUT"] = "90m"

    result = run_as(tmp_path, env)

    assert block_of(result.stdout) == [
        "=== Alice (reviewer) ===",
        f"harness  cc@fw/{FW_MODEL}",
        "ship     pr, as rbastian",
        "prompt   CODER.md + project.md",
        "logs     alice-logs",
        "timeout  90m",
        "version  unknown",
    ], result.stdout


def test_the_block_prints_before_the_first_poll(tmp_path):
    env = setup_fw(tmp_path)
    write_overlay(tmp_path, ship="local")

    result = run_as(tmp_path, env)

    out = result.stdout
    assert out.count("=== Alice (reviewer) ===") == 1
    assert out.index("=== Alice (reviewer) ===") < out.index("In-progress beads")


def test_defaults_without_logs_or_limit_or_overlay_inside_primary(tmp_path):
    env = setup_loop(tmp_path, "exit 0\n")
    write_overlay(tmp_path, ship="local")
    env["LOOP_SESSION_TIMEOUT"] = "0"

    result = run_as(tmp_path, env, agent="Ralph")

    block = block_of(result.stdout)
    assert block[0] == "=== Ralph (coder) ==="
    assert "harness  cc/claude-opus-5-5" in block
    assert "ship     local" in block
    # No PRIMARY in the overlay: the paths stay absolute.
    assert f"prompt   {tmp_path}/CODER.md + {tmp_path}/project.md" in block
    assert "logs     off" in block
    assert "timeout  none" in block


def test_no_overlay_prints_no_overlay(tmp_path):
    env = setup_loop(tmp_path, "exit 0\n")

    result = subprocess.run(
        ["bash", str(RUN_SH), "Ralph", "CODER.md"],
        check=False,
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    block = block_of(result.stdout)
    assert block[0] == "=== Ralph (unknown role) ==="
    assert f"prompt   {tmp_path}/CODER.md + no overlay" in block


@pytest.mark.parametrize(
    "agent, role",
    [("Ralph", "coder"), ("Alice", "reviewer"), ("Bob", "unknown role")],
)
def test_the_role_comes_from_the_overlay(tmp_path, agent, role):
    env = setup_loop(tmp_path, "exit 0\n")
    write_overlay(tmp_path, ship="local")

    result = run_as(tmp_path, env, agent=agent)

    assert block_of(result.stdout)[0] == f"=== {agent} ({role}) ==="


def harness_label(engine: str, model: str) -> str:
    """Run run.sh's harness_label function alone."""
    text = RUN_SH.read_text()
    start = text.index("\nharness_label() {\n")
    func = text[start : text.index("\n}\n", start) + 3]
    return subprocess.run(
        ["bash", "-c", func + 'harness_label "$1" "$2"', "-", engine, model],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.mark.parametrize(
    "engine, model, label",
    [
        ("claude", "claude-opus-5-5", "cc/claude-opus-5-5"),
        ("codex", "gpt-5.5", "codex/gpt-5.5"),
        ("codex", "", "codex/codex default"),
        ("fw", FW_MODEL, f"cc@fw/{FW_MODEL}"),
    ],
)
def test_run_sh_and_watch_py_give_the_same_label(engine, model, label):
    session = watch.Session()
    session.engine = engine
    session.model = model
    assert session.label == label
    assert harness_label(engine, model) == label


def test_the_session_start_line_names_agent_role_and_label(tmp_path):
    env = setup_fw(tmp_path)
    write_overlay(tmp_path, ship="local")

    result = run_as(tmp_path, env)

    starts = [line for line in result.stdout.splitlines() if "session starts" in line]
    assert len(starts) == 1, result.stdout
    assert starts[0].endswith(
        f"=== Alice (reviewer) on cc@fw/{FW_MODEL}: session starts ==="
    )
    assert "Starting" not in result.stdout


def test_no_token_or_key_appears_in_the_output(tmp_path):
    env = setup_fw(tmp_path)
    write_overlay(tmp_path)
    env["GH_TOKEN"] = TOKEN
    env["FIREWORKS_API_KEY"] = API_KEY

    result = run_as(tmp_path, env)

    out = result.stdout + result.stderr
    assert "=== Alice (reviewer) ===" in out
    assert TOKEN not in out
    assert API_KEY not in out


def test_print_prompt_prints_only_the_prompt(tmp_path):
    env = setup_loop(tmp_path, "exit 0\n")
    write_overlay(tmp_path, ship="local")
    env["LOOP_PRINT_PROMPT"] = "1"

    result = run_as(tmp_path, env, agent="Ralph")

    assert result.returncode == 0
    assert "===" not in result.stdout
    assert result.stdout.startswith("code\n")
