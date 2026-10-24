"""ralph/watch.py: the header must name the right agent, bead and model.

Alice's watcher showed `Ralph · no bead yet · model ?` through her whole review
of agents-ype on 2026-10-02. Every one of the three values was wrong, for three
unrelated reasons, so this file is organised by cause:

* the agent was a string literal, and one watcher now serves two loops;
* the bead was read only from a claim or a commit tag, and Alice neither claims
  nor commits — she names her bead in a `Review round <n> started` note;
* following seeks to the end of the log, so the init event carrying the model
  and the claim carrying the bead were already far above the live edge.

watch.py is a script rather than part of the package, so it is loaded by path.
The session lives in module globals, which is why every test here gets a fresh
one.
"""

import importlib.util
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location("ralph_watch", ROOT / "watch.py")
watch = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(watch)

STARTED = "2026-10-02T16:43:18.793Z"
# The next iteration's log, for the `current.jsonl` rollover.
RESTARTED = "2026-10-02T18:15:00.000Z"
MODEL = "claude-opus-5"
NEXT_MODEL = "claude-opus-5-5"


def local(stamp: str, fmt: str = "%H:%M:%S") -> str:
    """What the watcher says about a timestamp: it prints local time.

    The header prints seconds and the footer's finish time does not, so the
    format is the caller's.
    """
    return datetime.fromisoformat(stamp).astimezone().strftime(fmt)


BEGAN = local(STARTED)


def ended(at: str = STARTED, after: int = 7) -> str:
    """The HH:MM a `session_log` started at `at` reports as its finish time.

    The result event carries no clock of its own, so the finish falls back to
    the log's last timestamped event, `after` minutes in: seven for a plain
    `session_log`, more where the caller appended later events.
    """
    moment = datetime.fromisoformat(at) + timedelta(minutes=after)
    return local(moment.isoformat(), "%H:%M")


# The commands that may name a bead, quoted from real sessions. The claim is
# Ralph's first write of a bead, the tag his last, the note Alice's only one.
CLAIM = "bd update agents-ype --claim && git checkout -b feat/x-ype main"
COMMIT = 'git commit -m "feat: name the agent [agents-ype]"'
REVIEW = (
    'bd note agents-ype "Review round 1 started: feat/x-ype'
    ' @ $(git rev-parse --short HEAD)" && git checkout --detach feat/x-ype'
)
PLAIN_NOTE = 'bd note agents-ype "Non-blocking review findings: see agents-3hd"'
# The commit that made the header read `Ralph · mid-log` (agents-8vr): an
# ordinary hyphenated word stands between the subject and the tag, and it is
# bead-shaped.
HYPHENATED_COMMIT = (
    'git commit -m "feat: a result event mid-log does not finish the session'
    ' [agents-716]"'
)


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    """Cut every tie this module has to its environment.

    watch.py keeps the session, the agent and the repeat-collapsing buffer in
    module globals — the session because `follow` rebinds it per log, the agent
    because `main` resolves it once — so each test needs its own. LOG_DIR is
    the one global read from the environment, and it is read at import, so it
    is pinned here rather than deleted from os.environ: without it a suite run
    from Alice's shell, which exports RALPH_LOG_DIR, renames the agent under
    every test that goes through `main`. `bd show` is stubbed rather than
    `lookup_title` patched out, so the header tests still run the real method
    without the suite depending on the issue database. POLL_SECONDS is the
    0.4 s `follow` would otherwise sleep between polls.
    """
    monkeypatch.setattr(watch, "SESSION", watch.Session())
    monkeypatch.setattr(watch, "AGENT", "Ralph")
    monkeypatch.setattr(watch, "LOG_DIR", Path("/tmp/ralph-sessions"))
    monkeypatch.setattr(watch, "_last", [None, 0, ""])
    monkeypatch.setattr(watch, "COSTS", {})
    monkeypatch.setattr(watch, "CODEX_SESSIONS", set())
    monkeypatch.setattr(watch, "REPLAYING", False)
    monkeypatch.setattr(watch, "POLL_SECONDS", 0)
    monkeypatch.setattr(
        watch.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout="")
    )


def init_line(model: str = MODEL) -> str:
    """The session-start event. It carries the model and, as the live logs
    confirm, no timestamp — the start time comes from the first assistant
    event instead."""
    return json.dumps({"type": "system", "subtype": "init", "model": model})


# The 2026-10-05 input: an edit of this file whose text quotes a commit.
HEREDOC_TEST_EDIT = """python - <<'EOF'
case = ('git commit -m "wip: x [agents-bqz.3]"', "agents-bqz.3")
EOF"""


