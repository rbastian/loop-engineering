#!/bin/bash
# Reusable agent loop. Run from the target repo (or worktree).
# Usage: run.sh [AGENT_NAME] [PROMPT_FILE]
#   AGENT_NAME  — bd assignee filter (default: Ralph)
#   PROMPT_FILE — prompt file path, relative to cwd (default: PROMPT.md)
#
# Optional visibility switches (default OFF — set to any non-empty value to enable):
#   RALPH_STREAM_LOG=1   Stream tool calls + assistant turns as JSONL.
#                        Tees claude output to $RALPH_LOG_DIR/<timestamp>.jsonl
#                        (default $RALPH_LOG_DIR=/tmp/ralph-sessions) and maintains
#                        a "current.jsonl" symlink for tail -f.
#   RALPH_SHOW_BEAD=1    For each in-progress bead, also run `bd show <id>` so
#                        notes/checkpoint/gate-output are visible between sessions.
set -euo pipefail

AGENT_NAME="${1:-Ralph}"
PROMPT_FILE="${2:-PROMPT.md}"

if [ ! -f "$PROMPT_FILE" ]; then
    echo "ERROR: $PROMPT_FILE not found in $(pwd)"
    echo "Hint: cd into the target repo (or worktree) before running, or pass an absolute path as arg 2."
    exit 1
fi

while true; do

    # Re-read $PROMPT_FILE each iteration so changes take effect without restart
    PROMPT=$(cat "$PROMPT_FILE")

    # Show both in_progress (agent's claimed work) and ready (new work) beads.
    # Agent prioritizes in_progress per PROMPT.md; both lists are shown for visibility.
    IN_PROGRESS=$(bd list --assignee="$AGENT_NAME" --status=in_progress 2>&1)
    READY=$(bd ready --assignee="$AGENT_NAME" 2>&1)

    HAS_IN_PROGRESS=true
    HAS_READY=true
    echo "$IN_PROGRESS" | grep -q "No issues found" && HAS_IN_PROGRESS=false
    echo "$READY" | grep -q "No ready work found" && HAS_READY=false

    if ! $HAS_IN_PROGRESS && ! $HAS_READY; then
        echo "No beads for $AGENT_NAME. Zzzzzz..."
        sleep 30
        continue
    fi

    if $HAS_IN_PROGRESS; then
        echo "In-progress beads (claimed, not finished):"
        echo "$IN_PROGRESS"
        echo ""
        if [ -n "${RALPH_SHOW_BEAD:-}" ]; then
            for BEAD_ID in $(bd list --assignee="$AGENT_NAME" --status=in_progress --json 2>/dev/null \
                              | jq -r '.[].id // empty' 2>/dev/null | head -5); do
                echo "--- bd show $BEAD_ID ---"
                bd show "$BEAD_ID" 2>&1 | grep -v '^Warning:'
                echo ""
            done
        fi
    fi
    if $HAS_READY; then
        echo "Ready beads (unclaimed, no blockers):"
        echo "$READY"
        echo ""
    fi

    echo ""
    echo "=== $(date '+%Y-%m-%d %H:%M:%S') === Starting Claude session ==="
    echo "=================================================="

    if [ -n "${RALPH_STREAM_LOG:-}" ]; then
        LOG_DIR="${RALPH_LOG_DIR:-/tmp/ralph-sessions}"
        mkdir -p "$LOG_DIR"
        SESSION_LOG="$LOG_DIR/$(date +%Y%m%d-%H%M%S).jsonl"
        ln -sf "$SESSION_LOG" "$LOG_DIR/current.jsonl"
        echo "Stream log: $SESSION_LOG (tail -f $LOG_DIR/current.jsonl)"
        claude -p "$PROMPT" --dangerously-skip-permissions \
            --verbose --output-format stream-json </dev/null \
          | tee "$SESSION_LOG"
        CLAUDE_EXIT=${PIPESTATUS[0]}
    else
        claude -p "$PROMPT" --dangerously-skip-permissions </dev/null
        CLAUDE_EXIT=$?
    fi
    echo "claude exited with $CLAUDE_EXIT"
    echo "=== $(date '+%Y-%m-%d %H:%M:%S') === Session ended ==="
    echo ""

    sleep 30
done
