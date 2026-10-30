#!/bin/bash
# Reusable agent loop. Run from the target repo (or worktree).
# Usage: run.sh [AGENT_NAME] [PROMPT_FILE]
#   AGENT_NAME  — bd assignee filter (default: Ralph)
#   PROMPT_FILE — prompt file path, relative to cwd (default: CODER.md)
#
# Optional switches (default OFF — set to any non-empty value to enable):
#   RALPH_STREAM_LOG=1   Stream tool calls + assistant turns as JSONL.
#                        Tees claude output to $RALPH_LOG_DIR/<timestamp>.jsonl
#                        (default $RALPH_LOG_DIR=/tmp/ralph-sessions) and maintains
#                        a "current.jsonl" symlink for tail -f. After each
#                        session, also appends a "Session cost:" note to the
#                        bead (needs uv, which runs watch.py --summary).
#   RALPH_SHOW_BEAD=1    For each in-progress bead, also run `bd show <id>` so
#                        notes/checkpoint/gate-output are visible between sessions.
#   RALPH_SESSION_TIMEOUT  Max wall-clock time per session (default: 2h).
#                        Needs GNU timeout; on macOS: brew install coreutils.
#   RALPH_ENGINE         Which agent CLI runs each session: claude (default)
#                        or codex. Any other value stops the loop at startup.
#   RALPH_MODEL          Model for each session. Defaults to claude-opus-5-5 on
#                        the claude engine; on codex it has no default, and an
#                        unset one means the default model of the ChatGPT plan.
#   RALPH_OVERLAY        Project overlay appended to the prompt (default:
#                        project.md beside PROMPT_FILE; "none" disables it).
#   RALPH_PRINT_PROMPT=1 Print the combined prompt and exit.
set -euo pipefail

AGENT_NAME="${1:-Ralph}"
PROMPT_FILE="${2:-CODER.md}"
SESSION_TIMEOUT="${RALPH_SESSION_TIMEOUT:-2h}"
ENGINE="${RALPH_ENGINE:-claude}"

# The engine picks the command and the model default. Reviewing on a second
# model family is the point of the codex engine, so it gets no default model:
# an unset RALPH_MODEL there means whatever the ChatGPT plan runs by default.
case "$ENGINE" in
    claude) MODEL="${RALPH_MODEL:-claude-opus-5-5}" ;;
    codex) MODEL="${RALPH_MODEL:-}" ;;
    *)
        echo "ERROR: RALPH_ENGINE must be claude or codex (got: $ENGINE)"
        exit 1
        ;;
esac

# The agent reads this to choose its engine-specific steps: on codex, the reviewer
# reviews with `codex exec review` instead of the /code-review skill.
export RALPH_ENGINE="$ENGINE"

# bd resolves its actor from $BEADS_ACTOR (then git user.name, then $USER).
# The actor must match the bead's assignee or `bd update --claim` refuses
# ("already claimed by Ralph"), and it attributes the audit trail correctly.
export BEADS_ACTOR="$AGENT_NAME"

if [ ! -f "$PROMPT_FILE" ]; then
    echo "ERROR: $PROMPT_FILE not found in $(pwd)"
    echo "Hint: cd into the target repo (or worktree) before running, or pass an absolute path as arg 2."
    exit 1
fi

# The overlay defaults to project.md beside the prompt file. RALPH_OVERLAY
# overrides the path; RALPH_OVERLAY=none runs the base prompt alone.
OVERLAY_FILE="${RALPH_OVERLAY:-$(dirname "$PROMPT_FILE")/project.md}"
if [ "$OVERLAY_FILE" = "none" ]; then
    OVERLAY_FILE=""
elif [ ! -f "$OVERLAY_FILE" ]; then
    echo "ERROR: project overlay $OVERLAY_FILE not found"
    echo "Hint: create it, point RALPH_OVERLAY at it, or set RALPH_OVERLAY=none."
    exit 1
fi

# RALPH_PRINT_PROMPT=1 prints the combined prompt and exits, to check an overlay.
if [ -n "${RALPH_PRINT_PROMPT:-}" ]; then
    cat "$PROMPT_FILE"
    if [ -n "$OVERLAY_FILE" ]; then printf '\n\n'; cat "$OVERLAY_FILE"; fi
    exit 0
fi

if ! command -v jq >/dev/null 2>&1; then
    echo "ERROR: jq is required (brew install jq)"
    exit 1
