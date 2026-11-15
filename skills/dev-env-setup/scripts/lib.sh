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

# One KEY=value line of FILE, a stamp such as .loop/HARNESS_VERSION. Prints
# nothing when it has none. Usage: key_value FILE KEY
key_value() {
    sed -n "s/^$2=//p" "$1" 2>/dev/null | head -1
}

# Run loop/config.py of the clone at LOOP_HOME. Usage: config_py ARGS...
config_py() {
    uv run --quiet "$LOOP_HOME/loop/config.py" "$@"
}

# Set the shell variables that config.py export prints (CODER, REVIEWER,
# HUMAN, SHIP_MODE, CODER_WORKTREE and the others) from FILE, a loop.toml.
# When FILE is not valid, config.py prints each error with its key path, and
# the function prints one more line and fails. Usage: load_loop_config FILE
load_loop_config() {
    local values
    if ! values=$(config_py --file "$1" export); then
        echo "ERROR: $1 is not valid; fix the errors above"
        return 1
    fi
    eval "$values"
}

# The shell names of the values in loop.toml, as an extended regular
# expression for a KEY=value line of an old .loop/project.md.
LOOP_KEYS_RE='CODER|REVIEWER|HUMAN|CODER_ENGINE|CODER_MODEL|REVIEWER_ENGINE|REVIEWER_MODEL|BEAD_PREFIX|SHIP_MODE|GITHUB_ACCOUNT|PRIMARY|CODER_WORKTREE|REVIEWER_WORKTREE'

# Print one TOML table: the [TABLE] line, then KEY = "value" for each
# VARIABLE=KEY pair whose shell variable is set. An unset variable leaves its
# key out, so that config.py applies the default or reports the missing key.
# Usage: toml_table TABLE VARIABLE=KEY...
toml_table() {
    local pair var
    echo "[$1]"
    shift
    for pair in "$@"; do
        var="${pair%%=*}"
        [ -n "${!var+x}" ] || continue
        printf '%s = "%s"\n' "${pair#*=}" "$(printf '%s' "${!var}" | sed 's/[\\"]/\\&/g')"
    done
}

# Write FILE, a loop.toml, from the shell variables that config.py export
# names. Usage: write_loop_toml FILE
write_loop_toml() {
    {
        toml_table project PRIMARY=primary BEAD_PREFIX=bead_prefix HUMAN=human
        echo
        toml_table ship SHIP_MODE=mode GITHUB_ACCOUNT=github_account
        echo
        toml_table coder CODER=name CODER_ENGINE=engine CODER_MODEL=model CODER_WORKTREE=worktree
        echo
        toml_table reviewer REVIEWER=name REVIEWER_ENGINE=engine REVIEWER_MODEL=model REVIEWER_WORKTREE=worktree
    } >"$1"
}

# The names in a harness-files list, on one line with one space between
# them. Blank lines and lines that start with # are ignored.
# Usage: harness_files FILE
harness_files() {
    local name list=""
    while read -r name || [ -n "$name" ]; do
        case "$name" in '' | '#'*) continue ;; esac
        list="$list${list:+ }$name"
    done <"$1"
    echo "$list"
}

# The paths in the loop-engineering clone whose commits count as drift for
# the harness installed in DIR: loop/<name> for each line of
# DIR/harness-files, plus loop/interactive.template.md, which update.sh renders
# into CLAUDE.md and AGENTS.md. Without the list (an install from before
# loop/harness-files), every commit under loop/ counts. run.sh holds the same
# function, and a test checks that the two copies match.
# Usage: HARNESS_PATHS=$(harness_paths DIR)
harness_paths() {
    local name list=loop/interactive.template.md
    [ -f "$1/harness-files" ] || {
        echo loop
        return 0
    }
    while read -r name || [ -n "$name" ]; do
        case "$name" in '' | '#'*) continue ;; esac
        list="$list loop/$name"
    done <"$1/harness-files"
    echo "$list"
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
    count=$(git -C "$clone" rev-list --count "$commit..HEAD" -- $HARNESS_PATHS 2>/dev/null) || return 0
    case "$count" in 0) return 0 ;; 1) count="1 commit" ;; *) count="$count commits" ;; esac
    echo "harness is $count behind loop-engineering; run update.sh"
}

# Succeeds when MODEL is safe to write into .loop/loop.toml and into a pane
# command: letters, digits and . _ : / @ - [ ], for example
# deepseek-flash-latest[1m]. An empty MODEL passes. Usage: valid_model MODEL
valid_model() {
    local re='^[][A-Za-z0-9._:/@-]*$'
    [[ "$1" =~ $re ]]
}

# Check the engine and the model of one agent, ROLE CODER or REVIEWER. The
# coder runs on claude or fw, because its prompt uses /simplify, a Claude Code
# skill, and fw runs Claude Code. The reviewer runs on claude, codex or fw. fw
# has no default model. PREFIX goes before the variable names in the errors:
# LOOP_ for bootstrap.sh, empty for layout.sh. Prints the error and fails.
# Usage: check_engine PREFIX ROLE ENGINE MODEL
check_engine() {
    local engine_var="$1${2}_ENGINE" model_var="$1${2}_MODEL" engines
    case "$2" in
        CODER) engines="claude fw" ;;
        *) engines="claude codex fw" ;;
    esac
    case " $engines " in
        *" $3 "*) ;;
        *) echo "ERROR: $engine_var must be one of: $engines (got: $3)"; return 1 ;;
    esac
    if ! valid_model "$4"; then
        echo "ERROR: $model_var must be letters, digits and . _ : / @ - [ ] (got: $4)"
        return 1
    fi
    if [ "$3" = fw ] && [ -z "$4" ]; then
        echo "ERROR: $engine_var=fw needs $model_var, for example deepseek-flash-latest[1m]"
        return 1
    fi
}
