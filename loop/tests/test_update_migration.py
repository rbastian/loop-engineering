"""update.sh migrates the KEY=value lines of an old project.md to loop.toml (lpe-umq.2).

The fixture is this repository's .loop/project.md at commit 25a95f3, the last
form with the thirteen KEY=value lines in three bash code fences. update.sh
writes .loop/loop.toml from them, checks it with config.py, and removes the
lines and their empty fences from project.md. It never overwrites a
loop.toml, and a migration that fails the check changes nothing.
"""

import shlex
import subprocess
import sys
from pathlib import Path

from _loop_toml import CONFIG_PY
from test_update import (
    advance_clone,
    commit_all,
    make_clone,
    make_project,
    run_update,
    snapshot,
)

FIXTURE = Path(__file__).parent / "fixtures/project-25a95f3.md"
KEYS = (
    "CODER",
    "REVIEWER",
    "HUMAN",
    "CODER_ENGINE",
    "CODER_MODEL",
    "REVIEWER_ENGINE",
    "REVIEWER_MODEL",
    "BEAD_PREFIX",
    "SHIP_MODE",
    "GITHUB_ACCOUNT",
    "PRIMARY",
    "CODER_WORKTREE",
    "REVIEWER_WORKTREE",
)


def is_key_line(line: str) -> bool:
    return line.split("=", 1)[0] in KEYS and "=" in line


def old_values(text: str) -> dict[str, str]:
    lines = [line for line in text.splitlines() if is_key_line(line)]
    return dict(line.split("=", 1) for line in lines)


def export(toml: Path) -> dict[str, str]:
    out = subprocess.run(
        [sys.executable, str(CONFIG_PY), "--file", str(toml), "export"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return dict(shlex.split(line)[0].split("=", 1) for line in out.splitlines())


def old_project(tmp_path: Path, text: str) -> tuple[Path, Path]:
    """A project whose .loop/ has the old project.md TEXT and no loop.toml."""
    clone = make_clone(tmp_path)
    project = make_project(tmp_path, clone)
    (project / ".loop/loop.toml").unlink()
    (project / ".loop/project.md").write_text(text)
    commit_all(project, "an install from before loop.toml")
    advance_clone(clone)
    return clone, project


def test_the_fixture_has_the_thirteen_keys():
    assert sorted(old_values(FIXTURE.read_text())) == sorted(KEYS)


def test_migration_writes_loop_toml_and_strips_project_md(tmp_path):
    text = FIXTURE.read_text()
    clone, project = old_project(tmp_path, text)

    result = run_update(tmp_path, clone, project)

    assert result.returncode == 0, result.stdout + result.stderr
    assert export(project / ".loop/loop.toml") == old_values(text)

    new = (project / ".loop/project.md").read_text()
    old_lines, new_lines = text.splitlines(keepends=True), new.splitlines(keepends=True)
    # Only lines were removed: the new file is the old one with gaps.
    removed, i = [], 0
    for line in old_lines:
        if i < len(new_lines) and new_lines[i] == line:
            i += 1
        else:
            removed.append(line)
    assert i == len(new_lines)
    assert sorted(removed) == sorted(
        [line for line in old_lines if is_key_line(line.rstrip("\n"))]
        + ["```bash\n", "```\n", "\n"] * 3
    )
    assert "## Roles\n\n`$CODER` is the agent" in new
    assert "## Ship mode\n\n`SHIP_MODE` is `pr` or `local`" in new
    assert "## Paths\n\n`PRIMARY` is the primary checkout" in new
    # The format commands and the gate keep their fences.
    assert new.count("```bash\n") == 2

    assert "+++ .loop/project.md" in result.stdout
    assert "-CODER=Ralph" in result.stdout
    assert "commit it" in result.stdout


def test_missing_engines_and_models_get_their_defaults(tmp_path):
    text = "".join(
        line
        for line in FIXTURE.read_text().splitlines(keepends=True)
        if not line.startswith(("CODER_ENGINE=", "CODER_MODEL=", "REVIEWER_"))
        or line.startswith("REVIEWER_WORKTREE=")
    )
    clone, project = old_project(tmp_path, text)

    result = run_update(tmp_path, clone, project)

    assert result.returncode == 0, result.stdout + result.stderr
    values = export(project / ".loop/loop.toml")
    assert values["CODER_ENGINE"] == values["REVIEWER_ENGINE"] == "claude"
    assert values["CODER_MODEL"] == values["REVIEWER_MODEL"] == ""
    assert values["REVIEWER"] == "Alice"


def test_migration_never_overwrites_a_loop_toml(tmp_path):
    text = FIXTURE.read_text()
    clone, project = old_project(tmp_path, text)
    toml = project / ".loop/loop.toml"
    kept = (
        f'[project]\nprimary = "{project}"\nbead_prefix = "keep"\nhuman = "Kim"\n\n'
        '[ship]\nmode = "local"\n\n'
        f'[coder]\nname = "Kai"\nworktree = "{project}-kai"\n\n'
        f'[reviewer]\nname = "Lee"\nworktree = "{project}-lee"\n'
    )
    toml.write_text(kept)

    result = run_update(tmp_path, clone, project)

    assert result.returncode == 0, result.stdout + result.stderr
    assert toml.read_text() == kept
    assert (project / ".loop/project.md").read_text() == text
    assert ".loop/loop.toml exists; no migration" in result.stdout


def test_a_failed_check_after_a_migration_keeps_the_migration(tmp_path):
    text = FIXTURE.read_text()
    clone, project = old_project(tmp_path, text)
    (project / ".loop/PROMPT.md").write_text("old prompt\n")

    result = run_update(tmp_path, clone, project)

    assert result.returncode == 1
    assert export(project / ".loop/loop.toml") == old_values(text)
    assert "changed nothing after the migration: 1 check(s) failed" in result.stdout


def test_a_migration_that_fails_the_check_changes_nothing(tmp_path):
    text = FIXTURE.read_text().replace("SHIP_MODE=pr", "SHIP_MODE=git")
    clone, project = old_project(tmp_path, text)
    before = snapshot(project)

    result = run_update(tmp_path, clone, project)

    assert result.returncode == 1
    assert snapshot(project) == before
    assert not (project / ".loop/loop.toml").exists()
    assert "loop.toml: ship.mode: must be pr or local (got: git)" in result.stderr
    assert "changed nothing" in result.stdout
