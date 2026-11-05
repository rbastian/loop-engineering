"""skills/dev-env-setup/scripts/update.sh: bring an installed harness up to date (lpe-bl1).

Each test builds a scratch loop-engineering clone (a git repository with a
copy of loop/) and a scratch project with an install in .loop/ or ralph/. The
scripts run under /bin/bash, which is bash 3.2 on macOS.
"""

import re
import shutil
import subprocess
from pathlib import Path

from test_bootstrap_interactive import BEGIN, END

ROOT = Path(__file__).parents[2]
UPDATE = ROOT / "skills/dev-env-setup/scripts/update.sh"
FILES = ("run.sh", "watch.py", "CODER.md", "REVIEWER.md", "prices.json")
CLONE_FILES = FILES + (
    "project.template.md",
    "interactive.template.md",
    "README.md",
)
NAMES = {"CODER": "Bob", "REVIEWER": "Carol", "HUMAN": "Dana"}
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


def commit_all(repo: Path, message: str) -> str:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def make_clone(tmp_path: Path) -> Path:
    clone = (tmp_path / "loop-engineering").resolve()
    (clone / "loop").mkdir(parents=True)
    for f in CLONE_FILES:
        shutil.copy2(ROOT / "loop" / f, clone / "loop" / f)
    git(clone, "init", "-q", "-b", "main")
    commit_all(clone, "harness")
    return clone


def fill(text: str, **values: str) -> str:
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def rendered_section(clone: Path) -> str:
    return fill((clone / "loop/interactive.template.md").read_text(), **NAMES)


def project_md(clone: Path, project: Path) -> str:
    return fill(
        (clone / "loop/project.template.md").read_text(),
        PRIMARY=str(project),
        CODER_WORKTREE=f"{project}-bob",
        REVIEWER_WORKTREE=f"{project}-carol",
        SHIP_MODE="pr",
        GITHUB_ACCOUNT="dana-gh",
        CODER_ENGINE="claude",
        CODER_MODEL="",
        REVIEWER_ENGINE="claude",
        REVIEWER_MODEL="",
        BEAD_PREFIX="demo",
        **NAMES,
    )


CLAUDE_HEAD = "# My Project\n\nIntro text.\n\n"
CLAUDE_TAIL = "\nRules after the section.\n"
AGENTS_TEXT = "# Agents\n\nNo section here.\n"


def make_project(tmp_path: Path, clone: Path, install: str = ".loop") -> Path:
    """A committed project whose install matches the clone's HEAD, with a stamp."""
    project = (tmp_path / "proj").resolve()
    project.mkdir()
    git(project, "init", "-q", "-b", "main")
    harness = project / install
    harness.mkdir()
    for f in FILES:
        shutil.copy2(clone / "loop" / f, harness / f)
    (harness / "project.md").write_text(project_md(clone, project))
    stamp = f"commit={git(clone, 'rev-parse', 'HEAD')}\nclone={clone}\n"
    (harness / "HARNESS_VERSION").write_text(stamp)
    (project / "CLAUDE.md").write_text(
        CLAUDE_HEAD + rendered_section(clone) + CLAUDE_TAIL
    )
    (project / "AGENTS.md").write_text(AGENTS_TEXT)
    commit_all(project, "install")
    return project


def advance_clone(clone: Path) -> str:
    """One commit on loop/: a new CODER.md line and a new section line."""
    coder = clone / "loop/CODER.md"
    coder.write_text(coder.read_text() + "\nA new coder rule.\n")
    template = clone / "loop/interactive.template.md"
    template.write_text(
        template.read_text().replace(END, "A new line for {{CODER}}.\n" + END)
    )
    return commit_all(clone, "newer harness")


def run_update(
    tmp_path: Path, clone: Path, project: Path, *args: str
) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["/bin/bash", str(UPDATE), str(project), *args],
        env={
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "HOME": str(tmp_path),
            "LOOP_HOME": str(clone),
            **GIT_ENV,
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def snapshot(project: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(project)): p.read_bytes()
        for p in sorted(project.rglob("*"))
        if p.is_file() and ".git" not in p.relative_to(project).parts
    }


def assert_refused(result: subprocess.CompletedProcess, before, project: Path):
    assert result.returncode == 1, result.stdout + result.stderr
    assert snapshot(project) == before
    assert "changed nothing" in result.stdout


# Case 2: a project one commit behind.


