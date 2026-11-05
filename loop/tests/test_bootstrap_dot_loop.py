"""bootstrap.sh installs the loop into .loop/, and the gate skips it (lpe-wh5).

pytest skips folders that start with a dot by default (norecursedirs), but ruff
does not, so bootstrap.sh adds .loop to ruff's extend-exclude in pyproject.toml.
"""

import tomllib

from test_bootstrap_interactive import existing_repo, run_bootstrap

FILES = ("run.sh", "watch.py", "CODER.md", "REVIEWER.md", "project.md")


def ruff_excludes(project) -> list[str]:
    config = tomllib.loads((project / "pyproject.toml").read_text())
    return config["tool"]["ruff"]["extend-exclude"]


def test_the_harness_goes_into_dot_loop(tmp_path):
    project = tmp_path / "proj"
    result = run_bootstrap(tmp_path, project)
    for f in FILES:
        assert (project / ".loop" / f).is_file(), f
    assert not (project / "ralph").exists()
    assert "ralph/" not in result.stdout
    assert ".loop/project.md" in result.stdout


def test_ruff_skips_dot_loop_in_a_new_project(tmp_path):
    project = tmp_path / "proj"
    run_bootstrap(tmp_path, project)
    assert ".loop" in ruff_excludes(project)


def test_ruff_skips_dot_loop_beside_an_existing_ruff_table(tmp_path):
    project = existing_repo(tmp_path)
    (project / "pyproject.toml").write_text(
        '[project]\nname = "proj"\n\n[tool.ruff]\nline-length = 100\n\n'
        '[tool.ruff.lint]\nselect = ["E"]\n'
    )
    run_bootstrap(tmp_path, project)
    config = tomllib.loads((project / "pyproject.toml").read_text())
    assert config["tool"]["ruff"]["line-length"] == 100
    assert config["tool"]["ruff"]["extend-exclude"] == [".loop"]
    assert config["tool"]["ruff"]["lint"]["select"] == ["E"]


def test_an_existing_extend_exclude_is_left_alone_with_a_hint(tmp_path):
    project = existing_repo(tmp_path)
    original = '[project]\nname = "proj"\n\n[tool.ruff]\nextend-exclude = ["vendor"]\n'
    (project / "pyproject.toml").write_text(original)
    result = run_bootstrap(tmp_path, project)
    assert ruff_excludes(project) == ["vendor"]
    assert '".loop"' in result.stdout


def test_a_second_run_adds_no_second_exclude(tmp_path):
    project = tmp_path / "proj"
    run_bootstrap(tmp_path, project)
    run_bootstrap(tmp_path, project)
    assert ruff_excludes(project) == [".loop"]
