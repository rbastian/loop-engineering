# loop

This folder holds the multi-agent loop. Each agent is a headless session that `run.sh` starts again and again. Each agent works only on the beads that are assigned to it. To hand a bead to the next agent, an agent changes the assignee.

The loop has three roles: CODER, REVIEWER and HUMAN. The coder and the reviewer are agents. The coder implements and the reviewer reviews. The human specs, merges and settles escalations. Each project gives the names for all three roles in `.loop/project.md`. The default agent names are Ralph for the coder and Alice for the reviewer.

- The coder implements one bead per session in its own git worktree, on the home branch `loop`.
- The reviewer reads the coder's branch in its own worktree, on a detached HEAD.
- What happens after a review passes depends on the ship mode.

You write the spec interactively, and the agents implement it headlessly. Each session starts fresh and reads its bead, prompts, project configuration and repository. Beads records task progress and handoffs between sessions.

## Ship modes

The ship mode is a setting in `.loop/project.md`. It has two values.

`pr` is the default. Use it for every repository that more than one person works in.

1. The coder pushes the branch to `origin` and opens a pull request against `main`.
2. The reviewer reviews the branch and posts the result as a pull request comment.
3. If the review passes, the reviewer sets `loop=merge` and assigns the bead to the human.
4. The human approves and merges the pull request, then runs `bd close <id>` and `bd set-state <id> loop=done`.

The reviewer comments but does not approve. The agents act as the GitHub account in `GITHUB_ACCOUNT` in `.loop/project.md`, usually the human's own account. GitHub does not let an account approve its own pull request. Any CI on the pull request runs in addition to the gate.

`.loop/project.md` also holds the one list of the remote actions that each role can do in `pr` mode, under "Remote actions in `pr` mode". An action that is not on the list is not allowed.

`local` is only for a repository with one user. No remote is necessary. If the review passes, the reviewer merges the branch into `main` in the primary checkout with `git merge --no-ff`. Then the reviewer closes the bead, sets `loop=accept` and assigns the bead to the human.

### Pull request text

In `pr` mode the coder's pull request description and the reviewer's pull request comments are Markdown. Each agent passes the text with `--body-file -` and a quoted heredoc (`<<'EOF'`). The shell expands nothing inside a quoted heredoc, so backticks, `$` and quotes reach GitHub unchanged. The agent types the bead ID, the round and the sha into the text itself. The bead notes stay plain text with the same markers, because the routing, the watchers and `run.sh` read them.

When it opens the pull request, the coder writes the description once. It has a bead line, a summary, one bullet per changed file or area, and one checklist line per acceptance criterion:

```markdown
Bead: lpe-415

## Summary

The PR description and the review comments are structured Markdown. Each body goes through a quoted heredoc.

## Changes

- `loop/CODER.md`: step 13 opens the PR with `--body-file -`.
- `loop/REVIEWER.md`: each `gh pr comment` uses the headed layout.

## Acceptance criteria

- [x] 1. The PR body uses a quoted heredoc (`test_the_coder_opens_the_pr_with_a_body_file_heredoc`)
- [ ] 2. A live PR shows the layout (not checked: no network in the test run)
```

The reviewer posts one comment for each pass, round 1 fail and escalation. The heading names the outcome and the round: `passed`, `changes needed` or `escalated to <human>`. A short block gives the method, the finding counts and the gate result. Then come `### Blocking findings` (a numbered list, left out on a pass), `### Checked`, `### Non-blocking findings` and `### Acceptance evidence` as a table:

```markdown
## Review by Alice: changes needed (round 1)

/code-review: 3 findings (1 blocking). Gate: passed on `a1b2c3d`, 343 tests.

### Blocking findings

1. `loop/REVIEWER.md`: the escalation comment still uses `--body "..."`.

### Checked

- Design item 5: the bead-note markers are unchanged.

### Non-blocking findings

- None

### Acceptance evidence

| # | Outcome | Evidence |
|---|---|---|
| 1 | verified | `test_the_coder_opens_the_pr_with_a_body_file_heredoc` |
| 2 | not verified | the escalation comment, see finding 1 |
```

If lpe-6er.1 (the Behavior, Soundness and Evidence parts of a review) is built later, it changes these reviewer sections.

## Routing state

The agents do not route on the text of bead notes. Each bead carries two bd state dimensions (named values that bd stores as labels):

- `loop` tells where the bead stands. bd stores it as the label `loop:<value>`.
- `round` is the review round. bd stores it as the label `round:<n>`. A bead with no `round` label is at round 0.

