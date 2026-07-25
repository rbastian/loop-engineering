# AI Guild Demo Runbook — 15 minutes, hybrid live + pre-run

**Format:** live spec-refinement session + pre-run ralph results. The headless loop is never run live — it's minutes of silent tool calls and a CI wait you cannot afford in a 15-minute slot.

**The one-sentence pitch you're building to:** *"I spec work with an agent until there are no open questions, hand the bead to a loop, and it ships a merged PR while I do something else."*

---

## Day before

- [ ] Pick **two small beads** in the demo project, each shippable in one session with CI under ~5 min:
  - **Bead A (pre-run):** fully spec'd. This one ralph completes before the meeting.
  - **Bead B (live):** deliberately thin spec — one paragraph, missing details you can answer from memory. This is the live segment's raw material.
- [ ] Rehearse the full flow once on a throwaway bead: spec → assign → loop → PR → merge → close. Note actual timings.
- [ ] Record fallback material during the rehearsal: screen recording (or `asciinema`) of the loop session, plus screenshots of the PR, the merge, and the closed bead. Put them in a local `fallback/` folder.
- [ ] Confirm repo hygiene: `main` green, merge queue empty, auto-merge enabled, branch protection as expected.

## T-60 → T-30 (before the meeting)

- [ ] Assign Bead A: `bd update <A> --assignee=Ralph`
- [ ] In the ralph worktree: `RALPH_STREAM_LOG=1 ./run.sh Ralph PROMPT.md`
- [ ] Watch it through to **PR merged + bead closed**. Do not clear the terminal — the scrollback is demo material.
- [ ] If anything fails, fix and re-run now. This is why you start an hour early.

## T-10

- [ ] Verify end state: `bd show <A>` closed; PR shows merged; note whether ralph filed any discovered-work beads (gold if it did — call it out).
- [ ] Terminal layout (large font, dark-on-light if projecting):
  - **Pane 1:** interactive Claude Code session in the main checkout (for the live segment)
  - **Pane 2:** run.sh scrollback from the pre-run
  - **Pane 3:** `tail -20 /tmp/ralph-sessions/current.jsonl | jq -r '.type // empty'` ready to run (or just the file open)
  - **Browser tab:** the merged PR for Bead A
- [ ] Notifications off, Slack closed.

---

## Minute-by-minute

**0:00–1:30 — Hook + problem.**
"Before this meeting I assigned a work item to an agent called ralph. It's already shipped — I'll show you the merged PR in a few minutes. First, the problem this solves." Then the two-sentence version: agents have no memory between sessions; their markdown plans rot; discovered problems get noticed and forgotten.

**1:30–3:00 — The two borrowed ideas.**
Beads (Yegge): work lives in a queryable dependency graph, not prose — show `bd ready` output. Ralph (Huntley): one task per loop iteration, fresh context every time, human engineers the loop rather than the code. Don't linger; the articles are in the README.

**3:00–7:30 — LIVE: the spec ritual (the memorable part).**
- `bd show <B>` — point out how thin the spec is.
- In the interactive session, paste your standard prompt: *"Read bead `<B>`. Ask me questions about the spec until you have no questions left, then update the bead's design field."*
- Answer **two rounds max**, then narrate: "in real use I keep going until it's dry — that's the whole trick; every question answered here is a guess the headless agent won't make."
- Have the agent write the spec to the bead and assign it: `bd update <B> --assignee=Ralph`. "Ralph will pick this up next time the loop runs — that's tonight's episode, not this one."

**7:30–12:00 — The pre-run reveal.**
- Pane 2: scroll the run.sh output top-to-bottom — bead detected, session start, session end, exit code. Fast.
- Pane 3: ten seconds on the JSONL stream — "every tool call is logged; this is how I review what it did."
- `bd show <A>`: walk the breadcrumb notes in order — branch created, checkpoint committed, PR #N opened, closed. "This is the crash-recovery trail; any interrupted session resumes from these."
- Browser: the merged PR. Point at the test-first commits and the `Closes <bead-id>` line.
- If ralph filed a discovered-work bead: show it. "It hit something out of scope and filed it instead of fixing it or forgetting it. This alone pays for the setup."

**12:00–13:30 — Lessons (credibility segment).**
Three bugs found by reviewing the harness before trusting it: the daemon died on any bad session exit (`set -e`); a crashed session stranded its bead forever (no resume phase); and `bd --claim` silently required the actor identity to match. Moral: *review your automation like production code — the loop is the thing you're actually engineering.*

**13:30–15:00 — Adoption + Q&A.**
Repo: `github.com/rbastian/loop-engineering`. "Install `bd`, copy the template, fill in five placeholders, start with one small bead." Safety caveat in one line: auto-merge means CI is your only gate — choose your repos accordingly.

---

## Fallbacks

| Failure | Response |
|---------|----------|
| Live agent slow or hangs during spec segment | Narrate over the rehearsal recording; show the finished spec on the rehearsal bead instead. Cut, don't wait — never watch a spinner in silence. |
| Network/VPN dies | Everything after minute 3 works from scrollback + `fallback/` screenshots. The `bd` database is local. |
| Pre-run failed and you couldn't fix it by T-10 | Present the rehearsal recording as the pre-run. It is exactly as honest — it's the same process, run yesterday. |
| Running long at minute 12 | Drop the lessons segment, keep the repo link. The reveal is the payload. |

## Things not to do

- Don't run `run.sh` live. Don't demo on a repo with real deadlines attached.
- Don't show `--dangerously-skip-permissions` without saying the safety-caveat line — someone will ask, and it's better delivered than extracted.
- Don't let Q&A pull you into orchestrator-wars territory (Gas Town vs Loom vs Flow); redirect to "start with one bead and one loop."
