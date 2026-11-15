"""bootstrap.sh writes the engine and the model of each agent (lpe-6v6.3).

LOOP_CODER_ENGINE, LOOP_CODER_MODEL, LOOP_REVIEWER_ENGINE and
LOOP_REVIEWER_MODEL go into .loop/loop.toml. The coder runs on claude or fw,
the reviewer on claude, codex or fw. fw has no default model.
"""

import tomllib
from pathlib import Path

import pytest
from test_bootstrap_interactive import run_bootstrap

SKILL = Path(__file__).parents[2] / "skills/dev-env-setup/SKILL.md"


def roles(project: Path) -> dict:
    values = tomllib.loads((project / ".loop" / "loop.toml").read_text())
    return {role: values[role] for role in ("coder", "reviewer")}


def test_defaults_write_claude_and_empty_models(tmp_path):
    project = tmp_path / "proj"
    run_bootstrap(tmp_path, project)
    for role in roles(project).values():
        assert role["engine"] == "claude"
        assert role["model"] == ""


def test_fw_engines_and_models_go_into_loop_toml(tmp_path):
    project = tmp_path / "proj"
    run_bootstrap(
        tmp_path,
        project,
        {
            "LOOP_CODER_ENGINE": "fw",
            "LOOP_CODER_MODEL": "deepseek-flash-latest[1m]",
            "LOOP_REVIEWER_ENGINE": "fw",
            "LOOP_REVIEWER_MODEL": "kimi-latest",
        },
        extra_stubs=("fw",),
    )
    values = roles(project)
    assert values["coder"]["engine"] == "fw"
    assert values["coder"]["model"] == "deepseek-flash-latest[1m]"
    assert values["reviewer"]["engine"] == "fw"
    assert values["reviewer"]["model"] == "kimi-latest"


def test_codex_for_the_coder_is_rejected(tmp_path):
    project = tmp_path / "proj"
    result = run_bootstrap(
        tmp_path,
        project,
        {"LOOP_CODER_ENGINE": "codex"},
        check=False,
        extra_stubs=("codex",),
    )
    assert result.returncode == 1
    assert "LOOP_CODER_ENGINE" in result.stdout
    assert not (project / ".loop" / "project.md").exists()
    assert not (project / ".loop" / "loop.toml").exists()


@pytest.mark.parametrize("role", ["CODER", "REVIEWER"])
def test_fw_with_an_empty_model_is_rejected(tmp_path, role):
    project = tmp_path / "proj"
    result = run_bootstrap(
        tmp_path,
        project,
        {f"LOOP_{role}_ENGINE": "fw"},
        check=False,
        extra_stubs=("fw",),
    )
    assert result.returncode == 1
    assert f"LOOP_{role}_MODEL" in result.stdout
    assert not (project / ".loop" / "project.md").exists()


def test_fw_is_a_required_tool_when_an_agent_uses_it(tmp_path):
    project = tmp_path / "proj"
    result = run_bootstrap(
        tmp_path,
        project,
        {"LOOP_REVIEWER_ENGINE": "fw", "LOOP_REVIEWER_MODEL": "kimi-latest"},
        check=False,
    )
    assert result.returncode == 1
    assert "fw not found" in result.stdout


def test_a_model_with_shell_or_sed_characters_is_rejected(tmp_path):
    project = tmp_path / "proj"
    result = run_bootstrap(
        tmp_path,
        project,
        {"LOOP_CODER_ENGINE": "fw", "LOOP_CODER_MODEL": "a#b'c"},
        check=False,
        extra_stubs=("fw",),
    )
    assert result.returncode == 1
    assert "LOOP_CODER_MODEL" in result.stdout


def test_skill_asks_the_engine_of_each_agent():
    text = SKILL.read_text()
    assert "The coder's engine" in text
    assert "The reviewer's engine" in text
    assert "If `fw` is on `PATH`, offer `fw`." in text
    assert "deepseek-flash-latest[1m]" in text
    for var in (
        "LOOP_CODER_ENGINE",
        "LOOP_CODER_MODEL",
        "LOOP_REVIEWER_ENGINE",
        "LOOP_REVIEWER_MODEL",
    ):
        assert var in text
