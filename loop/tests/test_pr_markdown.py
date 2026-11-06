"""PR descriptions and PR comments are structured Markdown (lpe-415).

The coder and the reviewer pass each PR body with --body-file - and a quoted
heredoc, so that backticks, $ and quotes reach GitHub unchanged. The bead
notes stay plain text with the same markers.
"""

import re
import textwrap

from test_review_method import LOOP, LOOP_README, REVIEWER, fenced, section

CODER = (LOOP / "CODER.md").read_text()
PROMPTS = {"CODER.md": CODER, "REVIEWER.md": REVIEWER}
HEREDOC_START = "--body-file - <<'EOF'"

PASS = "Pass in `pr` mode → ready for the human to merge"
FAIL_1 = "Fail in round 1 → back to the coder"
ESCALATE = "Fail in round 2 → escalate to the human"

EVIDENCE_TABLE = "| # | Outcome | Evidence |"


def heredocs(commands: str) -> list[str]:
    """The bodies of the quoted heredocs in a shell text, dedented."""
    found = re.findall(r"<<'EOF'\n(.*?)^[ \t]*EOF$", commands, re.DOTALL | re.MULTILINE)
    return [textwrap.dedent(body) for body in found]


def gh_command_lines(text: str, verb: str) -> list[str]:
    """Each `gh pr <verb>` command in the fenced blocks, with its continuations."""
    joined = fenced(text).replace("\\\n", " ")
    return [line for line in joined.splitlines() if f"gh pr {verb}" in line]


def coder_pr_body() -> str:
    step13 = CODER.split("13. **In `pr` mode")[1].split("\n14. ")[0]
    commands = fenced(step13)
    assert "gh pr create" in commands
    (body,) = heredocs(commands[commands.index("gh pr create") :])
    return body


def comment_body(heading: str) -> str:
    commands = fenced(section(REVIEWER, heading))
    comment = commands[commands.index("gh pr comment") :]
    (body,) = heredocs(comment)
    return body


def in_order(text: str, parts: list[str]) -> bool:
    positions = [text.find(part) for part in parts]
    return -1 not in positions and positions == sorted(positions)


def test_the_coder_opens_the_pr_with_a_body_file_heredoc():
    (command,) = gh_command_lines(CODER, "create")
    assert HEREDOC_START in command
    assert "--body " not in command.replace(HEREDOC_START, "")


def test_the_pr_description_has_the_bead_line_and_three_sections():
    body = coder_pr_body()
    assert body.startswith("Bead: <bead-id>\n")
    assert in_order(body, ["## Summary", "## Changes", "## Acceptance criteria"])
    assert "- [x] <k>. " in body
    assert "- [ ] " in body, "a criterion the coder could not check"
    assert "$(" not in body and "${" not in body, "no shell expansion in the body"


def test_the_coder_writes_the_description_once():
    step13 = CODER.split("13. **In `pr` mode")[1].split("\n14. ")[0]
    assert "Write the body once" in step13
    assert "A later round does not edit it" in step13


def test_every_pr_comment_uses_a_body_file_heredoc():
    commands = gh_command_lines(REVIEWER, "comment")
    assert len(commands) == 3, "pass, round 1 fail and escalation"
    for command in commands:
        assert command.rstrip().endswith(HEREDOC_START), command


def test_no_prompt_passes_a_pr_body_inline():
    for name, text in PROMPTS.items():
        assert '--body "' not in text, name
        assert "--body '" not in text, name


def test_the_comment_heading_names_the_outcome_and_round():
    expected = {
        PASS: "## Review by <reviewer>: passed (round <n>)",
        FAIL_1: "## Review by <reviewer>: changes needed (round 1)",
        ESCALATE: "## Review by <reviewer>: escalated to <human> (round <n>)",
    }
    for heading, title in expected.items():
        assert comment_body(heading).startswith(title + "\n"), heading


def test_the_comment_block_gives_the_method_counts_and_the_gate():
    for heading in (PASS, FAIL_1, ESCALATE):
        block = comment_body(heading).split("###")[0]
        assert "<method>: <k> findings (<b> blocking)" in block, heading
        assert "Gate:" in block and "`<sha>`" in block and "<t> tests" in block


def test_the_comment_sections_are_in_order():
    sections = [
        "### Checked",
        "### Non-blocking findings",
        "### Acceptance evidence",
    ]
    assert in_order(comment_body(PASS), sections)
    assert "### Blocking findings" not in comment_body(PASS)
    for heading in (FAIL_1, ESCALATE):
        body = comment_body(heading)
        assert in_order(body, ["### Blocking findings", *sections]), heading
        blocking = body.split("### Blocking findings")[1].split("###")[0]
        assert "\n1. " in blocking, "a numbered list"


def test_the_evidence_is_a_table():
    for heading in (PASS, FAIL_1, ESCALATE):
        evidence = comment_body(heading).split("### Acceptance evidence")[1]
        assert EVIDENCE_TABLE in evidence, heading
        rows = [line for line in evidence.splitlines() if line.startswith("| 1 |")]
        assert rows, heading


def test_the_bodies_hold_no_bead_notes():
    for body in [coder_pr_body()] + [comment_body(h) for h in (PASS, FAIL_1, ESCALATE)]:
        assert "bd " not in body


# The note markers that run.sh, the watchers and the routing read, word for word.
CODER_MARKERS = [
    'bd note <id> "Branch created: feat/<name>"',
    'bd note <id> "Checkpoint committed: $(git rev-parse --short HEAD)"',
    'bd note <id> "PR opened: #<number> <url>"',
    'bd note <id> "Push failed: <error>"',
    'bd note <id> "Handed to $REVIEWER for review: <branch> @ $(git rev-parse --short HEAD)"',
]
REVIEWER_MARKERS = [
    'bd note <id> "Acceptance evidence: <one entry per criterion, as in Phase 1 step 4>"',
    'bd note <id> "Review summary: <method>: <k> findings (<b> blocking).',
    'bd note <id> "Review passed, PR #<number> awaiting merge approval"',
    'bd note <id> "Review round 1 failed: <finding>"',
    'bd note <id> "Returned to $CODER after review round 1"',
    'bd note <id> "Review round <n> failed: <finding>"',
    'bd note <id> "Escalated to $HUMAN after review round <n>: ',
]


def test_the_note_markers_are_unchanged():
    for marker in CODER_MARKERS:
        assert marker in CODER, marker
    for marker in REVIEWER_MARKERS:
        assert marker in REVIEWER, marker


def test_the_readme_shows_one_example_of_each_layout():
    examples = re.findall(r"```markdown\n(.*?)```", LOOP_README, re.DOTALL)
    descriptions = [e for e in examples if e.startswith("Bead: ")]
    comments = [e for e in examples if e.startswith("## Review by ")]
    assert len(descriptions) == 1 and len(comments) == 1
    assert in_order(
        descriptions[0], ["## Summary", "## Changes", "## Acceptance criteria"]
    )
    assert EVIDENCE_TABLE in comments[0]
    assert "--body-file -" in LOOP_README


def test_the_readme_names_the_later_evidence_parts():
    assert "lpe-6er.1" in LOOP_README