An agent reads a value with `bd state <id> loop` and sets one with `bd set-state <id> loop=<value> --reason "<short reason>"`. Each set replaces the old value. bd also records each change as a closed child bead of type `event`, for example `<id>.1`. These children do not appear in `bd ready`. Do not filter or delete them.

The notes stay the human-readable log, with the same markers as before, for example "Returned to Ralph after review round 1". `watch.py` and the human read them. No agent routes on them.

This table is the one source for the `loop` values. `CODER.md` and `REVIEWER.md` must agree with it. If they do not, `tests/test_routing_state.py` fails.

| `loop` value | Set by | When | Assignee after | Status |
|---|---|---|---|---|
| `coding` | coder | The coder sets it at claim (Phase 1 step 3). When the coder resumes a bead in state `parked`, `escalated` or `blocked`, the coder also sets it. A bead in state `returned` or `rebase` keeps that state until the handoff at step 14. | coder | `in_progress` |
| `review` | coder | At handoff (step 14) after new work or after it addresses review findings | reviewer | `in_progress` |
| `rebased` | coder | At handoff after a rebase only | reviewer | `in_progress` |
| `returned` | reviewer | Round 1 failed | coder | `in_progress` |
| `rebase` | reviewer | Merge conflict, or pull request `CONFLICTING` | coder | `in_progress` |
| `merge-wait` | reviewer | `local` mode, review passed, primary checkout busy | reviewer | `in_progress` |
| `merge` | reviewer | `pr` mode, review passed | human | `in_progress` |
| `accept` | reviewer | `local` mode, merged and closed | human | `closed` |
| `escalated` | reviewer | Round 2 or later failed | human | `in_progress` |
| `parked` | coder or reviewer | The coder: gate fails twice at step 12, push or `gh` fails at step 13, no code written at step 10, or design unclear. The reviewer: Review not run, because its default review method cannot run. | human | If a branch with work exists, use `in_progress`. For no code written or an unclear design, use `open` with the branch deleted. |
| `blocked` | coder | Gate fails on `main` (broken main), beside the dependency on the `broken-main` bug bead | coder | `open` |
| `done` | human | After the merge and `bd close` in `pr` mode, or after acceptance in `local` mode | unchanged | `closed` |

The `round` dimension follows these rules:

1. When the reviewer takes a bead in state `review`, it sets `round=<n>` with n = round + 1. It writes the "Review round <n> started" note.
2. When the reviewer takes a bead in state `rebased`, it keeps the round. It makes sure that the diff still shows what it reviewed, runs the gate again and goes to the outcome. It writes no new "started" note.
3. A failed round 1 sets `loop=returned`. A failed round 2 or later sets `loop=escalated`.
4. When the coder resumes a bead from `escalated`, it sets `round=0`, so that the next review is round 1 with one bounce available. No other resume resets the round.
5. When the reviewer resumes a bead from `parked`, it keeps the round, because the round did not run. It writes a "Review round <n> restarted" note instead of a new "started" note.

A parked or escalated bead goes to the human, so `run.sh` does not wake the coder for it. To resume it, add a note that tells the coder what to do, then run `bd update <id> --assignee=<coder>`. The coder reads your newest note, sets `loop=coding` and continues. A parked bead with status `open` becomes ready and goes through Phase 1, which reuses an existing `feat/` branch.

If its default review method cannot run, the reviewer parks a bead with a "Review not run: <error>" note. Fix the cause, then run `bd update <id> --assignee=<reviewer>`. The reviewer runs the same round again.

## Files

| File | Purpose |
|---|---|
| `run.sh` | The loop. It polls beads for work assigned to one agent name and starts one headless session per iteration. Every agent uses the same script with its own prompt. |
| `CODER.md` | The coder's prompt: the loop protocol for the coder role. |
| `REVIEWER.md` | The reviewer's prompt: the loop protocol for the reviewer role. |
| `project.template.md` | The template for `.loop/project.md`, the project overlay. |
| `interactive.template.md` | The template for the interactive section of `CLAUDE.md` and `AGENTS.md`. The section tells an interactive agent to orient a new person, to refine and assign beads, and not to implement them. |
| `watch.py` | The watcher. It shows a live session log as one line per tool call. |
| `../skills/dev-env-setup/scripts/queue.sh` | The queue script. It shows one agent's in-progress, ready and blocked beads. |
| `tests/` | Tests for `watch.py`, `run.sh`, the setup scripts and the prompts. |

## The project overlay

The agent prompts hold only the loop protocol. They contain no facts about a project. `run.sh` appends `project.md` to each prompt at the start of every session. The overlay gives these facts:

