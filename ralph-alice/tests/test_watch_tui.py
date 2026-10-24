"""ralph/watch.py --tui: a Rich Live screen with a pinned header and footer.

The scroll-region version crashed both watchers on a terminal resize
(RuntimeError: reentrant call inside BufferedWriter, 2026-10-14), so Rich owns
the screen now. These tests draw it into an in-memory console of a chosen size
and read the rows back.
"""

import importlib.util
import io
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
WATCH = ROOT / "watch.py"

_spec = importlib.util.spec_from_file_location("ralph_watch_tui", WATCH)
watch = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(watch)

rich_console = pytest.importorskip("rich.console")

STARTED = "2026-10-14T09:00:00+00:00"
# Captured before the fixture below stubs `subprocess.run` for the whole module.
REAL_RUN = subprocess.run


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setattr(watch, "SESSION", watch.Session())
    monkeypatch.setattr(watch, "AGENT", "Ralph")
    monkeypatch.setattr(watch, "_last", [None, 0, ""])
    monkeypatch.setattr(watch, "COSTS", {})
    monkeypatch.setattr(
        watch.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout="")
    )


def console(width=120, height=24):
    return rich_console.Console(
        file=io.StringIO(),
        force_terminal=True,
        width=width,
        height=height,
        color_system=None,
    )


@pytest.fixture
def screen(monkeypatch):
    pinned = watch.Pinned(enabled=True)
    pinned.enabled = True  # the test's stdout is not a tty
    monkeypatch.setattr(watch, "PINNED", pinned)
    pinned.start(console())
    yield pinned
    pinned.stop()


@pytest.fixture
def painted(screen, monkeypatch) -> list:
    """One entry per repaint of `screen`."""
    calls = []
    monkeypatch.setattr(screen.live, "refresh", lambda: calls.append(1))
    return calls


def rows(pinned) -> list[str]:
    """What the layout draws at the console's current size, one str per row."""
    cap = rich_console.Console(
        file=io.StringIO(),
        width=pinned.live.console.width,
        height=pinned.live.console.height,
        record=True,
        color_system=None,
    )
    cap.print(pinned.layout)
    return [r.rstrip() for r in cap.export_text().split("\n")][
        : pinned.live.console.height
    ]


def say(pinned, text: str) -> None:
    watch._write("09:00:00", "1", "label", text, 1)


def tool(command: str, at: str = STARTED) -> dict:
    return {
        "type": "assistant",
        "timestamp": at,
        "message": {
            "usage": {"output_tokens": 1, "input_tokens": 1},
            "content": [
                {"type": "tool_use", "name": "Bash", "input": {"command": command}}
            ],
        },
    }


def test_header_and_footer_stay_put_around_the_newest_lines(screen):
    watch.SESSION.name = "s.jsonl"
    for event in (
        {"type": "system", "subtype": "init", "model": "claude-opus-5"},
        tool("bd update agents-abc --claim"),
        tool(
            "uv run pytest -q",
            (datetime.fromisoformat(STARTED) + timedelta(minutes=3)).isoformat(),
        ),
    ):
        watch.handle(event)
    for n in range(60):
        say(screen, f"line {n}")
    screen_rows = rows(screen)

    assert len(screen_rows) == 24
    assert set(screen_rows[0]) == {"─"}
    assert screen_rows[1] == " Ralph · agents-abc"
    assert screen_rows[2].startswith(" session s.jsonl · started ")
    assert "model claude-opus-5" in screen_rows[2]
    assert set(screen_rows[3]) == {"─"}
    assert set(screen_rows[-3]) == {"─"}
    assert screen_rows[-2] == f" {watch.SESSION.totals()}"
    assert screen_rows[-1] == f" {watch.SESSION.phase_line()}"
    body = screen_rows[4:-3]
    assert body[-1].endswith("line 59")
    assert body[0].endswith("line 43")
    assert len(body) == 17


def test_a_resize_redraws_to_the_new_size_without_error(screen):
    for n in range(40):
        say(screen, f"line {n}")
    screen.live.console.size = (60, 12)

    screen.tick()
    smaller = rows(screen)

    assert len(smaller) == 12
    assert set(smaller[-3]) == {"─"}
    assert smaller[-4].endswith("line 39")
    assert screen.size == (60, 12)