def bash_line(command: str, at: str = STARTED) -> str:
    return json.dumps(
        {
            "type": "assistant",
            "timestamp": at,
            "message": {
                "usage": {"output_tokens": 10, "input_tokens": 2},
                "content": [
                    {"type": "tool_use", "name": "Bash", "input": {"command": command}}
                ],
            },
        }
    )


def session_log(
    path: Path,
    *results: str,
    model: str = MODEL,
    at: str = STARTED,
    bead_command: str = CLAIM,
) -> Path:
    """A log whose model, bead and start time all sit above the live edge.

    Three tool calls spread over seven minutes, so `elapsed` has a real span
    to report, then whatever closing result events the caller asked for. The
    middle call is `bead_command`, the one that names the bead: a claim by
    default, since that is how Ralph opens one.
    """
    began = datetime.fromisoformat(at)
    path.write_text(
        "\n".join(
            [
                init_line(model),
                bash_line("bd ready --assignee=Ralph", at=at),
                bash_line(bead_command, at=(began + timedelta(minutes=2)).isoformat()),
                bash_line(
                    "uv run pytest -q", at=(began + timedelta(minutes=7)).isoformat()
                ),
                *results,
            ]
        )
        + "\n"
    )
    return path


class Stop(Exception):
    """How a test gets out of `follow`, which loops forever by design."""


def paths(*targets: Path):
    """A `path_of` for `follow` that gives it each target in turn, then `Stop`.

    `follow` asks twice per log — once to choose it, once to stay on it for a
    pass of the tail loop — and leaves that loop as soon as the answer changes,
    so two targets drive a `current.jsonl` rollover and one is a plain tail.
    The doubling lives here so a caller counts logs, not polls.
    """
    remaining = [target for target in targets for _ in range(2)]

    def path_of():
        if not remaining:
            raise Stop
        return remaining.pop(0)

    return path_of


# --- the agent name ---------------------------------------------------------


@pytest.mark.parametrize(
    "directory,expected",
    [
        ("/tmp/ralph-sessions", "Ralph"),
        ("/tmp/alice-sessions", "Alice"),
        ("/tmp/sessions", "Ralph"),
        ("/var/log", "Ralph"),
        ("/tmp/-sessions", "Ralph"),
    ],
)
def test_agent_name_comes_from_the_log_directory(directory, expected):
    """run.sh gives each loop its own RALPH_LOG_DIR so their `current.jsonl`
    symlinks cannot collide, which makes the directory the one thing that
    already tells the two loops apart."""
    assert watch.agent_name(Path(directory)) == expected


@pytest.mark.parametrize("extra,expected", [([], "Alice"), (["--agent", "Bob"], "Bob")])
def test_the_header_names_the_agent(tmp_path, capsys, monkeypatch, extra, expected):
    """End to end through main: the directory names the agent, --agent wins."""
    log = tmp_path / "20261002-114315.jsonl"
    log.write_text(init_line() + "\n" + bash_line(CLAIM) + "\n")
    monkeypatch.setattr(watch, "LOG_DIR", Path("/tmp/alice-sessions"))

    assert watch.main(["--file", str(log), "--replay", *extra]) == 0
    assert f" {expected} · agents-ype" in capsys.readouterr().out


# --- the bead ---------------------------------------------------------------


@pytest.mark.parametrize(
    "command,expected",
    [
        (CLAIM, "agents-ype"),
        (COMMIT, "agents-ype"),
        (REVIEW, "agents-ype"),
        # The tag is the bead, not the first bead-shaped word in the subject.
        (HYPHENATED_COMMIT, "agents-716"),
        ('git commit -m "wip: set-up the add-on [agents-bqz.3]"', "agents-bqz.3"),
        # The claim outranks a tag later in the same command (agents-8vr).
        (CLAIM + ' && bd note agents-ype "Related [agents-bqz.3]"', "agents-ype"),
        # Only a git commit that starts a command carries the tag (agents-ejc).
        ("python - <<'EOF'\nassert x == '[agents-bqz.3]'\nEOF", None),
        (HEREDOC_TEST_EDIT, None),
        ('git add a.py && git commit -q -m "fix: x [agents-bbb]"', "agents-bbb"),
        ('bd note agents-ype "Finding: see [agents-bqz.3]"', None),
        (
            'echo "see [agents-aaa]" && git commit -m "fix: x [agents-bbb]"',
            "agents-bbb",
        ),
        # Brackets that hold no tag name no bead: the subject is prose.
        ('git commit -m "wip: pre-fix the set-up [no tag here]"', None),
        # A note without the marker may mention any bead at all, and `bd show`
        # is run on beads the agent is only reading.
        (PLAIN_NOTE, None),
        ("bd show agents-ype", None),
        ("bd ready --assignee=Ralph", None),
    ],
)
def test_only_an_unambiguous_command_names_the_bead(command, expected):
    watch.track(json.loads(bash_line(command)), "assistant")
    assert watch.SESSION.bead == expected


