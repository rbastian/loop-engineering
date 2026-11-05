#!/bin/bash
# Functions that bootstrap.sh, update.sh and layout.sh share. Source this file.
# It sets no shell options and runs nothing by itself. bash 3.2 and BSD tools.

INTERACTIVE_BEGIN='<!-- BEGIN LOOP INTERACTIVE -->'
INTERACTIVE_END='<!-- END LOOP INTERACTIVE -->'

# Fill the name placeholders of loop/interactive.template.md.
# Usage: render_interactive TEMPLATE CODER REVIEWER HUMAN >SECTION
render_interactive() {
    sed -e "s#{{CODER}}#$2#g" -e "s#{{REVIEWER}}#$3#g" -e "s#{{HUMAN}}#$4#g" "$1"
}

# Fails when DOC has a BEGIN marker line with no END marker line after it.
interactive_markers_ok() {
    awk -v begin="$INTERACTIVE_BEGIN" -v end="$INTERACTIVE_END" '
        $0 == begin { open = 1 }
        open && $0 == end { open = 0 }
        END { exit open }
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
    local doc="$1" section="$2" mode="$3"
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
        awk -v section="$section" -v begin="$INTERACTIVE_BEGIN" -v end="$INTERACTIVE_END" '
            function emit(line) {
                while ((getline line <section) > 0) print line
                close(section)
            }
            !inside && $0 == begin { emit(); inside = 1; next }
            inside { if ($0 == end) inside = 0; next }
            { print }
        ' "$doc" >"$doc.tmp"
        if cmp -s "$doc" "$doc.tmp"; then
            rm -f "$doc.tmp"
            echo "$doc holds the current interactive section"
        else
            mv "$doc.tmp" "$doc"
            echo "refreshed the interactive section in $doc"
        fi
        return 0
    fi
    # Pass 1 finds the first H1 outside a code fence and before any beads
    # block. Pass 2 puts the section after it, or at the top if there is none.
    awk -v section="$section" '
        function emit(line) {
            while ((getline line <section) > 0) print line
            close(section)
        }
        NR == FNR {
            if (stop) next
            if ($0 ~ /^(```|~~~)/) fence = !fence
            else if (!fence && $0 ~ /^<!-- BEGIN BEADS/) stop = 1
            else if (!fence && $0 ~ /^# /) { h1 = FNR; stop = 1 }
            next
        }
        FNR == 1 && !h1 { emit(); print "" }
        skip && $0 == "" { next }
        skip { print ""; skip = 0 }
        { print }
        FNR == h1 { print ""; emit(); skip = 1 }
    ' "$doc" "$doc" >"$doc.tmp"
    mv "$doc.tmp" "$doc"
    echo "added the interactive section to $doc"
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

# One KEY=value line of a stamp. Prints nothing when it has none.
stamp_value() {
    sed -n "s/^$2=//p" "$1" 2>/dev/null | head -1
}

# The drift line for the stamp FILE, or nothing when the harness is current.
# A missing stamp or clone, or a commit that the clone lacks, prints nothing.
# run.sh holds a copy of this function, because it cannot source this file.
drift_line() {
    local commit clone count
    [ -f "$1" ] || return 0
    commit=$(stamp_value "$1" commit)
    clone=$(stamp_value "$1" clone)
    [ -n "$commit" ] && [ -d "$clone" ] || return 0
    git -C "$clone" cat-file -e "$commit^{commit}" 2>/dev/null || return 0
    count=$(git -C "$clone" rev-list --count "$commit..HEAD" -- loop/ 2>/dev/null) || return 0
    case "$count" in '' | 0 | *[!0-9]*) return 0 ;; 1) count="1 commit" ;; *) count="$count commits" ;; esac
    echo "harness is $count behind loop-engineering; run update.sh"
}