def test_the_body_is_bounded(screen):
    for n in range(watch.Pinned.BODY_LINES * 3):
        say(screen, f"line {n}")

    assert len(screen.body) == watch.Pinned.BODY_LINES
    assert screen.body[-1][0].endswith(f"line {watch.Pinned.BODY_LINES * 3 - 1}")


def test_a_finished_sessions_age_moves_while_the_watcher_is_idle(
    screen, painted, monkeypatch
):
    watch.SESSION.last_kind = "result"
    watch.SESSION.result_at = datetime.now().astimezone() - timedelta(minutes=2)
    screen.draw()
    assert "2m ago" in rows(screen)[-1]

    screen.tick()  # painted just now, same size: nothing to do
    assert len(painted) == 1

    watch.SESSION.result_at -= timedelta(minutes=5)
    monkeypatch.setattr(screen, "painted_at", screen.painted_at - watch.REPAINT_SECONDS)
    screen.tick()

    assert len(painted) == 2
    assert "7m ago" in rows(screen)[-1]


def test_stop_releases_the_screen_and_is_safe_to_repeat(screen):
    screen.stop()
    screen.stop()

    assert screen.live is None


def test_ctrl_c_in_follow_restores_the_terminal(monkeypatch, tmp_path):
    started = []
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    real_start = watch.Pinned.start

    def start(self, console_=None):
        real_start(self, console())
        started.append(self)

    monkeypatch.setattr(watch.Pinned, "start", start)
    monkeypatch.setattr(watch, "PINNED", watch.Pinned(enabled=True))
    monkeypatch.setattr(watch, "LOG_DIR", tmp_path)
    monkeypatch.setattr(
        watch, "follow", lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt)
    )

    with pytest.raises(KeyboardInterrupt):
        watch.main(["--tui", "--agent", "Ralph"])

    assert started and started[0].live is None


def test_source_has_no_resize_handler_or_scroll_region():
    source = WATCH.read_text()

    assert "SIGWINCH" not in source
    assert "signal.signal" not in source
    assert "\\033[" not in source


def test_script_declares_rich_as_a_pep_723_dependency():
    head = WATCH.read_text().split('"""', 1)[0]

    assert re.search(r'^# requires-python = ">=3\.13"$', head, re.MULTILINE)
    assert re.search(r'^# dependencies = \["rich"\]$', head, re.MULTILINE)


def test_plain_mode_runs_without_rich_installed(tmp_path):
    log = tmp_path / "2026-10-14.jsonl"
    log.write_text(
        "\n".join(
            [
                json.dumps({"type": "system", "subtype": "init", "model": "m"}),
                json.dumps(tool("bd ready --assignee=Ralph")),
            ]
        )
        + "\n"
    )
    code = (
        "import sys; sys.modules['rich'] = None; "
        f"sys.argv = ['watch', '--agent', 'Ralph', '--replay', '--file', {str(log)!r}]; "
        f"import runpy; runpy.run_path({str(WATCH)!r}, run_name='__main__')"
    )

    done = REAL_RUN([sys.executable, "-I", "-c", code], capture_output=True, text=True)

    assert done.returncode == 0, done.stderr
    assert "find work" in done.stdout
    assert "\x1b" not in done.stdout


def test_replay_and_stdin_stay_plain_even_with_tui(monkeypatch, tmp_path):
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(watch, "PINNED", watch.Pinned(enabled=True))
    monkeypatch.setattr(watch, "LOG_DIR", tmp_path)
    log = tmp_path / "2026-10-14.jsonl"
    log.write_text(json.dumps(tool("bd ready")) + "\n")

    assert (
        watch.main(["--tui", "--agent", "Ralph", "--replay", "--file", str(log)]) == 0
    )
    assert watch.PINNED.live is None


def test_a_burst_of_lines_costs_one_repaint(screen, painted, monkeypatch):

    for n in range(100):
        say(screen, f"line {n}")
    assert painted == []

    screen.tick()
    screen.tick()

    assert len(painted) == 1


def test_waiting_for_the_first_log_still_paints_the_screen(
    screen, painted, monkeypatch
):
    """Started before run.sh writes current.jsonl: the screen must not stay blank."""

    class Stop(Exception):
        pass

    def sleep(_):
        raise Stop

    monkeypatch.setattr(watch.time, "sleep", sleep)
    screen.add("following current.jsonl — ctrl-c to stop")

    with pytest.raises(Stop):
        watch.follow(lambda: None)

    assert painted and not screen.dirty
    assert any("following current.jsonl" in r for r in rows(screen))
