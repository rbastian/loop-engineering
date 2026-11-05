"""The reviewer writes the evidence for each acceptance criterion (lpe-jv4).

The reviewer checks each criterion itself, labels it verified, trusted or not
verified, and writes one 'Acceptance evidence:' note per review round. In pr
mode the PR comment carries the same list.
"""

from pathlib import Path

from test_review_method import fenced, section, step

LOOP = Path(__file__).parents[1]
REVIEWER = (LOOP / "REVIEWER.md").read_text()
LOOP_README = (LOOP / "README.md").read_text()

EVIDENCE_NOTE = 'bd note <id> "Acceptance evidence:'
SUMMARY_NOTE = 'bd note <id> "Review summary:'

PASS_PATHS = [
    "Pass in `pr` mode → ready for the human to merge",
    "Pass in `local` mode → merge",
]
FAIL_PATHS = [
    "Fail in round 1 → back to the coder",
    "Fail in round 2 → escalate to the human",
]


def test_step_4_verifies_each_criterion_itself():
    text = step(4)
    assert "acceptance criteria one by one" in text
    assert "coder's note alone is not evidence" in text


def test_step_4_defines_the_three_outcomes():
    text = step(4)
    for outcome in ("**verified**", "**trusted**", "**not verified**"):
        assert outcome in text, outcome
    assert "Review round <n> failed: acceptance <k> not verified: <why>" in text
    assert "blocking" in text


def test_an_unverified_criterion_is_blocking():
    blocking = REVIEWER.split("**Blocking**")[1].split("**Everything else")[0]
    assert "acceptance criterion that is not verified" in blocking


def test_every_pass_and_fail_path_writes_the_evidence_note():
    for heading in PASS_PATHS + FAIL_PATHS:
        commands = fenced(section(REVIEWER, heading))
        assert EVIDENCE_NOTE in commands, heading
        if SUMMARY_NOTE in commands:
            assert commands.index(EVIDENCE_NOTE) < commands.index(SUMMARY_NOTE), heading


def test_every_pr_comment_template_carries_the_list():
    for heading in ["Pass in `pr` mode → ready for the human to merge", *FAIL_PATHS]:
        commands = fenced(section(REVIEWER, heading))
        comment = commands[commands.index("gh pr comment") :]
        assert "Acceptance evidence:" in comment, heading
        assert "<k> verified by <how>" in comment, heading


def test_a_merge_wait_resume_does_not_write_a_second_evidence_note():
    phase0 = section(REVIEWER, "Phase 0 — Resume check (ALWAYS FIRST)")
    (bullet,) = [
        line
        for line in phase0.splitlines()
        if line.lstrip().startswith("- **`merge-wait`**")
    ]
    assert "Acceptance evidence:" in bullet


def test_the_self_check_lists_the_evidence_note_for_every_pass_and_fail():
    text = section(REVIEWER, "Self-check: Am I done?")
    for state in (
        "**Ready to merge (`pr` mode):**",
        "**Merged (`local` mode):**",
        "**Awaiting merge (`local` mode):**",
        "**Bounced:**",
        "**Escalated:**",
    ):
        (bullet,) = [line for line in text.splitlines() if state in line]
        assert "`Acceptance evidence:`" in bullet, state


def test_the_readme_describes_the_evidence_note():
    assert "Acceptance evidence" in LOOP_README
