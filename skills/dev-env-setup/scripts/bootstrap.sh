#!/bin/bash
# Prepare a project for the Ralph (writer) and Alice (reviewer) loop:
# git, uv with the gate tools, beads, and the ralph/ harness from loop-engineering.
# Usage: bootstrap.sh PROJECT_DIR BEAD_PREFIX [DEV_PACKAGE ...]
#   PROJECT_DIR  — the primary checkout (created if missing)
#   BEAD_PREFIX  — lowercase letters only; watch.py cannot parse a hyphenated one
#   DEV_PACKAGE  — extra dev dependencies on top of ruff and pytest
#
# Safe to run twice: each step skips itself when its work is already done.
# Commits nothing and creates no worktrees; worktrees.sh does that afterwards.
set -euo pipefail

LOOP_HOME="${LOOP_HOME:-$HOME/github.com/rbastian/loop-engineering}"
HARNESS="$LOOP_HOME/ralph-alice"

if [ $# -lt 2 ]; then
    echo "Usage: bootstrap.sh PROJECT_DIR BEAD_PREFIX [DEV_PACKAGE ...]"
    exit 2
fi
mkdir -p "$1"
PROJECT="$(cd "$1" && pwd)"
PREFIX="$2"
shift 2

if ! [[ "$PREFIX" =~ ^[a-z]+$ ]]; then
    echo "ERROR: BEAD_PREFIX must be lowercase letters only (got: $PREFIX)"
    echo "watch.py reads bead IDs as <letters>-<3 chars>, so a hyphen breaks it."
    exit 1
fi

NAME="$(basename "$PROJECT")"
PARENT="$(dirname "$PROJECT")"
PKG="$(tr '[:upper:]-' '[:lower:]_' <<<"$NAME")"


step() { printf '\n==> %s\n' "$*"; }

missing=0
for tool in git uv bd jq claude; do
    command -v "$tool" >/dev/null 2>&1 || { echo "ERROR: $tool not found"; missing=1; }
done
command -v timeout >/dev/null 2>&1 || command -v gtimeout >/dev/null 2>&1 \
    || echo "WARNING: no timeout/gtimeout; sessions will have no time limit (brew install coreutils)"
for f in run.sh watch.py PROMPT.md ALICE.md project.template.md; do
    [ -f "$HARNESS/$f" ] || { echo "ERROR: $HARNESS/$f not found (set LOOP_HOME)"; missing=1; }
done
[ "$missing" -eq 0 ] || exit 1

cd "$PROJECT"

step "git"
if [ -d .git ]; then
    echo "already a git repository"
else
    git init -b main
fi
# Both worktrees branch from main, and Alice merges into it.
BRANCH="$(git symbolic-ref --short HEAD)"
if [ "$BRANCH" != main ]; then
    echo "ERROR: the primary checkout is on '$BRANCH'; the loop needs it on main"
    exit 1
fi

step "uv"
if [ -f pyproject.toml ]; then
    echo "pyproject.toml exists; skipping uv init"
else
    uv init --package --name "$NAME"
fi
uv add --dev ruff pytest "$@"
# uv init writes .gitignore only when it creates the repository itself, and
# git init ran first, so add the Python entries here.
if ! grep -qx '__pycache__/' .gitignore 2>/dev/null; then
    cat >>.gitignore <<'EOF'

# Python
.venv/
__pycache__/
*.pyc
.pytest_cache/
.ruff_cache/

# Local runtime data
data/
EOF
fi
if ! grep -q '^\[tool.pytest' pyproject.toml; then
    cat >>pyproject.toml <<'EOF'

[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.ruff.lint]
extend-select = ["I"]
EOF
fi
# pytest exits 5 when it collects nothing, which fails the gate on an empty project.
mkdir -p tests
if ! ls tests/test_*.py >/dev/null 2>&1; then
    if [ -d "src/$PKG" ]; then
        cat >tests/test_smoke.py <<EOF
import $PKG


def test_package_imports():
    assert $PKG.__name__ == "$PKG"
EOF
    else
        cat >tests/test_smoke.py <<'EOF'
def test_smoke():
    assert True
EOF
    fi
    echo "wrote tests/test_smoke.py"
fi

step "beads"
bd init --prefix "$PREFIX" --non-interactive --init-if-missing
# SessionStart hooks, so each headless session starts with bd context.
bd setup claude
bd setup codex

step "harness"
mkdir -p ralph
# PROMPT.md and ALICE.md hold only the loop protocol, so they copy unchanged.
# The project facts go in ralph/project.md, which run.sh appends to each prompt.
for f in run.sh watch.py PROMPT.md ALICE.md; do
    if [ -f "ralph/$f" ]; then
        echo "ralph/$f exists; keeping it"
    else
        cp "$HARNESS/$f" "ralph/$f"
        echo "copied ralph/$f"
    fi
done
chmod +x ralph/run.sh ralph/watch.py
if [ -f ralph/project.md ]; then
    echo "ralph/project.md exists; keeping it"
else
    sed -e "s#{{PRIMARY}}#$PROJECT#g" \
        -e "s#{{RALPH_WORKTREE}}#$PARENT/$NAME-ralph#g" \
        -e "s#{{ALICE_WORKTREE}}#$PARENT/$NAME-alice#g" \
        "$HARNESS/project.template.md" >ralph/project.md
    echo "wrote ralph/project.md with paths for $NAME"
fi

step "gate"
uv run ruff format .
uv run ruff check --fix .
uv run ruff format --check . && uv run ruff check . && uv run pytest -q

echo
echo "bootstrap done: $PROJECT"
echo "Next: fill the {{...}} placeholders in ralph/project.md, then run worktrees.sh."
