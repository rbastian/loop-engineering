#!/bin/bash
# Make the first commit on main and create both agent worktrees next to it:
#   ../<name>-ralph  home branch `loop`
#   ../<name>-alice  detached HEAD at main
# Usage: worktrees.sh PROJECT_DIR
# Safe to run twice: each step skips itself when its work is already done.
set -euo pipefail

PROJECT="$(cd "${1:?Usage: worktrees.sh PROJECT_DIR}" && pwd)"
NAME="$(basename "$PROJECT")"
PARENT="$(dirname "$PROJECT")"
RALPH_TREE="$PARENT/$NAME-ralph"
ALICE_TREE="$PARENT/$NAME-alice"

step() { printf '\n==> %s\n' "$*"; }

cd "$PROJECT"

step "commit"
if [ -n "$(git status --porcelain)" ]; then
    git add -A
    if git rev-parse --verify -q HEAD >/dev/null; then
        MSG="Set up the Ralph and Alice loop"
    else
        MSG="Initial commit: uv project, beads, and the ralph/ loop harness"
    fi
    git commit -q -m "$MSG" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
    git log --oneline -1
else
    echo "nothing to commit"
fi

step "Ralph's worktree"
if [ -e "$RALPH_TREE/.git" ]; then
    echo "exists: $RALPH_TREE"
elif git show-ref --verify -q refs/heads/loop; then
    git worktree add "$RALPH_TREE" loop
else
    git worktree add -b loop "$RALPH_TREE" main
fi

step "Alice's worktree"
if [ -e "$ALICE_TREE/.git" ]; then
    echo "exists: $ALICE_TREE"
else
    git worktree add --detach "$ALICE_TREE" main
fi

# Each worktree needs its own .venv for the gate; uv builds it on first use.
for tree in "$RALPH_TREE" "$ALICE_TREE"; do
    (cd "$tree" && uv sync -q)
done

step "check"
git worktree list
(cd "$RALPH_TREE" && bd list --json >/dev/null && echo "bd works from $NAME-ralph")
(cd "$ALICE_TREE" && bd list --json >/dev/null && echo "bd works from $NAME-alice")
