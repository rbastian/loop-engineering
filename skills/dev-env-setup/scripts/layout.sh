#!/bin/bash
# Start both loops in their own herdr tab, and both watchers and the beads list
# in the caller's tab:
#   loop tab:      coder loop | reviewer loop
#   caller's tab:  coder watcher (1/2)  | reviewer watcher (1/2)   (top third)
#                  calling pane (2/3)   | Beads (1/3)               (bottom two thirds)
# Usage: layout.sh PROJECT_DIR
# The agent names and worktree paths come from .loop/project.md.
# CODER_ENGINE, CODER_MODEL, REVIEWER_ENGINE and REVIEWER_MODEL in
# .loop/project.md pick each agent's CLI and model. The environment variables
# of the same names override them for one start. The coder runs on claude or
# fw, the reviewer on claude, codex or fw. A missing or empty field gives the
# default: engine claude, model claude-opus-5-5 for the coder and
# claude-sonnet-5-5 for the reviewer on claude, so the reviewer reviews with a
# different model. On codex the model has no default, and run.sh uses the
# plan's default model. fw has no default model, so an agent on fw needs one.
# Must run inside a herdr pane. Refuses to run twice for the same project.
set -euo pipefail

if [ "${HERDR_ENV:-}" != 1 ]; then
    echo "ERROR: not inside herdr (HERDR_ENV is not 1)"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=lib.sh
. "$SCRIPT_DIR/lib.sh"

PROJECT="$(cd "${1:?Usage: layout.sh PROJECT_DIR}" && pwd)"
NAME="$(basename "$PROJECT")"
LABEL="$NAME loop"

# One KEY=value line from the overlay; bootstrap.sh wrote them.
conf() { key_value "$PROJECT/.loop/project.md" "$1"; }
lower() { tr '[:upper:]' '[:lower:]' <<<"$1"; }

CODER="$(conf CODER)"
REVIEWER="$(conf REVIEWER)"
CODER_TREE="$(conf CODER_WORKTREE)"
REVIEWER_TREE="$(conf REVIEWER_WORKTREE)"
for v in CODER REVIEWER CODER_TREE REVIEWER_TREE; do
    case "${!v}" in "" | *"{{"*) echo "ERROR: $v is not set in .loop/project.md"; exit 1 ;; esac
done

# Set ROLE_ENGINE and ROLE_MODEL for ROLE (CODER or REVIEWER). ENGINES lists
# the engines that the role allows, and CLAUDE_MODEL is its default on claude.
# A model in .loop/project.md belongs to the engine in that file, so an
# engine override in the environment does not take it.
# Usage: pick_engine ROLE "ENGINES" CLAUDE_MODEL
pick_engine() {
    local role="$1" engines="$2" claude_model="$3"
    local engine_var="${1}_ENGINE" model_var="${1}_MODEL"
    local file_engine file_model engine model
    file_engine="$(conf "$engine_var")"
    file_engine="${file_engine:-claude}"
    file_model="$(conf "$model_var")"
    engine="${!engine_var:-$file_engine}"
    model="${!model_var:-}"
    if [ -z "$model" ] && [ "$engine" = "$file_engine" ]; then
        model="$file_model"
    fi
    case "$engine $model" in *"{{"*) echo "ERROR: $engine_var or $model_var is not set in .loop/project.md"; exit 1 ;; esac
    case " $engines " in
        *" $engine "*) ;;
        *) echo "ERROR: $engine_var must be one of: $engines (got: $engine)"; exit 1 ;;
    esac
    if ! valid_model "$model"; then
        echo "ERROR: $model_var must be letters, digits and . _ : / @ - [ ] (got: $model)"
        exit 1
    fi
    case "$engine" in
        claude) model="${model:-$claude_model}" ;;
        codex)
            command -v codex >/dev/null 2>&1 || { echo "ERROR: $engine_var=codex, but codex is not installed"; exit 1; }
            ;;
        fw)
            [ -n "$model" ] || { echo "ERROR: $engine_var=fw needs $model_var, for example deepseek-flash-latest[1m]"; exit 1; }
            command -v fw >/dev/null 2>&1 || { echo "ERROR: $engine_var=fw, but fw is not on PATH (usually ~/.local/bin/fw)"; exit 1; }
            ;;
    esac
    printf -v "$engine_var" '%s' "$engine"
    printf -v "$model_var" '%s' "$model"
}
pick_engine CODER "claude fw" claude-opus-5-5
pick_engine REVIEWER "claude codex fw" claude-sonnet-5-5

# The watchers match only this project's bead IDs. An overlay written before
# BEAD_PREFIX existed has no such line, and watch.py then matches any prefix.
BEAD_PREFIX="$(conf BEAD_PREFIX)"
case "$BEAD_PREFIX" in *"{{"*) echo "ERROR: BEAD_PREFIX is not set in .loop/project.md"; exit 1 ;; esac
PREFIX_ARG="${BEAD_PREFIX:+ --prefix $BEAD_PREFIX}"

# Per-project log directories, so two projects never share a current.jsonl.
# The names do not end in "<agent>-sessions", so the watchers get --agent.
CODER_LOG="/tmp/$NAME-$(lower "$CODER")-sessions"
REVIEWER_LOG="/tmp/$NAME-$(lower "$REVIEWER")-sessions"