fi

# Guard each session with a wall-clock timeout so a wedged session
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

# A killed or failed sleep must not end the loop under set -e (lpe-qi4).
pause() { sleep "$1" || true; }

# watch.py sits beside this script, in the primary checkout's ralph/ folder.
HARNESS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Append the finished session's cost to its bead. The agent cannot do this:
# the cost arrives in the closing event, after the agent has exited. watch.py
# --summary reads the bead and the cost back out of the log. A resumed session
# may never claim, tag or review, so the bead falls back to the one bead the
# agent held when the session started. Every failure only warns: a missing
# cost note must never stop the loop.
record_cost() {
    local log="$1" held="$2" summary bead note ids attempt
    if ! command -v uv >/dev/null 2>&1; then
        echo "WARNING: uv not found; no cost note for this session"
        return 0
    fi
    if ! summary=$(uv run --quiet "$HARNESS_DIR/watch.py" --summary "$log" --agent "$AGENT_NAME" 2>/dev/null); then
        echo "WARNING: could not read $log; no cost note for this session"
        return 0
    fi
    note=$(jq -r '.note // empty' <<<"$summary" 2>/dev/null) || note=""
    bead=$(jq -r '.bead // empty' <<<"$summary" 2>/dev/null) || bead=""
    if [ -z "$note" ]; then
        echo "WARNING: the session did not finish; no cost note"
        return 0
    fi
    if [ -z "$bead" ]; then
        read -ra ids <<<"$held"
        if [ "${#ids[@]}" -eq 1 ]; then
            bead="${ids[0]}"
        else
            echo "WARNING: no bead found for this session; no cost note: $note"
            return 0
        fi
    fi
    # bd is single-writer, so a human's interactive session can hold the lock.
    for attempt in 1 2 3; do
        if bd note "$bead" "$note" >/dev/null 2>&1; then
            echo "Cost note on $bead: $note"
            return 0
        fi
        if [ "$attempt" -lt 3 ]; then pause 10; fi
    done
    echo "WARNING: bd note failed on $bead; no cost note: $note"
    return 0
}

# A KEY=value line from the overlay, the same way worktrees.sh reads it.
# Prints nothing when there is no overlay or no such line.
overlay_value() {
    [ -n "$OVERLAY_FILE" ] || return 0
    sed -n "s/^$1=//p" "$OVERLAY_FILE" | head -1
}

# In local mode the reviewer merges into the primary checkout, and REVIEWER.md
# exits without a merge when the primary is not on main or has modified or
# staged tracked files outside .beads/. Starting a session then only burns
# money, so the loop waits. Prints the reason when busy; prints nothing and
# fails when the reviewer may run (also for the coder, pr mode, no overlay).
primary_busy_reason() {
    local primary branch
    [ "$(overlay_value SHIP_MODE)" = "local" ] || return 1
    [ "$AGENT_NAME" = "$(overlay_value REVIEWER)" ] || return 1
    primary=$(overlay_value PRIMARY)
    [ -n "$primary" ] || return 1
    branch=$(git -C "$primary" rev-parse --abbrev-ref HEAD 2>/dev/null) || branch="?"
    if [ "$branch" != "main" ]; then
        echo "on $branch"
    elif git -C "$primary" status --porcelain --untracked-files=no 2>/dev/null \
            | grep -v '\.beads/' | grep -q .; then
        echo "modified tracked files"
    else
        return 1
    fi
}

# The busy reason printed last, so a wait prints its reason once, not every 30s.
LAST_BUSY=""

