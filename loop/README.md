# loop

This folder holds the multi-agent loop. Each agent is a headless session that `run.sh` starts again and again. Each agent works only on the beads that are assigned to it. To hand a bead to the next agent, an agent changes the assignee.

The loop has three roles: CODER, REVIEWER and HUMAN. The coder and the reviewer are agents. The coder implements and the reviewer reviews. The human specs, merges and settles escalations. Each project gives the names for all three roles in `ralph/project.md`. The default agent names are Ralph for the coder and Alice for the reviewer.

- The coder implements one bead per session in its own git worktree, on the home branch `loop`.
- The reviewer reads the coder's branch in its own worktree, on a detached HEAD.
- What happens after a review passes depends on the ship mode.

You write the spec interactively, and the agents implement it headlessly. Each session starts fresh and reads its bead, prompts, project configuration and repository. Beads records task progress and handoffs between sessions.

## Ship modes

The ship mode is a setting in `ralph/project.md`. It has two values.

`pr` is the default. Use it for every repository that more than one person works in.

1. The coder pushes the branch to `origin` and opens a pull request against `main`.
2. The reviewer reviews the branch and posts the result as a pull request comment.
3. If the review passes, the reviewer assigns the bead to the human and adds the label `merge`.
4. The human approves and merges the pull request, then runs `bd close <id>` and removes the label.

The reviewer comments but does not approve. The agents usually push with the human's GitHub account, and GitHub does not let an account approve its own pull request. Any CI on the pull request runs in addition to the gate.

`local` is only for a repository with one user. No remote is necessary. If the review passes, the reviewer merges the branch into `main` in the primary checkout with `git merge --no-ff`. Then the reviewer closes the bead and adds the label `accept` for the human.

## Files

| File | Purpose |
|---|---|
| `run.sh` | The loop. It polls beads for work assigned to one agent name and starts one headless session per iteration. Every agent uses the same script with its own prompt. |
| `CODER.md` | The coder's prompt: the loop protocol for the coder role. |
| `REVIEWER.md` | The reviewer's prompt: the loop protocol for the reviewer role. |
| `project.template.md` | The template for `ralph/project.md`, the project overlay. |
| `watch.py` | The watcher. It shows a live session log as one line per tool call. |
| `tests/` | Tests for `watch.py`. |

## The project overlay

The agent prompts hold only the loop protocol. They contain no facts about a project. `run.sh` appends `project.md` to each prompt at the start of every session. The overlay gives these facts:

- The agent names (`CODER`, `REVIEWER`) and the human's bd assignee name (`HUMAN`).
- The reviewer's engine (`REVIEWER_ENGINE`): `claude` or `codex`.
- The ship mode (`SHIP_MODE`).
- The paths, the tech stack, the gate, the external services and the review method.

To rename an agent, change its name in `project.md` and restart its loop with the new name. Then assign each open bead of the old name to the new name. Worktree and log paths do not need to follow the name.

These variables control the overlay:

- `RALPH_OVERLAY` points `run.sh` at another overlay file.
- `RALPH_OVERLAY=none` runs the prompt with no overlay.
- `RALPH_PRINT_PROMPT=1` prints the combined prompt and exits. Use it to check an overlay.

## Install in a project

The `dev-env-setup` skill in `../skills/dev-env-setup` does the setup. See the root README for how to install it. The skill asks for the agent names, the ship mode and the human who approves merges. It copies this folder into the project as `ralph/` and writes `ralph/project.md` from the template. Then it creates both worktrees and starts both loops and both watchers in herdr.

To set up a project by hand, follow these steps:

1. Copy `run.sh`, `watch.py`, `CODER.md` and `REVIEWER.md` into the project as `ralph/`.
2. Copy `project.template.md` to `ralph/project.md` and fill every `{{...}}` placeholder.
3. In `pr` mode, make sure that the repository has an `origin` remote, that `main` is on it, and that `gh` is authenticated.
4. Create the worktrees from the primary checkout:

   ```bash
   git worktree add -b loop ../<name>-ralph main
   git worktree add --detach ../<name>-alice main
   ```

