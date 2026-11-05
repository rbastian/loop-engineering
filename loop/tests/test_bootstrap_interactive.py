"""bootstrap.sh writes the interactive section into CLAUDE.md and AGENTS.md (lpe-1q4).

The section comes from loop/interactive.template.md, filled with the agent
names. These tests run bootstrap.sh with stub tools on PATH, so they need no
network, no uv project and no beads database. The stub bd writes a CLAUDE.md
and an AGENTS.md with an H1 and a beads block, as `bd init` and `bd setup` do.
"""

import hashlib
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[2]
BOOTSTRAP = ROOT / "skills/dev-env-setup/scripts/bootstrap.sh"
TEMPLATE = ROOT / "loop/interactive.template.md"
BEGIN = "<!-- BEGIN LOOP INTERACTIVE -->"
END = "<!-- END LOOP INTERACTIVE -->"
BEADS = "<!-- BEGIN BEADS INTEGRATION -->"

STUBS = {
    # uv init --help must mention --bare; every other call succeeds.
    "uv": 'case "$1 $2" in "init --help") echo "--bare" ;; "init "*) touch pyproject.toml ;; esac\n',
    "bd": """case "$1 $2" in
  "init "*) for f in CLAUDE.md AGENTS.md; do
      [ -f "$f" ] || printf '# Agent Instructions\\n' >"$f"
    done ;;
  "setup claude") f=CLAUDE.md ;;
  "setup codex") f=AGENTS.md ;;
esac
if [ -n "${f:-}" ] && ! grep -q 'BEGIN BEADS' "$f"; then
  printf '\\n<!-- BEGIN BEADS INTEGRATION -->\\n## Beads\\n<!-- END BEADS INTEGRATION -->\\n' >>"$f"
fi
""",
    "jq": "",
    "claude": "",
    "gh": "",
    "timeout": "",
}


def fill(coder: str, reviewer: str, human: str) -> str:
    return (
        TEMPLATE.read_text()
        .replace("{{CODER}}", coder)
        .replace("{{REVIEWER}}", reviewer)
        .replace("{{HUMAN}}", human)
    )


def section(text: str) -> str:
    start = text.index(BEGIN)
    end = text.index(END) + len(END)
    return text[start:end] + "\n"


def run_bootstrap(
    tmp_path: Path,
    project: Path,
    extra_env: dict[str, str] | None = None,
    *,
    check: bool = True,
    prefix: str = "demo",
    extra_stubs: tuple[str, ...] = (),
) -> subprocess.CompletedProcess:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    for name, body in {**STUBS, **dict.fromkeys(extra_stubs, "")}.items():
        stub = bin_dir / name
        stub.write_text("#!/bin/bash\n" + body)
        stub.chmod(0o755)
    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "USER": "tester",
        "LOOP_HOME": str(ROOT),
        "LOOP_CODER": "Bob",
        "LOOP_REVIEWER": "Carol",
        "LOOP_HUMAN": "Dana",
        "LOOP_GITHUB_ACCOUNT": "dana-gh",
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
    }
    env.update(extra_env or {})
    result = subprocess.run(
        ["bash", str(BOOTSTRAP), str(project), prefix],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if check:
        assert result.returncode == 0, result.stdout + result.stderr
    return result


def existing_repo(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(project)], check=True)
    return project


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_template_has_markers_and_placeholders():
    text = TEMPLATE.read_text()
    assert text.startswith(BEGIN + "\n")
    assert text.endswith(END + "\n")
    for name in ("{{CODER}}", "{{REVIEWER}}", "{{HUMAN}}"):
        assert name in text
    for fixed in ("Ralph", "Alice", "Rob"):
        assert fixed not in text


def test_empty_folder_gets_the_section_before_the_beads_block(tmp_path):
    project = tmp_path / "proj"
    run_bootstrap(tmp_path, project)
    for name in ("CLAUDE.md", "AGENTS.md"):
        text = (project / name).read_text()
        assert text.count(BEGIN) == 1
        assert text.count(END) == 1
        assert "{{" not in text
        assert section(text) == fill("Bob", "Carol", "Dana")
        assert text.index("# Agent Instructions\n") < text.index(BEGIN)
        assert text.index(END) < text.index(BEADS)
    project_md = (project / ".loop" / "project.md").read_text()
    assert "\nGITHUB_ACCOUNT=dana-gh\n" in project_md


def test_second_run_changes_nothing(tmp_path):
    project = tmp_path / "proj"
    run_bootstrap(tmp_path, project)
    before = {n: sha(project / n) for n in ("CLAUDE.md", "AGENTS.md")}
    result = run_bootstrap(tmp_path, project)
    after = {n: sha(project / n) for n in ("CLAUDE.md", "AGENTS.md")}
    assert before == after
    assert "CLAUDE.md holds the interactive section; keeping it" in result.stdout
    assert "AGENTS.md holds the interactive section; keeping it" in result.stdout


def test_existing_h1_keeps_the_other_text(tmp_path):
    project = existing_repo(tmp_path)
    original = "# My Project\n\nSome rules.\n\n```bash\n# not a heading\n```\n"
    (project / "CLAUDE.md").write_text(original)
    run_bootstrap(tmp_path, project)
    text = (project / "CLAUDE.md").read_text()
    head, _, rest = text.partition(BEGIN)
    assert head == "# My Project\n\n"
    after = rest.split(END + "\n", 1)[1]
    assert after.startswith("\nSome rules.\n\n```bash\n# not a heading\n```\n")


def test_file_without_h1_gets_the_section_at_the_top(tmp_path):
    project = existing_repo(tmp_path)
    (project / "AGENTS.md").write_text("Plain text.\n")
    run_bootstrap(tmp_path, project)
    text = (project / "AGENTS.md").read_text()
    assert text.startswith(BEGIN)
    assert text.split(END + "\n", 1)[1].startswith("\nPlain text.\n\n" + BEADS)


def test_h1_after_the_beads_block_puts_the_section_at_the_top(tmp_path):
    project = existing_repo(tmp_path)
    original = BEADS + "\n## Beads\n<!-- END BEADS INTEGRATION -->\n\n# Later\n"
    (project / "CLAUDE.md").write_text(original)
    run_bootstrap(tmp_path, project)
    text = (project / "CLAUDE.md").read_text()
    assert text == fill("Bob", "Carol", "Dana") + "\n" + original


def test_this_repository_uses_the_filled_template():
    expected = fill("Ralph", "Alice", "Rob Bastian")
    for name in ("CLAUDE.md", "AGENTS.md"):
        text = (ROOT / name).read_text()
        assert text.count(BEGIN) == 1
        assert section(text) == expected
        assert "## Interactive sessions: refine and assign" not in text


def test_pr_mode_without_a_github_account_stops(tmp_path):
    project = tmp_path / "proj"
    result = run_bootstrap(tmp_path, project, {"LOOP_GITHUB_ACCOUNT": ""}, check=False)
    assert result.returncode == 1
    assert "LOOP_GITHUB_ACCOUNT" in result.stdout + result.stderr
    assert not (project / ".loop" / "project.md").exists()


def test_local_mode_writes_an_empty_github_account(tmp_path):
    project = tmp_path / "proj"
    run_bootstrap(tmp_path, project, {"LOOP_SHIP_MODE": "local"})
    text = (project / ".loop" / "project.md").read_text()
    assert "\nGITHUB_ACCOUNT=\n" in text
    assert "{{GITHUB_ACCOUNT}}" not in text


def test_interactive_section_has_the_remote_rule():
    text = TEMPLATE.read_text()
    assert "GITHUB_ACCOUNT" in text
    assert ".loop/project.md" in text
