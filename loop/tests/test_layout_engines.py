"""skills/dev-env-setup/scripts/layout.sh: the engine and the model of each agent.

.loop/project.md names CODER_ENGINE, CODER_MODEL, REVIEWER_ENGINE and
REVIEWER_MODEL, and the environment variables of the same names override them
for one start. layout.sh passes LOOP_ENGINE and LOOP_MODEL to both run.sh
commands (lpe-6v6.3). These tests run layout.sh with a fake herdr on PATH that
records each `herdr pane run` command.
"""

import pytest
from _layout_helpers import run_layout


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