def test_a_test_edit_that_quotes_a_commit_does_not_name_the_bead(tmp_path, capsys):
    """The 2026-10-05 log: a resumed session whose first bracketed command was
    a heredoc edit of this file, with a quoted commit in it. The header named
    that fixture's bead for the whole session (agents-ejc)."""
    log = session_log(
        tmp_path / "20261005-175038.jsonl", bead_command=HEREDOC_TEST_EDIT
    )
    with open(log, "a", encoding="utf-8") as fp:
        fp.write(bash_line('git add -A && git commit -m "wip: x [agents-716]"') + "\n")

    assert watch.main(["--file", str(log), "--replay"]) == 0
    assert " Ralph · agents-716" in capsys.readouterr().out


def test_the_first_bead_in_one_log_wins():
    """Within a single log the first bead wins: a session goes on to mention
    other beads after naming its own — Ralph files one, Alice quotes one in a
    finding — and the header must not follow them. The scope is the log, not
    the watcher: a new log gets a new session."""
    watch.track(json.loads(bash_line(CLAIM)), "assistant")
    watch.track(
        json.loads(bash_line('git commit -m "feat: x [agents-zzz]"')), "assistant"
    )
    assert watch.SESSION.bead == "agents-ype"


def test_a_resumed_session_names_the_bead_from_its_commit_tag(tmp_path, capsys):
    """A session that resumes a bead never runs `--claim`, so the commit tag is
    the first command naming the bead at all. The header read `mid-log` through
    the whole of the 2026-10-04 restart because the subject in front of that tag
    held a bead-shaped word (agents-8vr)."""
    log = session_log(
        tmp_path / "20261002-170939.jsonl", bead_command=HYPHENATED_COMMIT
    )

    assert watch.main(["--file", str(log), "--replay"]) == 0
    assert " Ralph \u00b7 agents-716" in capsys.readouterr().out


# --- attaching partway through a session ------------------------------------


def test_attaching_mid_session_catches_up_without_printing(tmp_path, capsys):
    log = session_log(tmp_path / "20261002-114315.jsonl")

    with open(log, encoding="utf-8") as fp:
        assert watch.catch_up(fp) == ""

    session = watch.SESSION
    assert session.model == MODEL
    assert session.bead == "agents-ype"
    assert session.first == datetime.fromisoformat(STARTED)
    assert (session.turns, session.tools) == (3, 3)
    assert capsys.readouterr().out == ""


def test_the_header_after_a_mid_session_attach(tmp_path, capsys):
    """The three values Alice's watcher got wrong, read back off the header."""
    log = session_log(tmp_path / "20261002-114315.jsonl")
    with open(log, encoding="utf-8") as fp:
        watch.catch_up(fp)
    watch.SESSION.name = log.name

    watch.SESSION.header()

    out = capsys.readouterr().out
    assert " Ralph · agents-ype" in out
    assert f"started {BEGAN}" in out, "the header still times the attach"
    assert f"model {MODEL}" in out


def test_follow_catches_up_before_it_tails(tmp_path, capsys):
    """The header is painted from the catch-up, not from the next tool call:
    a quiet session would otherwise keep reporting the attach."""
    log = session_log(tmp_path / "20261002-114315.jsonl")

    with pytest.raises(Stop):
        watch.follow(paths(log))

    out = capsys.readouterr().out
    assert f"── watching {log.name} ──" in out
    assert f"session {log.name} · started {BEGAN} · model {MODEL}" in out
    assert "find work" not in out, "the catch-up printed the lines it only counted"


def test_from_start_still_prints_the_whole_log(tmp_path, capsys):
    """Catching up must not swallow the body for the reader who asked for it."""
    log = session_log(tmp_path / "20261002-114315.jsonl")

    with pytest.raises(Stop):
        watch.follow(paths(log), from_start=True)

    assert "find work" in capsys.readouterr().out


def test_a_new_log_replaces_the_header(tmp_path, capsys):
    """run.sh repoints `current.jsonl` every iteration, and the watcher that
    Robert leaves running must move with it. First-bead-wins is scoped to one
    log; carrying it across the hand-over pinned the header to the first bead
    the watcher ever saw, for every bead after it."""
    first = session_log(tmp_path / "20261002-114315.jsonl")
    second = tmp_path / "20261002-131500.jsonl"
    second.write_text(
        init_line(NEXT_MODEL)
        + "\n"
        + bash_line("bd update agents-zzz --claim", at=RESTARTED)
        + "\n"
    )

    with pytest.raises(Stop):
        watch.follow(paths(first, second))

    out = capsys.readouterr().out
    assert " Ralph · agents-zzz" in out, "the header kept the first log's bead"
    assert (
        f"session {second.name} · started {local(RESTARTED)} · model {NEXT_MODEL}"
        in out
    ), "the header still describes the session before this one"
    # The one thing the header does not print, so it needs its own assertion.
    session = watch.SESSION
    assert (session.turns, session.tools) == (1, 1), "totals outlived their log"


