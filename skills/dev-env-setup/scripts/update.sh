#!/bin/bash
# Bring a project's installed harness up to date with this loop-engineering clone.
# Usage: update.sh PROJECT_DIR [--force]
#   PROJECT_DIR — the primary checkout, with the harness in .loop/ (or in ralph/,
#                 which update.sh moves to .loop/ first)
#   --force     — overwrite local edits in the installed files. It skips only
#                 the local-edit check.
#
# Every check runs before any file changes. If one fails, update.sh prints all
# failures, changes nothing and exits 1. Then it copies run.sh, watch.py,
# prices.json, metrics.py, CODER.md and REVIEWER.md, refreshes the interactive
# section of CLAUDE.md and AGENTS.md, writes .loop/HARNESS_VERSION and prints
# the diff. It never changes .loop/project.md (apart from the ralph/ path
# rewrite), and it commits nothing.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
LOOP_HOME="$(cd "${LOOP_HOME:-$SCRIPT_DIR/../../..}" && pwd)"
HARNESS="$LOOP_HOME/loop"
# shellcheck source=lib.sh
. "$SCRIPT_DIR/lib.sh"

usage() {
    echo "Usage: update.sh PROJECT_DIR [--force]"
    exit 2
}

FORCE=0
PROJECT_ARG=""
for arg in "$@"; do
    case "$arg" in
        --force) FORCE=1 ;;
        -*) usage ;;
        *)
            [ -z "$PROJECT_ARG" ] || usage
            PROJECT_ARG="$arg"
            ;;
    esac
done
[ -n "$PROJECT_ARG" ] || usage

FILES="run.sh watch.py prices.json metrics.py CODER.md REVIEWER.md"
DOCS="CLAUDE.md AGENTS.md"

# Errors that stop update.sh before the checks: nothing to compare against.
for f in $FILES project.template.md interactive.template.md README.md; do
    [ -f "$HARNESS/$f" ] || { echo "ERROR: $HARNESS/$f not found (set LOOP_HOME)"; exit 1; }
done
if ! clone_has_commit "$LOOP_HOME"; then
    echo "ERROR: $LOOP_HOME is not a git repository with a commit"
    exit 1
fi
[ -d "$PROJECT_ARG" ] || { echo "ERROR: $PROJECT_ARG is not a folder"; exit 1; }
PROJECT="$(cd "$PROJECT_ARG" && pwd)"
PROJECT_REAL="$(cd "$PROJECT_ARG" && pwd -P)"
if [ "$(git -C "$PROJECT" rev-parse --show-toplevel 2>/dev/null)" != "$PROJECT_REAL" ]; then
    echo "ERROR: $PROJECT is not the top of a git repository"
    exit 1
fi
if [ -d "$PROJECT/.loop" ]; then
    INSTALL=.loop
elif [ -d "$PROJECT/ralph" ]; then
    INSTALL=ralph
else
    echo "ERROR: $PROJECT has no .loop/ or ralph/; run bootstrap.sh first"
    exit 1
fi
DIR="$PROJECT/$INSTALL"
CONF="$DIR/project.md"
[ -f "$CONF" ] || { echo "ERROR: $CONF not found"; exit 1; }

conf() { key_value "$CONF" "$1"; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

FAILED=0
fail() {
    FAILED=$((FAILED + 1))
    printf '\nFAILED: %s\n' "$1"
}

# The run.sh processes of this project: the arguments name its install, or the
# working directory is one of its worktrees. A process is never chosen by its
# name alone, and update.sh never stops one.
project_loops() {
    local trees pid args cwd tree candidates="$TMP/candidates" cwds="$TMP/cwds"
    : >"$candidates"
    ps -Ao pid=,args= | while read -r pid args; do
        case "$args" in *run.sh | *run.sh\ *) ;; *) continue ;; esac
        case "$args" in
            *"$PROJECT/$INSTALL/"* | *"$PROJECT_REAL/$INSTALL/"*) echo "  PID $pid: $args" ;;
            *) echo "$pid $args" >>"$candidates" ;;
        esac
    done
    [ -s "$candidates" ] || return 0
    # The working directory of every other run.sh, as "PID CWD" lines, from
    # /proc on Linux or one lsof call on macOS.
    if [ -d /proc/self ]; then
        while read -r pid args; do
            cwd="$(readlink "/proc/$pid/cwd" 2>/dev/null)" && echo "$pid $cwd"
        done <"$candidates" >"$cwds" || true
    else
        lsof -a -d cwd -Fpn -p "$(cut -d' ' -f1 "$candidates" | paste -sd, -)" 2>/dev/null \
            | awk '/^p/ { pid = substr($0, 2) } /^n/ { print pid " " substr($0, 2) }' >"$cwds" || true
    fi
    trees="$(git -C "$PROJECT" worktree list --porcelain 2>/dev/null | sed -n 's/^worktree //p' \
        | while IFS= read -r tree; do (cd "$tree" 2>/dev/null && pwd -P) || true; done)"
    while read -r pid cwd; do
        while IFS= read -r tree; do
            [ -n "$tree" ] || continue
            case "$cwd/" in
                "$tree/"*)
                    echo "  PID $pid in $cwd: $(sed -n "s/^$pid //p" "$candidates")"
                    break
                    ;;
            esac
        done <<<"$trees"
    done <"$cwds"
}

