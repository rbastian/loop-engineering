"""skills/dev-env-setup/scripts/layout.sh: the watchers get their own Python.

watch.py names Python 3.13 and Rich in its inline script metadata. uv reads
that metadata only for `uv run <script>`. With `uv run python <script>` it runs
the file in the project venv, which bootstrap.sh gives only ruff and pytest, so
the watcher panes failed with ModuleNotFoundError: rich (lpe-a8p).
"""

from pathlib import Path

LAYOUT = Path(__file__).parents[2] / "skills/dev-env-setup/scripts/layout.sh"


def test_both_watchers_run_watch_py_as_a_uv_script():
    commands = [
        line
        for line in LAYOUT.read_text().splitlines()
        if line.startswith("herdr pane run") and "watch.py" in line
    ]
    assert len(commands) == 2
    for command in commands:
        assert "uv run ralph/watch.py" in command