## Running

Start each loop from its worktree, and point it at the `ralph/` files in the primary checkout. Prompt changes merged to `main` then take effect at the next session. The first argument to `run.sh` is the agent name from `project.md`. These examples use the default names.

```bash
cd ../<name>-ralph
RALPH_MODEL=claude-opus-5-5 RALPH_STREAM_LOG=1 RALPH_SHOW_BEAD=1 RALPH_LOG_DIR=/tmp/<name>-ralph-sessions \
  <primary>/ralph/run.sh Ralph <primary>/ralph/CODER.md

cd ../<name>-alice
RALPH_MODEL=claude-sonnet-5-5 RALPH_STREAM_LOG=1 RALPH_SHOW_BEAD=1 RALPH_LOG_DIR=/tmp/<name>-alice-sessions \
  <primary>/ralph/run.sh Alice <primary>/ralph/REVIEWER.md
```

Each loop must have its own `RALPH_LOG_DIR`. `run.sh` points `$RALPH_LOG_DIR/current.jsonl` at each new session log. Two loops that share one directory move the link under each other.

Follow a session with the watcher:

```bash
RALPH_LOG_DIR=/tmp/<name>-ralph-sessions uv run ralph/watch.py --agent Ralph --tui
RALPH_LOG_DIR=/tmp/<name>-alice-sessions uv run ralph/watch.py --agent Alice --tui
```

`RALPH_ENGINE` selects the agent CLI. It takes `claude` (the default) or `codex`. The coder always runs on `claude`, because its prompt uses the `/simplify` skill. The reviewer can run on `codex`, so that a different model family reads the diff. On `codex`, `RALPH_MODEL` has no default, and the review uses `codex exec review`. Before the first headless Codex session, open `codex` once in the primary checkout, trust the project and approve its hooks.

### run.sh variables

| Variable | Effect |
|---|---|
| `RALPH_STREAM_LOG=1` | Write each session as JSONL to `$RALPH_LOG_DIR`, with a `current.jsonl` link to the newest log. After each session, also append a cost note to the bead. |
| `RALPH_LOG_DIR` | The log directory. The default is `/tmp/ralph-sessions`. Give each agent its own. |
| `RALPH_SHOW_BEAD=1` | Print `bd show` for each in-progress bead between sessions. |
| `RALPH_SESSION_TIMEOUT` | The wall-clock limit per session. The default is `2h`. It needs GNU `timeout` (on macOS, `brew install coreutils`). |
| `RALPH_ENGINE` | `claude` (the default) or `codex`. |
| `RALPH_MODEL` | The model for each session. The default is `claude-opus-5-5` on `claude` and none on `codex`. |
| `RALPH_OVERLAY` | The overlay file. The default is `project.md` beside the prompt file. `none` turns it off. |
| `RALPH_PRINT_PROMPT=1` | Print the combined prompt and exit. |

The `RALPH_` prefix names the technique (the ralph loop), not an agent. Every agent uses the same variables.

### Cost notes

An agent cannot record what its own session cost. The cost arrives in the session's closing event, after the agent has exited. So `run.sh` records it. When `RALPH_STREAM_LOG=1` is set, `run.sh` reads the finished log with `watch.py --summary` and appends one note to the bead:

```text
Session cost: Ralph, claude-opus-5-5, $1.84 est., 12m30s, 41 turns, 18.2k out, 3.1k think, 412k ctx
```

The dollar figure is Claude Code's API-equivalent estimate, not a bill. Codex on a ChatGPT plan reports tokens and no dollar figure, and the note says so. Each session of a bead adds one note: the coder's rounds, the reviewer's rounds and any rebase. The sum of the notes is what the bead cost.

`run.sh` takes the bead from the log: the coder's claim or commit tag, or the reviewer's review note. If the log names no bead, `run.sh` uses the one bead that the agent held when the session started. In these cases `run.sh` prints a warning and writes no note:

- The session did not reach its closing event, for example after a crash or a timeout.
- `run.sh` cannot tell which bead the session worked on.
- `bd` is still locked after three tries.

A missing cost note never stops the loop. The note needs `uv` to run `watch.py`. Agents skip `Session cost:` notes when they route on the last status marker.

## Operations

### Stop and restart

Stop both the shell loop and its headless session before restarting. A session runs under GNU `timeout` when available and can outlive Ctrl-C or a closed terminal tab. Checkpoint commits, saved files and bead notes provide recovery state for the next session.

1. Press Ctrl-C in each loop pane to stop the shell loop. Make sure that the loop stops instead of starting another session.
2. From another terminal, list candidate agent processes:

   ```bash
   pgrep -fl 'ralph/run.sh|claude|codex'
   ```

3. Identify each old session by its working directory and parent process. Replace `12345` with a candidate process ID:

   ```bash
   lsof -a -p 12345 -d cwd
   ps -p 12345 -o pid,ppid,pgid,command
   pgrep -P 12345
   ```

   Match the directory to the coder or reviewer worktree in `ralph/project.md`. Inspect the parent process if necessary. Record the child process IDs and inspect their children too before stopping the session. The list can include unrelated interactive sessions or agents from other projects.
4. Stop only the identified old session and any remaining child processes. For each identified process, replace `12345` with its process ID:

   ```bash
   kill -TERM 12345
   ```

5. Repeat the process checks. Make sure that no shell loop, agent session or child process from the old loops remains before restarting. Do not stop unrelated sessions.

For a Herdr restart, then close the project's loop tab, both watcher panes and the Beads pane. Closing panes alone does not confirm that their sessions stopped. `layout.sh` refuses to start while that tab or those panes exist. From a Herdr pane that fills its tab, run the setup skill's layout script:

```bash
/path/to/loop-engineering/skills/dev-env-setup/scripts/layout.sh /path/to/project
```

The script reads names, paths and the reviewer's engine from `ralph/project.md`. For a manual restart, use the commands under [Running](#running) from each agent's worktree. In-progress beads take priority over new work.

### Session logs

The setup layout writes logs to `/tmp/<project>-<coder>-sessions` and `/tmp/<project>-<reviewer>-sessions`, with lowercase agent names. Each directory contains session JSONL files and a `current.jsonl` link to the latest session. These temporary files are not a durable archive.

