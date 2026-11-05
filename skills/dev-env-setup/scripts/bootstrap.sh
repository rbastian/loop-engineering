#!/bin/bash
# Prepare a project for the coder and reviewer loop:
# git, uv with the gate tools, beads, and the .loop/ harness from loop-engineering.
# Usage: bootstrap.sh PROJECT_DIR BEAD_PREFIX [DEV_PACKAGE ...]
#   PROJECT_DIR  — the primary checkout (created if missing)
#   BEAD_PREFIX  — lowercase letters, digits, - and _, starting with a letter
#   DEV_PACKAGE  — extra dev dependencies on top of ruff and pytest
# These go into .loop/project.md, where worktrees.sh and layout.sh read them back:
#   LOOP_CODER     — the coder agent's name (default: Ralph)
#   LOOP_REVIEWER   — the reviewer agent's name (default: Alice)
#   LOOP_HUMAN      — the bd assignee who approves merges (default: $USER)
#   LOOP_SHIP_MODE  — pr (default) or local, for a repository with one user
#   LOOP_CODER_ENGINE    — claude (default) or fw, the coder's CLI
#   LOOP_CODER_MODEL     — the coder's model; empty means the engine's default
#   LOOP_REVIEWER_ENGINE — claude (default), codex or fw, the reviewer's CLI
#   LOOP_REVIEWER_MODEL  — the reviewer's model; empty means the engine's default
#   fw has no default model, so an agent on fw needs its model variable.
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
# shellcheck source=lib.sh
. "$SCRIPT_DIR/lib.sh"