def test_catch_up_hands_back_an_unfinished_trailing_line(tmp_path):
    """The file is appended to while this reads it, so the partial last line is
    buffered for `drain`. Seeking to the end instead would skip whatever
    arrived during the catch-up."""
    log = tmp_path / "20261002-114315.jsonl"
    log.write_text(init_line() + "\n" + '{"type":"assis')

    with open(log, encoding="utf-8") as fp:
        tail = watch.catch_up(fp)

    assert tail == '{"type":"assis'
    assert watch.SESSION.model == MODEL


def test_a_malformed_line_in_the_catch_up_does_not_raise(tmp_path):
    """The catch-up needs feed's guard: the watcher runs as a pipeline stage in
    run.sh, where an exception breaks the pipe and kills the session it is only
    supposed to be watching. Not every bad line is a JSON error — a bare `[]`
    parses and then has no `.get`."""
    log = tmp_path / "20261002-114315.jsonl"
    log.write_text(
        "\n".join(["{not json at all}", "[]", "null", init_line(), bash_line(CLAIM)])
        + "\n"
    )

    with open(log, encoding="utf-8") as fp:
        watch.catch_up(fp)

    assert watch.SESSION.model == MODEL
    assert watch.SESSION.bead == "agents-ype"


def test_the_review_marker_matches_the_one_alice_is_told_to_write():
    """REVIEW_RE quotes prose out of ralph/ALICE.md, and nothing else binds the
    two: reword the marker there and the header silently loses Alice's bead.
    So build the command out of the document rather than out of a literal."""
    alice = (ROOT / "ALICE.md").read_text()
    (quoted,) = [
        found[1]
        for line in alice.splitlines()
        if (
            found := re.search(
                r'`(bd note <id> "Review round <n> started:[^`]*)`', line
            )
        )
    ]
    command = (
        quoted.replace("<id>", "agents-ype")
        .replace("<n>", "1")
        .replace("<branch>", "f")
    )
    assert watch.bead_in(command) == "agents-ype"


# --- the title lookup, now that it runs on attach ---------------------------


def test_a_failing_bd_show_cannot_take_the_watcher_down(tmp_path, monkeypatch, capsys):
    """`announce` calls lookup_title from outside feed's never-raise guard. An
    absent `bd` would otherwise crash the watcher on attach, before it printed
    anything — and the watcher must never take down the session it watches."""
    log = session_log(tmp_path / "20261002-114315.jsonl")
    calls = []

    def exploding_run(*args, **kwargs):
        calls.append(kwargs)
        raise FileNotFoundError("bd")

    monkeypatch.setattr(watch.subprocess, "run", exploding_run)

    with pytest.raises(Stop):
        watch.follow(paths(log))

    assert calls[0]["timeout"], "no timeout: a stuck bd would hang the attach"
    assert " Ralph · agents-ype" in capsys.readouterr().out, "header lost the bead"


