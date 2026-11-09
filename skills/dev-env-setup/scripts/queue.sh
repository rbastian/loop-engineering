#!/bin/bash
# Print one agent's in-progress, ready and blocked beads.
# Usage: queue.sh [--watch] AGENT
# With --watch, poll every five seconds and redraw only when the queue changes.
# Run from the project whose beads bd reads. Requires bd and jq.
set -euo pipefail

usage() {
    echo "Usage: queue.sh [--watch] AGENT" >&2
    exit 2
}

WATCH=0
if [ "${1:-}" = --watch ]; then
    WATCH=1
    shift
fi
[ "$#" -eq 1 ] || usage
AGENT="$1"

print_in_progress() {
    local json rendered
    printf 'In progress\n'
    if ! json="$(CLICOLOR_FORCE=1 bd list --assignee="$AGENT" --status=in_progress --json 2>&1)"; then
        printf '%s\n' "$json"
        return 0
    fi
    if ! rendered="$(printf '%s\n' "$json" | jq -r '
        .[] |
        "  \(.id)\(((.labels // []) | map(select(startswith("loop:")) | " [" + . + "]") | join(""))) \(.title)"
    ' 2>&1)"; then
        printf '%s\n' "$rendered"
        return 0
    fi
    if [ -n "$rendered" ]; then
        printf '%s\n' "$rendered"
    else
        printf '(none)\n'
    fi
}

print_ready() {
    local output
    printf 'Ready next\n'
    if ! output="$(CLICOLOR_FORCE=1 bd ready --assignee="$AGENT" 2>&1)"; then
        printf '%s\n' "$output"
        return 0
    fi
    case "$output" in
        "" | "No issues found." | *"No ready work found"*) printf '(none)\n' ;;
        *) printf '%s\n' "$output" ;;
    esac
}

print_waiting() {
    local assigned blocked rendered failed=0
    printf 'Waiting\n'
    if ! assigned="$(CLICOLOR_FORCE=1 bd list --assignee="$AGENT" --json 2>&1)"; then
        printf '%s\n' "$assigned"
        failed=1
    fi
    if ! blocked="$(CLICOLOR_FORCE=1 bd blocked --json 2>&1)"; then
        printf '%s\n' "$blocked"
        failed=1
    fi
    [ "$failed" -eq 0 ] || return 0
    if ! rendered="$(jq -r -n --argjson assigned "$assigned" --argjson blocked "$blocked" '
        ($assigned | map(.id)) as $ids |
        [$blocked[] | select(.id as $id | $ids | index($id))] as $waiting |
        if ($waiting | length) == 0 then
            "(none)"
        else
            "\($waiting | length) beads",
            ($waiting[:3][] |
                ((.blocked_by // []) | join(", ")) as $blockers |
                "  \(.id) (blocked by: \($blockers)) \(.title)"),
            (if ($waiting | length) > 3 then
                "  ... and \(($waiting | length) - 3) more"
            else
                empty
            end)
        end
    ' 2>&1)"; then
        printf '%s\n' "$rendered"
        return 0
    fi
    printf '%s\n' "$rendered"
}

print_queue() {
    print_in_progress
    print_ready
    print_waiting
}

if [ "$WATCH" -eq 0 ]; then
    print_queue
    exit 0
fi

# Capture before clearing so that polling never leaves the pane blank. Force
# color on each bd call only; bd disables color inside a command substitution.
prev=
while true; do
    out="$(print_queue 2>&1)" || true
    if [ "$out" != "$prev" ]; then
        clear
        date "+updated %H:%M:%S"
        printf '%s\n' "$out"
        prev="$out"
    fi
    sleep 5
done
