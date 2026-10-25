#!/bin/bash
# Start both loops in their own herdr tab, and both watchers in the caller's tab:
#   loop tab:      Ralph loop | Alice loop (Claude, a different model from Ralph)
#   caller's tab:  Ralph watcher | Alice watcher   (top third)
#                  the calling pane                (bottom two thirds)
# Usage: layout.sh PROJECT_DIR
# Ralph runs on RALPH_MODEL (default claude-opus-5-5). Alice runs on Claude Code
# with ALICE_MODEL (default claude-sonnet-5-5), so she reviews with a different model.
# Must run inside a herdr pane. Refuses to run twice for the same project.
set -euo pipefail

if [ "${HERDR_ENV:-}" != 1 ]; then
    echo "ERROR: not inside herdr (HERDR_ENV is not 1)"
    exit 1
fi

PROJECT="$(cd "${1:?Usage: layout.sh PROJECT_DIR}" && pwd)"
NAME="$(basename "$PROJECT")"
PARENT="$(dirname "$PROJECT")"
RALPH_TREE="$PARENT/$NAME-ralph"
ALICE_TREE="$PARENT/$NAME-alice"
LABEL="$NAME loop"

# Per-project log directories, so two projects never share a current.jsonl.
# The names do not end in "<agent>-sessions", so the watchers get --agent.
RALPH_LOG="/tmp/$NAME-ralph-sessions"
ALICE_LOG="/tmp/$NAME-alice-sessions"

for tree in "$RALPH_TREE" "$ALICE_TREE"; do
    [ -e "$tree/.git" ] || { echo "ERROR: $tree missing; run worktrees.sh first"; exit 1; }
done

if herdr tab list --workspace "$HERDR_WORKSPACE_ID" \
    | jq -e --arg l "$LABEL" '.result.tabs[] | select(.label == $l)' >/dev/null; then
    echo "ERROR: a tab named '$LABEL' already exists in this workspace; close it first"
    exit 1
fi
if herdr pane list --workspace "$HERDR_WORKSPACE_ID" \
    | jq -e --arg t "$HERDR_TAB_ID" \
        '.result.panes[] | select(.tab_id == $t and (.label // "" | endswith(" watcher")))' >/dev/null; then
    echo "ERROR: this tab already has watcher panes; close them first"
    exit 1
fi

split() { herdr pane split "$1" --direction "$2" --ratio "$3" --cwd "$4" --no-focus | jq -r '.result.pane.pane_id'; }

# Loops: a tab of their own, side by side.
TAB=$(herdr tab create --workspace "$HERDR_WORKSPACE_ID" --cwd "$RALPH_TREE" --label "$LABEL" --no-focus)
RALPH_PANE=$(jq -r '.result.root_pane.pane_id' <<<"$TAB")
ALICE_PANE=$(split "$RALPH_PANE" right 0.5 "$ALICE_TREE")

# Watchers: the split keeps the top third for the caller, then the swap moves
# the new pane up there. Pane IDs follow their processes through a swap.
RALPH_WATCH=$(split "$HERDR_PANE_ID" down 0.33 "$PROJECT")
herdr pane swap --source-pane "$RALPH_WATCH" --target-pane "$HERDR_PANE_ID" >/dev/null
ALICE_WATCH=$(split "$RALPH_WATCH" right 0.5 "$PROJECT")
# The swap moves focus to the watcher; give it back to the caller below.
herdr pane focus --direction down --pane "$RALPH_WATCH" >/dev/null

herdr pane rename "$RALPH_PANE" "Ralph" >/dev/null
herdr pane rename "$ALICE_PANE" "Alice" >/dev/null
herdr pane rename "$RALPH_WATCH" "Ralph watcher" >/dev/null
herdr pane rename "$ALICE_WATCH" "Alice watcher" >/dev/null

# Watchers first: they wait for current.jsonl, so nothing is missed.
# --script makes uv read the inline metadata in watch.py, which pulls in rich
# for --tui. `uv run python ralph/watch.py` ignores it and runs in the project's
# venv, which has no rich.
herdr pane run "$RALPH_WATCH" "RALPH_LOG_DIR=$RALPH_LOG uv run --script ralph/watch.py --agent Ralph --tui" >/dev/null
herdr pane run "$ALICE_WATCH" "RALPH_LOG_DIR=$ALICE_LOG uv run --script ralph/watch.py --agent Alice --tui" >/dev/null

# The loops read the primary's harness files, so prompt changes merged to
# main take effect without touching the worktrees.
herdr pane run "$RALPH_PANE" \
    "RALPH_MODEL=${RALPH_MODEL:-claude-opus-5-5} RALPH_STREAM_LOG=1 RALPH_SHOW_BEAD=1 RALPH_LOG_DIR=$RALPH_LOG $PROJECT/ralph/run.sh Ralph $PROJECT/ralph/PROMPT.md" >/dev/null
herdr pane run "$ALICE_PANE" \
    "RALPH_MODEL=${ALICE_MODEL:-claude-sonnet-5-5} RALPH_STREAM_LOG=1 RALPH_SHOW_BEAD=1 RALPH_LOG_DIR=$ALICE_LOG $PROJECT/ralph/run.sh Alice $PROJECT/ralph/ALICE.md" >/dev/null

echo "opened tab '$LABEL'"
echo "  Ralph: $RALPH_PANE   Alice: $ALICE_PANE"
echo "watchers in this tab"
echo "  Ralph watcher: $RALPH_WATCH   Alice watcher: $ALICE_WATCH"
