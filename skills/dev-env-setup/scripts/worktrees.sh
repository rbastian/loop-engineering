#!/bin/bash
# Make the first commit on main and create both agent worktrees next to it:
#   coder worktree    home branch `loop`
#   reviewer worktree  detached HEAD at main
# The agent names, the paths and the ship mode come from ralph/project.md.
# In pr mode, main must also be on origin, so pull requests have a base.
# Usage: worktrees.sh PROJECT_DIR
# Safe to run twice: each step skips itself when its work is already done.
set -euo pipefail

PROJECT="$(cd "${1:?Usage: worktrees.sh PROJECT_DIR}" && pwd)"

step() { printf '\n==> %s\n' "$*"; }
# One KEY=value line from the overlay; bootstrap.sh wrote them.
conf() { sed -n "s/^$1=//p" "$PROJECT/ralph/project.md" | head -1; }

[ -f "$PROJECT/ralph/project.md" ] || { echo "ERROR: ralph/project.md missing; run bootstrap.sh first"; exit 1; }
CODER="$(conf CODER)"
REVIEWER="$(conf REVIEWER)"
SHIP_MODE="$(conf SHIP_MODE)"
CODER_TREE="$(conf CODER_WORKTREE)"
REVIEWER_TREE="$(conf REVIEWER_WORKTREE)"
for v in CODER REVIEWER SHIP_MODE CODER_TREE REVIEWER_TREE; do
    case "${!v}" in "" | *"{{"*) echo "ERROR: $v is not set in ralph/project.md"; exit 1 ;; esac
done

cd "$PROJECT"

if [ "$SHIP_MODE" = pr ] && ! git remote get-url origin >/dev/null 2>&1; then
    echo "ERROR: ship mode is pr, but the repository has no origin remote"
    echo "Hint: add one (gh repo create, or git remote add origin <url>), or set SHIP_MODE=local in ralph/project.md."
    exit 1
fi

step "commit"
if [ -n "$(git status --porcelain)" ]; then
    git add -A
    if git rev-parse --verify -q HEAD >/dev/null; then
        MSG="Set up the $CODER and $REVIEWER loop"
    else
        MSG="Initial commit: uv project, beads, and the ralph/ loop harness"
    fi
    git commit -q -m "$MSG" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
    git log --oneline -1
else
    echo "nothing to commit"
fi

if [ "$SHIP_MODE" = pr ]; then
    step "push main"
    # Push only what origin lacks; never force, so a diverged main stops here.
    git push -u origin main
fi

step "$CODER's worktree"
if [ -e "$CODER_TREE/.git" ]; then
    echo "exists: $CODER_TREE"
elif git show-ref --verify -q refs/heads/loop; then
    git worktree add "$CODER_TREE" loop
else
    git worktree add -b loop "$CODER_TREE" main
fi

step "$REVIEWER's worktree"
if [ -e "$REVIEWER_TREE/.git" ]; then
    echo "exists: $REVIEWER_TREE"
else
    git worktree add --detach "$REVIEWER_TREE" main
fi

# Each worktree needs its own .venv for the gate; uv builds it on first use.
for tree in "$CODER_TREE" "$REVIEWER_TREE"; do
    (cd "$tree" && uv sync -q)
done

step "check"
git worktree list
for tree in "$CODER_TREE" "$REVIEWER_TREE"; do
    (cd "$tree" && bd list --json >/dev/null && echo "bd works from $(basename "$tree")")
done
