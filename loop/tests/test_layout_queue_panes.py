"""layout.sh opens one queue pane above each agent's loop pane (lpe-4h9.3)."""

from _layout_helpers import LAYOUT, operation_records, run_layout


def test_queue_panes_sit_above_the_loops_and_start_first(tmp_path):
    result, _ = run_layout(tmp_path, [])

    assert result.returncode == 0, result.stdout + result.stderr
    records = operation_records(tmp_path)
    project = tmp_path / "proj"
    assert ["split", "p0", "down", "0.67", str(project)] in records
    assert ["split", "p1", "down", "0.67", str(project)] in records
    assert ["swap", "p2", "p0"] in records
    assert ["swap", "p3", "p1"] in records
    assert ["rename", "p0", "Bob"] in records
    assert ["rename", "p1", "Carol"] in records
    assert ["rename", "p2", "Bob queue"] in records
    assert ["rename", "p3", "Carol queue"] in records

    queue = LAYOUT.parent / "queue.sh"
    agent_runs = [
        record
        for record in records
        if record[0] == "run"
        and ("queue.sh" in record[2] or "/.loop/run.sh" in record[2])
    ]
    assert agent_runs == [
        ["run", "p2", f"'{queue}' --watch Bob"],
        ["run", "p3", f"'{queue}' --watch Carol"],
        [
            "run",
            "p0",
            f"LOOP_ENGINE=claude LOOP_MODEL='claude-opus-5-5' LOOP_STREAM_LOG=1 LOOP_SHOW_BEAD=1 LOOP_LOG_DIR=/tmp/proj-bob-sessions {project}/.loop/run.sh Bob {project}/.loop/CODER.md",
        ],
        [
            "run",
            "p1",
            f"LOOP_ENGINE=claude LOOP_MODEL='claude-sonnet-5-5' LOOP_STREAM_LOG=1 LOOP_SHOW_BEAD=1 LOOP_LOG_DIR=/tmp/proj-carol-sessions {project}/.loop/run.sh Carol {project}/.loop/REVIEWER.md",
        ],
    ]


def test_a_queue_pane_anywhere_in_the_workspace_stops_the_layout(tmp_path):
    result, _ = run_layout(
        tmp_path,
        [],
        panes=[{"pane_id": "old", "tab_id": "another-tab", "label": "Old queue"}],
    )

    assert result.returncode == 1
    assert "Old queue" in result.stdout + result.stderr
    assert "close it first" in result.stdout + result.stderr
    assert not any(
        record[0] in ("tab", "split") for record in operation_records(tmp_path)
    )