Use the watcher commands under [Running](#running) for a live view. To read an older log, run:

```bash
uv run ralph/watch.py --agent Ralph --file /path/to/session.jsonl --replay
```

Use your configured agent name in place of `Ralph`.

### Update an installed harness

Bootstrap preserves existing files in `ralph/`. Rerunning it does not install newer copies of the runner, watcher or role prompts. It still runs `uv add --dev`, `ruff format .` and `ruff check --fix .`, which can change project files. In `local` mode, modified tracked files prevent merges until the human resolves those changes.

The standard launch commands read the runner and prompts from the primary checkout's working tree. They do not select the committed version on `main`. Keep that checkout on the reviewed version before restarting.

1. Stop both loops and their sessions with the procedure under [Stop and restart](#stop-and-restart).
2. Prepare the update on a branch in a separate clone or worktree. Compare the source files in `loop/` with that checkout's installed files in `ralph/`. Copy the intended updates there and review the diff. Keep project facts in `ralph/project.md`. Compare it with `loop/project.template.md` for new configuration fields instead of replacing it.
3. In the update checkout, inspect the combined prompts and resolve every `{{...}}` placeholder before committing. From that checkout's root, run `RALPH_PRINT_PROMPT=1 ralph/run.sh <agent> <prompt>` for each role. Use the configured agent name and its prompt path, such as `ralph/CODER.md`.
4. In `pr` mode, open a pull request and merge the reviewed update. In the primary checkout on `main`, pull the merged update with `git pull --ff-only origin main`. In `local` mode, merge the reviewed update into `main` in the primary checkout.
5. From the primary checkout's root, inspect the installed prompts again:

   ```bash
   cd /path/to/primary-checkout
   RALPH_PRINT_PROMPT=1 ralph/run.sh Ralph ralph/CODER.md
   RALPH_PRINT_PROMPT=1 ralph/run.sh Alice ralph/REVIEWER.md
   ```

   Use your configured agent names. Make sure that neither output contains unresolved `{{...}}` placeholders. This final check must read the primary checkout, because the loops use those files.
6. Restart the loops only after the reviewed update is on `main` in the primary checkout and the prompt checks pass. Restart the watchers to load watcher updates.

## Rules of engagement

- The coder implements and the reviewer reviews. In `pr` mode the human approves and merges. In `local` mode the reviewer merges and the human accepts.
- If the reviewer finds a blocking problem, it returns the bead to the coder once. After a second failed round, it escalates the bead to the human.
- The human has these queues, each one a bead label:
  - `merge` (`pr` mode): reviewed pull requests that wait for approval and merge.
  - `accept` (`local` mode): merged work that waits for acceptance. The human removes the label when satisfied, or reopens the bead.
  - `escalated`: unmerged work where the coder and the reviewer disagree. The human reads the findings and disputes, then updates the instructions, assignee and label.
  - `broken-main`: a bug bead that says `main` fails the gate. The coder files it (or reuses an open one), assigns it to the human, makes its own bead depend on it and puts its bead back to `open`. The coder does not park the bead, because `run.sh` starts a coder session every 30 seconds for an `in_progress` bead. A bead with an open dependency is not ready, so the coder sleeps. When the human fixes `main` and closes the bug bead, each blocked bead becomes ready again.
- The rule for closing a bead is that its code must be on `main`. A dependent bead becomes ready only after its blocker closes. In `pr` mode, the human closes the bead after the merge. In `local` mode, the reviewer closes it at the merge.
- The primary checkout belongs to the human. In `pr` mode no agent runs commands in it. In `local` mode, the reviewer first makes sure that it is on `main` with no modified or staged tracked files. Then the reviewer merges there. If it is not, the reviewer parks the bead as "Review passed, awaiting merge". `run.sh` waits for a clean primary before it starts the next reviewer session, and prints "primary checkout busy: <reason>; waiting to start <reviewer>".
- Bead notes are an append-only log. The last status line tells where the bead stands. Use `bd note`, not `bd update --notes`, on a live bead. In `pr` mode the pull request comments copy the review, but the bead notes stay the record.
- Assign a bead to the coder only after the spec ritual: "Read bead `<id>`. Ask me questions about the spec, one round at a time, until you have no questions left. Then update the bead's design field with the final spec." The reviewer reviews against the same design field.
- The loop runs headless with `--dangerously-skip-permissions`. Keep beads small. In `local` mode, the reviewer and the gate are the only checks before `main`.

## Add an agent

`run.sh` knows nothing about the roles. The agent name is the assignee filter, and `run.sh` exports it as `BEADS_ACTOR` so that `bd update --claim` works. A new agent needs these parts:

1. A role prompt in this folder, for example `TESTER.md`. Keep it to the loop protocol. Refer to agents by the names in `project.md`, never by a fixed name.
2. A name in `project.md`, for example `TESTER=Bob`, and its worktree path.
3. A handoff in and a handoff out. Decide which agent assigns beads to the new one. Then decide which agent gets each bead after the new one finishes. Write both handoffs into the prompts as a `bd note` and a `bd update <id> --assignee=<Name>`.
4. Its own worktree. An agent that reads or changes code needs one, and two agents must never share a worktree.
5. Its own `RALPH_LOG_DIR`, and a watcher started with `--agent <Name>`.

`watch.py` finds the current bead from a claim, a commit tag or the reviewer's `Review round <n> started` note. If the new agent does none of these, add its first status note to `watch.py`. The `dev-env-setup` scripts start only the coder and the reviewer. Add the new role to `bootstrap.sh` (the files it copies), `worktrees.sh` and `layout.sh`.

## Tests

```bash
cd loop
uv run --python 3.13 --with pytest --with rich pytest -q tests
```
