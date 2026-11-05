---
name: dev-env-setup
description: "Set up a new project for the multi-agent loop, with a coder agent (default Ralph) and a reviewer agent (default Alice) on Claude Code or Codex. It sets up git, a uv project with ruff and pytest, and beads. It copies run.sh, watch.py, CODER.md and REVIEWER.md from the loop/ folder of the loop-engineering repository into .loop/. It writes .loop/project.md with the agent names, the human who approves merges, the reviewer's engine, and the ship mode: pull requests by default, local merge for a repository with one user. Then it creates two git worktrees and starts both loops in a herdr tab, with both watchers in the calling tab. Use it to set up a development environment, bootstrap a project for the agent loop, or start the agent loop in a new repository."
---

# Development environment setup

This skill prepares a project for the multi-agent loop from `loop/` in the loop-engineering repository that holds this skill. Read `loop/README.md` in that repository for the rules of the loop.

The loop has two agents. The coder (default name Ralph) implements one bead per session in its own worktree, on `CODER_MODEL` (default `claude-opus-5-5`). The coder needs Claude Code, because its prompt uses the `/simplify` skill. The reviewer (default name Alice) reviews the coder's branch on Claude Code or on Codex. On Claude Code it uses a different model (`REVIEWER_MODEL`, default `claude-sonnet-5-5`). On Codex it uses a different model family, and `REVIEWER_MODEL` has no default. The ship mode decides what happens after a review passes:

- `pr` is the default. The coder pushes the branch and opens a pull request. The reviewer comments on it, and a human approves and merges it.
- `local` is only for a repository with one user. The reviewer merges the branch into `main` in the primary checkout. No remote is necessary.

The three scripts in `scripts/` do the mechanical work. Each script is safe to run twice, because each step skips itself when its work is already done.

| Script | What it does |
|---|---|
| `bootstrap.sh PROJECT_DIR BEAD_PREFIX [DEV_PACKAGE ...]` | git, uv, ruff and pytest, beads, the `.loop/` harness, `.loop/project.md` with the names, the ship mode and the paths filled in, the interactive section in `CLAUDE.md` and `AGENTS.md`, one gate run |
| `worktrees.sh PROJECT_DIR` | the first commit on `main`, then the push to `origin` in `pr` mode, then the two worktrees: the coder on branch `loop`, the reviewer on a detached HEAD |
| `layout.sh PROJECT_DIR` | a `<name> loop` tab with both loops side by side, and the two watchers and a Beads pane in the top third of the calling tab (coder left, reviewer center, Beads right) |

`bootstrap.sh` takes the names, the ship mode, the reviewer's engine and the GitHub account from six variables: `LOOP_CODER`, `LOOP_REVIEWER`, `LOOP_HUMAN`, `LOOP_SHIP_MODE`, `LOOP_REVIEWER_ENGINE` and `LOOP_GITHUB_ACCOUNT`. It writes them into `.loop/project.md`. `worktrees.sh` and `layout.sh` read them back from that file, so `.loop/project.md` is the one place to change them.

The harness source is `loop/` in the same repository. `bootstrap.sh` finds it from its own location, also through the `~/.claude/skills` symlink. To use another copy, set `LOOP_HOME` to that repository's root.

## Procedure

1. Get the project directory. If the user gives none, use the current working directory.
2. Ask the user these questions in one message:
   - The bead prefix. It can have lowercase letters, digits, `-` and `_`, and it must start with a letter. It must not end with `-` or `_`, or have two of them in a row. Suggest a short consonant abbreviation of the project name, four letters at most, for example `rsvc` for `resolution-service`.
   - Does more than one person work in this repository? If yes, or if the user is not sure, use `pr`. Use `local` only for a repository with one user.
   - In `pr` mode, who approves and merges the pull requests? Get the bd assignee name for that person. The default is `$USER`. The same person gets the acceptance and escalation queues in both modes.
   - In `pr` mode, which GitHub account do the agents use? The agents use one account for every `gh` command and every push, usually the human's own account. If `gh` is logged in to the account that owns the `origin` repository, suggest that account. `gh auth status` lists the logged-in accounts. In `local` mode, do not ask, because `bootstrap.sh` writes an empty value.
   - The agent names. The defaults are Ralph for the coder and Alice for the reviewer. Each name must be letters only, and the two names must differ.
   - The reviewer's engine: `claude` (the default) or `codex`. Offer `codex` only if `codex` is installed.
   - Any extra dev packages on top of ruff and pytest.
   - A short description of the project and its tech stack, for the prompt files.
