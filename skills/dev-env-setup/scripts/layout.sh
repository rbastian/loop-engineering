#!/bin/bash
# Start both loops in their own herdr tab, and both watchers in the caller's tab:
#   loop tab:      coder loop | reviewer loop (Claude, a different model from the coder)
#   caller's tab:  coder watcher | reviewer watcher   (top third)
#                  the calling pane                    (bottom two thirds)
# Usage: layout.sh PROJECT_DIR
# The agent names and worktree paths come from ralph/project.md.
# The coder runs on CODER_MODEL (default claude-opus-5-5). The reviewer runs on
# Claude Code with REVIEWER_MODEL (default claude-sonnet-5-5), so it reviews with
# a different model.
# Must run inside a herdr pane. Refuses to run twice for the same project.
set -euo pipefail

if [ "${HERDR_ENV:-}" != 1 ]; then
    echo "ERROR: not inside herdr (HERDR_ENV is not 1)"
    exit 1
fi

PROJECT="$(cd "${1:?Usage: layout.sh PROJECT_DIR}" && pwd)"
NAME="$(basename "$PROJECT")"
LABEL="$NAME loop"

# One KEY=value line from the overlay; bootstrap.sh wrote them.
conf() { sed -n "s/^$1=//p" "$PROJECT/ralph/project.md" | head -1; }
lower() { tr '[:upper:]' '[:lower:]' <<<"$1"; }

CODER="$(conf CODER)"
REVIEWER="$(conf REVIEWER)"
CODER_TREE="$(conf CODER_WORKTREE)"
REVIEWER_TREE="$(conf REVIEWER_WORKTREE)"
for v in CODER REVIEWER CODER_TREE REVIEWER_TREE; do
    case "${!v}" in "" | *"{{"*) echo "ERROR: $v is not set in ralph/project.md"; exit 1 ;; esac
done

# Per-project log directories, so two projects never share a current.jsonl.
# The names do not end in "<agent>-sessions", so the watchers get --agent.
CODER_LOG="/tmp/$NAME-$(lower "$CODER")-sessions"
REVIEWER_LOG="/tmp/$NAME-$(lower "$REVIEWER")-sessions"

for tree in "$CODER_TREE" "$REVIEWER_TREE"; do
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

herdr pane rename "$CODER_PANE" "$CODER" >/dev/null
herdr pane rename "$REVIEWER_PANE" "$REVIEWER" >/dev/null
herdr pane rename "$CODER_WATCH" "$CODER watcher" >/dev/null
herdr pane rename "$REVIEWER_WATCH" "$REVIEWER watcher" >/dev/null

# Watchers first: they wait for current.jsonl, so nothing is missed.
herdr pane run "$CODER_WATCH" "RALPH_LOG_DIR=$CODER_LOG uv run python ralph/watch.py --agent $CODER --tui" >/dev/null
herdr pane run "$REVIEWER_WATCH" "RALPH_LOG_DIR=$REVIEWER_LOG uv run python ralph/watch.py --agent $REVIEWER --tui" >/dev/null

# The loops read the primary's harness files, so prompt changes merged to
# main take effect without touching the worktrees.
herdr pane run "$CODER_PANE" \
    "RALPH_MODEL=${CODER_MODEL:-claude-opus-5-5} RALPH_STREAM_LOG=1 RALPH_SHOW_BEAD=1 RALPH_LOG_DIR=$CODER_LOG $PROJECT/ralph/run.sh $CODER $PROJECT/ralph/CODER.md" >/dev/null
herdr pane run "$REVIEWER_PANE" \
    "RALPH_MODEL=${REVIEWER_MODEL:-claude-sonnet-5-5} RALPH_STREAM_LOG=1 RALPH_SHOW_BEAD=1 RALPH_LOG_DIR=$REVIEWER_LOG $PROJECT/ralph/run.sh $REVIEWER $PROJECT/ralph/REVIEWER.md" >/dev/null

echo "opened tab '$LABEL'"
echo "  $CODER: $CODER_PANE   $REVIEWER: $REVIEWER_PANE"
echo "watchers in this tab"
echo "  $CODER watcher: $CODER_WATCH   $REVIEWER watcher: $REVIEWER_WATCH"
