"""The setup docs describe the agent queue panes and queue.sh (lpe-4h9.4)."""

import re
from pathlib import Path

ROOT = Path(__file__).parents[2]
SKILL = (ROOT / "skills/dev-env-setup/SKILL.md").read_text()
README = (ROOT / "loop/README.md").read_text()


def test_both_docs_show_the_queue_panes_above_the_loops():
    for document in (SKILL, README):
        diagrams = re.findall(r"```text\n(.*?)```", document, re.DOTALL)
        assert any(
            "coder queue" in diagram
            and "reviewer queue" in diagram
            and "coder loop" in diagram
            and "reviewer loop" in diagram
            and diagram.index("coder queue") < diagram.index("coder loop")
            and diagram.index("reviewer queue") < diagram.index("reviewer loop")
            for diagram in diagrams
        )


def test_the_readme_explains_each_queue_section():
    for section in ("In progress", "Ready next", "Waiting"):
        assert section in README


def test_the_docs_locate_queue_sh_in_the_skill_folder():
    path = "skills/dev-env-setup/scripts/queue.sh"
    assert path in SKILL
    assert path in README
    assert "not in `.loop/`" in README


def test_the_readme_shows_how_to_run_queue_sh_by_hand():
    assert (
        "/path/to/loop-engineering/skills/dev-env-setup/scripts/queue.sh --watch Ralph"
        in README
    )
