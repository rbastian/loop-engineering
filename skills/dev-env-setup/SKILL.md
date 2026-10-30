---
name: dev-env-setup
description: "Set up a new project for the multi-agent loop, with a coder agent (default Ralph) and a reviewer agent (default Alice) on Claude Code or Codex. It sets up git, a uv project with ruff and pytest, and beads. It copies run.sh, watch.py, CODER.md and REVIEWER.md from the loop/ folder of the loop-engineering repository into ralph/. It writes ralph/project.md with the agent names, the human who approves merges, the reviewer's engine, and the ship mode: pull requests by default, local merge for a repository with one user. Then it creates two git worktrees and starts both loops in a herdr tab, with both watchers in the calling tab. Use it to set up a development environment, bootstrap a project for the agent loop, or start the agent loop in a new repository."
---

# Development environment setup

This skill prepares a project for the multi-agent loop from `loop/` in the loop-engineering repository that holds this skill. Read `loop/README.md` in that repository for the rules of the loop.

The loop has two agents. The coder (default name Ralph) implements one bead per session in its own worktree, on `CODER_MODEL` (default `claude-opus-5-5`). The coder needs Claude Code, because its prompt uses the `/simplify` skill. The reviewer (default name Alice) reviews the coder's branch on Claude Code or on Codex. On Claude Code it uses a different model (`REVIEWER_MODEL`, default `claude-sonnet-5-5`). On Codex it uses a different model family, and `REVIEWER_MODEL` has no default. The ship mode decides what happens after a review passes:

- `pr` is the default. The coder pushes the branch and opens a pull request. The reviewer comments on it, and a human approves and merges it.
- `local` is only for a repository with one user. The reviewer merges the branch into `main` in the primary checkout. No remote is necessary.

The three scripts in `scripts/` do the mechanical work. Each script is safe to run twice, because each step skips itself when its work is already done.

| Script | What it does |
|---|---|
| `bootstrap.sh PROJECT_DIR BEAD_PREFIX [DEV_PACKAGE ...]` | git, uv, ruff and pytest, beads, the `ralph/` harness, `ralph/project.md` with the names, the ship mode and the paths filled in, one gate run |
| `worktrees.sh PROJECT_DIR` | the first commit on `main`, then the push to `origin` in `pr` mode, then the two worktrees: the coder on branch `loop`, the reviewer on a detached HEAD |
| `layout.sh PROJECT_DIR` | a `<name> loop` tab with both loops side by side, and the two watchers and a Beads pane in the top third of the calling tab (coder left, reviewer center, Beads right) |

`bootstrap.sh` takes the names, the ship mode and the reviewer's engine from five variables: `LOOP_CODER`, `LOOP_REVIEWER`, `LOOP_HUMAN`, `LOOP_SHIP_MODE` and `LOOP_REVIEWER_ENGINE`. It writes them into `ralph/project.md`. `worktrees.sh` and `layout.sh` read them back from that file, so `ralph/project.md` is the one place to change them.

The harness source is `loop/` in the same repository. `bootstrap.sh` finds it from its own location, also through the `~/.claude/skills` symlink. To use another copy, set `LOOP_HOME` to that repository's root.

## Procedure

1. Get the project directory. If the user gives none, use the current working directory.
2. Ask the user these questions in one message:
   - The bead prefix. It must be lowercase letters only, because a hyphen breaks the bead parser in `watch.py`. Suggest a short consonant abbreviation of the project name, four letters at most, for example `rsvc` for `resolution-service`.
   - Does more than one person work in this repository? If yes, or if the user is not sure, use `pr`. Use `local` only for a repository with one user.
   - In `pr` mode, who approves and merges the pull requests? Get the bd assignee name for that person. The default is `$USER`. The same person gets the acceptance and escalation queues in both modes.
   - The agent names. The defaults are Ralph for the coder and Alice for the reviewer. Each name must be letters only, and the two names must differ.
   - The reviewer's engine: `claude` (the default) or `codex`. Offer `codex` only if `codex` is installed.
   - Any extra dev packages on top of ruff and pytest.
   - A short description of the project and its tech stack, for the prompt files.
