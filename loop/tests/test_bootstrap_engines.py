"""bootstrap.sh writes the engine and the model of each agent (lpe-6v6.3).

LOOP_CODER_ENGINE, LOOP_CODER_MODEL, LOOP_REVIEWER_ENGINE and
LOOP_REVIEWER_MODEL go into .loop/project.md. The coder runs on claude or fw,
the reviewer on claude, codex or fw. fw has no default model.
"""

from pathlib import Path

import pytest
from test_bootstrap_interactive import run_bootstrap

SKILL = Path(__file__).parents[2] / "skills/dev-env-setup/SKILL.md"


def test_defaults_write_claude_and_empty_models(tmp_path):
    project = tmp_path / "proj"
    run_bootstrap(tmp_path, project)
    text = (project / ".loop" / "project.md").read_text()
    for line in (
        "CODER_ENGINE=claude",
        "CODER_MODEL=",
        "REVIEWER_ENGINE=claude",
        "REVIEWER_MODEL=",
    ):
        assert f"\n{line}\n" in text
    assert "{{" not in text.split("## Ship mode")[0].split("```bash")[1]


def test_fw_engines_and_models_go_into_project_md(tmp_path):
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
    text = (project / ".loop" / "project.md").read_text()
    assert "\nCODER_ENGINE=fw\n" in text
    assert "\nCODER_MODEL=deepseek-flash-latest[1m]\n" in text
    assert "\nREVIEWER_ENGINE=fw\n" in text
    assert "\nREVIEWER_MODEL=kimi-latest\n" in text


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
    assert "If `fw` is on `PATH`, offer `fw`" in text
    assert "deepseek-flash-latest[1m]" in text
    for var in (
        "LOOP_CODER_ENGINE",
        "LOOP_CODER_MODEL",
        "LOOP_REVIEWER_ENGINE",
        "LOOP_REVIEWER_MODEL",
    ):
        assert var in text
