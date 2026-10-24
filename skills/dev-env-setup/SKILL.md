---
name: dev-env-setup
description: Set up a new project for the Ralph (writer) and Alice (reviewer) agent loop. Initializes git, a uv project with ruff and pytest, and beads, copies the ralph/ harness (run.sh, watch.py, PROMPT.md, ALICE.md) from ~/github.com/rbastian/loop-engineering/ralph-alice, writes the ralph/project.md overlay, creates the two git worktrees, starts both loops in a herdr tab, and puts both watchers at the top of the tab where the skill runs. Use when the user asks to set up their development environment, bootstrap a project for Ralph and Alice, or start the agent loop in a new repository.
---

# Development environment setup

This skill prepares a project for the two-agent loop from `~/github.com/rbastian/loop-engineering/ralph-alice`. Ralph implements one bead per session in his own worktree, on `RALPH_MODEL` (default `claude-opus-5-5`). Alice reviews his branch on Claude Code with a different model (`ALICE_MODEL`, default `claude-sonnet-5-5`) and merges it into `main`. Read `~/github.com/rbastian/loop-engineering/ralph-alice/README.md` for the rules of the loop.

The three scripts in `scripts/` do the mechanical work. Each script is safe to run twice, because each step skips itself when its work is already done.

| Script | What it does |
|---|---|
| `bootstrap.sh PROJECT_DIR BEAD_PREFIX [DEV_PACKAGE ...]` | git, uv, ruff and pytest, beads, the `ralph/` harness, `ralph/project.md` with the paths filled in, one gate run |
| `worktrees.sh PROJECT_DIR` | first commit on `main`, `../<name>-ralph` on branch `loop`, `../<name>-alice` on a detached HEAD |
| `layout.sh PROJECT_DIR` | a `<name> loop` tab with Ralph and Alice side by side, and the two watchers in the top third of the calling tab (Ralph left, Alice right) |

The harness source is `ralph-alice/` in the loop-engineering repository that holds this skill. `bootstrap.sh` finds it from its own location, also through the `~/.claude/skills` symlink. To use another copy, set `LOOP_HOME` to that repository's root.

## Procedure

1. Get the project directory. If the user gives none, use the current working directory.
2. Ask the user for three things in one question:
   - The bead prefix. It must be lowercase letters only, because a hyphen breaks the bead parser in `watch.py`. Suggest a short consonant abbreviation of the project name, four letters at most, for example `rsvc` for `resolution-service`.
   - Extra dev packages on top of ruff and pytest, if any.
   - A short description of the project and its tech stack, for the prompt files.
3. Run `bootstrap.sh`. If the gate at the end fails, stop and show the output to the user.
4. Fill the `{{...}}` placeholders in `ralph/project.md` with the facts for this project: what it is, the tech stack, the key directories, the external services and the review method. `bootstrap.sh` already filled the three paths. Change the format commands and the gate only if this project needs other commands. Do not change `ralph/PROMPT.md` or `ralph/ALICE.md`, because they hold only the loop protocol.
5. Run `RALPH_PRINT_PROMPT=1 ralph/run.sh Ralph ralph/PROMPT.md` and search the output for `{{`. Make sure that no placeholder remains.
6. Run `worktrees.sh`. It commits all files, then creates both worktrees.
7. Run `layout.sh`. It needs `HERDR_ENV=1`. If the skill does not run inside herdr, stop and give the user the command to run from a herdr pane.
8. Report the result: the loop tab name, the four pane IDs, and the log directories `/tmp/<name>-ralph-sessions` and `/tmp/<name>-alice-sessions`. Remind the user that the loops find no work until a bead gets the spec ritual and an assignment to Ralph.

## Facts the scripts depend on

- `bd init` uses the directory name as the default prefix. For `resolution-service`, bead IDs would be `resolution-service-abc`, and `watch.py` reads that as `service-abc`. This is why the prefix is an argument.
- On an empty project, `pytest` finds no tests and exits with code 5, which fails the gate. `bootstrap.sh` writes `tests/test_smoke.py` for this reason.
- `watch.py` gets the agent name from the log directory name. The per-project directories do not match its pattern, so `layout.sh` passes `--agent`.
- `run.sh` appends `ralph/project.md` to the prompt at each session. `RALPH_OVERLAY` points it at another file, and `RALPH_OVERLAY=none` runs the prompt alone.
- The loops read `PROMPT.md`, `ALICE.md` and `project.md` from the primary checkout, not from the worktrees. Prompt changes merged to `main` take effect at the next session.
- `layout.sh` refuses to run when a tab named `<name> loop` already exists, or when the calling tab already has watcher panes. To restart, close the loop tab and both watcher panes first.
- `layout.sh` splits the calling pane, so the watchers take one third of that pane's height, not of the whole tab. Run it from a pane that fills the tab.
