Your goal is to pick up and complete one ready bead assigned to you.

## Context

This project is **{{PROJECT_NAME}}** — {{PROJECT_DESCRIPTION}}. All work is tracked through beads.

Find your next bead:

```bash
bd ready --assignee={{AGENT_NAME}}
```

Then review it:

```bash
bd show <id>
```

The bead's description and design fields contain all the context you need for implementation.

**Tech Stack:**
{{TECH_STACK}}

{{KEY_DIRECTORIES}}

## Task Management (Beads)

**CRITICAL: You work on ONE bead at a time. NEVER start another bead until the current one is closed.**

Your workflow has four phases. Always start with Phase 0.

### Phase 0 — Resume check (ALWAYS FIRST)

Before looking for new work, check for a bead you already claimed in a previous session:

```bash
bd list --assignee={{AGENT_NAME}} --status=in_progress
```

- If **nothing** is in progress → go to Phase 1.
- If a bead is in progress, you MUST resume it instead of picking up new work. Run `bd show <id>` — the notes contain the branch name, checkpoint commits, and PR number. Re-enter the workflow at the right point:
  - **PR merged** → `bd close <id>`, clean up the branch (see Worktree Hygiene), and EXIT.
  - **PR open, checks failed** → check out the branch, fix, push, re-enable auto-merge (Phase 3, step 14).
  - **PR open, checks pending** → EXIT; a later session will reconcile.
  - **PR closed without merging** → find out why (`gh pr view <number> --comments`), note it on the bead, and either fix and reopen the PR or set the bead back to open for human review.
  - **No PR yet** → check out the branch from the notes, run `git log origin/main..HEAD` and `git diff` to see how far you got, and continue from the matching phase.

### Phase 1 — Implement

1. Run `bd ready --assignee={{AGENT_NAME}}` to find the highest-priority unblocked bead.
2. Run `bd show <id>` to review the bead details, design, and dependencies.
3. Claim it atomically: `bd update <id> --claim`
4. **Create the feature branch immediately** (see Git Workflow below).
   → `bd update <id> --notes="Branch created: feat/<name>"`
5. **Write tests FIRST** before implementing (Test-Driven Development).
6. Implement and get tests passing.
7. **Commit checkpoint:** `git add <files> && git commit -m "wip: <description> [<bead-id>]"` — saves your work in case the session drops.
   → `bd update <id> --notes="Checkpoint committed: $(git rev-parse --short HEAD)"`

### Phase 2 — Clean

8. Run these commands in sequence:
   {{LINT_COMMANDS}}
   Then run `/simplify` to review the code.

9. **Immediately after `/simplify` returns**, move to Phase 3 — do it NOW, before anything else. `/simplify` returning "no fixes needed", "All clean", "Here's what was fixed", or ANY other output means your code passed review. It does NOT mean you are done. You have not shipped yet.

### Phase 3 — Ship (MANDATORY)

**You MUST complete every step below before exiting. No exceptions.**

10. Verify there is work to ship. Because you commit checkpoints during Phase 1, a clean `git status` does NOT mean there is nothing to ship — check the branch against main:
    ```bash
    git status
    git log origin/main..HEAD --oneline
    ```
    - Commits ahead of `origin/main` and/or uncommitted changes → continue to step 11.
    - NO commits ahead AND a clean tree → you did not complete the bead. Run `bd update <id> --status=open --notes="No code written — needs clarification"`, delete the feature branch (`git checkout loop && git branch -D <branch>`), and EXIT.
11. If there are uncommitted changes: `git add <files> && git commit -m "feat: <description> [<bead-id>]"`
12. `git push -u origin <branch-name>`
13. Open PR:
    ```bash
    gh pr create --title "feat: <description>" --body "$(cat <<'EOF'
    ## Summary
    <1-3 bullet points>

    Closes <bead-id>

    ## Test plan
    <bulleted checklist>
    EOF
    )"
    ```
14. Enable auto-merge and record the PR on the bead:
    ```bash
    gh pr merge <number> --auto
    bd update <id> --notes="PR #<number> opened, auto-merge enabled"
    ```
15. Give the merge queue ONE bounded window (~5 minutes) to complete — do NOT poll forever:
    ```bash
    for i in 1 2 3 4 5 6 7 8 9 10; do
      state=$(gh pr view <number> --json state --jq '.state')
      [ "$state" != "OPEN" ] && break
      sleep 30
    done
    echo "PR state: $state"
    ```