def test_update_one_commit_behind(tmp_path):
    clone = make_clone(tmp_path)
    project = make_project(tmp_path, clone)
    head_before = git(project, "rev-parse", "HEAD")
    md_before = (project / ".loop/project.md").read_bytes()
    new_commit = advance_clone(clone)

    result = run_update(tmp_path, clone, project)

    assert result.returncode == 0, result.stdout + result.stderr
    for f in FILES:
        assert (project / ".loop" / f).read_bytes() == (clone / "loop" / f).read_bytes()
    assert (project / ".loop/run.sh").stat().st_mode & 0o111
    assert (project / ".loop/watch.py").stat().st_mode & 0o111
    assert (project / ".loop/project.md").read_bytes() == md_before
    claude = (project / "CLAUDE.md").read_text()
    assert claude == CLAUDE_HEAD + rendered_section(clone) + CLAUDE_TAIL
    assert "A new line for Bob." in claude
    stamp = (project / ".loop/HARNESS_VERSION").read_text()
    assert stamp == f"commit={new_commit}\nclone={clone}\n"
    # It prints the diff, and it does not commit.
    assert "A new coder rule." in result.stdout
    assert ".loop/CODER.md" in result.stdout
    assert git(project, "rev-parse", "HEAD") == head_before
    assert "committed nothing" in result.stdout


# Case 7: a file without a section gets one; a file with one gets it replaced.


def test_update_installs_prices_json_into_an_older_install(tmp_path):
    """An install from before lpe-6v6.2 has no prices.json, and gets one."""
    clone = make_clone(tmp_path)
    project = make_project(tmp_path, clone)
    (project / ".loop/prices.json").unlink()
    commit_all(project, "an install from before prices.json")

    result = run_update(tmp_path, clone, project)

    assert result.returncode == 0, result.stdout + result.stderr
    installed = project / ".loop/prices.json"
    assert installed.read_bytes() == (clone / "loop/prices.json").read_bytes()


def test_file_without_a_section_gets_one(tmp_path):
    clone = make_clone(tmp_path)
    project = make_project(tmp_path, clone)
    advance_clone(clone)
    result = run_update(tmp_path, clone, project)
    assert result.returncode == 0, result.stdout + result.stderr
    agents = (project / "AGENTS.md").read_text()
    assert agents.count(BEGIN) == 1
    assert agents.count(END) == 1
    head, _, rest = agents.partition(BEGIN)
    assert head == "# Agents\n\n"
    assert rest.split(END + "\n", 1)[1] == "\nNo section here.\n"
    assert "A new line for Bob." in agents


def test_a_second_update_changes_nothing(tmp_path):
    clone = make_clone(tmp_path)
    project = make_project(tmp_path, clone)
    advance_clone(clone)
    assert run_update(tmp_path, clone, project).returncode == 0
    before = snapshot(project)
    result = run_update(tmp_path, clone, project)
    assert result.returncode == 0, result.stdout + result.stderr
    assert snapshot(project) == before


# Case 3: each failed check exits 1 and changes no file.


def stub_loop(tmp_path: Path, *args: str, cwd: Path) -> subprocess.Popen:
    """A process named run.sh, as a loop shows in ps."""
    stub_dir = tmp_path / "stub"
    stub_dir.mkdir(exist_ok=True)
    stub = stub_dir / "run.sh"
    stub.write_text("#!/bin/bash\ntrap 'kill $!; exit 0' TERM\nsleep 60 &\nwait\n")
    stub.chmod(0o755)
    return subprocess.Popen(["/bin/bash", str(stub), *args], cwd=cwd)


def stop(proc: subprocess.Popen) -> None:
    proc.terminate()
    proc.wait(timeout=10)


def test_refuses_while_a_run_sh_names_the_install(tmp_path):
    clone = make_clone(tmp_path)
    project = make_project(tmp_path, clone)
    advance_clone(clone)
    before = snapshot(project)
    proc = stub_loop(tmp_path, "Bob", f"{project}/.loop/CODER.md", cwd=tmp_path)
    try:
        result = run_update(tmp_path, clone, project)
    finally:
        stop(proc)
    assert_refused(result, before, project)
    assert str(proc.pid) in result.stdout


def test_refuses_while_a_run_sh_runs_in_a_worktree(tmp_path):
    clone = make_clone(tmp_path)
    project = make_project(tmp_path, clone)
    tree = tmp_path / "proj-bob"
    git(project, "worktree", "add", "-q", "-b", "loop", str(tree))
    advance_clone(clone)
    before = snapshot(project)
    proc = stub_loop(tmp_path, "Bob", ".loop/CODER.md", cwd=tree)
    try:
        result = run_update(tmp_path, clone, project)
    finally:
        stop(proc)
    assert_refused(result, before, project)
    assert str(proc.pid) in result.stdout


def test_a_run_sh_of_another_project_does_not_block(tmp_path):
    clone = make_clone(tmp_path)
    project = make_project(tmp_path, clone)
    other = tmp_path / "other"
    other.mkdir()
    advance_clone(clone)
    proc = stub_loop(tmp_path, "Bob", f"{other}/.loop/CODER.md", cwd=other)
    try:
        result = run_update(tmp_path, clone, project)
    finally:
        stop(proc)
    assert result.returncode == 0, result.stdout + result.stderr