3. Run `bootstrap.sh` with the answers, for example `LOOP_CODER=Ralph LOOP_REVIEWER=Alice LOOP_HUMAN=<name> LOOP_SHIP_MODE=pr LOOP_GITHUB_ACCOUNT=<account> LOOP_REVIEWER_ENGINE=claude scripts/bootstrap.sh <dir> <prefix>`. In `pr` mode, `bootstrap.sh` stops with an error when `LOOP_GITHUB_ACCOUNT` is empty. If the gate at the end fails, `bootstrap.sh` prints `bootstrap failed` and exits 1. Stop and show the output to the user. If the project directory held files before the run, `bootstrap.sh` treats it as an existing repository and runs only the check-only gate, because the format commands rewrite files. If that gate fails on formatting or lint, ask the user before you run `uv run ruff format .` or `uv run ruff check --fix .`. Do not change the user's files without the user's consent.
4. Fill the `{{...}}` placeholders in `.loop/project.md` with the facts for this project: what it is, the tech stack, the key directories, the external services and the review method. `bootstrap.sh` already filled the names, the ship mode, the GitHub account, the reviewer's engine and the paths. Change the format commands and the gate only if this project needs other commands. For an existing repository, adjust `pyproject.toml` and the gate in `.loop/project.md` to the project: the pytest `testpaths`, extra dev packages (for example `rich`), `requires-python`, and checks for sources that are not Python (for example `bash -n` on the shell scripts). Do not change `.loop/CODER.md` or `.loop/REVIEWER.md`, because they hold only the loop protocol.
5. Run `LOOP_PRINT_PROMPT=1 .loop/run.sh <coder> .loop/CODER.md` and search the output for `{{`. Make sure that no placeholder remains.
6. In `pr` mode, make sure that the repository has an `origin` remote and that `gh auth status` lists the account in `GITHUB_ACCOUNT`. At start, `run.sh` stops when `gh` has no token for that account, or when an SSH `origin` pushes as another account. If there is no remote, ask the user which remote to use. Tell the user that the next step pushes `main` to `origin`.
7. Run `worktrees.sh`. It commits all files, pushes `main` in `pr` mode, then creates both worktrees.
8. If the reviewer runs on Codex, ask the user to open `codex` once in the primary checkout, trust the project and approve its hooks. A headless Codex session cannot do this step. Wait until the user confirms.
9. Run `layout.sh`. It needs `HERDR_ENV=1`. If the skill does not run inside herdr, stop and give the user the command to run from a herdr pane.
10. Report the result: the ship mode, the reviewer's engine, the loop tab name, the five pane IDs, and the log directories `/tmp/<name>-<coder>-sessions` and `/tmp/<name>-<reviewer>-sessions`, with the agent names in lowercase. Remind the user that the loops find no work until a bead gets the spec ritual and an assignment to the coder. Tell the user that an interactive Claude Code or Codex session in the project explains the loop and helps with the jobs of the human. Point the user to "From specification to beads" in the loop-engineering README for the breakdown of a specification into beads. In `pr` mode, also tell the user that beads with the label `merge` wait for them: approve and merge the pull request, then run `bd close <id>` and remove the label.

## Facts the scripts depend on

- `bd init` uses the directory name as the default prefix. For `resolution-service`, bead IDs are `resolution-service-abc`. Short IDs are easier to read and type, so the prefix is an argument.
- When `pytest` finds no tests, it exits with code 5, which fails the gate. If the project has no `test_*.py` or `*_test.py` file, `bootstrap.sh` writes `tests/test_smoke.py` and sets `testpaths = ["tests"]` for this reason. If the project has test files, `bootstrap.sh` writes no smoke test and no `testpaths`, and `pytest` finds the tests by its default rules.
- On an existing repository without `pyproject.toml`, `bootstrap.sh` runs `uv init --bare`, which writes only `pyproject.toml`. On an empty folder, it runs `uv init --package`, which also adds a `src/<name>` package.
- `watch.py` gets the agent name from the log directory name. The per-project directories do not match its pattern, so `layout.sh` passes `--agent`. `layout.sh` also passes `--prefix` from `BEAD_PREFIX` in `.loop/project.md`, so the watchers match only this project's bead IDs.
- `.loop/` is a dot folder. pytest skips it by default, and `bootstrap.sh` adds `.loop` to ruff's `extend-exclude` in `pyproject.toml`. If `[tool.ruff]` already has an `extend-exclude` key, `bootstrap.sh` prints a note, and you add `".loop"` to that list by hand. ripgrep also skips dot folders, but the prompts name the paths, so the agents find the files.
- `run.sh` appends `.loop/project.md` to the prompt at each session. `LOOP_OVERLAY` points it at another file, and `LOOP_OVERLAY=none` runs the prompt alone.
- The loops read `CODER.md`, `REVIEWER.md` and `project.md` from the primary checkout, not from the worktrees. Prompt changes merged to `main` take effect at the next session.
- In `pr` mode, the reviewer comments on the pull request but does not approve it. The agents act as the account in `GITHUB_ACCOUNT`, usually the human's own account, and GitHub does not let an account approve its own pull request. `.loop/project.md` lists the remote actions of each role under "Remote actions in `pr` mode".
- `layout.sh` refuses to run when a tab named `<name> loop` already exists, or when the calling tab already has watcher panes or a Beads pane. To restart, close the loop tab, both watcher panes and the Beads pane first.
- `layout.sh` splits the calling pane, so the watchers take one third of that pane's height, not of the whole tab. Run it from a pane that fills the tab.
- The Beads pane runs `CLICOLOR_FORCE=1 bd list --status open,blocked,in_progress` every 5 seconds and redraws only when the output changes. CLICOLOR_FORCE=1 keeps the colors of bd, because bd turns color off when the pane captures its output. The header line shows the time of the last change, not the time of the last check.
