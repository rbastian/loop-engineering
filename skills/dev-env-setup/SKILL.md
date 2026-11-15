---
name: dev-env-setup
description: "Set up a new project for the multi-agent loop, with a coder agent (default Ralph) and a reviewer agent (default Alice). The coder runs on Claude Code or on fw (Claude Code on a Fireworks model). The reviewer runs on Claude Code, Codex or fw. It sets up git, a uv project with ruff and pytest, and beads. It copies run.sh, watch.py, notify.py, reply.py, prices.json, CODER.md and REVIEWER.md from the loop/ folder of the loop-engineering repository into .loop/. It writes .loop/loop.toml with the agent names, the human who approves merges, the engine and the model of each agent, and the ship mode: pull requests by default, local merge for a repository with one user. It writes .loop/project.md, the prose of the project, from a template. Then it creates two git worktrees and starts both loops in a herdr tab, with both watchers in the calling tab. Use it to set up a development environment or bootstrap a project for the agent loop. Use it to start the agent loop in a new repository."
---

# Development environment setup

This skill uses `loop/` in the loop-engineering repository that holds this skill. Read `loop/README.md` in that repository for the rules of the loop.

The loop has two agents. The coder (default name Ralph) implements one bead per session in its own worktree. The reviewer (default name Alice) reviews the coder's branch. Each agent runs on an engine, the CLI of its loop. `fw` is a launcher that runs Claude Code on a Fireworks model. The coder runs on `claude` or `fw`, because its prompt uses the `/simplify` skill of Claude Code. The reviewer runs on `claude`, `codex` or `fw`. `CODER_MODEL` and `REVIEWER_MODEL` hold the model of each agent. On `claude`, an empty model gives `claude-opus-5-5` for the coder and `claude-sonnet-5-5` for the reviewer, so the reviewer reviews with a different model. On `codex`, an empty model gives the plan's default model. `fw` has no default model, so an agent on `fw` must have one. The ship mode decides what happens after a review passes:

- `pr` is the default. The coder pushes the branch and opens a pull request. The reviewer comments on it, and a human approves and merges it.
- `local` is only for a repository with one user. The reviewer merges the branch into `main` in the primary checkout. No remote is necessary.

The scripts in `scripts/` do the mechanical work. Each script is safe to run twice. When its work is already done, each step skips itself. `lib.sh` holds the functions that the scripts share.

| Script | What it does |
|---|---|
| `bootstrap.sh PROJECT_DIR BEAD_PREFIX [DEV_PACKAGE ...]` | Sets up git, uv, ruff, pytest and beads. Installs the loop files in `.loop/` and writes `.loop/loop.toml` and `.loop/project.md`. Adds the interactive section to `CLAUDE.md` and `AGENTS.md`. Runs the gate once |
| `worktrees.sh PROJECT_DIR` | the first commit on `main`, then the push to `origin` in `pr` mode, then the two worktrees: the coder on branch `loop`, the reviewer on a detached HEAD |
| `layout.sh PROJECT_DIR` | a `<name> loop` tab with a queue above each agent's loop. The calling tab holds both watchers and a Beads pane |
| `queue.sh [--watch] AGENT` | one agent's beads, grouped into In progress, Ready next and Waiting sections |
| `update.sh PROJECT_DIR [--force]` | Updates an installed loop from the clone's current `loop/`. A failed check leaves the install unchanged. See `loop/README.md` for instructions |

`loop/harness-files` in the clone is the one list of the files that `bootstrap.sh` and `update.sh` copy into `.loop/`. `run.sh` and `layout.sh` read the installed copy to find drift. A new harness file needs one line in that list and no other change.

`layout.sh` arranges the loop tab like this:

```text
+-------------------+-------------------+
| coder queue       | reviewer queue    |
+-------------------+-------------------+
| coder loop        | reviewer loop     |
+-------------------+-------------------+
```

An agent queue shows the beads assigned to one agent. In progress lists the agent's active beads with their `loop` state labels. Ready next lists the unblocked beads that wait for the agent. Waiting lists the agent's blocked beads and their blockers.

