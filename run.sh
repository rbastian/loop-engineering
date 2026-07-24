#!/bin/bash
# Reusable agent loop. Run from the target repo (or worktree).
# Usage: run.sh [AGENT_NAME] [PROMPT_FILE]
#   AGENT_NAME  — bd assignee filter (default: Ralph)
#   PROMPT_FILE — prompt file path, relative to cwd (default: PROMPT.md)
#
# Optional switches (default OFF — set to any non-empty value to enable):
#   RALPH_STREAM_LOG=1   Stream tool calls + assistant turns as JSONL.
#                        Tees claude output to $RALPH_LOG_DIR/<timestamp>.jsonl
#                        (default $RALPH_LOG_DIR=/tmp/ralph-sessions) and maintains
#                        a "current.jsonl" symlink for tail -f.
#   RALPH_SHOW_BEAD=1    For each in-progress bead, also run `bd show <id>` so
#                        notes/checkpoint/gate-output are visible between sessions.
#   RALPH_SESSION_TIMEOUT  Max wall-clock time per claude session (default: 2h).
#                        Needs GNU timeout; on macOS: brew install coreutils.
set -euo pipefail

AGENT_NAME="${1:-Ralph}"
PROMPT_FILE="${2:-PROMPT.md}"
SESSION_TIMEOUT="${RALPH_SESSION_TIMEOUT:-2h}"

if [ ! -f "$PROMPT_FILE" ]; then
    echo "ERROR: $PROMPT_FILE not found in $(pwd)"
    echo "Hint: cd into the target repo (or worktree) before running, or pass an absolute path as arg 2."
    exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
    echo "ERROR: jq is required (brew install jq)"
    exit 1
fi

# Guard each claude session with a wall-clock timeout so a wedged session
# (hung tool call, endless poll) can't stall the loop forever.
TIMEOUT_CMD=""
if command -v timeout >/dev/null 2>&1; then
    TIMEOUT_CMD="timeout --signal=INT --kill-after=60 $SESSION_TIMEOUT"
elif command -v gtimeout >/dev/null 2>&1; then
    TIMEOUT_CMD="gtimeout --signal=INT --kill-after=60 $SESSION_TIMEOUT"
else
    echo "WARNING: timeout/gtimeout not found — sessions have no time limit (brew install coreutils)"
fi

# Count beads via JSON rather than scraping human-readable output, which
# breaks silently if bd rewords its messages. Prints -1 when bd itself fails
# (e.g. embedded Dolt is single-writer, so a concurrent interactive bd
# session can hold the lock) so callers can tell "no work" from "bd down".
bead_count() {
    local json
    json=$("$@" --json 2>/dev/null) || { echo -1; return 0; }
    jq 'length' <<<"$json" 2>/dev/null || echo -1
}

while true; do

    # Re-read $PROMPT_FILE each iteration so changes take effect without restart
    PROMPT=$(cat "$PROMPT_FILE")

    # Show both in_progress (agent's claimed work) and ready (new work) beads.
    # Agent resumes in_progress first per PROMPT.md Phase 0; both lists are
    # shown here for operator visibility.
    IN_PROGRESS_COUNT=$(bead_count bd list --assignee="$AGENT_NAME" --status=in_progress)
    READY_COUNT=$(bead_count bd ready --assignee="$AGENT_NAME")

    if [ "$IN_PROGRESS_COUNT" -lt 0 ] || [ "$READY_COUNT" -lt 0 ]; then
        echo "WARNING: bd unavailable (db locked or erroring); retrying in 30s"
        sleep 30
        continue
    fi

    if [ "$IN_PROGRESS_COUNT" -eq 0 ] && [ "$READY_COUNT" -eq 0 ]; then
        echo "No beads for $AGENT_NAME. Zzzzzz..."
        sleep 30
        continue
    fi

    if [ "$IN_PROGRESS_COUNT" -gt 0 ]; then
        echo "In-progress beads (claimed, not finished):"
        bd list --assignee="$AGENT_NAME" --status=in_progress 2>&1 || true
        echo ""
        if [ -n "${RALPH_SHOW_BEAD:-}" ]; then
            for BEAD_ID in $(bd list --assignee="$AGENT_NAME" --status=in_progress --json 2>/dev/null \
                              | jq -r '.[].id // empty' 2>/dev/null | head -5); do
                echo "--- bd show $BEAD_ID ---"
                bd show "$BEAD_ID" 2>&1 | grep -v '^Warning:' || true
                echo ""
            done
        fi
    fi
    if [ "$READY_COUNT" -gt 0 ]; then
        echo "Ready beads (unclaimed, no blockers):"
        bd ready --assignee="$AGENT_NAME" 2>&1 || true
        echo ""
    fi

    echo ""
    echo "=== $(date '+%Y-%m-%d %H:%M:%S') === Starting Claude session ==="
    echo "=================================================="

    # Capture claude's exit code explicitly: under set -e a bare failing
    # command would kill the whole loop, turning one bad session (API blip,
    # rate limit, timeout) into a dead daemon.
    set +e
    if [ -n "${RALPH_STREAM_LOG:-}" ]; then
        LOG_DIR="${RALPH_LOG_DIR:-/tmp/ralph-sessions}"
        mkdir -p "$LOG_DIR"
        SESSION_LOG="$LOG_DIR/$(date +%Y%m%d-%H%M%S).jsonl"
        ln -sf "$SESSION_LOG" "$LOG_DIR/current.jsonl"
        echo "Stream log: $SESSION_LOG (tail -f $LOG_DIR/current.jsonl)"
        ${TIMEOUT_CMD} claude -p "$PROMPT" --dangerously-skip-permissions \
            --verbose --output-format stream-json </dev/null \
          | tee "$SESSION_LOG"
        CLAUDE_EXIT=${PIPESTATUS[0]}
    else
        ${TIMEOUT_CMD} claude -p "$PROMPT" --dangerously-skip-permissions </dev/null
        CLAUDE_EXIT=$?
    fi
    set -e

    if [ "$CLAUDE_EXIT" -eq 124 ]; then
        echo "claude session timed out after $SESSION_TIMEOUT"
    else
        echo "claude exited with $CLAUDE_EXIT"
    fi
    echo "=== $(date '+%Y-%m-%d %H:%M:%S') === Session ended ==="
    echo ""

    sleep 30
done
