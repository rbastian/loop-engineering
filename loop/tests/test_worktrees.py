"""skills/dev-env-setup/scripts/worktrees.sh reads .loop/loop.toml (lpe-umq.2).

worktrees.sh checks loop.toml through loop/config.py first, and stops with
the error of each key path before it commits or creates a worktree. These
tests run it under /bin/bash, which is bash 3.2 on macOS, with a fake uv.
"""

import subprocess
from pathlib import Path

from _loop_toml import ROOT, write_loop_toml, write_uv

WORKTREES = ROOT / "skills/dev-env-setup/scripts/worktrees.sh"
GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
    "GIT_CONFIG_GLOBAL": "/dev/null",
}


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        env={"PATH": "/usr/bin:/bin", **GIT_ENV},
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def make_project(tmp_path: Path, values: dict) -> Path:
    project = (tmp_path / "proj").resolve()
    project.mkdir()
    git(project, "init", "-q", "-b", "main")
    (project / "README.md").write_text("hello\n")
    write_loop_toml(
        project / ".loop/loop.toml",
        {
            "project.primary": str(project),
            "coder.worktree": f"{project}-ralph",
            "reviewer.worktree": f"{project}-alice",
            **values,
        },
    )
    return project


def run_worktrees(tmp_path: Path, project: Path) -> subprocess.CompletedProcess:
    bin_dir = tmp_path / "bin"
    write_uv(bin_dir, "exit 0\n")
    bd = bin_dir / "bd"
    bd.write_text("#!/bin/bash\necho '[]'\n")
    bd.chmod(0o755)
    return subprocess.run(
        ["/bin/bash", str(WORKTREES), str(project)],
        env={"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path), **GIT_ENV},
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def test_an_invalid_loop_toml_stops_before_any_commit_or_worktree(tmp_path):
    project = make_project(
        tmp_path, {"ship.mode": "git", "coder.worktree": "proj-ralph"}
    )
    result = run_worktrees(tmp_path, project)
    assert result.returncode == 1
    assert "loop.toml: ship.mode: must be pr or local (got: git)" in result.stderr
    assert (
        "loop.toml: coder.worktree: must be an absolute path (got: proj-ralph)"
        in result.stderr
    )
    assert "is not valid" in result.stdout
    assert "==> commit" not in result.stdout
    assert git(project, "worktree", "list").count("\n") == 0
    assert not (tmp_path / "proj-alice").exists()


def test_a_missing_loop_toml_stops_with_a_hint(tmp_path):
    project = make_project(tmp_path, {})
    (project / ".loop/loop.toml").unlink()
    result = run_worktrees(tmp_path, project)
    assert result.returncode == 1
    assert ".loop/loop.toml missing" in result.stdout
    assert "bootstrap.sh" in result.stdout
    assert "==> commit" not in result.stdout


def test_a_valid_loop_toml_creates_both_worktrees(tmp_path):
    project = make_project(tmp_path, {})
    result = run_worktrees(tmp_path, project)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (Path(f"{project}-ralph") / ".git").exists()
    assert (Path(f"{project}-alice") / ".git").exists()
    assert "Ralph's worktree" in result.stdout
    assert "Alice's worktree" in result.stdout
