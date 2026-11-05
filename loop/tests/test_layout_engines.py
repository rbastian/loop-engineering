"""skills/dev-env-setup/scripts/layout.sh: the engine and the model of each agent.

.loop/project.md names CODER_ENGINE, CODER_MODEL, REVIEWER_ENGINE and
REVIEWER_MODEL, and the environment variables of the same names override them
for one start. layout.sh passes LOOP_ENGINE and LOOP_MODEL to both run.sh
commands (lpe-6v6.3). These tests run layout.sh with a fake herdr on PATH that
records each `herdr pane run` command.
"""

import re
import shlex
import shutil
import subprocess
from itertools import takewhile
from pathlib import Path

import pytest

LAYOUT = Path(__file__).parents[2] / "skills/dev-env-setup/scripts/layout.sh"

FAKE_HERDR = """#!/bin/bash
case "$1 $2" in
  "tab list") echo '{"result":{"tabs":[]}}' ;;
  "pane list") echo '{"result":{"panes":[]}}' ;;
  "tab create") echo '{"result":{"root_pane":{"pane_id":"p0"}}}' ;;
  "pane split")
    n=$(cat "$HERDR_LOG.n" 2>/dev/null || echo 0); n=$((n + 1)); echo "$n" >"$HERDR_LOG.n"
    echo "{\\"result\\":{\\"pane\\":{\\"pane_id\\":\\"p$n\\"}}}" ;;
  "pane run") printf '%s\\n' "$4" >>"$HERDR_LOG" ;;
esac
"""

BASE_LINES = [
    "CODER=Bob",
    "REVIEWER=Carol",
    "BEAD_PREFIX=demo",
]


def run_layout(
    tmp_path: Path,
    lines: list[str],
    env: dict[str, str] | None = None,
    *,
    fw: bool = True,
) -> tuple[subprocess.CompletedProcess, dict[str, dict[str, str]]]:
    """Run layout.sh; return the result and the run.sh variables per agent."""
    project = tmp_path / "proj"
    (project / ".loop").mkdir(parents=True)
    trees = {}
    for agent in ("bob", "carol"):
        tree = tmp_path / f"proj-{agent}"
        tree.mkdir()
        (tree / ".git").write_text("gitdir: x\n")
        trees[agent] = tree
    overlay = BASE_LINES + [
        f"CODER_WORKTREE={trees['bob']}",
        f"REVIEWER_WORKTREE={trees['carol']}",
        *lines,
    ]
    (project / ".loop" / "project.md").write_text("\n".join(overlay) + "\n")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    herdr = bin_dir / "herdr"
    herdr.write_text(FAKE_HERDR)
    herdr.chmod(0o755)
    (bin_dir / "jq").symlink_to(shutil.which("jq"))
    if fw:
        stub = bin_dir / "fw"
        stub.write_text("#!/bin/sh\n")
        stub.chmod(0o755)

    log = tmp_path / "herdr.log"
    full_env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "HERDR_ENV": "1",
        "HERDR_WORKSPACE_ID": "w1",
        "HERDR_TAB_ID": "t1",
        "HERDR_PANE_ID": "caller",
        "HERDR_LOG": str(log),
    }
    full_env.update(env or {})
    result = subprocess.run(
        ["bash", str(LAYOUT), str(project)],
        env=full_env,
        capture_output=True,
        text=True,
        check=False,
    )
    commands = {}
    if log.exists():
        for command in log.read_text().splitlines():
            if "/.loop/run.sh" not in command:
                continue
            words = shlex.split(command)
            prefix = takewhile(lambda w: re.match(r"\w+=", w), words)
            assigns = dict(w.split("=", 1) for w in prefix)
            role = "coder" if words[-1].endswith("CODER.md") else "reviewer"
            commands[role] = assigns
    return result, commands


