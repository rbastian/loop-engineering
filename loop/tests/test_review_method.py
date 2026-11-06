"""The reviewer always runs the default method for its engine (lpe-cd2).

The Project section can only add checks to the default method. It can never
replace or skip it. If the method cannot run, the reviewer parks the bead to
the human, and the human resumes it with the same round number.
"""

import re
from pathlib import Path

LOOP = Path(__file__).parents[1]
REVIEWER = (LOOP / "REVIEWER.md").read_text()
TEMPLATE = (LOOP / "project.template.md").read_text()
LOOP_README = (LOOP / "README.md").read_text()

# Wording that lets a project swap the default method out, or that makes the
# default a fallback for a project that names no method.
LOOPHOLES = re.compile(
    r"different method|gives no method|no method for it|"
    r"method that the Project section gives|otherwise use the default|"
    r"if the project section (?:gives|names|lists) no",
    re.IGNORECASE,
)


def section(text: str, heading: str) -> str:
    """The text under a markdown heading, up to the next heading of any level.

    A line inside a code fence is never a heading, so a Markdown body in a
    heredoc does not end the section.
    """
    lines, inside, found = [], False, False
    for line in text.splitlines(keepends=True):
        is_heading = not inside and re.match(r"#+ ", line)
        if line.strip().startswith("```"):
            inside = not inside
        if is_heading and found:
            break
        if found:
            lines.append(line)
        elif is_heading and line.rstrip("\n") == f"{line.split(' ')[0]} {heading}":
            found = True
    assert found, heading
    return "".join(lines)


def step(number: int) -> str:
    """One numbered step of REVIEWER.md Phase 1, with its indented lines."""
    phase1 = section(REVIEWER, "Phase 1 — Review round")
    found = re.search(
        rf"^{number}\. (.*?)(?=^\d+\. |^\S)", phase1, re.DOTALL | re.MULTILINE
    )
    assert found, number
    return found[1]


def fenced(text: str) -> str:
    return "".join(re.findall(r"```bash\n(.*?)```", text, re.DOTALL))


def test_no_text_lets_a_project_replace_the_default_method():
    for name, text in {"REVIEWER.md": REVIEWER, "template": TEMPLATE}.items():
        assert not LOOPHOLES.search(text), (name, LOOPHOLES.search(text)[0])


def test_the_loophole_pattern_catches_the_old_wording():
    old_reviewer = (
        "Review the change against `$BASE` with the review method that the Project "
        "section gives for this kind of change. If the Project section gives no "
        "method for it, use the method for your engine"
    )
    old_template = (
        "Use the default method for your engine. {{If some kinds of change need a "
        "different method, describe it here}}."
    )
    assert LOOPHOLES.search(old_reviewer)
    assert LOOPHOLES.search(old_template)


def test_step_5_always_runs_the_default_method():
    text = step(5)
    assert "always" in text
    assert 'codex exec review --base "$BASE"' in text
    assert "`/code-review`" in text and "**high**" in text
    assert "add" in text and "never replace" in text.lower()
    assert "Review not run" in text


def test_the_template_has_the_new_review_method_text():
    body = section(TEMPLATE, "Review method (for the reviewer)")
    assert (
        "The reviewer always runs the default method for its engine. List here only "
        "the checks that add to it, chosen by the files that the branch changes."
    ) in body
    assert re.search(r"\{\{[^}]+\}\}", body), "no placeholder for the extra checks"


def test_the_readme_says_the_default_method_always_runs():
    assert "default method always runs" in LOOP_README
    assert "only adds checks" in LOOP_README


def test_the_review_summary_and_pr_comment_carry_the_finding_count():
    count = "<method>: <k> findings (<b> blocking)"
    summaries = [
        line
        for line in REVIEWER.splitlines()
        if 'bd note <id> "Review summary:' in line
    ]
    assert len(summaries) == 2, "pr mode and local mode"
    for line in summaries:
        assert count in line, line
    passed = REVIEWER.split("## Review by <reviewer>: passed (round <n>)")[1]
    assert count in passed.split("###")[0]


def test_review_not_run_parks_the_bead_to_the_human():
    text = section(REVIEWER, "Review not run → park to the human")
    commands = fenced(text)
    assert 'bd note <id> "Review not run: <error>"' in commands
    assert "bd set-state <id> loop=parked" in commands
    assert 'bd update <id> --assignee="$HUMAN"' in commands
    assert "round=" not in commands, "the round stays as it is"
    assert "loop=parked" in REVIEWER.split("### Phase 0")[0], "not in the state table"


def test_the_self_check_lists_the_park():
    text = section(REVIEWER, "Self-check: Am I done?")
    assert "**Parked:**" in text
    assert "Review not run" in text
    assert "loop=parked" in text


def test_phase_0_restarts_a_parked_round_with_the_same_number():
    phase0 = section(REVIEWER, "Phase 0 — Resume check (ALWAYS FIRST)")
    (bullet,) = [
        line
        for line in phase0.splitlines()
        if line.lstrip().startswith("- **`parked`**")
    ]
    assert 'bd note <id> "Review round <n> restarted:' in bullet
    assert "steps 2 to 6" in bullet
    assert "loop=review" in bullet and "Never" in bullet
    assert "bd set-state <id> round" in bullet and "do not run" in bullet.lower()
    # The parked bullet must come before the catch-all that starts a new round.
    assert phase0.index("- **`parked`**") < phase0.index("- **`review`, no value")