def test_refuses_an_old_prompt_file(tmp_path):
    clone = make_clone(tmp_path)
    project = make_project(tmp_path, clone)
    (project / ".loop/PROMPT.md").write_text("old prompt\n")
    advance_clone(clone)
    before = snapshot(project)
    result = run_update(tmp_path, clone, project)
    assert_refused(result, before, project)
    assert "PROMPT.md" in result.stdout


def test_refuses_a_dirty_clone(tmp_path):
    clone = make_clone(tmp_path)
    project = make_project(tmp_path, clone)
    advance_clone(clone)
    (clone / "loop/watch.py").write_text("# uncommitted\n")
    before = snapshot(project)
    result = run_update(tmp_path, clone, project)
    assert_refused(result, before, project)
    assert "Commit or stash" in result.stdout


def test_refuses_a_missing_key_and_says_what_it_means(tmp_path):
    clone = make_clone(tmp_path)
    project = make_project(tmp_path, clone)
    md = project / ".loop/project.md"
    md.write_text(
        "".join(
            line
            for line in md.read_text().splitlines(keepends=True)
            if not line.startswith("GITHUB_ACCOUNT=")
        )
    )
    advance_clone(clone)
    before = snapshot(project)
    result = run_update(tmp_path, clone, project)
    assert_refused(result, before, project)
    assert "GITHUB_ACCOUNT" in result.stdout
    assert "the GitHub account that" in result.stdout


def test_every_template_key_has_a_meaning(tmp_path):
    clone = make_clone(tmp_path)
    project = make_project(tmp_path, clone)
    (project / ".loop/project.md").write_text("# Project\n")
    result = run_update(tmp_path, clone, project)
    assert result.returncode == 1
    template = (clone / "loop/project.template.md").read_text()
    keys = re.findall(r"^([A-Z][A-Z0-9_]*)=", template, re.MULTILINE)
    assert len(keys) == 13
    for key in keys:
        lines = [line for line in result.stdout.splitlines() if f"{key}:" in line]
        assert lines, key
        assert "loop/project.template.md" not in lines[0], lines[0]


def test_refuses_a_local_edit_and_shows_its_diff(tmp_path):
    clone = make_clone(tmp_path)
    project = make_project(tmp_path, clone)
    watch = project / ".loop/watch.py"
    watch.write_text(watch.read_text() + "# my local change\n")
    advance_clone(clone)
    before = snapshot(project)
    result = run_update(tmp_path, clone, project)
    assert_refused(result, before, project)
    assert "watch.py" in result.stdout
    assert "+# my local change" in result.stdout
    assert "--force" in result.stdout


def test_two_failures_are_both_printed(tmp_path):
    clone = make_clone(tmp_path)
    project = make_project(tmp_path, clone)
    (project / ".loop/ALICE.md").write_text("old prompt\n")
    watch = project / ".loop/watch.py"
    watch.write_text(watch.read_text() + "# my local change\n")
    advance_clone(clone)
    before = snapshot(project)
    result = run_update(tmp_path, clone, project)
    assert_refused(result, before, project)
    assert "ALICE.md" in result.stdout
    assert "+# my local change" in result.stdout


def test_refuses_a_section_without_an_end_marker(tmp_path):
    clone = make_clone(tmp_path)
    project = make_project(tmp_path, clone)
    (project / "AGENTS.md").write_text("# Agents\n\n" + BEGIN + "\nhalf a section\n")
    advance_clone(clone)
    before = snapshot(project)
    result = run_update(tmp_path, clone, project)
    assert_refused(result, before, project)
    assert "AGENTS.md" in result.stdout


# Case 4: --force overwrites a local edit and skips no other check.


def test_force_overwrites_a_local_edit(tmp_path):
    clone = make_clone(tmp_path)
    project = make_project(tmp_path, clone)
    watch = project / ".loop/watch.py"
    watch.write_text(watch.read_text() + "# my local change\n")
    advance_clone(clone)
    result = run_update(tmp_path, clone, project, "--force")
    assert result.returncode == 0, result.stdout + result.stderr
    assert watch.read_bytes() == (clone / "loop/watch.py").read_bytes()


def test_force_skips_no_other_check(tmp_path):
    clone = make_clone(tmp_path)
    project = make_project(tmp_path, clone)
    (project / ".loop/PROMPT.md").write_text("old prompt\n")
    advance_clone(clone)
    (clone / "loop/watch.py").write_text("# uncommitted\n")
    before = snapshot(project)
    result = run_update(tmp_path, clone, project, "--force")
    assert_refused(result, before, project)
    assert "PROMPT.md" in result.stdout
    assert "Commit or stash" in result.stdout


