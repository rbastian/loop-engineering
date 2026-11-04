#!/bin/bash
# Prepare a project for the coder and reviewer loop:
# git, uv with the gate tools, beads, and the ralph/ harness from loop-engineering.
# Usage: bootstrap.sh PROJECT_DIR BEAD_PREFIX [DEV_PACKAGE ...]
#   PROJECT_DIR  — the primary checkout (created if missing)
#   BEAD_PREFIX  — lowercase letters only; watch.py cannot parse a hyphenated one
#   DEV_PACKAGE  — extra dev dependencies on top of ruff and pytest
# These go into ralph/project.md, where worktrees.sh and layout.sh read them back:
#   LOOP_CODER     — the coder agent's name (default: Ralph)
#   LOOP_REVIEWER   — the reviewer agent's name (default: Alice)
#   LOOP_HUMAN      — the bd assignee who approves merges (default: $USER)
#   LOOP_SHIP_MODE  — pr (default) or local, for a repository with one user
#   LOOP_REVIEWER_ENGINE — claude (default) or codex, the reviewer's CLI
#   LOOP_GITHUB_ACCOUNT — the GitHub account that the agents use; required in
#                         pr mode, written empty in local mode
#
# Safe to run twice: each step skips itself when its work is already done.
# Commits nothing and creates no worktrees; worktrees.sh does that afterwards.
set -euo pipefail

# The skill lives in loop-engineering/skills/dev-env-setup, so the repository
# root is three levels above this script. pwd -P resolves the symlink that
# installs the skill under ~/.claude/skills. LOOP_HOME overrides it.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
LOOP_HOME="${LOOP_HOME:-$(cd "$SCRIPT_DIR/../../.." && pwd)}"
HARNESS="$LOOP_HOME/loop"

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

CODER="${LOOP_CODER:-Ralph}"
REVIEWER="${LOOP_REVIEWER:-Alice}"
HUMAN="${LOOP_HUMAN:-$USER}"
SHIP_MODE="${LOOP_SHIP_MODE:-pr}"
REVIEWER_ENGINE="${LOOP_REVIEWER_ENGINE:-claude}"
GITHUB_ACCOUNT="${LOOP_GITHUB_ACCOUNT:-}"
# The agent names become bd assignees and, lowercased, worktree and log paths.
for agent in "$CODER" "$REVIEWER"; do
    if ! [[ "$agent" =~ ^[A-Za-z]+$ ]]; then
        echo "ERROR: agent names must be letters only (got: $agent)"
        exit 1
    fi
done
if [ "$CODER" = "$REVIEWER" ]; then
    echo "ERROR: the coder and the reviewer need different names"
    exit 1
fi
case "$REVIEWER_ENGINE" in
    claude | codex) ;;
    *)
        echo "ERROR: LOOP_REVIEWER_ENGINE must be claude or codex (got: $REVIEWER_ENGINE)"
        exit 1
        ;;
esac
case "$SHIP_MODE" in
    pr | local) ;;
    *)
        echo "ERROR: LOOP_SHIP_MODE must be pr or local (got: $SHIP_MODE)"
        exit 1
        ;;
esac
# run.sh pins this account in pr mode. local mode has no remote, so no account.
if [ "$SHIP_MODE" = local ]; then
    GITHUB_ACCOUNT=""
elif [ -z "$GITHUB_ACCOUNT" ]; then
    echo "ERROR: pr mode needs LOOP_GITHUB_ACCOUNT, the GitHub account that the agents use"
    exit 1
elif ! [[ "$GITHUB_ACCOUNT" =~ ^[A-Za-z0-9-]+$ ]]; then
    echo "ERROR: LOOP_GITHUB_ACCOUNT must be a GitHub user name: letters, digits and hyphens (got: $GITHUB_ACCOUNT)"
    exit 1
fi

NAME="$(basename "$PROJECT")"
PARENT="$(dirname "$PROJECT")"
PKG="$(tr '[:upper:]-' '[:lower:]_' <<<"$NAME")"


step() { printf '\n==> %s\n' "$*"; }
lower() { tr '[:upper:]' '[:lower:]' <<<"$1"; }
# The sed expressions that fill the name placeholders in both templates.
NAMES=(-e "s#{{CODER}}#$CODER#g" -e "s#{{REVIEWER}}#$REVIEWER#g" -e "s#{{HUMAN}}#$HUMAN#g")

missing=0
TOOLS=(git uv bd jq claude)
# pr mode pushes branches and opens pull requests.
[ "$SHIP_MODE" = pr ] && TOOLS+=(gh)
[ "$REVIEWER_ENGINE" = codex ] && TOOLS+=(codex)
for tool in "${TOOLS[@]}"; do
    command -v "$tool" >/dev/null 2>&1 || { echo "ERROR: $tool not found"; missing=1; }
done
for f in run.sh watch.py CODER.md REVIEWER.md project.template.md interactive.template.md; do
    [ -f "$HARNESS/$f" ] || { echo "ERROR: $HARNESS/$f not found (set LOOP_HOME)"; missing=1; }
done
[ "$missing" -eq 0 ] || exit 1

cd "$PROJECT"

# A folder that holds anything besides .git is an existing repository.
# bootstrap.sh then adds no package and rewrites none of its files.
EXISTING=0
if [ -n "$(ls -A | grep -vx '.git' || true)" ]; then
    EXISTING=1
fi

step "git"
if [ -d .git ]; then
    echo "already a git repository"
else
    git init -b main
