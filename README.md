# loop-engineering

A small, practical harness for running [Claude Code](https://claude.com/claude-code) as an autonomous implementation agent, with [Beads](https://github.com/gastownhall/beads) as its persistent memory and work queue.

The core idea, in one sentence: **specify interactively, implement headlessly.**

- A human and an agent refine a work item (a "bead") together until the spec has no open questions.
- The bead is assigned to **ralph** — a shell loop that repeatedly launches a fresh headless Claude Code session to pick up one ready bead, implement it test-first, open a PR, and close the bead once the PR merges.
- Each session starts with a clean context window and re-orients itself entirely from the bead database. No markdown plans, no session memory, nothing to decay.

## Why

Coding agents have no memory between sessions, and their markdown plans rot: plans spawn sub-plans, compactions erase the outer context, and discovered problems get noticed and then forgotten. Two writeups shaped this setup:

- **Steve Yegge — [Introducing Beads](https://steve-yegge.medium.com/introducing-beads-a-coding-agent-memory-system-637d7d92514a):** replace prose plans with a dependency-aware issue graph agents can *query* (`bd ready`), so a fresh session re-orients in seconds and discovered work is filed instead of lost.
- **Geoffrey Huntley — [everything is a ralph loop](https://ghuntley.com/loop/):** run the agent in a loop, one task per iteration, and put your engineering effort into watching the loop and eliminating each failure class so it never recurs.

This repo is the minimal synthesis: Beads holds the *what*, the loop provides the *how*, and the human's job is the spec and the loop's failure modes.

## What's here

| File | Purpose |
|------|---------|
| `run.sh` | The ralph loop. Polls Beads for work assigned to an agent name, launches one headless Claude Code session per iteration, sleeps, repeats. |
| `PROMPT_TEMPLATE.md` | The prompt each headless session receives. Defines a four-phase workflow: resume check → implement (TDD) → clean → ship (PR, auto-merge, close bead). |
| `docs/DEMO_RUNBOOK.md` | Minute-by-minute script for demoing the process live. |
| `docs/TALKING_POINTS.md` | Narrative arc and slide outline for presenting it. |

## Prerequisites

- [Claude Code](https://claude.com/claude-code) CLI, authenticated
- [Beads](https://github.com/gastownhall/beads) (`bd`) — installed system-wide, `bd init` run in the target repo
- [GitHub CLI](https://cli.github.com/) (`gh`), authenticated, with auto-merge enabled on the target repo
- `jq`
- GNU `timeout` for per-session time limits (macOS: `brew install coreutils`) — optional but recommended

## Setup

1. **Create a dedicated git worktree** for the agent, on a home-base branch named `loop`:

   ```bash
   git worktree add ../myproject-ralph loop
   ```

   The agent branches off `origin/main` for each bead and never touches your checkout.

2. **Instantiate the prompt.** Copy `PROMPT_TEMPLATE.md` into the worktree as `PROMPT.md` and fill in the `{{PLACEHOLDERS}}` (project name/description, tech stack, key directories, lint commands, merge-queue notes).

3. **Spec the work.** In an interactive Claude Code session, flesh out a bead until it can stand alone:

   > Read bead `<id>`. Ask me questions about the spec, one round at a time, until you have no questions left. Then update the bead's design field with the final spec.

   This ritual is the load-bearing step — it front-loads every clarification that a headless agent would otherwise resolve by guessing.

4. **Assign and run:**

   ```bash
   bd update <id> --assignee=Ralph
   cd ../myproject-ralph && /path/to/run.sh Ralph PROMPT.md
   ```

### Options

| Variable | Effect |
|----------|--------|
| `RALPH_STREAM_LOG=1` | Tee each session's tool calls/turns as JSONL to `$RALPH_LOG_DIR` (default `/tmp/ralph-sessions`), with a `current.jsonl` symlink for `tail -f`. |
| `RALPH_SHOW_BEAD=1` | Print `bd show` for each in-progress bead between sessions. |
| `RALPH_SESSION_TIMEOUT` | Wall-clock cap per session (default `2h`). |

## Design notes

- **One bead per session, then exit.** Sessions are disposable; the agent always works near the start of its context window, where it makes its best decisions and takes the fewest shortcuts.
- **Bead status mirrors `main`.** A bead closes only when its PR has actually merged. A session may legitimately end with the PR still in the merge queue — the next session's resume check (Phase 0) reconciles it.
- **Crash-safe by construction.** Checkpoint commits plus breadcrumb notes on the bead (`Branch created: …`, `Checkpoint committed: …`, `PR #N opened…`) mean any interrupted session can be resumed by the next one.
- **Discovered work is never lost.** Bugs and orthogonal work become new beads; in-scope subtasks become hierarchical child beads — never prose notes.
- **`BEADS_ACTOR` matters.** `run.sh` exports it to the agent name; without it, `bd update --claim` fails because the actor won't match the bead's assignee.

## Safety caveats

The headless session runs with `--dangerously-skip-permissions` and ships via PR auto-merge, so the only gates between the agent and `main` are your CI and branch protection. Run it in a dedicated worktree, on repos where that trade-off is acceptable, with credentials scoped as tightly as you can. If you want a human gate, replace the auto-merge step with "request review and exit" — the resume logic handles the rest unchanged.

## Credits

Process synthesized from Steve Yegge's Beads posts and Geoffrey Huntley's ralph-loop writing. Reviewed and hardened with Claude Code — see the commit history for the bugs found along the way, which are themselves a decent argument for reviewing your automation like production code.
