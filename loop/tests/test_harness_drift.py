"""The harness version stamp and the drift warning (lpe-bl1).

bootstrap.sh writes .loop/HARNESS_VERSION. layout.sh and run.sh read it and
print one line when the clone has newer commits on the installed files.
"""

import re
import subprocess
from pathlib import Path

import pytest
from test_bootstrap_interactive import run_bootstrap
from test_update import (
    FILES,
    GIT_ENV,
    ROOT,
    UPDATE,
    add_listed_file,
    advance_clone,
    commit_all,
    git,
    make_clone,
    make_project,
    run_update,
)

LAYOUT = ROOT / "skills/dev-env-setup/scripts/layout.sh"
RUN_SH = ROOT / "loop/run.sh"
LIB_SH = ROOT / "skills/dev-env-setup/scripts/lib.sh"
BOOTSTRAP = ROOT / "skills/dev-env-setup/scripts/bootstrap.sh"


def stamp_lines(project: Path) -> list[str]:
    return (project / ".loop/HARNESS_VERSION").read_text().splitlines()


# Case 1: bootstrap.sh writes the stamp.


def test_bootstrap_writes_the_stamp(tmp_path):
    clone = make_clone(tmp_path)
    project = tmp_path / "proj"
    run_bootstrap(tmp_path, project, {"LOOP_HOME": str(clone)})
    assert stamp_lines(project) == [
        f"commit={git(clone, 'rev-parse', 'HEAD')}",
        f"clone={clone}",
    ]


def test_bootstrap_marks_a_dirty_clone(tmp_path):
    clone = make_clone(tmp_path)
    coder = clone / "loop/CODER.md"
    coder.write_text(coder.read_text() + "uncommitted\n")
    project = tmp_path / "proj"
    result = run_bootstrap(tmp_path, project, {"LOOP_HOME": str(clone)})
    assert stamp_lines(project) == [
        f"commit={git(clone, 'rev-parse', 'HEAD')}",
        f"clone={clone}",
        "dirty=1",
    ]
    assert "WARNING" in result.stdout
    assert "uncommitted" in result.stdout


def test_bootstrap_keeps_an_existing_stamp(tmp_path):
    clone = make_clone(tmp_path)
    project = tmp_path / "proj"
    run_bootstrap(tmp_path, project, {"LOOP_HOME": str(clone)})
    before = stamp_lines(project)
    advance_clone(clone)
    run_bootstrap(tmp_path, project, {"LOOP_HOME": str(clone)})
    assert stamp_lines(project) == before


# Case 8: layout.sh prints the drift line.

HERDR_STUB = """#!/bin/bash
echo '{"result":{"tabs":[],"panes":[],"root_pane":{"pane_id":"p1"},"pane":{"pane_id":"p2"}}}'
"""


