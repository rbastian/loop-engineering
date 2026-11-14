"""layout.sh starts the Telegram notifier in its own pane (lpe-2gm).

The pane runs loop/notify.py from the loop-engineering clone, as the queue
panes run queue.sh, so the installed harness in .loop/ does not change.
"""

from _layout_helpers import LAYOUT, operation_records, run_layout

NOTIFY = LAYOUT.resolve().parents[3] / "loop/notify.py"


def notifier_command(project) -> str:
    return f"uv run '{NOTIFY}' --project '{project}'"


def notifier_pane(records: list[list[str]]) -> str:
    renames = [r for r in records if r[0] == "rename" and r[2] == "Notifier"]
    assert len(renames) == 1, records
    return renames[0][1]


def test_notifier_gets_its_own_pane_next_to_the_watchers(tmp_path):
    result, _ = run_layout(tmp_path, [])

    assert result.returncode == 0, result.stdout + result.stderr
    records = operation_records(tmp_path)
    pane = notifier_pane(records)
    watchers = {r[1]: r[2] for r in records if r[0] == "rename"}
    reviewer_watch = next(
        p for p, label in watchers.items() if label == "Carol watcher"
    )
    project = tmp_path / "proj"
    splits = [r for r in records if r[0] == "split"]
    # The fake herdr numbers each new pane p<n> in split order.
    split = splits[int(pane[1:]) - 1]
    assert split[1] == reviewer_watch
    assert split[2] == "right"
    assert split[4] == str(project)

    runs = [r for r in records if r[0] == "run" and r[1] == pane]
    assert runs == [["run", pane, notifier_command(project)]]
    assert pane in result.stdout


def test_notifier_starts_before_the_loops(tmp_path):
    run_layout(tmp_path, [])
    records = operation_records(tmp_path)
    runs = [r[2] for r in records if r[0] == "run"]
    notifier = runs.index(notifier_command(tmp_path / "proj"))
    loops = [i for i, command in enumerate(runs) if "/.loop/run.sh" in command]
    assert loops and notifier < min(loops)


def test_a_notifier_pane_in_this_tab_stops_the_layout(tmp_path):
    result, _ = run_layout(
        tmp_path,
        [],
        panes=[{"pane_id": "old", "tab_id": "t1", "label": "Notifier"}],
    )

    assert result.returncode == 1
    assert "close them first" in result.stdout + result.stderr
    assert not any(
        record[0] in ("tab", "split") for record in operation_records(tmp_path)
    )