if [ $# -lt 2 ]; then
    echo "Usage: bootstrap.sh PROJECT_DIR BEAD_PREFIX [DEV_PACKAGE ...]"
    exit 2
fi
PREFIX="$2"

# bd renames a prefix that starts with a digit to bd_<prefix>, so it must start
# with a letter. Each - or _ must be followed by a letter or a digit, so the
# prefix cannot end with one or have two in a row. watch.py gets the prefix
# through --prefix and matches it exactly.
PREFIX_RE='^[a-z]([a-z0-9]|[-_][a-z0-9])*$'
if ! [[ "$PREFIX" =~ $PREFIX_RE ]]; then
    echo "ERROR: BEAD_PREFIX must be lowercase letters, digits, - and _, and start with a letter (got: $PREFIX)"
    echo "It must not end with - or _, or have two of them in a row."
    exit 1
fi

mkdir -p "$1"
PROJECT="$(cd "$1" && pwd)"
shift 2

CODER="${LOOP_CODER:-Ralph}"
REVIEWER="${LOOP_REVIEWER:-Alice}"
HUMAN="${LOOP_HUMAN:-$USER}"
SHIP_MODE="${LOOP_SHIP_MODE:-pr}"
CODER_ENGINE="${LOOP_CODER_ENGINE:-claude}"
CODER_MODEL="${LOOP_CODER_MODEL:-}"
REVIEWER_ENGINE="${LOOP_REVIEWER_ENGINE:-claude}"
REVIEWER_MODEL="${LOOP_REVIEWER_MODEL:-}"
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
check_engine LOOP_ CODER "$CODER_ENGINE" "$CODER_MODEL" || exit 1
check_engine LOOP_ REVIEWER "$REVIEWER_ENGINE" "$REVIEWER_MODEL" || exit 1
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

missing=0
TOOLS=(git uv bd jq claude)
# pr mode pushes branches and opens pull requests.
[ "$SHIP_MODE" = pr ] && TOOLS+=(gh)
# Each engine is also its command. run.sh runs fw --check at start, so
# bootstrap.sh only looks for the command.
for engine in "$CODER_ENGINE" "$REVIEWER_ENGINE"; do
    [ "$engine" = claude ] || TOOLS+=("$engine")
done
for tool in "${TOOLS[@]}"; do
    command -v "$tool" >/dev/null 2>&1 || { echo "ERROR: $tool not found"; missing=1; }
done
for f in run.sh watch.py prices.json CODER.md REVIEWER.md project.template.md interactive.template.md; do
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
EXISTING_TESTS="$(find . \( -name .git -o -name .venv -o -name .loop -o -name node_modules \) -prune \
    -o -type f \( -name 'test_*.py' -o -name '*_test.py' \) -print -quit)"
HAS_PYTEST_CONF=0
grep -q '^\[tool.pytest' pyproject.toml && HAS_PYTEST_CONF=1
if [ "$HAS_PYTEST_CONF" -eq 0 ] && [ -z "$EXISTING_TESTS" ]; then
    cat >>pyproject.toml <<'EOF'

[tool.pytest.ini_options]
testpaths = ["tests"]
EOF
fi
# pytest skips dot folders by default, but ruff lints them, so the gate would
# check the installed harness against the project's rules. A [tool.ruff] table
# gets the key on its first line. One that already has the key gets a hint.
export RUFF_TABLE='^\[tool\.ruff\][[:space:]]*(#.*)?$'
if grep -q '"\.loop"' pyproject.toml; then
    echo "pyproject.toml excludes .loop from ruff already"
elif ! grep -Eq "$RUFF_TABLE" pyproject.toml; then
    printf '\n[tool.ruff]\nextend-exclude = [".loop"]\n' >>pyproject.toml
elif ! awk '
        /^[[:space:]]*\[/ { in_table = ($0 ~ ENVIRON["RUFF_TABLE"]) }
        in_table && /^[[:space:]]*extend-exclude[[:space:]]*=/ { found = 1 }
        END { exit !found }
    ' pyproject.toml; then
    awk '{ print } $0 ~ ENVIRON["RUFF_TABLE"] { print "extend-exclude = [\".loop\"]" }' \
        pyproject.toml >pyproject.toml.tmp
    mv pyproject.toml.tmp pyproject.toml
else
    echo "NOTE: add \".loop\" to extend-exclude in [tool.ruff] in pyproject.toml, so that ruff skips the harness"
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
fill_names "$HARNESS/interactive.template.md" "$CODER" "$REVIEWER" "$HUMAN" >"$SECTION"
for doc in CLAUDE.md AGENTS.md; do
    install_interactive "$doc" "$SECTION" keep
done
rm -f "$SECTION"

step "harness"
mkdir -p .loop
# CODER.md and REVIEWER.md hold only the loop protocol, so they copy unchanged.
# The project facts go in .loop/project.md, which run.sh appends to each prompt.
KEPT=0
for f in run.sh watch.py prices.json CODER.md REVIEWER.md; do
    if [ -f ".loop/$f" ]; then
        echo ".loop/$f exists; keeping it"
        KEPT=1
    else
        cp "$HARNESS/$f" ".loop/$f"
        echo "copied .loop/$f"
    fi
done
chmod +x .loop/run.sh .loop/watch.py
# The stamp names the clone commit that the files came from. update.sh and the
# drift warning read it. Kept files may be older than the clone, so a stamp is
# written only when bootstrap.sh copied every file.
if [ -f .loop/HARNESS_VERSION ]; then
    echo ".loop/HARNESS_VERSION exists; keeping it"
elif [ "$KEPT" -eq 1 ]; then
    echo "NOTE: the kept harness has no .loop/HARNESS_VERSION; run update.sh to bring it up to date"
elif ! clone_has_commit "$LOOP_HOME"; then
    echo "WARNING: $LOOP_HOME is not a git repository with a commit; wrote no .loop/HARNESS_VERSION"
else
    write_stamp .loop/HARNESS_VERSION "$LOOP_HOME"
    echo "wrote .loop/HARNESS_VERSION"
    if [ "$(key_value .loop/HARNESS_VERSION dirty)" = 1 ]; then
        echo "WARNING: loop/ in $LOOP_HOME has uncommitted changes; the stamp says dirty=1, and update.sh will ask for --force"
    fi
fi
if [ -f .loop/project.md ]; then
    echo ".loop/project.md exists; keeping it"
else
    fill_names "$HARNESS/project.template.md" "$CODER" "$REVIEWER" "$HUMAN" | sed \
        -e "s#{{PRIMARY}}#$PROJECT#g" \
        -e "s#{{CODER_WORKTREE}}#$PARENT/$NAME-$(lower "$CODER")#g" \
        -e "s#{{REVIEWER_WORKTREE}}#$PARENT/$NAME-$(lower "$REVIEWER")#g" \
        -e "s#{{SHIP_MODE}}#$SHIP_MODE#g" \
        -e "s#{{GITHUB_ACCOUNT}}#$GITHUB_ACCOUNT#g" \
        -e "s#{{CODER_ENGINE}}#$CODER_ENGINE#g" \
        -e "s#{{CODER_MODEL}}#$CODER_MODEL#g" \
        -e "s#{{REVIEWER_ENGINE}}#$REVIEWER_ENGINE#g" \
        -e "s#{{REVIEWER_MODEL}}#$REVIEWER_MODEL#g" \
        -e "s#{{BEAD_PREFIX}}#$PREFIX#g" >.loop/project.md
    echo "wrote .loop/project.md for $NAME: $CODER codes, $REVIEWER reviews, $HUMAN merges, ship mode $SHIP_MODE${GITHUB_ACCOUNT:+ as $GITHUB_ACCOUNT}, coder on $CODER_ENGINE${CODER_MODEL:+ ($CODER_MODEL)}, reviewer on $REVIEWER_ENGINE${REVIEWER_MODEL:+ ($REVIEWER_MODEL)}"
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
echo "Next: fill the {{...}} placeholders in .loop/project.md, then run worktrees.sh."
