"""The harness version stamp and the drift warning (lpe-bl1).

bootstrap.sh writes .loop/HARNESS_VERSION. layout.sh and run.sh read it and
print one line when the clone has newer commits on loop/.
"""

import subprocess
from pathlib import Path

from test_bootstrap_interactive import run_bootstrap
from test_update import (
    GIT_ENV,
    ROOT,
    advance_clone,
    commit_all,
    git,
    make_clone,
    make_project,
)

LAYOUT = ROOT / "skills/dev-env-setup/scripts/layout.sh"
RUN_SH = ROOT / "loop/run.sh"


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
    assert result.stdout.count("Starting claude session") == 2
    assert result.stdout.index(line) < result.stdout.index("Starting claude session")


def test_run_sh_prints_nothing_without_a_usable_stamp(tmp_path):
    clone, harness = loop_project(tmp_path)
    advance_clone(clone)
    stamp = harness / "HARNESS_VERSION"
    cases = {
        "no stamp": None,
        "missing clone": f"commit={git(clone, 'rev-parse', 'HEAD~1')}\n"
        f"clone={tmp_path / 'gone'}\n",
        "not a repository": f"commit={git(clone, 'rev-parse', 'HEAD~1')}\n"
        f"clone={tmp_path}\n",
        "unknown commit": f"commit={'0' * 40}\nclone={clone}\n",
    }
    for name, text in cases.items():
        if text is None:
            stamp.unlink(missing_ok=True)
        else:
            stamp.write_text(text)
        (tmp_path / "sleep.count").unlink(missing_ok=True)
        result = run_loop(tmp_path, harness)
        assert "behind" not in result.stdout, name
        assert "Starting claude session" in result.stdout, name
