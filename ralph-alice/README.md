# ralph-alice

This folder holds a two-agent version of the loop. Ralph is the writer and Alice is the reviewer. The loop runs locally, with no remote and no pull requests:

- Ralph implements one bead per session in his own git worktree, on the home branch `loop`.
- Alice reviews his branch in her own worktree, on a detached HEAD.
- If the review passes, Alice merges the branch into `main` in the primary checkout.

The idea is the same as in the root of this repository. You write the spec interactively, and the agents implement it headlessly. Each session starts with a fresh context, and the beads database is the only memory.

| | Root loop | ralph-alice |
|---|---|---|
| Workspace | One worktree, ships through a remote | Two worktrees: `../<name>-ralph` (branch `loop`) and `../<name>-alice` (detached HEAD) |
| Ship | Push, pull request, auto-merge, CI | Ralph hands the bead to Alice. Alice reviews and runs `git -C <primary> merge --no-ff`. |
| Merge gate | CI and branch protection | Alice's review against the bead's design, then the project gate on the final code |
| Remote | Required (gh, auto-merge) | None |

## Files

| File | Purpose |
|---|---|
| `run.sh` | The loop. It polls beads for work assigned to one agent name and starts one headless session per iteration. Ralph and Alice use the same script with different prompts. |
| `PROMPT.md` | Ralph's prompt: the loop protocol for the writer. |
| `ALICE.md` | Alice's prompt: the loop protocol for the reviewer. |
| `project.template.md` | The template for `ralph/project.md`, the project overlay. |
| `watch.py` | The watcher. It shows a live session log as one line per tool call. |
| `tests/` | Tests for `watch.py`. |

## The project overlay

`PROMPT.md` and `ALICE.md` hold only the loop protocol. They contain no facts about a project. `run.sh` appends `project.md` to each prompt at the start of every session. The overlay gives the paths, the tech stack, the gate, the external services and Alice's review method.

- `RALPH_OVERLAY` points `run.sh` at another overlay file.
- `RALPH_OVERLAY=none` runs the prompt with no overlay.
- `RALPH_PRINT_PROMPT=1` prints the combined prompt and exits. Use it to check an overlay.

## Install in a project

The `dev-env-setup` skill in `../skills/dev-env-setup` does the setup. See the root README for how to install it. The skill copies this folder into the project as `ralph/` and writes `ralph/project.md` from the template. Then it creates both worktrees and starts both loops and both watchers in herdr.

To set up a project by hand, follow these steps:

1. Copy `run.sh`, `watch.py`, `PROMPT.md` and `ALICE.md` into the project as `ralph/`.
2. Copy `project.template.md` to `ralph/project.md` and fill every `{{...}}` placeholder.
3. Create the worktrees from the primary checkout:

   ```bash
   git worktree add -b loop ../<name>-ralph main
   git worktree add --detach ../<name>-alice main
   ```

## Running

Start each loop from its worktree, and point it at the `ralph/` files in the primary checkout. Prompt changes merged to `main` then take effect at the next session.

```bash
cd ../<name>-ralph
RALPH_MODEL=claude-opus-5-5 RALPH_STREAM_LOG=1 RALPH_SHOW_BEAD=1 RALPH_LOG_DIR=/tmp/<name>-ralph-sessions \
  <primary>/ralph/run.sh Ralph <primary>/ralph/PROMPT.md

cd ../<name>-alice
RALPH_MODEL=claude-sonnet-5-5 RALPH_STREAM_LOG=1 RALPH_SHOW_BEAD=1 RALPH_LOG_DIR=/tmp/<name>-alice-sessions \
  <primary>/ralph/run.sh Alice <primary>/ralph/ALICE.md
```

Each loop must have its own `RALPH_LOG_DIR`. `run.sh` points `$RALPH_LOG_DIR/current.jsonl` at each new session log. Two loops that share one directory move the link under each other.

Follow a session with the watcher:

```bash
RALPH_LOG_DIR=/tmp/<name>-ralph-sessions uv run ralph/watch.py --agent Ralph --tui
RALPH_LOG_DIR=/tmp/<name>-alice-sessions uv run ralph/watch.py --agent Alice --tui
```

`RALPH_ENGINE` selects the agent CLI. It takes `claude` (the default) or `codex`. Ralph always runs on `claude`. Alice can run on `codex`, so that a different model family reads the diff. On `codex`, `RALPH_MODEL` has no default, and Alice's review uses `codex exec review --base main`. Before the first headless Codex session, open `codex` once in the primary checkout, trust the project and approve its hooks.

## Rules of engagement

- Ralph implements, Alice reviews and merges, and the human accepts. If Alice finds a blocking problem, she returns the bead to Ralph once. After a second failed round, she escalates the bead to the human.
- The human has two queues. The label `accept` marks merged work that waits for acceptance. The label `escalated` marks unmerged work where Ralph and Alice disagree.
- At the merge, Alice closes the bead. The human accepts it later. A dependent bead becomes ready after its blocker closes, so the queue does not wait for the human.
- The primary checkout belongs to the human. Before a merge, Alice makes sure that it is on `main` with no modified or staged tracked files. If it is not, she parks the bead as "Review passed, awaiting merge".
- Bead notes are an append-only log. The last status line tells where the bead stands. Use `bd note`, not `bd update --notes`, on a live bead.
- Assign a bead to Ralph only after the spec ritual: "Read bead `<id>`. Ask me questions about the spec, one round at a time, until you have no questions left. Then update the bead's design field with the final spec." Alice reviews against the same design field.
- The loop runs headless with `--dangerously-skip-permissions`. Alice and the gate are the only automated checks, so keep beads small.

## Tests

```bash
cd ralph-alice
uv run --python 3.13 --with pytest --with rich pytest -q tests
```