`queue.sh` lives in `skills/dev-env-setup/scripts/` in the loop-engineering clone, not in the project's `.loop/` folder. To run it by hand, start in the project's primary checkout and give the full path to the skill folder:

```bash
cd /path/to/project
/path/to/loop-engineering/skills/dev-env-setup/scripts/queue.sh --watch Ralph
```

Use your coder or reviewer name in place of Ralph. Leave out `--watch` to print the queue once.

`bootstrap.sh` takes the names, the ship mode, the engines, the models and the GitHub account from ten variables: `LOOP_CODER`, `LOOP_REVIEWER`, `LOOP_HUMAN`, `LOOP_SHIP_MODE`, `LOOP_CODER_ENGINE`, `LOOP_CODER_MODEL`, `LOOP_REVIEWER_ENGINE`, `LOOP_REVIEWER_MODEL` and `LOOP_GITHUB_ACCOUNT`. It writes them into `.loop/loop.toml`, with the bead prefix and the paths, and runs `config.py check` on the file. It keeps an existing `.loop/loop.toml`. `run.sh`, `worktrees.sh` and `layout.sh` read the values back from that file through `config.py`, so `.loop/loop.toml` is the one place to change them. Each script stops with the error of each key path if the file is not valid. For an older install whose `.loop/project.md` holds `KEY=value` lines, `update.sh` migrates the lines into `.loop/loop.toml`.

The harness source is `loop/` in the same repository. `bootstrap.sh` finds it from its own location, also through the `~/.claude/skills` symlink. To use another copy, set `LOOP_HOME` to that repository's root.

## Procedure

1. Get the project directory. If the user gives none, use the current working directory.
2. Ask the user these questions in one message:
   - The bead prefix. It can have lowercase letters, digits, `-` and `_`, and it must start with a letter. It must not end with `-` or `_`, or have two of them in a row. Suggest a short consonant abbreviation of the project name, four letters at most, for example `rsvc` for `resolution-service`.
   - Does more than one person work in this repository? If yes, or if the user is not sure, use `pr`. Use `local` only for a repository with one user.
   - In `pr` mode, who approves and merges the pull requests? Get the bd assignee name for that person. The default is `$USER`. The same person gets the acceptance and escalation queues in both modes.
   - In `pr` mode, which GitHub account do the agents use? The agents use one account for every `gh` command and every push, usually the human's own account. If `gh` is logged in to the account that owns the `origin` repository, suggest that account. `gh auth status` lists the logged-in accounts. In `local` mode, do not ask, because `bootstrap.sh` writes an empty value.
   - The agent names. The defaults are Ralph for the coder and Alice for the reviewer. Each name must be letters only, and the two names must differ.
   - The coder's engine: `claude` (the default) or `fw`. If `fw` is on `PATH`, offer `fw`.
   - The reviewer's engine: `claude` (the default), `codex` or `fw`. If `codex` is installed, offer `codex`. If `fw` is on `PATH`, offer `fw`.
   - For each agent on `fw`, the model. Suggest `deepseek-flash-latest[1m]`. `fw` has no default model. For an agent on `claude` or `codex`, leave the model empty, unless the user asks for another model.
   - Any extra dev packages on top of ruff and pytest.
   - A short description of the project and its tech stack, for the prompt files.