3. Run `bootstrap.sh` with the answers, for example `LOOP_CODER=Ralph LOOP_REVIEWER=Alice LOOP_HUMAN=<name> LOOP_SHIP_MODE=pr LOOP_REVIEWER_ENGINE=claude scripts/bootstrap.sh <dir> <prefix>`. If the gate at the end fails, stop and show the output to the user.
4. Fill the `{{...}}` placeholders in `ralph/project.md` with the facts for this project: what it is, the tech stack, the key directories, the external services and the review method. `bootstrap.sh` already filled the names, the ship mode, the reviewer's engine and the paths. Change the format commands and the gate only if this project needs other commands. Do not change `ralph/CODER.md` or `ralph/REVIEWER.md`, because they hold only the loop protocol.
5. Run `RALPH_PRINT_PROMPT=1 ralph/run.sh <coder> ralph/CODER.md` and search the output for `{{`. Make sure that no placeholder remains.
6. In `pr` mode, make sure that the repository has an `origin` remote and that `gh auth status` succeeds. If there is no remote, ask the user which remote to use. Tell the user that the next step pushes `main` to `origin`.
7. Run `worktrees.sh`. It commits all files, pushes `main` in `pr` mode, then creates both worktrees.
8. If the reviewer runs on Codex, ask the user to open `codex` once in the primary checkout, trust the project and approve its hooks. A headless Codex session cannot do this step. Wait until the user confirms.
9. Run `layout.sh`. It needs `HERDR_ENV=1`. If the skill does not run inside herdr, stop and give the user the command to run from a herdr pane.
10. Report the result: the ship mode, the reviewer's engine, the loop tab name, the five pane IDs, and the log directories `/tmp/<name>-<coder>-sessions` and `/tmp/<name>-<reviewer>-sessions`, with the agent names in lowercase. Remind the user that the loops find no work until a bead gets the spec ritual and an assignment to the coder. Point the user to "From specification to beads" in the loop-engineering README for the breakdown of a specification into beads. In `pr` mode, also tell the user that beads with the label `merge` wait for them: approve and merge the pull request, then run `bd close <id>` and remove the label.

## Facts the scripts depend on

- `bd init` uses the directory name as the default prefix. For `resolution-service`, bead IDs are `resolution-service-abc`, and `watch.py` reads that as `service-abc`. This is why the prefix is an argument.
- On an empty project, `pytest` finds no tests and exits with code 5, which fails the gate. `bootstrap.sh` writes `tests/test_smoke.py` for this reason.
- `watch.py` gets the agent name from the log directory name. The per-project directories do not match its pattern, so `layout.sh` passes `--agent`.
- `run.sh` appends `ralph/project.md` to the prompt at each session. `RALPH_OVERLAY` points it at another file, and `RALPH_OVERLAY=none` runs the prompt alone.
- The loops read `CODER.md`, `REVIEWER.md` and `project.md` from the primary checkout, not from the worktrees. Prompt changes merged to `main` take effect at the next session.
- In `pr` mode, the reviewer comments on the pull request but does not approve it. The agents usually push with the human's GitHub account, and GitHub does not let an account approve its own pull request.
- `layout.sh` refuses to run when a tab named `<name> loop` already exists, or when the calling tab already has watcher panes or a Beads pane. To restart, close the loop tab, both watcher panes and the Beads pane first.
- `layout.sh` splits the calling pane, so the watchers take one third of that pane's height, not of the whole tab. Run it from a pane that fills the tab.
- The Beads pane runs `CLICOLOR_FORCE=1 bd list --status open,blocked,in_progress` every 5 seconds and redraws only when the output changes. CLICOLOR_FORCE=1 keeps the colors of bd, because bd turns color off when the pane captures its output. The header line shows the time of the last change, not the time of the last check.