for tree in "$CODER_TREE" "$REVIEWER_TREE"; do
    [ -e "$tree/.git" ] || { echo "ERROR: $tree missing; run worktrees.sh first"; exit 1; }
done

# One line when the clone has newer commits on loop/ than the installed harness.
# The check never stops the layout.
drift_line "$PROJECT/.loop/HARNESS_VERSION" || true

if herdr tab list --workspace "$HERDR_WORKSPACE_ID" \
    | jq -e --arg l "$LABEL" '.result.tabs[] | select(.label == $l)' >/dev/null; then
    echo "ERROR: a tab named '$LABEL' already exists in this workspace; close it first"
    exit 1
fi
if herdr pane list --workspace "$HERDR_WORKSPACE_ID" \
    | jq -e --arg t "$HERDR_TAB_ID" \
        '.result.panes[] | select(.tab_id == $t and (.label // "" | endswith(" watcher") or . == "Beads"))' >/dev/null; then
    echo "ERROR: this tab already has watcher or Beads panes; close them first"
    exit 1
fi

split() { herdr pane split "$1" --direction "$2" --ratio "$3" --cwd "$4" --no-focus | jq -r '.result.pane.pane_id'; }

# Loops: a tab of their own, side by side.
TAB=$(herdr tab create --workspace "$HERDR_WORKSPACE_ID" --cwd "$CODER_TREE" --label "$LABEL" --no-focus)
CODER_PANE=$(jq -r '.result.root_pane.pane_id' <<<"$TAB")
REVIEWER_PANE=$(split "$CODER_PANE" right 0.5 "$REVIEWER_TREE")

# Watchers: the split keeps the top third for the caller, then the swap moves
# the new pane up there. Pane IDs follow their processes through a swap.
CODER_WATCH=$(split "$HERDR_PANE_ID" down 0.33 "$PROJECT")
herdr pane swap --source-pane "$CODER_WATCH" --target-pane "$HERDR_PANE_ID" >/dev/null
REVIEWER_WATCH=$(split "$CODER_WATCH" right 0.5 "$PROJECT")
# The swap moves focus to the watcher; give it back to the caller below.
herdr pane focus --direction down --pane "$CODER_WATCH" >/dev/null
# Beads: the right third of the bottom area, beside the calling pane.
BEADS_PANE=$(split "$HERDR_PANE_ID" right 0.67 "$PROJECT")

herdr pane rename "$CODER_PANE" "$CODER" >/dev/null
herdr pane rename "$REVIEWER_PANE" "$REVIEWER" >/dev/null
herdr pane rename "$CODER_WATCH" "$CODER watcher" >/dev/null
herdr pane rename "$REVIEWER_WATCH" "$REVIEWER watcher" >/dev/null
herdr pane rename "$BEADS_PANE" "Beads" >/dev/null

# Watchers first: they wait for current.jsonl, so nothing is missed.
herdr pane run "$CODER_WATCH" "LOOP_LOG_DIR=$CODER_LOG uv run .loop/watch.py --agent $CODER$PREFIX_ARG --tui" >/dev/null
herdr pane run "$REVIEWER_WATCH" "LOOP_LOG_DIR=$REVIEWER_LOG uv run .loop/watch.py --agent $REVIEWER$PREFIX_ARG --tui" >/dev/null

# The beads list redraws only when it changes. bd list takes about 0.6 s, so a
# loop that clears first leaves the pane blank on every cycle. bd turns color
# off when it writes into a command substitution, so CLICOLOR_FORCE=1 keeps the
# colors. Set it on the bd call only, not for the whole pane shell.
BEADS_LOOP='clear; prev=; while true; do out=$(CLICOLOR_FORCE=1 bd list --status open,blocked,in_progress 2>&1); if [ "$out" != "$prev" ]; then clear; date "+updated %H:%M:%S"; printf "%s\n" "$out"; prev=$out; fi; sleep 5; done'
herdr pane run "$BEADS_PANE" "$BEADS_LOOP" >/dev/null

# The loops read the primary's harness files, so prompt changes merged to
# main take effect without touching the worktrees. The quotes keep a model
# such as deepseek-flash-latest[1m] from being read as a glob.
herdr pane run "$CODER_PANE" \
    "LOOP_ENGINE=$CODER_ENGINE LOOP_MODEL='$CODER_MODEL' LOOP_STREAM_LOG=1 LOOP_SHOW_BEAD=1 LOOP_LOG_DIR=$CODER_LOG $PROJECT/.loop/run.sh $CODER $PROJECT/.loop/CODER.md" >/dev/null
herdr pane run "$REVIEWER_PANE" \
    "LOOP_ENGINE=$REVIEWER_ENGINE LOOP_MODEL='$REVIEWER_MODEL' LOOP_STREAM_LOG=1 LOOP_SHOW_BEAD=1 LOOP_LOG_DIR=$REVIEWER_LOG $PROJECT/.loop/run.sh $REVIEWER $PROJECT/.loop/REVIEWER.md" >/dev/null

echo "opened tab '$LABEL'"
echo "  $CODER: $CODER_PANE ($CODER_ENGINE)   $REVIEWER: $REVIEWER_PANE ($REVIEWER_ENGINE)"
echo "watchers in this tab"
echo "  $CODER watcher: $CODER_WATCH   $REVIEWER watcher: $REVIEWER_WATCH   Beads: $BEADS_PANE"