def test_reviewer_on_fw_gets_engine_and_model_from_project_md(tmp_path):
    result, commands = run_layout(
        tmp_path,
        ["REVIEWER_ENGINE=fw", "REVIEWER_MODEL=deepseek-flash-latest[1m]"],
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert commands["reviewer"]["LOOP_ENGINE"] == "fw"
    assert commands["reviewer"]["LOOP_MODEL"] == "deepseek-flash-latest[1m]"
    assert commands["coder"]["LOOP_ENGINE"] == "claude"


def test_coder_on_fw_gets_engine_and_model_from_project_md(tmp_path):
    result, commands = run_layout(
        tmp_path,
        ["CODER_ENGINE=fw", "CODER_MODEL=deepseek-flash-latest[1m]"],
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert commands["coder"]["LOOP_ENGINE"] == "fw"
    assert commands["coder"]["LOOP_MODEL"] == "deepseek-flash-latest[1m]"
    assert commands["reviewer"]["LOOP_ENGINE"] == "claude"


@pytest.mark.parametrize("role", ["CODER", "REVIEWER"])
def test_fw_with_an_empty_model_exits_1(tmp_path, role):
    result, commands = run_layout(tmp_path, [f"{role}_ENGINE=fw", f"{role}_MODEL="])
    assert result.returncode == 1
    assert f"{role}_MODEL" in result.stdout
    assert commands == {}


@pytest.mark.parametrize("role", ["CODER", "REVIEWER"])
def test_fw_missing_from_path_exits_1(tmp_path, role):
    result, commands = run_layout(
        tmp_path,
        [f"{role}_ENGINE=fw", f"{role}_MODEL=deepseek-flash-latest[1m]"],
        fw=False,
    )
    assert result.returncode == 1
    assert "fw" in result.stdout
    assert commands == {}


def test_old_project_md_keeps_todays_defaults(tmp_path):
    result, commands = run_layout(tmp_path, [])
    assert result.returncode == 0, result.stdout + result.stderr
    assert commands["coder"]["LOOP_ENGINE"] == "claude"
    assert commands["coder"]["LOOP_MODEL"] == "claude-opus-5-5"
    assert commands["reviewer"]["LOOP_ENGINE"] == "claude"
    assert commands["reviewer"]["LOOP_MODEL"] == "claude-sonnet-5-5"


def test_empty_fields_on_claude_give_the_defaults(tmp_path):
    result, commands = run_layout(
        tmp_path,
        [
            "CODER_ENGINE=claude",
            "CODER_MODEL=",
            "REVIEWER_ENGINE=claude",
            "REVIEWER_MODEL=",
        ],
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert commands["coder"]["LOOP_MODEL"] == "claude-opus-5-5"
    assert commands["reviewer"]["LOOP_MODEL"] == "claude-sonnet-5-5"


def test_environment_overrides_project_md_for_one_start(tmp_path):
    result, commands = run_layout(
        tmp_path,
        [
            "CODER_ENGINE=claude",
            "CODER_MODEL=claude-opus-5-5",
            "REVIEWER_ENGINE=claude",
            "REVIEWER_MODEL=claude-sonnet-5-5",
        ],
        {
            "CODER_ENGINE": "fw",
            "CODER_MODEL": "kimi-latest",
            "REVIEWER_ENGINE": "fw",
            "REVIEWER_MODEL": "deepseek-flash-latest[1m]",
        },
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert commands["coder"]["LOOP_ENGINE"] == "fw"
    assert commands["coder"]["LOOP_MODEL"] == "kimi-latest"
    assert commands["reviewer"]["LOOP_ENGINE"] == "fw"
    assert commands["reviewer"]["LOOP_MODEL"] == "deepseek-flash-latest[1m]"
    assert "(fw)" in result.stdout


def test_engine_override_drops_the_model_of_the_other_engine(tmp_path):
    """A model in project.md belongs to the engine in project.md. An override
    to claude does not hand a Fireworks model to Claude Code."""
    result, commands = run_layout(
        tmp_path,
        ["REVIEWER_ENGINE=fw", "REVIEWER_MODEL=deepseek-flash-latest[1m]"],
        {"REVIEWER_ENGINE": "claude"},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert commands["reviewer"]["LOOP_ENGINE"] == "claude"
    assert commands["reviewer"]["LOOP_MODEL"] == "claude-sonnet-5-5"


def test_codex_is_not_allowed_for_the_coder(tmp_path):
    result, commands = run_layout(tmp_path, ["CODER_ENGINE=codex"])
    assert result.returncode == 1
    assert "CODER_ENGINE" in result.stdout
    assert commands == {}


def test_summary_names_both_engines(tmp_path):
    result, _ = run_layout(
        tmp_path,
        ["CODER_ENGINE=fw", "CODER_MODEL=deepseek-flash-latest[1m]"],
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Bob: p0 (fw)" in result.stdout
    assert "(claude)" in result.stdout
