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
ALL_TEXTS = {"CODER.md": CODER, "REVIEWER.md": REVIEWER, **DOCS}

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
    for name, text in ALL_TEXTS.items():
        assert not old.search(text), name
        assert not label_word.search(text), name


def test_the_human_queues_use_the_state_labels():
    for label in ("loop:merge", "loop:accept", "loop:escalated", "loop:parked"):
        assert label in LOOP_README, label
        assert label in DOCS["README.md"], label
    assert "bd set-state <id> loop=done" in DOCS["loop/interactive.template.md"]


def test_the_accept_queue_lists_closed_beads():
    # The reviewer closes the bead before it sets loop=accept, and bd list
    # hides closed beads, so the queue command must ask for them.
    seen = 0
    for name, text in ALL_TEXTS.items():
        for line in text.splitlines():
            if re.search(r"bd list[^`\n]*loop:accept", line):
                seen += 1
                assert re.search(r"--status[= ]closed|--all", line), (name, line)
    assert seen >= 2


def _routing_bullet(value: str) -> str:
    (bullet,) = [
        line
        for line in CODER.splitlines()
        if line.lstrip().startswith(f"- **`{value}`**")
    ]
    return bullet


def test_returned_and_rebase_stay_set_until_the_handoff():
    # A session that crashes mid-resume must still see why the bead came back.
    for value in ("returned", "rebase"):
        assert "loop=coding" not in _routing_bullet(value), value
    coding_rows = [
        line
        for text in (CODER, LOOP_README)
        for line in text.splitlines()
        if line.startswith(("| `coding`", "| `loop=coding`"))
    ]
    assert len(coding_rows) == 2
    for row in coding_rows:
        (resumes,) = re.findall(r"resumes? ([^.|]*)", row)
        assert "`returned`" not in resumes and "`rebase`" not in resumes, row


def test_code_fences_are_well_formed():
    # A closing fence with text after it is not a closing fence in CommonMark.
    for name, text in ALL_TEXTS.items():
        inside = False
        for number, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if not stripped.startswith("```"):
                continue
            info = stripped[3:]
            if inside:
                assert info == "", f"{name}:{number}: text after a closing fence"
            else:
                assert " " not in info, f"{name}:{number}: prose after a fence"
            inside = not inside
        assert not inside, f"{name}: unclosed fence"


def test_the_round_start_note_is_in_the_code_block():
    found = re.search(
        r"1\. Record the round in the state.*?```bash\n(.*?)```", REVIEWER, re.DOTALL
    )
    assert found, "no code block under Phase 1 step 1"
    fenced = found[1]
    assert 'bd note <id> "Review round <n> started:' in fenced
    assert "git checkout --detach <branch>" in fenced