echo "==> checks for $DIR"

# The loops read these files while they run, and a rewrite of run.sh under a
# running bash can corrupt it.
LOOPS="$(project_loops)"
if [ -n "$LOOPS" ]; then
    fail "loops of this project are running. Stop them first (see 'Stop and restart' in loop/README.md):"
    echo "$LOOPS"
fi

OLD=""
for f in PROMPT.md ALICE.md; do
    if [ -f "$DIR/$f" ]; then OLD="$OLD $INSTALL/$f"; fi
done
if [ -n "$OLD" ]; then
    fail "old prompt files:$OLD. Migrate them to CODER.md and REVIEWER.md by hand, and delete them."
fi

if ! clone_clean "$LOOP_HOME"; then
    fail "loop/ in $LOOP_HOME has uncommitted changes. Commit or stash them in the clone first:"
    git -C "$LOOP_HOME" status --short -- loop/ | sed 's/^/  /'
fi

# Each KEY= line of the template that project.md lacks or did not fill, with
# the first sentence of the template that says what the key is.
MISSING=""
UNFILLED=""
for key in $(sed -n 's/^\([A-Z][A-Z0-9_]*\)=.*/\1/p' "$HARNESS/project.template.md"); do
    if grep -q "^$key=" "$CONF"; then
        case "$(conf "$key")" in *"{{"*) UNFILLED="$UNFILLED $key" ;; esac
        continue
    fi
    meaning="$(grep -oE "\`\\\$?$key\` is [^.]*\." "$HARNESS/project.template.md" | head -1)" || true
    MISSING="$MISSING  $key: ${meaning:-see loop/project.template.md}"$'\n'
done
if [ -n "$MISSING" ]; then
    fail "$INSTALL/project.md lacks keys that loop/project.template.md has. Add each one as a KEY=value line, then run update.sh again:"
    printf '%s' "$MISSING"
fi
if [ -n "$UNFILLED" ]; then
    fail "these keys in $INSTALL/project.md still hold a {{...}} placeholder:$UNFILLED"
fi
# The names fill the interactive section, so they must not be empty. An empty
# GITHUB_ACCOUNT is valid in local mode.
for key in CODER REVIEWER HUMAN; do
    if grep -q "^$key=" "$CONF" && [ -z "$(conf "$key")" ]; then
        fail "$key has no value in $INSTALL/project.md"
    fi
done

for doc in $DOCS; do
    if [ -f "$PROJECT/$doc" ] && ! interactive_markers_ok "$PROJECT/$doc"; then
        fail "$doc has a '$INTERACTIVE_BEGIN' line with no '$INTERACTIVE_END' line after it. Fix the markers by hand."
    fi
done

# Local edits: compare each installed file with the file at the stamped commit.
# Without a usable stamp, compare with the clone's current file instead.
STAMP="$DIR/HARNESS_VERSION"
if [ "$FORCE" -eq 1 ]; then
    echo "--force: skipping the local-edit check"
else
    BASE_COMMIT=""
    NO_BASE=""
    if [ ! -f "$STAMP" ]; then
        NO_BASE="$INSTALL/HARNESS_VERSION is missing"
    elif [ "$(key_value "$STAMP" dirty)" = 1 ]; then
        NO_BASE="$INSTALL/HARNESS_VERSION says dirty=1"
    else
        BASE_COMMIT="$(key_value "$STAMP" commit)"
        if [ -z "$BASE_COMMIT" ] || ! git -C "$LOOP_HOME" cat-file -e "$BASE_COMMIT^{commit}" 2>/dev/null; then
            NO_BASE="$LOOP_HOME does not have the stamped commit '${BASE_COMMIT}'"
            BASE_COMMIT=""
        fi
    fi
    EDITS="$TMP/edits"
    : >"$EDITS"
    for f in $FILES; do
        [ -f "$DIR/$f" ] || continue
        if [ -n "$BASE_COMMIT" ]; then
            base="$TMP/base"
            git -C "$LOOP_HOME" show "$BASE_COMMIT:loop/$f" >"$base" 2>/dev/null || : >"$base"
            label="loop/$f at ${BASE_COMMIT:0:12}"
        else
            base="$HARNESS/$f"
            label="loop/$f now"
        fi
        diff -u -L "$label" -L "$INSTALL/$f" "$base" "$DIR/$f" >>"$EDITS" || true
    done
    if [ -s "$EDITS" ]; then
        if [ -n "$NO_BASE" ]; then
            fail "$NO_BASE, so update.sh cannot tell local edits from an old version. These files differ from the clone's current version. Rerun with --force to overwrite them:"
        else
            fail "local edits in the installed files. Move them into $HARNESS, or rerun with --force to overwrite them:"
        fi
        cat "$EDITS"
    fi
fi

if [ "$FAILED" -gt 0 ]; then
    printf '\nupdate.sh changed nothing: %s check(s) failed.\n' "$FAILED"
    exit 1
fi
echo "all checks passed"

if [ "$INSTALL" = ralph ]; then
    echo
    echo "==> move ralph/ to .loop/"
    git -C "$PROJECT" mv ralph .loop
    DIR="$PROJECT/.loop"
    CONF="$DIR/project.md"
    STAMP="$DIR/HARNESS_VERSION"
    sed 's#ralph/#.loop/#g' "$CONF" >"$CONF.tmp"
    mv "$CONF.tmp" "$CONF"
    echo "moved ralph/ to .loop/ and changed the ralph/ paths in .loop/project.md to .loop/"
    REFS="$TMP/refs"
    : >"$REFS"
    for doc in $DOCS; do
        [ -f "$PROJECT/$doc" ] || continue
        lines_outside_section "$PROJECT/$doc" | grep -F 'ralph/' | sed "s#^#  $doc:#" >>"$REFS" || true
    done
    if [ -s "$REFS" ]; then
        echo "These lines outside the interactive section still name ralph/. Change them by hand:"
        cat "$REFS"
    fi
    echo "The RALPH_ variables are now LOOP_ variables. Rename each one that your shell or herdr setup sets:"
    sed -n 's/^| `\(RALPH_[A-Z_]*\)` | `\(LOOP_[A-Z_]*\)` |$/  \1 -> \2/p' "$HARNESS/README.md"
fi

echo
echo "==> update .loop/ from $LOOP_HOME"
for f in $FILES; do
    cp "$HARNESS/$f" "$DIR/$f"
done
chmod +x "$DIR/run.sh" "$DIR/watch.py" "$DIR/metrics.py"
echo "copied $FILES"

SECTION="$TMP/section"
fill_names "$HARNESS/interactive.template.md" "$(conf CODER)" "$(conf REVIEWER)" "$(conf HUMAN)" >"$SECTION"
for doc in $DOCS; do
    (cd "$PROJECT" && install_interactive "$doc" "$SECTION" replace)
done

write_stamp "$STAMP" "$LOOP_HOME"
echo "wrote .loop/HARNESS_VERSION: $(key_value "$STAMP" commit)"

echo
echo "==> changes"
git -C "$PROJECT" status --short -- .loop $DOCS
git -C "$PROJECT" --no-pager diff --stat -- .loop $DOCS
git -C "$PROJECT" --no-pager diff -- .loop $DOCS

echo
echo "update.sh committed nothing. Next:"
if [ "$(conf SHIP_MODE)" = local ]; then
    echo "  1. Review the diff above and commit it on main."
    echo "  2. Reset each worktree's loop branch to main: git -C <worktree> reset --hard main"
else
    echo "  1. Review the diff above, commit it on a branch and open a pull request."
    echo "  2. After the merge, pull main in the primary checkout, and reset each worktree's"
    echo "     loop branch to main: git -C <worktree> fetch origin && git -C <worktree> reset --hard origin/main"
fi
echo "  3. Restart the loops and the watchers."