- The agent names (`CODER`, `REVIEWER`) and the human's bd assignee name (`HUMAN`).
- The engine and the model of each agent (`CODER_ENGINE`, `CODER_MODEL`, `REVIEWER_ENGINE`, `REVIEWER_MODEL`). The coder runs on `claude` or `fw`. The reviewer runs on `claude`, `codex` or `fw`.
- The ship mode (`SHIP_MODE`) and, in `pr` mode, the GitHub account of the agents (`GITHUB_ACCOUNT`).
- The paths, the tech stack, the gate, the external services and the extra review checks.

To rename an agent, change its name in `project.md` and restart its loop with the new name. Then assign each open bead of the old name to the new name. Worktree and log paths do not need to follow the name.

These variables control the overlay:

- `LOOP_OVERLAY` points `run.sh` at another overlay file.
- `LOOP_OVERLAY=none` runs the prompt with no overlay.
- `LOOP_PRINT_PROMPT=1` prints the combined prompt and exits. Use it to check an overlay.

## Install in a project

The `dev-env-setup` skill in `../skills/dev-env-setup` does the setup. See the root README for how to install it. The skill asks for the agent names, the ship mode and the human who approves merges. It copies this folder into the project as `.loop/` and writes `.loop/project.md` from the template. It also writes the interactive section into `CLAUDE.md` and `AGENTS.md`, between the `<!-- BEGIN LOOP INTERACTIVE -->` and `<!-- END LOOP INTERACTIVE -->` markers. Then it creates both worktrees and starts both loops and both watchers in herdr.

To set up a project by hand, follow these steps:

1. Copy `run.sh`, `watch.py`, `prices.json`, `CODER.md` and `REVIEWER.md` into the project as `.loop/`.
2. Copy `project.template.md` to `.loop/project.md` and fill every `{{...}}` placeholder.
3. Add `extend-exclude = [".loop"]` under `[tool.ruff]` in `pyproject.toml`, so that the gate does not lint the harness. pytest skips folders that start with a dot.
4. Fill the placeholders in `interactive.template.md` and put the result into `CLAUDE.md` and `AGENTS.md`, after the first H1 heading and before the beads blocks.
5. In `pr` mode, make sure that the repository has an `origin` remote, that `main` is on it, and that `gh` is authenticated.
6. Create the worktrees from the primary checkout:

   ```bash
   git worktree add -b loop ../<name>-ralph main
   git worktree add --detach ../<name>-alice main
   ```

## Running

Start each loop from its worktree, and point it at the `.loop/` files in the primary checkout. Prompt changes merged to `main` then take effect at the next session. The first argument to `run.sh` is the agent name from `project.md`. These examples use the default names.

```bash
cd ../<name>-ralph
LOOP_MODEL=claude-opus-5-5 LOOP_STREAM_LOG=1 LOOP_SHOW_BEAD=1 LOOP_LOG_DIR=/tmp/<name>-ralph-sessions \
  <primary>/.loop/run.sh Ralph <primary>/.loop/CODER.md

cd ../<name>-alice
LOOP_MODEL=claude-sonnet-5-5 LOOP_STREAM_LOG=1 LOOP_SHOW_BEAD=1 LOOP_LOG_DIR=/tmp/<name>-alice-sessions \
  <primary>/.loop/run.sh Alice <primary>/.loop/REVIEWER.md
```

Each loop must have its own `LOOP_LOG_DIR`. `run.sh` points `$LOOP_LOG_DIR/current.jsonl` at each new session log. Two loops that share one directory move the link under each other.

Follow a session with the watcher:

```bash
LOOP_LOG_DIR=/tmp/<name>-ralph-sessions uv run .loop/watch.py --agent Ralph --prefix <prefix> --tui
LOOP_LOG_DIR=/tmp/<name>-alice-sessions uv run .loop/watch.py --agent Alice --prefix <prefix> --tui
```

`--prefix` is the bead prefix from `BEAD_PREFIX` in `.loop/project.md`. With it, the watcher matches only that project's bead IDs. Without it, the watcher matches any prefix, can name the wrong bead, and prints a warning. If `BEAD_PREFIX` is set, `run.sh` passes it to `watch.py --summary`.

`LOOP_ENGINE` selects the agent CLI. It takes `claude` (the default) or `codex`. The coder always runs on `claude`, because its prompt uses the `/simplify` skill. The reviewer can run on `codex`, so that a different model family reads the diff. On `codex`, `LOOP_MODEL` has no default, and the review uses `codex exec review`. Before the first headless Codex session, open `codex` once in the primary checkout, trust the project and approve its hooks.

### Agent queues