# Case 5: no stamp stops with the diffs, and passes with --force.


def test_no_stamp_stops_with_the_diffs(tmp_path):
    clone = make_clone(tmp_path)
    project = make_project(tmp_path, clone)
    (project / ".loop/HARNESS_VERSION").unlink()
    advance_clone(clone)
    before = snapshot(project)
    result = run_update(tmp_path, clone, project)
    assert_refused(result, before, project)
    assert "HARNESS_VERSION" in result.stdout
    assert "-A new coder rule." in result.stdout

    result = run_update(tmp_path, clone, project, "--force")
    assert result.returncode == 0, result.stdout + result.stderr
    assert (
        (project / ".loop/HARNESS_VERSION")
        .read_text()
        .startswith(f"commit={git(clone, 'rev-parse', 'HEAD')}\n")
    )


def test_a_dirty_or_unknown_stamp_stops_like_no_stamp(tmp_path):
    clone = make_clone(tmp_path)
    project = make_project(tmp_path, clone)
    advance_clone(clone)
    stamp = project / ".loop/HARNESS_VERSION"
    for text in (
        stamp.read_text() + "dirty=1\n",
        f"commit={'0' * 40}\nclone={clone}\n",
    ):
        stamp.write_text(text)
        before = snapshot(project)
        result = run_update(tmp_path, clone, project)
        assert_refused(result, before, project)
        assert "-A new coder rule." in result.stdout


# Case 6: an old ralph/ install.


def make_old_project(tmp_path: Path, clone: Path) -> Path:
    project = make_project(tmp_path, clone, install="ralph")
    md = project / "ralph/project.md"
    md.write_text(md.read_text() + "\nThe loop files are in ralph/ and ralph/run.sh.\n")
    claude = project / "CLAUDE.md"
    claude.write_text(
        claude.read_text().replace(BEGIN, BEGIN + "\nInside ralph/ text.", 1)
        + "Start ralph/run.sh by hand.\n"
    )
    commit_all(project, "old install")
    return project


def claude_line(project: Path) -> int:
    lines = (project / "CLAUDE.md").read_text().splitlines()
    return lines.index("Start ralph/run.sh by hand.") + 1


def test_migrates_an_old_ralph_install(tmp_path):
    clone = make_clone(tmp_path)
    project = make_old_project(tmp_path, clone)
    head_before = git(project, "rev-parse", "HEAD")
    ref_line = claude_line(project)
    advance_clone(clone)

    result = run_update(tmp_path, clone, project)

    assert result.returncode == 0, result.stdout + result.stderr
    assert not (project / "ralph").exists()
    for f in FILES:
        assert (project / ".loop" / f).read_bytes() == (clone / "loop" / f).read_bytes()
    md = (project / ".loop/project.md").read_text()
    assert "ralph/" not in md
    assert "The loop files are in .loop/ and .loop/run.sh." in md
    staged = git(project, "diff", "--cached", "--name-status", "-M")
    assert "R" in staged and "ralph/run.sh" in staged and ".loop/run.sh" in staged
    refs = [
        line for line in result.stdout.splitlines() if line.startswith("  CLAUDE.md:")
    ]
    assert refs == ["  CLAUDE.md:" + str(ref_line) + ": Start ralph/run.sh by hand."]
    claude = (project / "CLAUDE.md").read_text()
    assert "Start ralph/run.sh by hand." in claude
    assert "Inside ralph/ text." not in claude
    assert "RALPH_MODEL" in result.stdout and "LOOP_MODEL" in result.stdout
    assert git(project, "rev-parse", "HEAD") == head_before


def test_a_failed_check_stops_before_the_move(tmp_path):
    clone = make_clone(tmp_path)
    project = make_old_project(tmp_path, clone)
    (project / "ralph/PROMPT.md").write_text("old prompt\n")
    advance_clone(clone)
    before = snapshot(project)
    result = run_update(tmp_path, clone, project)
    assert_refused(result, before, project)
    assert (project / "ralph/run.sh").is_file()
    assert not (project / ".loop").exists()


def test_refuses_a_key_that_still_holds_a_placeholder(tmp_path):
    clone = make_clone(tmp_path)
    project = make_project(tmp_path, clone)
    md = project / ".loop/project.md"
    md.write_text(
        md.read_text().replace("BEAD_PREFIX=demo", "BEAD_PREFIX={{BEAD_PREFIX}}")
    )
    advance_clone(clone)
    before = snapshot(project)
    result = run_update(tmp_path, clone, project)
    assert_refused(result, before, project)
    assert "placeholder: BEAD_PREFIX" in result.stdout
