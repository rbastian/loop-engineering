"""skills/dev-env-setup/scripts/layout.sh: where the watchers and Beads go.

The watchers share the top row, half each. The Beads pane sits beside the
calling pane, which keeps the left two thirds of the bottom area (lpe-7af).
"""

import re
from pathlib import Path

LAYOUT = Path(__file__).parents[2] / "skills/dev-env-setup/scripts/layout.sh"
TEXT = LAYOUT.read_text()


def split_args(var: str) -> tuple[str, str, str]:
    """The (source, direction, ratio) of the split that assigns var."""
    match = re.search(
        rf'^{var}=\$\(split "([^"]+)" (\w+) ([\d.]+) ', TEXT, re.MULTILINE
    )
    assert match, f"no split assigns {var}"
    return match.groups()


def test_coder_watcher_takes_the_top_third_with_a_swap():
    assert split_args("CODER_WATCH") == ("$HERDR_PANE_ID", "down", "0.33")
    assert (
        'herdr pane swap --source-pane "$CODER_WATCH" --target-pane "$HERDR_PANE_ID"'
        in TEXT
    )


def test_reviewer_watcher_gets_half_the_top_row():
    assert split_args("REVIEWER_WATCH") == ("$CODER_WATCH", "right", "0.5")


def test_beads_pane_goes_beside_the_calling_pane():
    assert split_args("BEADS_PANE") == ("$HERDR_PANE_ID", "right", "0.67")


def test_beads_split_comes_after_the_focus_line():
    lines = TEXT.splitlines()
    focus = next(i for i, line in enumerate(lines) if "herdr pane focus" in line)
    beads = next(i for i, line in enumerate(lines) if line.startswith("BEADS_PANE="))
    assert beads > focus