def test_the_title_is_looked_up_once_per_bead(monkeypatch):
    """Once whether or not it worked. A failed lookup that retried would shell
    out on every repaint, and the pinned header repaints on every line."""
    calls = []

    def empty_run(*args, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(watch.subprocess, "run", empty_run)
    watch.SESSION.bead = "agents-ype"

    watch.SESSION.lookup_title()
    watch.SESSION.lookup_title()

    assert len(calls) == 1


# --- what a session cost, and that it has ended -----------------------------
#
# Every session log ends in a `result` event carrying total_cost_usd and a
# modelUsage block. Two things come off it: the cost, which no other event
# reports correctly, and the fact that the session is over, which nothing
# reported at all — Alice's watcher still said "working" two days after her
# October 2 review ended.


def result_line(cost=5.38, output=58914, at=None):
    """A session's closing event, shaped like the real ones.

    The live logs carry no `timestamp` on this event, so `at` defaults to
    absent and the finish time falls back to the session's last event.
    """
    event = {
        "type": "result",
        "subtype": "success",
        "num_turns": 3,
    }
    if cost is not None:
        event["total_cost_usd"] = cost
    event["modelUsage"] = {
        MODEL: {
            "inputTokens": 146,
            "outputTokens": output,
            "cacheReadInputTokens": 4001019,
            "cacheCreationInputTokens": 249568,
            "costUSD": cost,
        }
    }
    if at:
        event["timestamp"] = at
    return json.dumps(event)


# What a mid-session result really looks like, quoted from
# /tmp/ralph-sessions/20261002-113222.jsonl: a background task posts a result
# carrying a running total, then the agent works on for another hundred lines
# before the session closes for real. Append it to a `session_log` to put a
# result in the middle of one.
RESUMED = (
    result_line(cost=1.20, output=100),
    bash_line(
        "uv run pytest -q",
        at=(datetime.fromisoformat(STARTED) + timedelta(minutes=12)).isoformat(),
    ),
)


def feed_log(path: Path) -> None:
    """Read a whole log through the catch-up, which is what an attaching
    watcher does — and the only path that reaches an already-ended session."""
    watch.SESSION.name = path.name
    with open(path, encoding="utf-8") as fp:
        watch.catch_up(fp)


def test_the_footer_shows_the_session_cost_and_the_watcher_total(tmp_path):
    feed_log(session_log(tmp_path / "20261002-114315.jsonl", result_line()))

    totals = watch.SESSION.totals()
    assert "session $5.38 est." in totals
    assert "watcher $5.38 est. over 1 sessions" in totals


def test_before_any_result_the_cost_is_promised_not_shown(tmp_path):
    """A live session has no exact figure yet, and watch.py will not estimate
    one: the assistant events undercount output by roughly a quarter of the
    cost, and a price table here would drift against the API's."""
    feed_log(session_log(tmp_path / "20261002-114315.jsonl"))

    totals = watch.SESSION.totals()
    assert "session cost at end" in totals
    assert "watcher $0.00 est. over 0 sessions" in totals


def test_a_repeated_result_event_counts_once(tmp_path):
    """Background tasks re-report a running total, so one log can hold several
    result events. The last one replaces the session's cost; adding them would
    bill the watcher several times for one session."""
    feed_log(
        session_log(
            tmp_path / "20261002-114315.jsonl",
            result_line(cost=2.00),
            result_line(cost=5.38),
        )
    )

    totals = watch.SESSION.totals()
    assert "session $5.38 est." in totals
    assert "watcher $5.38 est. over 1 sessions" in totals


def test_two_logs_in_sequence_add_up(tmp_path):
    """The watcher total spans the rollover; the session figure does not.
    Session is recreated per log, so the total cannot live on it."""
    first = session_log(tmp_path / "20261002-114315.jsonl", result_line(cost=2.00))
    second = session_log(
        tmp_path / "20261002-131500.jsonl",
        result_line(cost=5.38),
        model=NEXT_MODEL,
        at=RESTARTED,
    )

    with pytest.raises(Stop):
        watch.follow(paths(first, second))

    totals = watch.SESSION.totals()
    assert "session $5.38 est." in totals, "the session figure outlived its log"
    assert "watcher $7.38 est. over 2 sessions" in totals


def test_the_output_counter_comes_from_the_result_event(tmp_path):
    """The assistant events report output tokens that are hundreds against the
    result's tens of thousands, so the footer's `k out` was wrong all along.
    Until the result arrives the assistant-event sum is all there is."""
    log = session_log(tmp_path / "20261002-114315.jsonl", result_line(output=58914))

    feed_log(session_log(tmp_path / "20261002-110000.jsonl"))
    assert watch.SESSION.output == 30, "three assistant events at 10 output each"

    watch.SESSION = watch.Session(log.name)
    feed_log(log)
    assert watch.SESSION.output == 58914


def test_a_result_without_a_cost_adds_nothing(tmp_path):
    """An older CLI reports no total_cost_usd. The watcher must not raise, and
    must not count the session at a cost it does not know."""
    feed_log(session_log(tmp_path / "20261002-114315.jsonl", result_line(cost=None)))

    assert "watcher $0.00 est. over 0 sessions" in watch.SESSION.totals()


# --- a finished session says so ---------------------------------------------


def test_the_phase_line_says_working_until_the_result_arrives(tmp_path):
    """The phase where the session has reached one, `working` where it has
    not — a watcher that attached mid-session has counted the log without
    classifying any of it."""
    feed_log(session_log(tmp_path / "20261002-114315.jsonl"))
    assert watch.SESSION.phase_line() == "working"

    watch.SESSION.phase = "PHASE 2 run tests"
    assert watch.SESSION.phase_line() == "PHASE 2 run tests"


def test_the_phase_line_says_finished_after_the_result(tmp_path):
    """Alice's watcher read `working` for two days after her session ended,
    because nothing in the stream was marking a session as over."""
    feed_log(session_log(tmp_path / "20261002-114315.jsonl", result_line()))

    line = watch.SESSION.phase_line()
    assert line.startswith(f"finished {ended()}")
    assert line.endswith("ago · waiting for the next session")


@pytest.mark.parametrize(
    "seconds,expected",
    [
        (0, "0m"),
        (59, "0m"),
        (90, "1m"),
        (59 * 60, "59m"),
        (60 * 60, "1h 0m"),
        (64 * 60, "1h 4m"),
        (23 * 3600 + 59 * 60, "23h 59m"),
        (24 * 3600, "1d 0h"),
        (2 * 86400 + 3 * 3600, "2d 3h"),
        (-30, "0m"),
    ],
)
def test_the_age_renders_in_each_unit_range(seconds, expected):
    """Whole minutes under an hour, then hours and minutes, then days and
    hours. A clock that has gone backwards reads 0m rather than negative."""
    since = datetime.fromisoformat(STARTED)
    assert watch.age_since(since, since + timedelta(seconds=seconds)) == expected


def test_the_age_keeps_counting_while_the_watcher_waits(tmp_path):
    """The age is read from the clock each time the line is built, not frozen
    when the result arrived, so a repaint alone keeps it current. Back-date
    the finish rather than patch the clock: the real clock is the point."""
    feed_log(session_log(tmp_path / "20261002-114315.jsonl", result_line()))

    watch.SESSION.result_at = datetime.now().astimezone() - timedelta(
        hours=2, minutes=5
    )

    assert "2h 5m ago" in watch.SESSION.phase_line()


def test_the_elapsed_time_stops_at_the_last_event(tmp_path):
    """Elapsed means the session's own length. It must not keep growing into
    the wait for the next session."""
    feed_log(session_log(tmp_path / "20261002-114315.jsonl", result_line()))
    assert watch.SESSION.elapsed() == "7m00s", "the log's own span"

    watch.track(json.loads(result_line()), "result")

    assert watch.SESSION.elapsed() == "7m00s"


def test_a_session_that_works_on_past_a_result_is_not_finished(tmp_path):
    """Nothing but the end of the log makes a result event the last word. A
    marker that only ever went on showed a working session as over for the
    rest of its life, which is the inverse of the bug this footer fixes."""
    feed_log(session_log(tmp_path / "20261002-113222.jsonl", *RESUMED))

    assert watch.SESSION.phase_line() == "working"


def test_the_finish_time_comes_from_the_last_event_not_the_first_result(tmp_path):
    """The mid-log result froze the finish at its own moment. Deriving the
    marker makes the closing result read the time off the work that followed
    it, and the cost is still the last result's rather than the sum."""
    feed_log(session_log(tmp_path / "20261002-113222.jsonl", *RESUMED, result_line()))

    assert watch.SESSION.phase_line().startswith(f"finished {ended(after=12)}")
    assert "session $5.38 est." in watch.SESSION.totals()


def test_several_result_events_use_the_last_ones_timestamp(tmp_path):
    feed_log(
        session_log(
            tmp_path / "20261002-114315.jsonl",
            result_line(at=STARTED),
            result_line(at=RESTARTED),
        )
    )

    assert watch.SESSION.phase_line().startswith(
        f"finished {local(RESTARTED, '%H:%M')}"
    )


def test_replay_prints_the_finish_time_without_an_age(tmp_path, capsys):
    """--replay reads a log that ended long ago; `3d 4h ago · waiting for the
    next session` would describe the watcher, which has already exited."""
    log = session_log(tmp_path / "20261002-114315.jsonl", result_line())

    assert watch.main(["--file", str(log), "--replay"]) == 0

    out = capsys.readouterr().out
    assert f" finished {ended()}" in out
    assert "ago" not in out
    assert "session $5.38 est." in out, "the plain footer must print the cost too"


# --- the session line and the Codex engine (agents-b86) ---------------------
#
# Alice can review on Codex instead of Claude, so one watcher now reads two
# event vocabularies. Codex's JSON names no model and carries no timestamps at
# all, so run.sh writes both into a `ralph.session` line at the top of every
# log — for both engines, because the start time is worth having either way.

CODEX_MODEL = "gpt-5.1-codex"
# The exact shape run.sh writes: `date +%Y-%m-%dT%H:%M:%S%z`, offset without a
# colon. Python 3.13's fromisoformat reads it; an older one would not.
CODEX_STARTED = "2026-10-05T14:30:12-0500"
# Earlier than the first assistant event of a `session_log`, so a test can tell
# a start time read off the session line from one read off the stream.
EARLY = (datetime.fromisoformat(STARTED) - timedelta(minutes=5)).isoformat()
# The same note as Codex reports it: one command, no shell chaining. Derived
# from REVIEW rather than retyped, so the marker stays tied to the ALICE.md
# prose that `test_the_review_marker_matches_the_one_alice_is_told_to_write`
# pins — reword it there and the Codex half of the watcher fails too.
CODEX_REVIEW = REVIEW.split(" && ")[0]


def session_line(engine: str = "codex", model: str = "", started: str = CODEX_STARTED):
    """run.sh's first line: which engine wrote the log, its model, its start."""
    return json.dumps(
        {
            "type": "ralph.session",
            "engine": engine,
            "model": model,
            "started": started,
        }
    )


def codex_command(command: str, *, kind: str = "item.started", exit_code=None) -> str:
    """A `command_execution` item, as `codex exec --json` reports it."""
    return json.dumps(
        {
            "type": kind,
            "item": {
                "id": "item_0",
                "type": "command_execution",
                "command": command,
                "aggregated_output": "",
                "exit_code": exit_code,
                "status": "in_progress" if kind == "item.started" else "completed",
            },
        }
    )


def codex_message(text: str) -> str:
    return json.dumps(
        {
            "type": "item.completed",
            "item": {"id": "item_1", "type": "agent_message", "text": text},
        }
    )


def codex_usage(inputs=32697, cached=24576, output=47, reasoning=0) -> str:
    """`turn.completed`, which closes a Codex session and fills its footer."""
    return json.dumps(
        {
            "type": "turn.completed",
            "usage": {
                "input_tokens": inputs,
                "cached_input_tokens": cached,
                "cache_write_input_tokens": 0,
                "output_tokens": output,
                "reasoning_output_tokens": reasoning,
            },
        }
    )


CODEX_SAYS = "The gate passes on the branch HEAD."


def codex_log(path: Path, *extra: str, model: str = "") -> Path:
    """A Codex session log: the session line, a thread, Alice's note, a message."""
    path.write_text(
        "\n".join(
            [
                session_line(model=model),
                json.dumps({"type": "thread.started", "thread_id": "th_1"}),
                json.dumps({"type": "turn.started"}),
                codex_command(CODEX_REVIEW),
                codex_command(CODEX_REVIEW, kind="item.completed", exit_code=0),
                codex_message(CODEX_SAYS),
                *extra,
            ]
        )
        + "\n"
    )
    return path


def replay_codex(tmp_path: Path) -> None:
    """Replay a finished Codex log through main, the way --replay reads one.

    Four tests ask what a replay does and only differ in what they then read
    back, so the log and the invocation live here rather than in each of them.
    """
    log = codex_log(tmp_path / "20261005-143012.jsonl", codex_usage())

    assert watch.main(["--file", str(log), "--replay"]) == 0


def test_the_session_line_gives_the_header_its_model_and_start(tmp_path, capsys):
    """The two values a Codex stream never reports, read back off the header —
    including for a watcher that attached after the line scrolled past."""
    feed_log(codex_log(tmp_path / "20261005-143012.jsonl", model=CODEX_MODEL))

    watch.SESSION.header()

    out = capsys.readouterr().out
    assert " Ralph · agents-ype" in out
    assert f"started {local(CODEX_STARTED)}" in out
    assert f"model {CODEX_MODEL}" in out


def test_a_codex_session_with_no_model_says_so(tmp_path, capsys):
    """run.sh passes no -m unless RALPH_MODEL is set, so the model really is
    unknown here — and `model ?` would read as a watcher that lost it."""
    feed_log(codex_log(tmp_path / "20261005-143012.jsonl"))

    watch.SESSION.header()

    assert "model codex default" in capsys.readouterr().out


def test_a_claude_log_takes_its_start_from_the_session_line_too(tmp_path):
    """run.sh writes the line for both engines. The init event still names the
    model on a Claude log, and the start now predates the first tool call."""
    log = tmp_path / "20261005-143012.jsonl"
    log.write_text(
        "\n".join(
            [session_line(engine="claude", model=MODEL, started=EARLY), init_line()]
        )
        + "\n"
        + bash_line(CLAIM)
        + "\n"
    )

    feed_log(log)

    assert watch.SESSION.engine == "claude"
    assert watch.SESSION.model == MODEL
    assert watch.SESSION.first == datetime.fromisoformat(EARLY)


def test_a_log_without_a_session_line_is_read_as_claude(tmp_path):
    """Every log written before this change, and any log from an older run.sh."""
    feed_log(session_log(tmp_path / "20261002-114315.jsonl", result_line()))

    assert watch.SESSION.engine == "claude"
    assert "session $5.38 est." in watch.SESSION.totals()


def test_a_codex_log_renders_its_bead_commands_and_messages(tmp_path, capsys):
    """The header's bead comes from the same `Review round <n> started` note on
    either engine: Codex reports it as a command, so it goes through bead_in."""
    replay_codex(tmp_path)

    out = capsys.readouterr().out
    assert " Ralph · agents-ype" in out
    assert "Review round 1 started" in out, "the command line never printed"
    assert CODEX_SAYS in out, "Alice's own narration never printed"


def test_the_codex_footer_shows_tokens_and_no_cost(tmp_path):
    """A ChatGPT plan bills no per-session figure, so the footer says so rather
    than promising one that never arrives."""
    feed_log(
        codex_log(
            tmp_path / "20261005-143012.jsonl",
            codex_usage(output=58914, reasoning=4096),
        )
    )

    totals = watch.SESSION.totals()
    assert "58.9k out" in totals
    assert "4.1k think" in totals
    assert "33k ctx (25k cached)" in totals
    assert "no cost (ChatGPT plan)" in totals
    assert "session $" not in totals, "a Codex session was given a dollar figure"


def test_turn_completed_marks_a_codex_session_finished(tmp_path):
    feed_log(codex_log(tmp_path / "20261005-143012.jsonl", codex_usage()))

    line = watch.SESSION.phase_line()
    assert line.startswith("finished ")
    assert line.endswith("ago · waiting for the next session")


def test_a_codex_session_that_works_on_past_a_turn_is_not_finished(tmp_path):
    """The same rule the Claude result event follows: only the last event read
    can close a log."""
    feed_log(
        codex_log(
            tmp_path / "20261005-143012.jsonl",
            codex_usage(),
            codex_command("uv run pytest -q"),
        )
    )

    assert watch.SESSION.phase_line() == "working"


def test_the_totals_count_codex_sessions_apart_from_the_dollar_total(tmp_path):
    """COSTS holds dollar figures only: a 0 for a Codex session would dilute
    `over N sessions`, which is what the dollar total is averaged over."""
    claude = session_log(tmp_path / "20261002-114315.jsonl", result_line(cost=1.20))
    codex = codex_log(tmp_path / "20261005-143012.jsonl", codex_usage())

    with pytest.raises(Stop):
        watch.follow(paths(claude, codex))

    totals = watch.SESSION.totals()
    assert "watcher $1.20 est. over 1 sessions" in totals
    assert "1 Codex sessions (no cost)" in totals


def test_a_failing_codex_command_is_called_out(tmp_path, capsys):
    """`item.started` prints every command; only a non-zero exit prints twice."""
    log = codex_log(
        tmp_path / "20261005-143012.jsonl",
        codex_command("uv run pytest -q", kind="item.completed", exit_code=1),
        codex_usage(),
    )

    assert watch.main(["--file", str(log), "--replay"]) == 0

    out = capsys.readouterr().out
    assert "FAILED" in out
    assert "exit 1" in out


def test_an_unrecorded_codex_event_is_ignored(tmp_path):
    """The design lists the event shapes it recorded; anything else is a guess,
    and a later codex-cli will add shapes this watcher has never seen."""
    feed_log(
        codex_log(
            tmp_path / "20261005-143012.jsonl",
            json.dumps(
                {"type": "item.completed", "item": {"type": "reasoning", "text": "x"}}
            ),
            json.dumps({"type": "nonsense.event"}),
            codex_usage(),
        )
    )

    assert watch.SESSION.bead == "agents-ype"
    assert watch.SESSION.engine == "codex"


def test_replaying_a_codex_log_invents_no_clock_times(tmp_path, capsys):
    """Codex events carry no clock, so the live view stamps them as they
    arrive. A replay's arrival time is the replay's, not the session's, and a
    plausible wrong time is worse than none."""
    replay_codex(tmp_path)

    body = [
        line
        for line in capsys.readouterr().out.splitlines()
        if "note " in line or "says " in line
    ]
    assert body, "the replay printed no body lines at all"
    for line in body:
        assert not re.match(r"\s*\d\d:\d\d", line), f"invented a clock time: {line!r}"


def test_a_live_codex_session_reports_how_long_it_has_been_running(tmp_path):
    """No Codex event carries a clock, so nothing advances the session's last
    seen moment and the footer's elapsed time would read `?` for the whole
    run. The live view already stamps Codex body lines as they arrive, and the
    footer reads the same clock."""
    feed_log(codex_log(tmp_path / "20261005-143012.jsonl"))

    assert watch.SESSION.last is not None
    assert not watch.SESSION.totals().startswith("?")


def test_replaying_a_codex_log_claims_no_elapsed_time(tmp_path):
    """The other half of the same rule: a replay's clock is its own, not the
    session's, so it reports the duration it does not know as `?`."""
    replay_codex(tmp_path)

    assert watch.SESSION.totals().startswith("? · ")


def test_replaying_a_codex_log_prints_no_finish_time(tmp_path, capsys):
    """The same rule again, in the footer. `turn.completed` carries no clock,
    so a replay that fell back to its own printed a finish an hour before the
    start the session line gave, next to an elapsed time of `?`."""
    replay_codex(tmp_path)

    assert watch.SESSION.finished is None
    assert "finished " not in capsys.readouterr().out
