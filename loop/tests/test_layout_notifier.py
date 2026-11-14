"""layout.sh starts the Telegram notifier in the loop tab (lpe-2gm).

The notifier pane sits to the right of the reviewer queue, so the top row of
the loop tab reads: coder queue | reviewer queue | notifier. Its working
directory is the primary checkout, where .envrc lives, so the pane runs the
notifier under direnv when direnv is on PATH.
"""

from _layout_helpers import operation_records, run_layout

PLAIN = "uv run .loop/notify.py"
DIRENV = "direnv exec . uv run .loop/notify.py"


def notifier_pane(records: list[list[str]]) -> str:
    renames = [r for r in records if r[0] == "rename" and r[2] == "notifier"]
    assert len(renames) == 1, records
    return renames[0][1]


def split_of(records: list[list[str]], pane: str) -> list[str]:
    """The split that made PANE. The fake herdr numbers new panes p1, p2, ..."""
    splits = [r for r in records if r[0] == "split"]
    return splits[int(pane[1:]) - 1]


def direnv_stub(tmp_path):
    stub = tmp_path / "direnv-bin" / "direnv"
    stub.parent.mkdir()
    stub.write_text("#!/bin/sh\n")
    stub.chmod(0o755)
    return stub.parent


def test_notifier_sits_right_of_the_reviewer_queue_in_the_loop_tab(tmp_path):
    result, _ = run_layout(tmp_path, [])

    assert result.returncode == 0, result.stdout + result.stderr
    records = operation_records(tmp_path)
    pane = notifier_pane(records)
    reviewer_queue = next(
        r[1] for r in records if r[0] == "rename" and r[2] == "Carol queue"
    )
    assert split_of(records, pane) == [
        "split",
        reviewer_queue,
        "right",
        "0.5",
        str(tmp_path / "proj"),
    ]
    assert pane in result.stdout


def test_notifier_runs_plain_uv_without_direnv(tmp_path):
    run_layout(tmp_path, [])
    records = operation_records(tmp_path)
    pane = notifier_pane(records)
    assert [r for r in records if r[0] == "run" and r[1] == pane] == [
        ["run", pane, PLAIN]
    ]


def test_notifier_runs_under_direnv_when_direnv_is_on_path(tmp_path):
    bin_dir = direnv_stub(tmp_path)
    run_layout(tmp_path, [], {"PATH": f"{tmp_path}/bin:{bin_dir}:/usr/bin:/bin"})
    records = operation_records(tmp_path)
    pane = notifier_pane(records)
    assert [r for r in records if r[0] == "run" and r[1] == pane] == [
        ["run", pane, DIRENV]
    ]


def test_notifier_starts_before_the_loops(tmp_path):
    run_layout(tmp_path, [])
    runs = [r[2] for r in operation_records(tmp_path) if r[0] == "run"]
    loops = [i for i, command in enumerate(runs) if "/.loop/run.sh" in command]
    assert loops and runs.index(PLAIN) < min(loops)


def test_a_notifier_pane_anywhere_in_the_workspace_stops_the_layout(tmp_path):
    result, _ = run_layout(
        tmp_path,
        [],
        panes=[{"pane_id": "old", "tab_id": "another-tab", "label": "notifier"}],
    )

    assert result.returncode == 1
    out = result.stdout + result.stderr
    assert "notifier" in out
    assert "close it first" in out
    assert not any(
        record[0] in ("tab", "split") for record in operation_records(tmp_path)
    )
