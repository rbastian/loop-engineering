"""bootstrap.sh writes .loop/loop.toml and a prose-only .loop/project.md (lpe-umq.2).

loop.toml gets the names, the ship mode, the GitHub account, the engines, the
models, the bead prefix and the paths that bootstrap.sh computes. bootstrap.sh
runs config.py check on it, and keeps an existing loop.toml.
"""

import re
import subprocess
import sys
import tomllib

from _loop_toml import CONFIG_PY
from test_bootstrap_interactive import run_bootstrap

KEY_LINE = re.compile(r"^[A-Z][A-Z0-9_]*=", re.MULTILINE)


def check(path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CONFIG_PY), "--file", str(path), "check"],
        capture_output=True,
        text=True,
        check=False,
    )


def test_bootstrap_writes_a_loop_toml_that_passes_the_check(tmp_path):
    project = tmp_path / "proj"
    result = run_bootstrap(
        tmp_path,
        project,
        {"LOOP_REVIEWER_ENGINE": "fw", "LOOP_REVIEWER_MODEL": "kimi-latest[1m]"},
        extra_stubs=("fw",),
    )
    toml = project / ".loop/loop.toml"
    assert check(toml).returncode == 0, check(toml).stderr
    assert tomllib.loads(toml.read_text()) == {
        "project": {"primary": str(project), "bead_prefix": "demo", "human": "Dana"},
        "ship": {"mode": "pr", "github_account": "dana-gh"},
        "coder": {
            "name": "Bob",
            "engine": "claude",
            "model": "",
            "worktree": f"{tmp_path}/proj-bob",
        },
        "reviewer": {
            "name": "Carol",
            "engine": "fw",
            "model": "kimi-latest[1m]",
            "worktree": f"{tmp_path}/proj-carol",
        },
    }
    assert "wrote .loop/loop.toml" in result.stdout


def test_bootstrap_keeps_an_existing_loop_toml(tmp_path):
    project = tmp_path / "proj"
    run_bootstrap(tmp_path, project)
    toml = project / ".loop/loop.toml"
    kept = toml.read_text().replace('"Dana"', '"Erin \\"E\\" Doe"')
    toml.write_text(kept)
    result = run_bootstrap(tmp_path, project, {"LOOP_HUMAN": "Frank"})
    assert toml.read_text() == kept
    assert ".loop/loop.toml exists; keeping it" in result.stdout


def test_bootstrap_stops_on_a_kept_loop_toml_that_is_not_valid(tmp_path):
    project = tmp_path / "proj"
    run_bootstrap(tmp_path, project)
    toml = project / ".loop/loop.toml"
    toml.write_text(toml.read_text().replace('mode = "pr"', 'mode = "git"'))
    result = run_bootstrap(tmp_path, project, check=False)
    assert result.returncode == 1
    assert "loop.toml: ship.mode: must be pr or local (got: git)" in result.stderr


def test_bootstrap_writes_project_md_without_key_value_lines(tmp_path):
    project = tmp_path / "proj"
    run_bootstrap(tmp_path, project)
    text = (project / ".loop/project.md").read_text()
    assert not KEY_LINE.search(text)
    assert ".loop/loop.toml" in text
