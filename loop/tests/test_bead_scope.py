"""Coder edits stay within the bead, and the reviewer enforces that (lpe-byd)."""

from pathlib import Path

LOOP = Path(__file__).parents[1]
CODER = (LOOP / "CODER.md").read_text()
REVIEWER = (LOOP / "REVIEWER.md").read_text()


def test_coder_hard_rules_limit_changes_to_the_bead():
    rules = CODER.split("Rules:\n", 1)[1].split("\n## ", 1)[0]
    assert "Change only what the bead needs." in rules
    assert "Do not reword, reformat or restyle" in rules
    assert "write it in a bead note" in rules
    assert (
        "The reviewer returns a branch that changes lines the bead does not need."
        in rules
    )


def test_reviewer_blocks_changes_outside_the_bead():
    blocking = REVIEWER.split("**Blocking**", 1)[1].split(
        "**Everything else is non-blocking**", 1
    )[0]
    assert (
        "a change to code, comments or documentation that the bead does not need, "
        "such as rewording, reformatting or restyling unrelated lines"
    ) in blocking
    assert "The finding names the unrelated lines" in blocking


def test_reviewer_keeps_in_scope_style_findings_non_blocking():
    non_blocking = REVIEWER.split("**Everything else is non-blocking**", 1)[1]
    assert "work the bead did not ask for" not in non_blocking
    assert "style, naming, a tidier shape inside the lines that the bead needs" in (
        non_blocking
    )
