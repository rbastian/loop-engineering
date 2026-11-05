#!/bin/bash
# Functions that bootstrap.sh, update.sh and layout.sh share. Source this file.
# It sets no shell options and runs nothing by itself. bash 3.2 and BSD tools.

INTERACTIVE_BEGIN='<!-- BEGIN LOOP INTERACTIVE -->'
INTERACTIVE_END='<!-- END LOOP INTERACTIVE -->'

# Fill the name placeholders of a template: interactive.template.md or
# project.template.md. Usage: fill_names TEMPLATE CODER REVIEWER HUMAN >OUT
fill_names() {
    sed -e "s#{{CODER}}#$2#g" -e "s#{{REVIEWER}}#$3#g" -e "s#{{HUMAN}}#$4#g" "$1"
}

# The same awk rule finds the section everywhere: it starts at a BEGIN marker
# line and ends at the next END marker line.
# Fails when DOC has a BEGIN marker line with no END marker line after it.
interactive_markers_ok() {
    awk -v begin="$INTERACTIVE_BEGIN" -v end="$INTERACTIVE_END" '
        !inside && $0 == begin { inside = 1; next }
        inside && $0 == end { inside = 0 }
        END { exit inside }
    ' "$1"
}

# Print each line of DOC outside the interactive section as NUMBER: LINE.
lines_outside_section() {
    awk -v begin="$INTERACTIVE_BEGIN" -v end="$INTERACTIVE_END" '
        !inside && $0 == begin { inside = 1; next }
        inside { if ($0 == end) inside = 0; next }
        { print FNR ": " $0 }
    ' "$1"
}

# Put the rendered SECTION file into DOC and print what it did.
# Usage: install_interactive DOC SECTION keep|replace
# A missing DOC becomes a copy of SECTION. A DOC without a section gets one
# after its first H1 outside a code fence and before any beads block, or at
# the top if there is none. A DOC with a section keeps it (keep), or gets the
# text between the markers replaced (replace). Text outside the markers never
# changes.
install_interactive() {
    local doc="$1" section="$2" mode="$3" done replace=0
    if [ ! -f "$doc" ]; then
        cp "$section" "$doc"
        echo "wrote $doc with the interactive section"
        return 0
    fi
    if grep -qxF "$INTERACTIVE_BEGIN" "$doc"; then
        if [ "$mode" = keep ]; then
            echo "$doc holds the interactive section; keeping it"
            return 0
        fi
        done="refreshed the interactive section in"
        replace=1
    else
        done="added the interactive section to"
    fi
    # A section between the markers is replaced in place. Without one, pass 1
    # finds the first H1 outside a code fence and before any beads block, and
    # pass 2 puts the section after it, or at the top if there is none.
    awk -v section="$section" -v begin="$INTERACTIVE_BEGIN" -v end="$INTERACTIVE_END" -v replace="$replace" '
        function emit(line) {
            while ((getline line <section) > 0) print line
            close(section)
        }
        NR == FNR {
            if (stop || replace) next
            if ($0 ~ /^(```|~~~)/) fence = !fence
            else if (!fence && $0 ~ /^<!-- BEGIN BEADS/) stop = 1
            else if (!fence && $0 ~ /^# /) { h1 = FNR; stop = 1 }
            next
        }
        replace {
            if (!inside && $0 == begin) { emit(); inside = 1; next }
            if (inside) { if ($0 == end) inside = 0; next }
            print
            next
        }
        FNR == 1 && !h1 { emit(); print "" }
        skip && $0 == "" { next }
        skip { print ""; skip = 0 }
        { print }
        FNR == h1 { print ""; emit(); skip = 1 }
    ' "$doc" "$doc" >"$doc.tmp"
    if cmp -s "$doc" "$doc.tmp"; then
        rm -f "$doc.tmp"
        echo "$doc holds the current interactive section"
    else
        mv "$doc.tmp" "$doc"
        echo "$done $doc"
    fi
}

# Fails unless $1 is a git repository with at least one commit.
clone_has_commit() {
    git -C "$1" rev-parse --verify -q HEAD >/dev/null 2>&1
}

# Fails when loop/ in the clone at $1 has uncommitted changes.
clone_clean() {
    [ -z "$(git -C "$1" status --porcelain -- loop/)" ]
}

# Write the version stamp FILE for the clone at HOME: the clone's HEAD and its
# path, and dirty=1 when loop/ in the clone has uncommitted changes.
# Usage: write_stamp FILE HOME
write_stamp() {
    {
        echo "commit=$(git -C "$2" rev-parse HEAD)"
        echo "clone=$2"
        clone_clean "$2" || echo "dirty=1"
    } >"$1"
}

# One KEY=value line of FILE, a stamp or .loop/project.md. Prints nothing
# when it has none. Usage: key_value FILE KEY
key_value() {
    sed -n "s/^$2=//p" "$1" 2>/dev/null | head -1
}

# The drift line for the stamp FILE, or nothing when the harness is current.
# A missing stamp or clone, or a commit that the clone lacks, prints nothing.
# run.sh holds the same text, because it cannot source this file. A test
# checks that the two copies match.
drift_line() {
    local commit clone count
    commit=$(sed -n 's/^commit=//p' "$1" 2>/dev/null | head -1)
    clone=$(sed -n 's/^clone=//p' "$1" 2>/dev/null | head -1)
    [ -n "$commit" ] && [ -d "$clone" ] || return 0
    count=$(git -C "$clone" rev-list --count "$commit..HEAD" -- loop/ 2>/dev/null) || return 0
    case "$count" in 0) return 0 ;; 1) count="1 commit" ;; *) count="$count commits" ;; esac
    echo "harness is $count behind loop-engineering; run update.sh"
}