3. Run `bootstrap.sh` with the answers, for example `LOOP_CODER=Ralph LOOP_REVIEWER=Alice LOOP_HUMAN=<name> LOOP_SHIP_MODE=pr LOOP_GITHUB_ACCOUNT=<account> LOOP_CODER_ENGINE=claude LOOP_REVIEWER_ENGINE=fw LOOP_REVIEWER_MODEL='deepseek-flash-latest[1m]' scripts/bootstrap.sh <dir> <prefix>`. Put a model in single quotes, because the shell reads `[1m]` as a glob. In `pr` mode, an empty `LOOP_GITHUB_ACCOUNT` stops `bootstrap.sh` with an error. If an engine is not allowed for its agent, the script stops with an error. If an agent on `fw` has no model, the script also stops with an error. If the gate at the end fails, `bootstrap.sh` prints `bootstrap failed` and exits 1. Stop and show the output to the user. If the project directory held files before the run, `bootstrap.sh` treats it as an existing repository. The format commands rewrite files, so the script runs only the check-only gate. If that gate fails on formatting or lint, ask the user before you run `uv run ruff format .` or `uv run ruff check --fix .`. Do not change the user's files without the user's consent.
4. Fill the `{{...}}` placeholders in `.loop/project.md` with the facts for this project: what it is, the tech stack, the key directories, the external services and the extra review checks. `.loop/project.md` holds the prose that the team shares. The reviewer always runs the default method for its engine, so list only the checks that add to it. `bootstrap.sh` already wrote the names, the ship mode, the GitHub account, the engines, the models and the paths into `.loop/loop.toml`, not into `.loop/project.md`. To change one of those values, edit `.loop/loop.toml`. If this project needs other commands, change the format commands and the gate. For an existing repository, adjust `pyproject.toml` and the gate in `.loop/project.md` to the project. Adjust the pytest `testpaths`, extra dev packages, `requires-python`, and checks for sources that are not Python. For example, add `rich` or `bash -n` on the shell scripts. Do not change `.loop/CODER.md` or `.loop/REVIEWER.md`, because they hold only the loop protocol.
5. Run `LOOP_PRINT_PROMPT=1 .loop/run.sh <coder> .loop/CODER.md` and search the output for `{{`. Make sure that no placeholder remains.
6. In `pr` mode, make sure that the repository has an `origin` remote and that `gh auth status` lists the account in `github_account` in `.loop/loop.toml`. If `gh` has no token for that account, `run.sh` stops at start. If an SSH `origin` pushes as another account, `run.sh` also stops. If there is no remote, ask the user which remote to use. Tell the user that the next step pushes `main` to `origin`.
7. Run `worktrees.sh`. It commits all files, pushes `main` in `pr` mode, then creates both worktrees.
8. If the reviewer runs on Codex, ask the user to open `codex` once in the primary checkout, trust the project and approve its hooks. A headless Codex session cannot do this step. Wait for the user's reply before you continue.
9. Run `layout.sh`. It needs `HERDR_ENV=1`. If the skill does not run inside herdr, stop and give the user the command to run from a herdr pane.
10. Report the ship mode, the engine and the model of each agent, and the loop tab name. Report the seven pane IDs. Tell the user that `run.sh` sends Telegram messages only after the setup in "Telegram messages" below. Report the log directories `/tmp/<name>-<coder>-sessions` and `/tmp/<name>-<reviewer>-sessions`, with the agent names in lowercase. Remind the user that the loops find no work until a bead gets the spec ritual and an assignment to the coder. Tell the user that an interactive Claude Code or Codex session in the project explains the loop and helps with the jobs of the human. Point the user to "From specification to beads" in the loop-engineering README for the breakdown of a specification into beads. In `pr` mode, also tell the user that beads with the state label `loop:merge` wait for them: approve and merge the pull request, then run `bd close <id>` and `bd set-state <id> loop=done`.

## Telegram messages

`run.sh` sends short Telegram messages to the human through `.loop/notify.py`. No pane and no separate process poll bd. Before each session, `run.sh` records the bead states. After the session, it sends one message for each bead of that agent whose loop state changed: escalated and parked beads, blocked beads, pull requests that are ready to merge, and progress. It also sends a message when a session times out, when 3 sessions in a row fail, and when the loop stops. `run.sh` runs `notify.py` under `direnv exec <primary checkout>` when direnv is on `PATH`, and the agent sessions never get the `TELEGRAM_` variables. `notify.py` only sends. `.loop/reply.py` reads the replies, see below. Without the two variables below, the startup block of `run.sh` shows `notifications off`, and no message goes out. To turn the messages on, tell the user to do these steps:

1. In Telegram, open a chat with @BotFather, send `/newbot` and follow its questions. BotFather gives a bot token.
2. Send any message to the new bot, so that the bot gets a chat with the user.
3. Open `https://api.telegram.org/bot<token>/getUpdates` in a browser, with the token in place of `<token>`. Copy the number at `message.chat.id`. That number is the chat ID.
4. Export `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in a git-ignored `.envrc` in the primary checkout. If direnv is installed, run `direnv allow` once in the primary checkout, so that `direnv exec` loads the file. Without direnv, export the two variables in the shell that starts herdr.
5. Restart both loops: press Ctrl-C in each loop pane, then run the same command again. The startup block shows `notifications on`.

The token gives control of the bot. Do not commit it, and do not paste it into a bead or a chat.

A message about an escalated or parked bead is a decision message. The human replies to it, and `.loop/reply.py` adds the reply to the bead as a note from the human and assigns the bead to the coder or the reviewer. A reply that starts with `<coder>:` or `<reviewer>:` chooses the agent. One reader serves every repository that uses the same bot, and `layout.sh` does not start it. To turn replies on, tell the user to run `direnv exec . uv run .loop/reply.py` in a spare pane, from the primary checkout of any project that has the harness, or `uv run .loop/reply.py` without direnv. If a reader already runs, the second one exits 1. Telegram keeps a reply for 24 hours, so a reply sent while the reader is down for longer is lost.

## Facts the scripts depend on

- `bd init` uses the directory name as the default prefix. For `resolution-service`, bead IDs are `resolution-service-abc`. Short IDs are easier to read and type, so the prefix is an argument.
- When `pytest` finds no tests, it exits with code 5, which fails the gate. If the project has no `test_*.py` or `*_test.py` file, `bootstrap.sh` writes `tests/test_smoke.py` and sets `testpaths = ["tests"]` for this reason. If the project has test files, `bootstrap.sh` writes no smoke test and no `testpaths`, and `pytest` finds the tests by its default rules.
- On an existing repository without `pyproject.toml`, `bootstrap.sh` runs `uv init --bare`, which writes only `pyproject.toml`. On an empty folder, it runs `uv init --package`, which also adds a `src/<name>` package.
- `watch.py` gets the agent name from the log directory name. The per-project directories do not match its pattern, so `layout.sh` passes `--agent`. `layout.sh` also passes `--prefix` from `bead_prefix` in `.loop/loop.toml`, so the watchers match only this project's bead IDs.
- `.loop/` is a dot folder. pytest skips it by default, and `bootstrap.sh` adds `.loop` to ruff's `extend-exclude` in `pyproject.toml`. If `[tool.ruff]` already has an `extend-exclude` key, `bootstrap.sh` prints a note, and you add `".loop"` to that list by hand. ripgrep also skips dot folders, but the prompts name the paths, so the agents find the files.
- `run.sh` appends `.loop/project.md` to the prompt at each session, then the "Roles and paths" block with the values of `.loop/loop.toml`. `LOOP_OVERLAY` points it at another prose file, and `LOOP_OVERLAY=none` leaves the prose out. The block is always there.
- The loops read `CODER.md`, `REVIEWER.md` and `project.md` from the primary checkout, not from the worktrees. Prompt changes merged to `main` take effect at the next session.
- In `pr` mode, the reviewer comments on the pull request but does not approve it. The agents act as the account in `github_account` in `.loop/loop.toml`, usually the human's own account. GitHub does not let an account approve its own pull request. `.loop/project.md` lists the remote actions of each role under "Remote actions in `pr` mode".
- If a tab named `<name> loop` already exists, `layout.sh` refuses to run. If the calling tab already has watcher panes or a Beads pane, it also refuses to run. To restart, close the loop tab, both watcher panes and the Beads pane first.
- `layout.sh` splits the calling pane, so the watchers take one third of that pane's height, not of the whole tab. The Beads pane takes one third of the width of the calling pane that remains below the watchers. Run it from a pane that fills the tab.
- The Beads pane runs `CLICOLOR_FORCE=1 bd list --status open,blocked,in_progress` every 5 seconds. It redraws only after the output changes. When the pane captures the output of `bd`, `bd` turns color off. CLICOLOR_FORCE=1 keeps the colors of `bd`. The header line shows the time of the last change, not the time of the last check.
