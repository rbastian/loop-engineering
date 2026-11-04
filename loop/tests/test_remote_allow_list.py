"""The allow list of remote actions lives once, in the project template (lpe-e52).

CODER.md and REVIEWER.md point to it. Neither prompt names a gh command that
the list does not allow its role.
"""

import re
from pathlib import Path

LOOP = Path(__file__).parents[1]
TEMPLATE = (LOOP / "project.template.md").read_text()
CODER = (LOOP / "CODER.md").read_text()
REVIEWER = (LOOP / "REVIEWER.md").read_text()

HEADING = "### Remote actions in `pr` mode"


def gh_commands(text: str) -> set[str]:
    return set(re.findall(r"gh pr [a-z]+", text))


def test_the_template_has_the_list_once_with_the_account_field():
    assert TEMPLATE.count(HEADING) == 1
    assert "GITHUB_ACCOUNT={{GITHUB_ACCOUNT}}" in TEMPLATE


def test_both_prompts_point_to_the_list():
    for prompt in (CODER, REVIEWER):
        assert HEADING.removeprefix("### ") in prompt


def test_the_coder_uses_only_allowed_gh_commands():
    assert gh_commands(CODER) <= {"gh pr view", "gh pr create"}


def test_the_reviewer_uses_only_allowed_gh_commands():
    # gh pr review appears only in the rule that forbids an approval.
    reviewer = REVIEWER.replace("not `gh pr review --approve`", "")
    assert gh_commands(reviewer) <= {"gh pr view", "gh pr comment"}