16. Act on the result:
    - **MERGED** → `bd close <id>`, delete the branch (`git checkout loop && git branch -d <branch>`), and EXIT.
    - **Still OPEN** → run `gh pr checks <number>`:
      - Checks **failed** → read the failure, fix, push, re-enable auto-merge, and repeat step 15 ONCE. If it fails again, leave the bead `in_progress` with a note describing the failure and EXIT.
      - Checks **pending** → leave the bead `in_progress` (the note from step 14 tells the next session where to pick up) and EXIT. Phase 0 of a later session will close the bead once the PR merges.
    - **CLOSED** (rejected without merge) → note the reason on the bead, set it back to open, and EXIT.
17. EXIT. **Do NOT start another bead.**

### Self-check: Am I done?

Before exiting, verify your end state is ONE of these two:

- **Shipped:** code committed and pushed, PR merged, bead closed, feature branch deleted.
- **In the queue:** code committed and pushed, PR open with auto-merge enabled, bead `in_progress` with a note recording the PR number.

Any other state means you are NOT done. Go back to the first incomplete step.

**Work on the most important bead first.** Beads are ordered by priority and dependencies.

## Git Workflow

Each bead gets its own feature branch off `main`. {{MERGE_QUEUE_NOTE}}

**Commit message format:** `feat: <description> [<bead-id>]`

**Branch naming:** `feat/<short-description>-<bead-short-id>`

### Worktree Hygiene

You are working in a **separate git worktree** — you cannot checkout `main` because it is checked out in the primary worktree. Your home base branch is `loop`.

**Before starting work:**

1. If `git status` shows a dirty tree (a previous session crashed mid-work), do NOT discard it — commit it on the current branch: `git add -A && git commit -m "wip: crash-recovery checkpoint"`. If that branch belongs to the in-progress bead you are resuming, keep working there.
2. Create feature branches directly from `origin/main` — no need to touch `loop` first:

```bash
git fetch origin main
git checkout -b feat/<short-description>-<bead-short-id> origin/main
```

**After a bead ships (PR merged):** `git checkout loop && git branch -d <feature-branch>` so the next session starts clean.

## Merge Queue and Dependencies

**CRITICAL: Do NOT close a bead until its PR has actually merged to `main`.** Bead status must reflect the true state of the codebase. It is fine — and expected — for a session to end with the bead still `in_progress` while its PR waits in the merge queue; Phase 0 of the next session reconciles it.

**When a bead has upstream dependencies:**

- A bead showing as "ready" in `bd ready` means its logical blockers are closed.
- Before starting, verify the dependency's code is actually on `main`: `git fetch origin main && git log origin/main --oneline -5`
- If the upstream PR is still in the merge queue, **do not start the dependent bead**. EXIT and let the next session pick it up.
- Never branch off another feature branch to "stack" work — always branch from `main`.

## Definition of Done

A bead is **not complete** until ALL of the following are true:

- [ ] Tests are written FIRST (before implementation)
- [ ] Implementation is 100% complete per the bead description
- [ ] All existing tests pass — if tests exist
- [ ] Broken tests are fixed to reflect the new behavior
- [ ] New test coverage is added for any new code (when applicable)
- [ ] Code has been reviewed and simplified using `/simplify` skill
- [ ] Lint/format checks pass (see Phase 2)
- [ ] **Code is committed and pushed**
- [ ] **PR is open and merged**
- [ ] **Bead is closed**

A session may legitimately END before every box is checked (the "In the queue" end state above), but the bead only CLOSES when every box is checked.

## Handling Discovered Work

- If you discover a **bug** during implementation, create a new bug bead: `bd create --title="..." --type=bug --priority=2`
- If you discover **orthogonal work** (not required for the current bead), create a new task bead: `bd create --title="..." --type=task --priority=2`
- If you discover work that is a **subtask** of the current bead, create a child bead rather than burying it in prose notes, so it survives the session and shows up in the dependency graph: `bd create --title="..." --type=task --parent=<current-bead-id>` (check `bd create --help` if the parent flag differs in your bd version)

## When Things Go Wrong

- **Tests already failing on main:** Note the failures, file a bug bead, and proceed with your bead if unrelated. Do not fix unrelated test failures in your PR.
- **Dependency not on main yet:** EXIT. Do not start the bead. The next session will pick it up.
- **Bead design is incomplete or unclear:** Add a note to the bead (`bd update <id> --notes="Blocked: <reason>"`), set it back to open (`bd update <id> --status=open`), and delete any branch you created for it. Pick up a different bead or EXIT.
- **Merge queue rejects your PR:** Read the failure, fix the issue, push again, re-enable auto-merge, and run the bounded wait (step 15) once more. If it fails a second time, leave the bead `in_progress` with a note describing the failure and EXIT — never poll or retry forever.
- **You were interrupted mid-bead in a previous session:** Your checkpoint commits and bead notes are the recovery data — Phase 0 tells you how to resume from them.
