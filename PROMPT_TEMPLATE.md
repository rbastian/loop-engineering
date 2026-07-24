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

Your workflow has three phases. You are not done until Phase 3 is complete.

### Phase 1 — Implement

1. Run `bd ready --assignee={{AGENT_NAME}}` to find the highest-priority unblocked bead.
2. Run `bd show <id>` to review the bead details, design, and dependencies.
3. Run `bd update <id> --status=in_progress` to claim it.
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

9. **Immediately after `/simplify` returns**, run `git status` and `git diff --stat`. This is your transition to Phase 3 — do it NOW, before anything else. `/simplify` returning "no fixes needed", "All clean", "Here's what was fixed", or ANY other output means your code passed review. It does NOT mean you are done. You have not shipped yet.

### Phase 3 — Ship (MANDATORY)

**You MUST complete every step below before exiting. No exceptions.**

10. Verify `git status` shows changes to ship (from step 9).
    - If there are changes → continue to step 11.
    - If there are NO changes → you did not complete the bead. Run `bd update <id> --status=open --notes="No code written — needs clarification"` and EXIT.
11. `git add <files> && git commit -m "feat: <description> [<bead-id>]"`
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
14. Enable auto-merge: `gh pr merge <number> --auto`
15. Poll until merged:
    ```bash
    while true; do
      state=$(gh pr view <number> --json state --jq '.state')
      if [ "$state" = "MERGED" ]; then break; fi
      sleep 30
    done
    ```
16. Close the bead: `bd close <id>`
17. EXIT.

### Self-check: Am I done?

Before exiting, verify ALL of these are true:

- [ ] Code is committed (not just staged)
- [ ] Branch is pushed to origin
- [ ] PR is open and has been merged
- [ ] Bead is closed

If ANY box is unchecked, you are NOT done. Go back to the first unchecked step.

**Work on the most important bead first.** Beads are ordered by priority and dependencies.

## Git Workflow

Each bead gets its own feature branch off `main`. {{MERGE_QUEUE_NOTE}}

**Commit message format:** `feat: <description> [<bead-id>]`

**Branch naming:** `feat/<short-description>-<bead-short-id>`

**Before starting work:**

You are working in a **separate git worktree** — you cannot checkout `main` because it is checked out in the primary worktree. Your home base branch is `loop`. Use `fetch` + `rebase` instead:

```bash
git checkout loop
git fetch origin main
git rebase origin/main
git checkout -b feat/<short-description>-<bead-short-id>
```

## Merge Queue and Dependencies

**CRITICAL: Do NOT close a bead until its PR has actually merged to `main`.** Bead status must reflect the true state of the codebase.

The merge queue flow:

1. Enable auto-merge (`gh pr merge <number> --auto`) — bead stays `in_progress`.
2. Queue runs CI checks and merges to `main` asynchronously.
3. Poll until the PR merges (see step 15 above).
4. Close the bead: `bd close <id>`
5. **EXIT immediately. Do NOT start another bead.** Downstream beads are now unblocked for the next session.

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

## Handling Discovered Work

- If you discover a **bug** during implementation, create a new bug bead: `bd create --title="..." --type=bug --priority=2`
- If you discover **orthogonal work** (not required for the current bead), create a new task bead: `bd create --title="..." --type=task --priority=2`
- If you discover work that is a **subtask** of the current bead, add notes to the current bead: `bd update <id> --notes="Subtask: ..."`

## When Things Go Wrong

- **Tests already failing on main:** Note the failures, file a bug bead, and proceed with your bead if unrelated. Do not fix unrelated test failures in your PR.
- **Dependency not on main yet:** EXIT. Do not start the bead. The next session will pick it up.
- **Bead design is incomplete or unclear:** Add a note to the bead (`bd update <id> --notes="Blocked: <reason>"`) and set it back to open (`bd update <id> --status=open`). Pick up a different bead or EXIT.
- **Merge queue rejects your PR:** Read the failure, fix the issue, push again, and re-enable auto-merge.