fi
# Both worktrees branch from main, and every bead lands on it.
BRANCH="$(git symbolic-ref --short HEAD)"
if [ "$BRANCH" != main ]; then
    echo "ERROR: the primary checkout is on '$BRANCH'; the loop needs it on main"
    exit 1
fi

step "uv"
if [ -f pyproject.toml ]; then
    echo "pyproject.toml exists; skipping uv init"
elif [ "$EXISTING" -eq 0 ]; then
    uv init --package --name "$NAME"
elif uv init --help | grep -q -- '--bare'; then
    # Only pyproject.toml: no src/ package, README or main.py.
    uv init --bare --name "$NAME"
else
    cat >pyproject.toml <<EOF
[project]
name = "$NAME"
version = "0.1.0"
dependencies = []
EOF
    echo "wrote a minimal pyproject.toml"
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
# Existing tests anywhere in the project. pytest then finds them by its
# default rules, so bootstrap.sh sets no testpaths and writes no smoke test.
EXISTING_TESTS="$(find . \( -name .git -o -name .venv -o -name ralph -o -name node_modules \) -prune \
    -o -type f \( -name 'test_*.py' -o -name '*_test.py' \) -print -quit)"
HAS_PYTEST_CONF=0
grep -q '^\[tool.pytest' pyproject.toml && HAS_PYTEST_CONF=1
if [ "$HAS_PYTEST_CONF" -eq 0 ] && [ -z "$EXISTING_TESTS" ]; then
    cat >>pyproject.toml <<'EOF'

[tool.pytest.ini_options]
testpaths = ["tests"]
EOF
fi
if [ "$HAS_PYTEST_CONF" -eq 0 ] && ! grep -q '^\[tool.ruff.lint\]' pyproject.toml; then
    cat >>pyproject.toml <<'EOF'

[tool.ruff.lint]
extend-select = ["I"]
EOF
fi
# pytest exits 5 when it collects nothing, which fails the gate on a project without tests.
if [ -n "$EXISTING_TESTS" ]; then
    echo "found existing tests; writing no tests/test_smoke.py"
else
    mkdir -p tests
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

step "interactive section"
# The rule and the orientation for an interactive session, between markers.
# It goes after the first H1, before the beads blocks that bd setup wrote.
# A file that already holds the BEGIN marker keeps its section unchanged.
SECTION="$(mktemp)"
sed "${NAMES[@]}" "$HARNESS/interactive.template.md" >"$SECTION"
for doc in CLAUDE.md AGENTS.md; do
    if [ ! -f "$doc" ]; then
        cp "$SECTION" "$doc"
        echo "wrote $doc with the interactive section"
        continue
    fi
    if grep -qF '<!-- BEGIN LOOP INTERACTIVE -->' "$doc"; then
        echo "$doc holds the interactive section; keeping it"
        continue
    fi
    # Pass 1 finds the first H1 outside a code fence and before any beads
    # block. Pass 2 puts the section after it, or at the top if there is none.
    awk -v section="$SECTION" '
        function emit(line) {
            while ((getline line <section) > 0) print line
            close(section)
        }
        NR == FNR {
            if (stop) next
            if ($0 ~ /^(```|~~~)/) fence = !fence
            else if (!fence && $0 ~ /^<!-- BEGIN BEADS/) stop = 1
            else if (!fence && $0 ~ /^# /) { h1 = FNR; stop = 1 }
            next
        }
        FNR == 1 && !h1 { emit(); print "" }
        skip && $0 == "" { next }
        skip { print ""; skip = 0 }
        { print }
        FNR == h1 { print ""; emit(); skip = 1 }
    ' "$doc" "$doc" >"$doc.tmp"
    mv "$doc.tmp" "$doc"
    echo "added the interactive section to $doc"
done
rm -f "$SECTION"

step "harness"
mkdir -p ralph
# CODER.md and REVIEWER.md hold only the loop protocol, so they copy unchanged.
# The project facts go in ralph/project.md, which run.sh appends to each prompt.
for f in run.sh watch.py CODER.md REVIEWER.md; do
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
        -e "s#{{CODER_WORKTREE}}#$PARENT/$NAME-$(lower "$CODER")#g" \
        -e "s#{{REVIEWER_WORKTREE}}#$PARENT/$NAME-$(lower "$REVIEWER")#g" \
        "${NAMES[@]}" \
        -e "s#{{SHIP_MODE}}#$SHIP_MODE#g" \
        -e "s#{{GITHUB_ACCOUNT}}#$GITHUB_ACCOUNT#g" \
        -e "s#{{REVIEWER_ENGINE}}#$REVIEWER_ENGINE#g" \
        "$HARNESS/project.template.md" >ralph/project.md
    echo "wrote ralph/project.md for $NAME: $CODER codes, $REVIEWER reviews, $HUMAN merges, ship mode $SHIP_MODE${GITHUB_ACCOUNT:+ as $GITHUB_ACCOUNT}, reviewer on $REVIEWER_ENGINE"
fi

step "gate"
# On an existing repository, run only the checks: the format commands would
# rewrite the user's files.
if [ "$EXISTING" -eq 0 ]; then
    uv run ruff format .
    uv run ruff check --fix .
fi
# set -e ignores a failure inside an && list, so test the list explicitly.
if ! { uv run ruff format --check . && uv run ruff check . && uv run pytest -q; }; then
    echo "bootstrap failed: the gate failed in $PROJECT" >&2
    exit 1
fi

echo
echo "bootstrap done: $PROJECT"
echo "Next: fill the {{...}} placeholders in ralph/project.md, then run worktrees.sh."
