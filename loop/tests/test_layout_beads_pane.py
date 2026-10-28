"""skills/dev-env-setup/scripts/layout.sh: the Beads pane keeps bd's colors.

The pane captures `bd list` in a command substitution so that it redraws only
when the list changes. bd turns color off when its output is not a terminal,
so the pane printed without color until the bd call got CLICOLOR_FORCE=1
(lpe-te8). These tests run the pane's capture with a fake bd on PATH.
"""

import re
import subprocess
from pathlib import Path

LAYOUT = Path(__file__).parents[2] / "skills/dev-env-setup/scripts/layout.sh"


def beads_capture() -> str:
    """The `out=$(...)` assignment from the BEADS_LOOP line of layout.sh."""
    line = next(
        line
        for line in LAYOUT.read_text().splitlines()
        if line.startswith("BEADS_LOOP=")
    )
    return re.search(r"out=\$\(.*?\);", line).group(0)


def run_capture(tmp_path: Path) -> str:
    fake_bd = tmp_path / "bd"
    fake_bd.write_text('#!/bin/sh\nprintf "bd sees %s" "${CLICOLOR_FORCE-unset}"\n')
    fake_bd.chmod(0o755)
    script = (
        beads_capture() + ' printf "%s|shell sees %s" "$out" "${CLICOLOR_FORCE-unset}"'
    )
    result = subprocess.run(
        ["bash", "-c", script],
        env={"PATH": f"{tmp_path}:/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def test_color_is_forced_on_the_bd_call_only(tmp_path):
    assert run_capture(tmp_path) == "bd sees 1|shell sees unset"
