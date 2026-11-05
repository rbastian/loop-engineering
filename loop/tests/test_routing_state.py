"""The loop routes on bd state dimensions, not on note text (lpe-0y3).

loop/README.md holds the one table of `loop` values. CODER.md and REVIEWER.md
must set only values from that table, and every value in the table must be set
somewhere in the prompts or the docs. The round number lives in the `round`
dimension, so neither prompt counts notes or routes on the last note marker.
"""

import re
from pathlib import Path

LOOP = Path(__file__).parents[1]
ROOT = LOOP.parent
CODER = (LOOP / "CODER.md").read_text()
REVIEWER = (LOOP / "REVIEWER.md").read_text()
LOOP_README = (LOOP / "README.md").read_text()
DOCS = {
    "loop/README.md": LOOP_README,
    "README.md": (ROOT / "README.md").read_text(),
    "loop/interactive.template.md": (LOOP / "interactive.template.md").read_text(),
    "skills/dev-env-setup/SKILL.md": (
        ROOT / "skills" / "dev-env-setup" / "SKILL.md"
    ).read_text(),
}

TABLE_HEADER = "| `loop` value | Set by | When | Assignee after | Status |"
SET_LOOP = re.compile(r"\bloop=([a-z][a-z-]*)")
SET_ROUND = re.compile(r"\bround=(\S+?)[\s`\"]")


def table_values() -> list[str]:
    lines = LOOP_README.splitlines()
    assert LOOP_README.count(TABLE_HEADER) == 1, "want exactly one state table"
    start = lines.index(TABLE_HEADER) + 2  # skip the header and the rule
    values = []
    for line in lines[start:]:
        if not line.startswith("|"):
            break
        (value,) = re.findall(r"^\| `([a-z-]+)` \|", line)
        values.append(value)
    return values


def test_the_table_has_every_state_of_the_design():
    assert table_values() == [
        "coding",
        "review",
        "rebased",
        "returned",
        "rebase",
        "merge-wait",
        "merge",
        "accept",
        "escalated",
        "parked",
        "blocked",
        "done",
    ]


def test_every_loop_value_in_the_prompts_is_in_the_table():
    used = set(SET_LOOP.findall(CODER)) | set(SET_LOOP.findall(REVIEWER))
    assert used, "found no loop= in the prompts"
    assert used <= set(table_values())


def test_every_table_value_is_set_somewhere():
    text = CODER + REVIEWER + "".join(DOCS.values())
    for value in table_values():
        assert f"loop={value}" in text, value


def test_the_coder_and_the_reviewer_each_set_their_own_values():
    coder = set(SET_LOOP.findall(CODER))
    reviewer = set(SET_LOOP.findall(REVIEWER))
    assert {"coding", "review", "rebased", "parked", "blocked"} <= coder
    assert {
        "returned",
        "rebase",
        "merge-wait",
        "merge",
        "accept",
        "escalated",
    } <= reviewer


def test_the_round_is_a_state_dimension():
    assert set(SET_ROUND.findall(REVIEWER)) == {"<n>"}
    assert set(SET_ROUND.findall(CODER)) == {"0"}
    assert "bd state <id> round" in REVIEWER
    for prompt in (CODER, REVIEWER):
        assert "bd state <id> loop" in prompt


def test_no_prompt_routes_on_note_text():
    for prompt in (CODER, REVIEWER):
        assert "last marker" not in prompt
        assert "last status marker" not in prompt.lower()
        assert "bottom-up" not in prompt
    assert "markers are already in the notes" not in REVIEWER
    assert "Gate passed, awaiting merge" not in CODER


def test_the_old_queue_labels_are_gone():
    old = re.compile(r"bd label (?:add|remove) <id> (?:merge|accept|escalated)\b")
    label_word = re.compile(r"label(?:led)? `(?:merge|accept|escalated)`")
    for name, text in {"CODER.md": CODER, "REVIEWER.md": REVIEWER, **DOCS}.items():
        assert not old.search(text), name
        assert not label_word.search(text), name


def test_the_human_queues_use_the_state_labels():
    for label in ("loop:merge", "loop:accept", "loop:escalated", "loop:parked"):
        assert label in LOOP_README, label
        assert label in DOCS["README.md"], label
    assert "bd set-state <id> loop=done" in DOCS["loop/interactive.template.md"]