`layout.sh` puts an agent queue above each loop in the loop tab:

```text
+-------------------+-------------------+
| coder queue       | reviewer queue    |
+-------------------+-------------------+
| coder loop        | reviewer loop     |
+-------------------+-------------------+
```

An agent queue shows the beads assigned to one agent. In progress lists the agent's active beads with their `loop` state labels. Ready next lists the unblocked beads that wait for the agent. Waiting lists the agent's blocked beads and their blockers.

`queue.sh` lives at `skills/dev-env-setup/scripts/queue.sh` in the loop-engineering clone, not in `.loop/`. To run it by hand, start in the project's primary checkout and give the full path to the skill folder:

```bash
cd /path/to/project
/path/to/loop-engineering/skills/dev-env-setup/scripts/queue.sh --watch Ralph
```

Use your coder or reviewer name in place of Ralph. Leave out `--watch` to print the queue once.

### run.sh variables

| Variable | Effect |
|---|---|
| `LOOP_STREAM_LOG=1` | Write each session as JSONL to `$LOOP_LOG_DIR`, with a `current.jsonl` link to the newest log. After each session, also append a cost note to the bead. |
| `LOOP_LOG_DIR` | The log directory. The default is `/tmp/loop-sessions`. Give each agent its own. |
| `LOOP_SHOW_BEAD=1` | Print `bd show` for each in-progress bead between sessions. |
| `LOOP_SESSION_TIMEOUT` | The wall-clock limit per session. The default is `2h`. The value is a whole number with an optional suffix `s`, `m`, `h` or `d`. `0` means no limit. Any other value stops the loop at startup. See [Session time limit](#session-time-limit). |
| `LOOP_KEEP_AWAKE=1` | Run each session under `caffeinate -i`, so that the Mac does not idle-sleep during a session. It is off by default. Without `caffeinate` on `PATH`, the loop prints one warning and runs without it. |
| `LOOP_ENGINE` | `claude` (the default) or `codex`. |
| `LOOP_MODEL` | The model for each session. The default is `claude-opus-5-5` on `claude` and none on `codex`. |
| `LOOP_OVERLAY` | The overlay file. The default is `project.md` beside the prompt file. `none` turns it off. |
| `LOOP_PRINT_PROMPT=1` | Print the combined prompt and exit. |

Every agent uses the same variables. `LOOP_ENGINE` and `LOOP_REVIEWER_ENGINE` are different variables. `LOOP_ENGINE` is the engine of one `run.sh` process, and `layout.sh` sets it for each loop. `LOOP_CODER_ENGINE` and `LOOP_REVIEWER_ENGINE` are inputs to `bootstrap.sh`, which writes them into `.loop/project.md` as `CODER_ENGINE` and `REVIEWER_ENGINE`. `layout.sh` reads them and the two model fields back, and passes each agent's values to its `run.sh` as `LOOP_ENGINE` and `LOOP_MODEL`.

Before lpe-wh5, these variables started with `RALPH_`. `run.sh` and `watch.py` read only the `LOOP_` names. If you set an old name, the loop uses the default value and does not warn you. Rename each old variable that you set:

| Old name | New name |
|---|---|
| `RALPH_STREAM_LOG` | `LOOP_STREAM_LOG` |
| `RALPH_LOG_DIR` | `LOOP_LOG_DIR` |
| `RALPH_SHOW_BEAD` | `LOOP_SHOW_BEAD` |
| `RALPH_SESSION_TIMEOUT` | `LOOP_SESSION_TIMEOUT` |
| `RALPH_KEEP_AWAKE` | `LOOP_KEEP_AWAKE` |
| `RALPH_ENGINE` | `LOOP_ENGINE` |
| `RALPH_MODEL` | `LOOP_MODEL` |
| `RALPH_OVERLAY` | `LOOP_OVERLAY` |
| `RALPH_PRINT_PROMPT` | `LOOP_PRINT_PROMPT` |

The default log directory changed from `/tmp/ralph-sessions` to `/tmp/loop-sessions`. The first line of each session log now has the type `loop.session`. `watch.py` also reads the old type `ralph.session`, so it can replay an old log.

### Startup block

After every startup check passes, and before it polls for beads, `run.sh` prints its configuration once. For example, the reviewer on `fw` in `pr` mode prints this block:

```text
=== Alice (reviewer) ===
harness  cc@fw/glm-fast-latest[1m]
ship     pr, as rbastian
prompt   .loop/REVIEWER.md + .loop/project.md
logs     /tmp/loop-alice
timeout  2h
version  b7e1166 (up to date)
```

The rows have these values:

| Row | Value |
|---|---|
| title | The agent name and its role. If the name equals `CODER` in the overlay, the role is `coder`. If it equals `REVIEWER`, the role is `reviewer`. Otherwise, the role is `unknown role`. |
| `harness` | The label in the same form as the watcher: `cc/<model>` on `claude`, `codex/<model>` on `codex` (`codex/codex default` with no model), and `cc@fw/<model>` on `fw`. |
| `ship` | `pr, as <GITHUB_ACCOUNT>` in `pr` mode, `local` in `local` mode, and `unknown` with no `SHIP_MODE`. |
| `prompt` | The prompt file and the overlay file. If `LOOP_OVERLAY=none`, the value is `+ no overlay`. |
| `logs` | `LOOP_LOG_DIR`, or `off` without `LOOP_STREAM_LOG`. |
| `timeout` | `LOOP_SESSION_TIMEOUT`, or `none` for `0`. |
| `version` | The short commit from `HARNESS_VERSION`, with `up to date` or the drift text. `unknown` without a stamp. |

A path inside the primary checkout (`PRIMARY` in the overlay) shows relative to it. Every other path shows in full. The block never shows `GH_TOKEN` or an API key. `LOOP_PRINT_PROMPT=1` prints only the prompt, without the block.

Each session starts with one line that names the agent, the role and the same label:

```text
=== 2026-11-05 14:02:11 === Alice (reviewer) on cc@fw/glm-fast-latest[1m]: session starts ===
```

### GitHub account

In `pr` mode, `run.sh` pins the GitHub account that the agents use. A wrong active `gh` account then cannot open a pull request or post a comment. At start, before the first session, `run.sh` does these steps:

1. It reads `GITHUB_ACCOUNT` from `.loop/project.md`. If the value is empty, it stops with an error that names `project.md`.
2. It gets the token of that account with `gh auth token --user <account>`. If that fails, it stops and tells you to run `gh auth login` for that account.
3. It exports the token as `GH_TOKEN` for every session. `gh` uses it, and so does `git` over HTTPS through the credential helper of `gh`. `run.sh` does not print the token.
4. If `origin` is an SSH URL (`git@<host>:...` or `ssh://git@<host>/...`), it runs `ssh -T git@<host>` once. If the reply does not greet `GITHUB_ACCOUNT`, it stops with an error that shows both account names. An HTTPS `origin` gets no SSH check.

Each failure stops the loop with exit code 1. `run.sh` does not change the SSH or git configuration. In `local` mode, `run.sh` skips all of these steps and calls neither `gh` nor `ssh`.

### Session time limit

`run.sh` starts each session in its own process group (the agent and every process it starts). A watchdog compares the clock with the start time every 5 seconds. When the limit passes, it sends INT to the process group, and KILL 60 seconds later if the group still exists. The loop then prints `<engine> session timed out after <limit>` and starts the next iteration.

The limit counts wall-clock time, including time while the Mac sleeps. If the Mac sleeps during a session, the first check after it wakes stops the session. Set `LOOP_KEEP_AWAKE=1` to keep the Mac awake while a session runs.

### Cost notes

An agent cannot record what its own session cost. The cost arrives in the session's closing event, after the agent exits. So `run.sh` records it. When `LOOP_STREAM_LOG=1` is set, `run.sh` reads the finished log with `watch.py --summary` and appends one note to the bead:

```text
Session cost: Ralph, cc/claude-opus-5-5, $1.84 est., 12m30s wall, 41 turns, 18.2k out, 3.1k think, 412k ctx
```

The second field is the label `<harness>[@<provider>]/<model>`. Its first part is the agent CLI: `cc` for Claude Code and `codex` for Codex. If the requests go to a provider that is not the CLI's own, the label includes `@<provider>`. For example, `cc@fw/deepseek-flash-latest[1m]` names the `fw` engine on Fireworks. The watcher shows the same label in its header and on the `── session ──` line. Notes written before lpe-6v6.6 show the model alone, for example `claude-opus-5-5`. A tool that reads cost notes must accept both forms.

The dollar figure is Claude Code's API-equivalent estimate, not a bill. Codex on a ChatGPT plan reports tokens and no dollar figure, and the note says so. Each session of a bead adds one note: the coder's rounds, the reviewer's rounds and any rebase. The sum of the notes is what the bead cost.

`run.sh` takes the bead from the log: the coder's claim or commit tag, or the reviewer's review note. If the log names no bead, `run.sh` uses the one bead that the agent held when the session started. In these cases `run.sh` prints a warning and writes no note:

- The session did not reach its closing event, for example after a crash or a timeout.
- `run.sh` cannot tell which bead the session worked on.
- `bd` is still locked after three tries.

A missing cost note never stops the loop. The note needs `uv` to run `watch.py`. Agents route on the state dimensions, not on notes, so a cost note never changes what a session does.

## Operations

### Stop and restart

Stop both the shell loop and its headless session before restarting. Ctrl-C on a loop sends INT to its session's process group, and KILL 10 seconds later. A session runs in its own process group, so it can outlive a closed terminal tab or a killed `run.sh`. Checkpoint commits, saved files and bead notes provide recovery state for the next session.

1. Press Ctrl-C in each loop pane to stop the shell loop. Make sure that the loop stops instead of starting another session.
2. From another terminal, list candidate agent processes:

   ```bash
   pgrep -fl '.loop/run.sh|claude|codex'
   ```

3. Identify each old session by its working directory and parent process. Replace `12345` with a candidate process ID:

   ```bash
   lsof -a -p 12345 -d cwd
   ps -p 12345 -o pid,ppid,pgid,command
   pgrep -P 12345
   ```

   Match the directory to the coder or reviewer worktree in `.loop/project.md`. If necessary, inspect the parent process. Record the child process IDs and inspect their children too before stopping the session. The list can include unrelated interactive sessions or agents from other projects.
4. Stop only the identified old session and any remaining child processes. For each identified process, replace `12345` with its process ID:

   ```bash
   kill -TERM 12345
   ```

5. Repeat the process checks. Make sure that no shell loop, agent session or child process from the old loops remains before restarting. Do not stop unrelated sessions.

For a Herdr restart, close the project's loop tab, both watcher panes and the Beads pane. Closing panes alone does not show that their sessions stopped. `layout.sh` refuses to start while that tab or those panes exist. From a Herdr pane that fills its tab, run the setup skill's layout script:

```bash
/path/to/loop-engineering/skills/dev-env-setup/scripts/layout.sh /path/to/project
```

The script reads names, paths, engines and models from `.loop/project.md`. The environment variables `CODER_ENGINE`, `CODER_MODEL`, `REVIEWER_ENGINE` and `REVIEWER_MODEL` override them for one start. For a manual restart, use the commands under [Running](#running) from each agent's worktree. In-progress beads take priority over new work.

### Session logs

The setup layout writes logs to `/tmp/<project>-<coder>-sessions` and `/tmp/<project>-<reviewer>-sessions`, with lowercase agent names. Each directory contains session JSONL files and a `current.jsonl` link to the latest session. These temporary files are not a durable archive.

Use the watcher commands under [Running](#running) for a live view. To read an older log, run:

```bash
uv run .loop/watch.py --agent Ralph --prefix <prefix> --file /path/to/session.jsonl --replay
```

Use your configured agent name in place of `Ralph`.

### Update an installed harness

`bootstrap.sh` keeps the files that `.loop/` already holds, so a rerun does not install newer copies of the runner, the watcher or the prompts. `update.sh` in the setup skill does the update. It copies `run.sh`, `watch.py`, `prices.json`, `CODER.md` and `REVIEWER.md` from `loop/` in your loop-engineering clone into `.loop/`. It never changes `.loop/project.md`, and it commits nothing.

The version stamp `.loop/HARNESS_VERSION` tells `update.sh` which version is installed. The stamp has two lines: `commit=`, the full SHA of the clone's HEAD, and `clone=`, the absolute path of the clone. `bootstrap.sh` and `update.sh` write it. If `loop/` in the clone contains uncommitted changes, `bootstrap.sh` adds the line `dirty=1` and prints a warning.

When the clone has newer commits on `loop/` than the stamp, `layout.sh` prints one line:

```text
harness is 3 commits behind loop-engineering; run update.sh
```

`run.sh` prints the same text once at start, in the `version` row of its [startup block](#startup-block). The text is only a warning and never stops a loop. If the stamp is missing, the `version` row shows `unknown`. If the clone path does not exist or the clone does not have the stamped commit, the row shows only the short commit.

To update a project, do these steps:

1. Stop both loops and their sessions with the procedure under [Stop and restart](#stop-and-restart).
2. In the primary checkout, start a branch for the update in `pr` mode. In `local` mode, stay on `main`.
3. Run the update:

   ```bash
   /path/to/loop-engineering/skills/dev-env-setup/scripts/update.sh /path/to/project
   ```

   `update.sh` finds the clone from its own location, like `bootstrap.sh`. Set `LOOP_HOME` to use another clone.
4. Read the diff that `update.sh` prints. Make sure that neither combined prompt contains unresolved `{{...}}` placeholders: run `LOOP_PRINT_PROMPT=1 .loop/run.sh <agent> .loop/CODER.md`, and the same for `.loop/REVIEWER.md`.
5. Commit the change. In `pr` mode, open a pull request, merge it, and pull `main` in the primary checkout.
6. Reset each worktree to `main`. The coder's worktree is on the branch `loop`, so run `git reset --hard origin/main` there in `pr` mode, or `git reset --hard main` in `local` mode.
7. Restart the loops and the watchers.

`update.sh` runs every check before it changes a file. If a check fails, it prints every failure, changes nothing and exits 1. It checks these conditions:

- A loop of the project runs: a `run.sh` process whose arguments name the project's `.loop/` or `ralph/`, or whose working directory is one of the project's worktrees. `update.sh` never stops a process.
- The install has an old `PROMPT.md` or `ALICE.md`. Migrate them by hand.
- `loop/` in the clone contains uncommitted changes. Commit or stash them in the clone first.
- `.loop/project.md` lacks a `KEY=` line that `loop/project.template.md` has. `update.sh` prints each key and what it means. Add the keys, then run `update.sh` again.
- A `KEY=` line in `.loop/project.md` still holds a `{{...}}` placeholder, or `CODER`, `REVIEWER` or `HUMAN` is empty.
- An installed file differs from the same file at the stamped commit: a local edit. `update.sh` prints each diff. Move the edit into `loop/` in the clone, or run `update.sh --force` to overwrite it.
- The stamp is missing, says `dirty=1`, or names a commit that the clone does not have. Then `update.sh` cannot tell a local edit from an old version, so it prints each file's diff against the clone's current version. `--force` overwrites them.
- `CLAUDE.md` or `AGENTS.md` has a BEGIN marker of the interactive section with no END marker after it.

`--force` skips only the local-edit check. All other checks still run.

`update.sh` also refreshes the interactive section of `CLAUDE.md` and `AGENTS.md`. It fills `interactive.template.md` with the names in `.loop/project.md` and replaces the text between the `<!-- BEGIN LOOP INTERACTIVE -->` and `<!-- END LOOP INTERACTIVE -->` markers. A file without the section gets one, in the same place that `bootstrap.sh` puts it. Text outside the markers does not change.

### Move routing state from notes to bd state

Before lpe-0y3, the agents routed on the last marker in the bead notes. The human queues were the labels `merge`, `accept` and `escalated`. The new prompts route only on the `loop` and `round` dimensions, and they have no fallback to note markers. Before you restart the loops on the new prompts, set the state of each bead that is in flight:

1. Stop both loops and their sessions with the procedure under [Stop and restart](#stop-and-restart).
2. List the in-flight beads: `bd list --status=in_progress`, and the beads with the old labels: `bd list --label merge`, `bd list --label accept` and `bd list --label escalated`.
3. For each bead, read its last note marker and set `loop` from the table under [Routing state](#routing-state). For example, "Returned to Ralph after review round 1" becomes `loop=returned`, and "Review passed, awaiting merge" becomes `loop=merge-wait`.
4. For each bead that the reviewer saw, set `round` to the number in its newest "Review round <n> started" note: `bd set-state <id> round=<n>`.
5. Replace each old label with its state: run `bd set-state <id> loop=<value>`, then `bd label remove <id> <old label>`.
6. Update the installed prompts as in [Update an installed harness](#update-an-installed-harness), then restart the loops.

### Move an install from ralph/ to .loop/

Before lpe-wh5, `bootstrap.sh` installed the harness into `ralph/`. It now installs into `.loop/`. If a project has `ralph/` and no `.loop/`, `update.sh` moves the install and then updates it in the same run:

1. It runs every check from [Update an installed harness](#update-an-installed-harness) against `ralph/`. If a check fails, it stops before the move.
2. It moves the folder with `git mv ralph .loop`.
3. It changes each `ralph/` path in `.loop/project.md` to `.loop/`.
4. It prints each line outside the interactive section of `CLAUDE.md` and `AGENTS.md` that still names `ralph/`. Change those lines by hand. The interactive section itself gets the new text.
5. It prints the `RALPH_` to `LOOP_` renames from the table under [run.sh variables](#runsh-variables). Rename each variable that your shell or herdr setup sets.
6. It does the update.

Then exclude `.loop` from ruff, as in step 3 of [Install in a project](#install-in-a-project). Commit the change as in the update steps.

## Rules of engagement

- The coder implements and the reviewer reviews. In `pr` mode the human approves and merges. In `local` mode the reviewer merges and the human accepts.
- The reviewer's default method always runs on every branch: the `/code-review` skill at high effort on `claude`, or `codex exec review` on `codex`. The Project section only adds checks to it. The `Review summary:` note gives the number of findings that the default method returned.
- The reviewer checks each acceptance criterion itself. A coder's note alone is not evidence. Before the `Review summary:` note, the reviewer writes one `Acceptance evidence:` note, with one entry per criterion. Each entry is verified, trusted or not verified. A verified entry names the test, command or line that supports it. If the reviewer cannot repeat the check, a trusted entry names the coder's note that reports the result. A criterion that is not verified is a blocking finding. In `pr` mode the pull request comment carries the same list as a table, one row per criterion.
- If the reviewer finds a blocking problem, it returns the bead to the coder once. After a second failed round, it escalates the bead to the human.
- The human has these queues. Each queue is a `loop` state label, and `bd list --label <label>` lists it. The `loop:accept` beads are closed, so list that queue with `bd list --label loop:accept --status=closed`:
  - `loop:merge` (`pr` mode): reviewed pull requests that wait for approval and merge. After the merge, run `bd close <id>` and `bd set-state <id> loop=done`.
  - `loop:accept` (`local` mode): merged work that waits for acceptance. If you are satisfied, run `bd set-state <id> loop=done`. Otherwise, reopen the bead.
  - `loop:escalated`: unmerged work where the coder and the reviewer disagree. Read the findings and disputes, add a note with your decision, and assign the bead back to the coder.
  - `loop:parked`: work that the coder cannot continue, for example a gate that fails twice, a failed push or an unclear design. Read the coder's note, fix the cause or add a note, and assign the bead back to the coder. If its default review method cannot run, the reviewer also parks a bead. For a `Review not run:` note, fix the cause and assign the bead back to the reviewer.
  - `broken-main`: a bug bead that says `main` fails the gate. The coder files it or reuses an open one. The coder assigns it to the human and makes its own bead depend on it. The coder sets `loop=blocked` and puts its bead back to `open`. A bead with an open dependency is not ready, so the coder sleeps. When the human fixes `main` and closes the bug bead, each blocked bead becomes ready again.
- The rule for closing a bead is that its code must be on `main`. A dependent bead becomes ready only after its blocker closes. In `pr` mode, the human closes the bead after the merge. In `local` mode, the reviewer closes it at the merge.
- The primary checkout belongs to the human. In `pr` mode no agent runs commands in it. In `local` mode, the reviewer first makes sure that it is on `main` with no modified or staged tracked files. Then the reviewer merges there. If it is not, the reviewer sets `loop=merge-wait` and keeps the bead. `run.sh` waits for a clean primary before it starts the next reviewer session, and prints `primary checkout busy: <reason>; waiting to start <reviewer>`.
- Bead notes are an append-only log for humans. The `loop` and `round` state tells where the bead stands. Use `bd note`, not `bd update --notes`, on a live bead. In `pr` mode the pull request comments copy the review, but the bead notes stay the record.
- Assign a bead to the coder only after the spec ritual: "Read bead `<id>`. Ask me questions about the spec, one round at a time, until you have no questions left. Then update the bead's design field with the final spec." The reviewer reviews against the same design field.
- The loop runs headless with `--dangerously-skip-permissions`. Keep beads small. In `local` mode, the reviewer and the gate are the only checks before `main`.

## Add an agent

`run.sh` knows nothing about the roles. The agent name is the assignee filter, and `run.sh` exports it as `BEADS_ACTOR` so that `bd update --claim` works. A new agent needs these parts:

1. A role prompt in this folder, for example `TESTER.md`. Keep it to the loop protocol. Refer to agents by the names in `project.md`, never by a fixed name.
2. A name in `project.md`, for example `TESTER=Bob`, and its worktree path.
3. A handoff in and a handoff out. Decide which agent assigns beads to the new one. Then decide which agent gets each bead after the new one finishes. Write both handoffs into the prompts as a `bd note` and a `bd update <id> --assignee=<Name>`.
4. Its own worktree. An agent that reads or changes code needs one, and two agents must never share a worktree.
5. Its own `LOOP_LOG_DIR`, and a watcher started with `--agent <Name>`.

`watch.py` finds the current bead from a claim, a commit tag or the reviewer's `Review round <n> started` note. If the new agent does none of these, add its first status note to `watch.py`. The `dev-env-setup` scripts start only the coder and the reviewer. Add the new role to `bootstrap.sh` (the files it copies), `worktrees.sh` and `layout.sh`.

## Tests

```bash
cd loop
uv run --python 3.13 --with pytest --with rich pytest -q tests
```
