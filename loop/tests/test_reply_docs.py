"""The reviewer resumes an escalated bead from a decision, and the docs describe
the Telegram reply reader (lpe-kri)."""

import re
from pathlib import Path

from test_review_method import LOOP_README, REVIEWER, section

LOOP = Path(__file__).parents[1]
ROOT = LOOP.parent
README = (ROOT / "README.md").read_text()
SKILL = (ROOT / "skills/dev-env-setup/SKILL.md").read_text()


def phase0_routes() -> list[str]:
    """The route bullets of REVIEWER.md Phase 0, each with its sub-bullets."""
    phase0 = section(REVIEWER, "Phase 0 — Resume check (ALWAYS FIRST)")
    return re.split(r"\n  - (?=\*\*)", phase0)[1:]


def escalated_route() -> str:
    (route,) = [r for r in phase0_routes() if r.startswith("**`escalated`**")]
    return route


def test_the_escalated_route_comes_before_the_catch_all():
    heads = [route.split("→", 1)[0] for route in phase0_routes()]
    escalated = next(i for i, h in enumerate(heads) if "`escalated`" in h)
    catch_all = next(i for i, h in enumerate(heads) if "any other value" in h)
    assert escalated < catch_all


def test_the_escalated_route_keeps_the_round_and_writes_the_resumed_note():
    route = escalated_route()
    assert "Decision from $HUMAN" in route
    assert "Do not run `bd set-state <id> round`" in route
    assert (
        'bd note <id> "Review round <n> resumed after decision from $HUMAN:'
        ' <branch> @ $(git rev-parse --short <branch>)"' in route
    )
    assert "round=" not in route


def test_the_escalated_route_covers_every_case_of_the_design():
    route = escalated_route()
    # Code changes go to the coder, and the state stays escalated.
    assert (
        'bd note <id> "Routed to $CODER: the decision from $HUMAN needs code changes"'
        in route
    )
    assert 'bd update <id> --assignee="$CODER"' in route
    assert "Leave `loop=escalated`" in route
    # A changed branch gets a full round with the same number.
    assert "Review round <n> started" in route
    assert "Review round <n> restarted" in route
    assert "Phase 1 steps 2 to 6" in route
    # An unchanged branch gets the gate only, then Phase 2.
    assert "git checkout --detach <branch>" in route
    assert "Phase 1 step 6" in route
    assert "Do not run the default review method again" in route
    assert "non-blocking" in route
    # A failing gate or an uncovered blocking finding escalates again.
    assert "Fail in round 2" in route
    assert "same round" in route
    assert "Review summary:" in route


def test_the_state_tables_and_round_rules_agree():
    assert "after a decision from `$HUMAN`" in REVIEWER.split("### Phase 0")[0]
    assert "after a decision from the human" in LOOP_README
    assert (
        "When the reviewer resumes a bead from `escalated`, it keeps the round"
        in LOOP_README
    )
    assert "assign back to the coder or the reviewer" in README


def test_the_docs_describe_the_reply_reader():
    for text in (LOOP_README, SKILL):
        assert "uv run .loop/reply.py" in text
        assert "24 hours" in text
        assert "one reader" in text.lower()
        assert "It reads no replies." not in text
    assert "`reply.py`" in LOOP_README


# lpe-qqv: no note that the reviewer writes starts with the human's decision prefix.


def test_no_reviewer_note_starts_with_the_decision_prefix():
    notes = re.findall(r'bd note <id> "([^"]*)"', REVIEWER)
    assert notes
    assert not [n for n in notes if n.startswith("Decision from")]
    routed = "Routed to $CODER: the decision from $HUMAN needs code changes"
    assert REVIEWER.count(routed) == 2
    assert "needs code changes: routed to" not in REVIEWER + LOOP_README


def test_the_docs_say_replies_work_only_in_the_private_chat():
    replies = section(LOOP_README, "Telegram replies")
    assert "only in the private chat with the bot" in replies
    assert "from.id" in replies
    assert "Group chats" in replies
