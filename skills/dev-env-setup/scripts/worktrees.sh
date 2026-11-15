#!/bin/bash
# Make the first commit on main and create both agent worktrees next to it:
#   coder worktree    home branch `loop`
#   reviewer worktree  detached HEAD at main
# The agent names, the paths and the ship mode come from .loop/loop.toml,
# through loop/config.py of the clone. worktrees.sh checks the file first and
# stops with the error of each key path when it is not valid.
# In pr mode, main must also be on origin, so pull requests have a base.
# Usage: worktrees.sh PROJECT_DIR
# Safe to run twice: each step skips itself when its work is already done.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
LOOP_HOME="${LOOP_HOME:-$(cd "$SCRIPT_DIR/../../.." && pwd)}"
# shellcheck source=lib.sh
. "$SCRIPT_DIR/lib.sh"

PROJECT="$(cd "${1:?Usage: worktrees.sh PROJECT_DIR}" && pwd)"

step() { printf '\n==> %s\n' "$*"; }

[ -f "$PROJECT/.loop/loop.toml" ] || { echo "ERROR: .loop/loop.toml missing; run bootstrap.sh first, or update.sh to migrate an old .loop/project.md"; exit 1; }
load_loop_config "$PROJECT/.loop/loop.toml" || exit 1

cd "$PROJECT"

if [ "$SHIP_MODE" = pr ] && ! git remote get-url origin >/dev/null 2>&1; then
    echo "ERROR: ship mode is pr, but the repository has no origin remote"
    echo "Hint: add one (gh repo create, or git remote add origin <url>), or set mode = \"local\" under [ship] in .loop/loop.toml."
    exit 1
fi

step "commit"
if [ -n "$(git status --porcelain)" ]; then
    git add -A
    if git rev-parse --verify -q HEAD >/dev/null; then
        MSG="Set up the $CODER and $REVIEWER loop"
    else
        MSG="Initial commit: uv project, beads, and the .loop/ loop harness"
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
if [ -e "$CODER_WORKTREE/.git" ]; then
    echo "exists: $CODER_WORKTREE"
elif git show-ref --verify -q refs/heads/loop; then
    git worktree add "$CODER_WORKTREE" loop
else
    git worktree add -b loop "$CODER_WORKTREE" main
fi

step "$REVIEWER's worktree"
if [ -e "$REVIEWER_WORKTREE/.git" ]; then
    echo "exists: $REVIEWER_WORKTREE"
else
    git worktree add --detach "$REVIEWER_WORKTREE" main
fi

# Each worktree needs its own .venv for the gate; uv builds it on first use.
for tree in "$CODER_WORKTREE" "$REVIEWER_WORKTREE"; do
    (cd "$tree" && uv sync -q)
done

step "check"
git worktree list
for tree in "$CODER_WORKTREE" "$REVIEWER_WORKTREE"; do
    (cd "$tree" && bd list --json >/dev/null && echo "bd works from $(basename "$tree")")
done