while true; do

    # Re-read $PROMPT_FILE each iteration so changes take effect without restart
    PROMPT=$(cat "$PROMPT_FILE")
    # Project overlay: the base prompt holds the loop protocol, the overlay
    # holds the project facts (context, paths, gate, review method). Re-read
    # each iteration like the base.
    if [ -n "$OVERLAY_FILE" ]; then
        PROMPT+=$'\n\n'"$(cat "$OVERLAY_FILE")"
    fi

    # Show both in_progress (agent's claimed work) and ready (new work) beads.
    # Agent resumes in_progress first per its prompt's Phase 0; both lists are
    # shown here for operator visibility.
    IN_PROGRESS_COUNT=$(bead_count bd list --assignee="$AGENT_NAME" --status=in_progress)
    READY_COUNT=$(bead_count bd ready --assignee="$AGENT_NAME")

    if [ "$IN_PROGRESS_COUNT" -lt 0 ] || [ "$READY_COUNT" -lt 0 ]; then
        echo "WARNING: bd unavailable (db locked or erroring); retrying in 30s"
        pause 30
        continue
    fi

    if [ "$IN_PROGRESS_COUNT" -eq 0 ] && [ "$READY_COUNT" -eq 0 ]; then
        echo "No beads for $AGENT_NAME. Zzzzzz..."
        pause 30
        continue
    fi

    # After the bead counts, so that "No beads" still prints with no work.
    if BUSY=$(primary_busy_reason); then
        if [ "$BUSY" != "$LAST_BUSY" ]; then
            echo "primary checkout busy: $BUSY; waiting to start $AGENT_NAME"
            LAST_BUSY="$BUSY"
        fi
        pause 30
        continue
    fi
    LAST_BUSY=""

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

    # The beads this agent holds as the session starts: the fallback for a
    # session whose log names no bead (see record_cost).
    HELD=$(bd list --assignee="$AGENT_NAME" --status=in_progress --json 2>/dev/null \
               | jq -r '.[].id // empty' 2>/dev/null | tr '\n' ' ') || HELD=""

    echo ""
    echo "=== $(date '+%Y-%m-%d %H:%M:%S') === Starting $ENGINE session (model: ${MODEL:-codex default}) ==="
    echo "=================================================="

    # Built here rather than at startup: $PROMPT is re-read each iteration.
    # One array for both call sites below. claude needs two flags to emit the
    # JSONL that codex exec --json emits on its own, so only it reads
    # $RALPH_STREAM_LOG here.
    if [ "$ENGINE" = "codex" ]; then
        AGENT_CMD=(codex exec --json --dangerously-bypass-approvals-and-sandbox)
        if [ -n "$MODEL" ]; then
            AGENT_CMD+=(-m "$MODEL")
        fi
        AGENT_CMD+=("$PROMPT")
    else
        AGENT_CMD=(claude -p "$PROMPT" --model "$MODEL" --dangerously-skip-permissions)
        if [ -n "${RALPH_STREAM_LOG:-}" ]; then
            AGENT_CMD+=(--verbose --output-format stream-json)
        fi
    fi

    # Capture the session's exit code explicitly: under set -e a bare failing
    # command would kill the whole loop, turning one bad session (API blip,
    # rate limit, timeout) into a dead daemon.
    set +e
    SESSION_LOG=""
    if [ -n "${RALPH_STREAM_LOG:-}" ]; then
        LOG_DIR="${RALPH_LOG_DIR:-/tmp/ralph-sessions}"
        mkdir -p "$LOG_DIR"
        SESSION_LOG="$LOG_DIR/$(date +%Y%m%d-%H%M%S).jsonl"
        ln -sf "$SESSION_LOG" "$LOG_DIR/current.jsonl"
        echo "Stream log: $SESSION_LOG (tail -f $LOG_DIR/current.jsonl)"
        # watch.py reads this first line for the engine, the model and the
        # start time: codex exec names no model in its own JSON even when -m
        # was passed, and its events carry no timestamps at all. jq builds it
        # so the JSON stays valid whatever the values hold, and the session is
        # APPENDED below — a plain `tee` would truncate this line away.
        jq -nc --arg engine "$ENGINE" --arg model "$MODEL" \
            --arg started "$(date +%Y-%m-%dT%H:%M:%S%z)" \
            '{type:"ralph.session",engine:$engine,model:$model,started:$started}' \
            >"$SESSION_LOG"
        ${TIMEOUT_CMD} "${AGENT_CMD[@]}" </dev/null | tee -a "$SESSION_LOG"
        SESSION_EXIT=${PIPESTATUS[0]}
    else
        ${TIMEOUT_CMD} "${AGENT_CMD[@]}" </dev/null
        SESSION_EXIT=$?
    fi
    set -e

    if [ "$SESSION_EXIT" -eq 124 ]; then
        echo "$ENGINE session timed out after $SESSION_TIMEOUT"
    else
        echo "$ENGINE exited with $SESSION_EXIT"
    fi
    if [ -n "$SESSION_LOG" ]; then
        record_cost "$SESSION_LOG" "$HELD"
    fi
    echo "=== $(date '+%Y-%m-%d %H:%M:%S') === Session ended ==="
    echo ""

    pause 30
done