def run_layout(tmp_path: Path, project: Path) -> subprocess.CompletedProcess:
    bin_dir = tmp_path / "layout-bin"
    bin_dir.mkdir(exist_ok=True)
    herdr = bin_dir / "herdr"
    herdr.write_text(HERDR_STUB)
    herdr.chmod(0o755)
    for tree in (f"{project}-bob", f"{project}-carol"):
        Path(tree).mkdir(exist_ok=True)
        Path(tree, ".git").write_text("gitdir: elsewhere\n")
    result = subprocess.run(
        ["/bin/bash", str(LAYOUT), str(project)],
        env={
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "HOME": str(tmp_path),
            "HERDR_ENV": "1",
            "HERDR_WORKSPACE_ID": "w1",
            "HERDR_TAB_ID": "t1",
            "HERDR_PANE_ID": "p0",
            **GIT_ENV,
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result


def test_layout_prints_the_drift_line_when_behind(tmp_path):
    clone = make_clone(tmp_path)
    project = make_project(tmp_path, clone)
    advance_clone(clone)
    (clone / "notes.txt").write_text("not in loop/\n")
    commit_all(clone, "outside loop/")
    advance_clone(clone)
    result = run_layout(tmp_path, project)
    assert "harness is 2 commits behind loop-engineering; run update.sh" in (
        result.stdout
    )


def test_layout_prints_nothing_when_current(tmp_path):
    clone = make_clone(tmp_path)
    project = make_project(tmp_path, clone)
    (clone / "notes.txt").write_text("not in loop/\n")
    commit_all(clone, "outside loop/")
    result = run_layout(tmp_path, project)
    assert "behind" not in result.stdout


# Case 8: run.sh prints the drift line once at start.


def run_loop(tmp_path: Path, harness: Path) -> subprocess.CompletedProcess:
    """run.sh with one bead ready and a fake claude, stopped by the 2nd sleep."""
    bin_dir = tmp_path / "run-bin"
    bin_dir.mkdir(exist_ok=True)
    scripts = {
        "bd": 'case "$1" in ready) echo \'[{"id":"demo-1"}]\' ;; *) echo "[]" ;; esac\n',
        "claude": "echo session\n",
        "sleep": 'n=$(( $(cat "$SLEEP_COUNT" 2>/dev/null || echo 0) + 1 ))\n'
        'echo "$n" >"$SLEEP_COUNT"\n'
        '[ "$n" -lt 2 ] || kill -TERM $PPID\n',
    }
    for name, body in scripts.items():
        exe = bin_dir / name
        exe.write_text("#!/bin/bash\n" + body)
        exe.chmod(0o755)
    return subprocess.run(
        ["/bin/bash", str(harness / "run.sh"), "Bob", str(harness / "CODER.md")],
        cwd=tmp_path,
        env={
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "HOME": str(tmp_path),
            "LOOP_OVERLAY": "none",
            "SLEEP_COUNT": str(tmp_path / "sleep.count"),
            **GIT_ENV,
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def loop_project(tmp_path: Path) -> tuple[Path, Path]:
    clone = make_clone(tmp_path)
    project = make_project(tmp_path, clone)
    # The project's run.sh is the copy under test.
    (project / ".loop/run.sh").write_bytes(RUN_SH.read_bytes())
    return clone, project / ".loop"


def test_run_sh_prints_the_drift_line_once(tmp_path):
    clone, harness = loop_project(tmp_path)
    advance_clone(clone)
    result = run_loop(tmp_path, harness)
    line = "harness is 1 commit behind loop-engineering; run update.sh"
    assert result.stdout.count(line) == 1, result.stdout
    commit = git(clone, "rev-parse", "--short", "HEAD~1")
    assert f"version  {commit} ({line})" in result.stdout.splitlines()
    assert result.stdout.count("session starts ===") == 2
    assert result.stdout.index(line) < result.stdout.index("session starts ===")


def test_run_sh_shows_a_current_harness_as_up_to_date(tmp_path):
    clone, harness = loop_project(tmp_path)
    result = run_loop(tmp_path, harness)
    commit = git(clone, "rev-parse", "--short", "HEAD")
    assert f"version  {commit} (up to date)" in result.stdout.splitlines()


def unusable_stamp(case: str, tmp_path: Path, clone: Path) -> str | None:
    older = git(clone, "rev-parse", "HEAD~1")
    return {
        "no stamp": None,
        "missing clone": f"commit={older}\nclone={tmp_path / 'gone'}\n",
        "not a repository": f"commit={older}\nclone={tmp_path}\n",
        "unknown commit": f"commit={'0' * 40}\nclone={clone}\n",
    }[case]


@pytest.mark.parametrize(
    "case", ["no stamp", "missing clone", "not a repository", "unknown commit"]
)
def test_run_sh_prints_nothing_without_a_usable_stamp(tmp_path, case):
    clone, harness = loop_project(tmp_path)
    advance_clone(clone)
    stamp = harness / "HARNESS_VERSION"
    text = unusable_stamp(case, tmp_path, clone)
    if text is None:
        stamp.unlink()
    else:
        stamp.write_text(text)
    result = run_loop(tmp_path, harness)
    assert "behind" not in result.stdout
    assert "up to date" not in result.stdout
    assert "session starts ===" in result.stdout


def function_text(path: Path, name: str) -> str:
    text = path.read_text()
    start = text.index(f"\n{name}() {{\n")
    return text[start : text.index("\n}\n", start) + 3]


def test_run_sh_and_lib_sh_share_the_same_drift_line():
    assert function_text(RUN_SH, "drift_line") == function_text(LIB_SH, "drift_line")


# lpe-t0w: only commits that change an installed file count as drift.


def installed_paths() -> list[str]:
    """The files in loop/harness-files plus interactive.template.md, as
    paths in the clone (lpe-gas)."""
    return sorted(f"loop/{f}" for f in (*FILES, "interactive.template.md"))


def test_the_drift_paths_come_from_the_list():
    assert "loop/harness-files" in installed_paths()
    assert "loop/notify.py" in installed_paths()
    assert "loop/reply.py" in installed_paths()


def test_run_sh_and_lib_sh_share_the_same_harness_paths():
    assert function_text(RUN_SH, "harness_paths") == function_text(
        LIB_SH, "harness_paths"
    )


def test_no_script_holds_a_literal_list_of_harness_files():
    for script in (RUN_SH, LIB_SH, UPDATE, BOOTSTRAP):
        text = script.read_text()
        literal = r'^\s*(FILES|HARNESS_PATHS)="[^$"]*"$'
        assert not re.search(literal, text, re.MULTILINE), script
        assert "notify.py reply.py" not in text, script
        assert "watch.py prices.json" not in text, script


def test_commits_outside_the_installed_files_are_not_drift(tmp_path):
    clone, harness = loop_project(tmp_path)
    commit = git(clone, "rev-parse", "--short", "HEAD")
    (clone / "loop/tests").mkdir()
    (clone / "loop/tests/test_x.py").write_text("not installed\n")
    commit_all(clone, "change loop/tests/")
    (clone / "loop/README.md").write_text("not installed\n")
    commit_all(clone, "change loop/README.md")
    result = run_loop(tmp_path, harness)
    assert "behind" not in result.stdout
    assert f"version  {commit} (up to date)" in result.stdout.splitlines()
    assert "behind" not in run_layout(tmp_path, harness.parent).stdout


ONE_BEHIND = "harness is 1 commit behind loop-engineering; run update.sh"


@pytest.mark.parametrize("rel", installed_paths())
def test_a_change_to_one_installed_file_is_drift(tmp_path, rel):
    clone, harness = loop_project(tmp_path)
    target = clone / rel
    target.write_text(target.read_text() + "\n")
    commit_all(clone, f"change {rel}")
    assert ONE_BEHIND in run_loop(tmp_path, harness).stdout
    assert ONE_BEHIND in run_layout(tmp_path, harness.parent).stdout


def test_without_a_list_any_commit_under_loop_is_drift(tmp_path):
    """A project installed before lpe-gas has no .loop/harness-files."""
    clone, harness = loop_project(tmp_path)
    (harness / "harness-files").unlink()
    (clone / "notes.txt").write_text("not in loop/\n")
    commit_all(clone, "outside loop/")
    assert "behind" not in run_loop(tmp_path, harness).stdout
    assert "behind" not in run_layout(tmp_path, harness.parent).stdout
    (clone / "loop/README.md").write_text("not installed\n")
    commit_all(clone, "change loop/README.md")
    assert ONE_BEHIND in run_loop(tmp_path, harness).stdout
    assert ONE_BEHIND in run_layout(tmp_path, harness.parent).stdout


def test_one_line_in_the_list_is_enough_to_watch_a_new_file(tmp_path):
    clone, harness = loop_project(tmp_path)
    add_listed_file(clone)
    result = run_update(tmp_path, clone, harness.parent)
    assert result.returncode == 0, result.stdout + result.stderr
    commit_all(harness.parent, "update")
    extra = clone / "loop/extra.sh"
    extra.write_text(extra.read_text() + "echo newer\n")
    commit_all(clone, "change extra.sh")
    assert ONE_BEHIND in run_loop(tmp_path, harness).stdout
    assert ONE_BEHIND in run_layout(tmp_path, harness.parent).stdout
