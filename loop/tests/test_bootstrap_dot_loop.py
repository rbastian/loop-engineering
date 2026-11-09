"""bootstrap.sh installs the loop into .loop/, and the gate skips it (lpe-wh5).

pytest skips folders that start with a dot by default (norecursedirs), but ruff
does not, so bootstrap.sh adds .loop to ruff's extend-exclude in pyproject.toml.
"""

import tomllib

from test_bootstrap_interactive import existing_repo, run_bootstrap

FILES = (
    "run.sh",
    "watch.py",
    "prices.json",
    "metrics.py",
    "CODER.md",
    "REVIEWER.md",
    "project.md",
)


def ruff_table(project) -> dict:
    return tomllib.loads((project / "pyproject.toml").read_text())["tool"]["ruff"]


def test_a_new_project_gets_dot_loop_and_one_ruff_exclude(tmp_path):
    project = tmp_path / "proj"
    result = run_bootstrap(tmp_path, project)
    for f in FILES:
        assert (project / ".loop" / f).is_file(), f
    assert not (project / "ralph").exists()
    assert "ralph/" not in result.stdout
    assert ".loop/project.md" in result.stdout
    assert ruff_table(project)["extend-exclude"] == [".loop"]

    run_bootstrap(tmp_path, project)
    assert ruff_table(project)["extend-exclude"] == [".loop"]


def test_ruff_skips_dot_loop_beside_an_existing_ruff_table(tmp_path):
    project = existing_repo(tmp_path)
    (project / "pyproject.toml").write_text(
        '[project]\nname = "proj"\n\n[tool.ruff]\nline-length = 100\n\n'
        '[tool.ruff.lint]\nselect = ["E"]\n'
    )
    run_bootstrap(tmp_path, project)
    ruff = ruff_table(project)
    assert ruff["line-length"] == 100
    assert ruff["extend-exclude"] == [".loop"]
    assert ruff["lint"]["select"] == ["E"]


def test_an_existing_extend_exclude_is_left_alone_with_a_hint(tmp_path):
    project = existing_repo(tmp_path)
    original = '[project]\nname = "proj"\n\n[tool.ruff]\nextend-exclude = ["vendor"]\n'
    (project / "pyproject.toml").write_text(original)
    result = run_bootstrap(tmp_path, project)
    assert ruff_table(project)["extend-exclude"] == ["vendor"]
    assert '".loop"' in result.stdout
