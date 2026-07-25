# Talking Points — "Spec interactively, implement headlessly"

Narrative arc for the AI Guild session. Six beats, one slide each if you want slides at all — the terminal is the better visual for beats 3–5.

---

## 1. The claim (hook)

Before this meeting, I handed a work item to an unattended agent. By the time I finish this sentence's slide, it has: created a branch, written tests first, implemented, self-reviewed, opened a PR, waited for the merge queue, and closed the ticket. I'll show you the receipts.

**The point is not "AI writes code."** Everyone here has seen that. The point is a *repeatable process* where the human's effort goes into two places only: the specification, and the failure modes of the loop.

## 2. The problem: agent amnesia

- Coding agents have no memory between sessions, and sessions are short. Every compaction is a head injury.
- Their default coping mechanism — markdown plan files — decays: plans spawn sub-plans, outer context evaporates, and eventually the agent declares victory on phase 3-of-5 of phase 3-of-6. (Yegge ended up with 605 dead plan files before giving up on plans.)
- Worse, work discovered mid-task ("these tests were already broken") gets noticed, mentioned, and *lost* — there's nowhere durable to put it.

Source: Steve Yegge, *Introducing Beads* — the best written diagnosis of this failure mode. Link in the repo README.

## 3. The two borrowed ideas

- **Beads (Yegge):** an issue tracker built for agents. Work is a dependency graph in a local database, queryable from the CLI: `bd ready` answers "what can I start right now?" in one command. A fresh agent session re-orients in seconds instead of re-reading prose. Discovered work becomes a linked issue, permanently.
- **The ralph loop (Huntley):** don't run one long, degrading session — run a *loop* of short, disposable ones. One task per iteration, fresh context each time. Your job shifts from writing code to watching the loop and permanently eliminating each class of failure you observe.

My setup is the minimal synthesis: **Beads holds the what; the loop provides the how.**

## 4. The process (demo)

1. **Spec ritual (live):** in an interactive session — *"Read this bead. Ask me questions until you have none left."* Iterate to dry. Every question answered here is a guess the headless agent won't have to make later; this is where the human adds the most value per minute.
2. **Handoff:** `bd update <id> --assignee=Ralph`. That's the entire deployment step.
3. **The loop (pre-run):** a ~130-line shell script polls for ralph's beads and launches one headless Claude Code session per bead. The session claims the bead, branches off main, writes tests first, implements, lints, self-reviews, opens a PR, enables auto-merge, and closes the bead only when the code is actually on `main`.
4. **The receipts:** breadcrumb notes on the bead (branch, checkpoints, PR number), a JSONL log of every tool call, and the merged PR.

## 5. Lessons learned (what I'd tell you before you copy this)

- **The spec ritual is load-bearing.** Skipping it produces exactly the guessing and shortcut-taking you'd expect. The quality of the headless run is decided before it starts.
- **Review the harness like production code.** A code review of my own loop found three real bugs: the daemon died on any failed session (`set -e` swallowed the retry logic); a crashed session stranded its bead forever (no resume step); and `bd --claim` requires the actor identity to match the assignee (`BEADS_ACTOR`), which would have failed on the first bead. Huntley's advice generalizes: *the loop is the artifact you're actually engineering.*
- **Bead status must mirror reality.** A bead closes when its PR merges — never before. Disposable sessions only work because the durable state is trustworthy.
- **Small beads win twice.** Sessions stay near the start of the context window (better decisions, fewer end-of-context shortcuts) and each session is cheap to throw away.

## 6. Honest caveats + how to start

- The headless session runs with permissions checks off, and auto-merge means **CI is the only gate to `main`**. I run this on repos where that trade-off is deliberate. Add a human-review gate if yours isn't.
- Costs tokens; budget like a tool, not a toy.
- This is one loop and one agent — deliberately. No orchestrator, no swarm. Walk before Gas Town.

**Start here:** `github.com/rbastian/loop-engineering` — install `bd`, copy `PROMPT_TEMPLATE.md`, fill in five placeholders, pick one small well-spec'd bead, run the loop, and read every line it produced. Scale only after the loop has earned it.

---

## Anticipated questions

- **"How is this different from just using Claude Code?"** — Continuity and unattended operation. Interactive sessions die with their context; this survives crashes, spans days, and never loses discovered work.
- **"Why Beads and not Jira/ADO?"** — Latency and shape. The agent needs a sub-second, local, queryable dependency graph with atomic claims, not a web UI and a ticket workflow. (Nothing stops you mirroring milestones into ADO for humans.)
- **"What if it writes bad code?"** — Same answer as for humans: tests first, CI, and review gates sized to the repo's stakes. Plus: every session's tool calls are in the JSONL log; behavioral review is possible in a way it isn't with humans.
- **"Did it ever go wrong?"** — Yes, and each failure became either a prompt rule or a script fix. That's the method: failures are input to the loop's design, not anecdotes.
- **"Can we run more than one ralph?"** — The pieces are there (atomic claims, per-agent worktrees), but one loop is the right starting dose. Multi-agent is a different talk.
