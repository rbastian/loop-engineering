"""loop/run.sh pins the GitHub account that the agents use in pr mode (lpe-e52).

project.md names the account in GITHUB_ACCOUNT. At start, run.sh gets that
account's token from gh, exports it as GH_TOKEN, and, for an SSH origin,
checks that ssh -T greets the same account. These tests run run.sh against a
scratch git repository with stub bd, gh, ssh and claude on PATH, and a fake
sleep that stops run.sh with SIGTERM after the first loop pause.
"""

import subprocess
from pathlib import Path

RUN_SH = Path(__file__).parents[1] / "run.sh"

TOKEN = "gho_stubtoken123"
STARTED = "Starting claude session"


def write_exe(path: Path, body: str) -> None:
    path.write_text("#!/bin/bash\n" + body)
    path.chmod(0o755)


def run_loop(
    tmp_path: Path,
    *,
    ship_mode: str = "pr",
    account: str = "rbastian",
    origin: str | None = "git@github-personal:rbastian/repo.git",
    gh_ok: bool = True,
    ssh_reply: str = "Hi rbastian! You've successfully authenticated, but GitHub does not provide shell access.",
) -> tuple[subprocess.CompletedProcess, str, list[str]]:
    """Run run.sh once. Returns the result, the session's GH_TOKEN and the stub calls."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(repo)], check=True, capture_output=True
    )
    if origin is not None:
        subprocess.run(
            ["git", "-C", str(repo), "remote", "add", "origin", origin],
            check=True,
            capture_output=True,
        )

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "calls.log"
    write_exe(
        bin_dir / "bd",
        'case "$*" in\n'
        "  *--status=in_progress*--json*) echo '[]' ;;\n"
        '  ready*--json*) echo \'[{"id":"lpe-y"}]\' ;;\n'
        "esac\n",
    )
    write_exe(
        bin_dir / "gh",
        f'echo "gh $*" >>"{calls}"\n'
        + (
            f'[ "$*" = "auth token --user {account}" ] && echo {TOKEN} && exit 0\n'
            if gh_ok
            else ""
        )
        + 'echo "no oauth token found for $4" >&2\nexit 1\n',
    )
    # ssh -T to GitHub prints its greeting on stderr and exits 1 on success.
    write_exe(
        bin_dir / "ssh",
        f'echo "ssh $*" >>"{calls}"\necho "{ssh_reply}" >&2\nexit 1\n',
    )
    write_exe(
        bin_dir / "claude",
        f'echo "${{GH_TOKEN-unset}}" >"{tmp_path / "token"}"\n',
    )
    write_exe(
        bin_dir / "sleep",
        '[ "$1" = 30 ] || exec /bin/sleep "$@"\nkill -TERM $PPID\n',
    )

    prompt_dir = repo / ".loop"
    prompt_dir.mkdir()
    (prompt_dir / "CODER.md").write_text("code\n")
    (prompt_dir / "project.md").write_text(
        "# Project\n\n```bash\nCODER=Ralph\nREVIEWER=Alice\n```\n\n"
        f"```bash\nSHIP_MODE={ship_mode}\nGITHUB_ACCOUNT={account}\n```\n"
    )

    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "HOME": str(tmp_path),
    }
    result = subprocess.run(
        ["bash", str(RUN_SH), "Ralph", ".loop/CODER.md"],
        check=False,
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    token_file = tmp_path / "token"
    token = token_file.read_text().strip() if token_file.exists() else ""
    stub_calls = calls.read_text().splitlines() if calls.exists() else []
    return result, token, stub_calls


def output(result: subprocess.CompletedProcess) -> str:
    return result.stdout + result.stderr


def test_pr_mode_without_an_account_stops_and_names_project_md(tmp_path):
    result, token, _ = run_loop(tmp_path, account="")
    assert result.returncode == 1
    assert STARTED not in result.stdout
    assert "GITHUB_ACCOUNT" in output(result)
    assert "project.md" in output(result)
    assert token == ""


def test_gh_without_a_token_for_the_account_stops_with_login_hint(tmp_path):
    result, token, _ = run_loop(tmp_path, gh_ok=False)
    assert result.returncode == 1
    assert STARTED not in result.stdout
    assert "gh auth login" in output(result)
    assert "rbastian" in output(result)
    assert token == ""


def test_ssh_greeting_for_another_account_stops_and_shows_both(tmp_path):
    result, token, calls = run_loop(
        tmp_path, ssh_reply="Hi other! You've successfully authenticated."
    )
    assert result.returncode == 1
    assert STARTED not in result.stdout
    assert "other" in output(result)
    assert "rbastian" in output(result)
    assert any("git@github-personal" in c for c in calls if c.startswith("ssh "))
    assert token == ""


def test_ssh_greeting_for_the_account_starts_with_the_token(tmp_path):
    result, token, calls = run_loop(tmp_path)
    assert STARTED in result.stdout
    assert token == TOKEN
    assert TOKEN not in output(result)
    ssh_calls = [c for c in calls if c.startswith("ssh ")]
    assert len(ssh_calls) == 1
    assert "-T" in ssh_calls[0].split()
    assert ssh_calls[0].endswith("git@github-personal")


def test_ssh_url_form_is_checked_against_its_host(tmp_path):
    result, token, calls = run_loop(
        tmp_path, origin="ssh://git@github.example:2222/rbastian/repo.git"
    )
    assert STARTED in result.stdout
    assert token == TOKEN
    ssh_calls = [c for c in calls if c.startswith("ssh ")]
    assert len(ssh_calls) == 1
    assert "2222" in ssh_calls[0].split()
    assert ssh_calls[0].endswith("git@github.example")


def test_https_origin_skips_ssh_and_starts_with_the_token(tmp_path):
    result, token, calls = run_loop(
        tmp_path, origin="https://github.com/rbastian/repo.git"
    )
    assert STARTED in result.stdout
    assert token == TOKEN
    assert not [c for c in calls if c.startswith("ssh ")]


def test_local_mode_calls_neither_gh_nor_ssh(tmp_path):
    result, token, calls = run_loop(tmp_path, ship_mode="local", account="")
    assert STARTED in result.stdout
    assert calls == []
    assert token == "unset"
