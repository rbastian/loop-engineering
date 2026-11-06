"""loop/metrics.py reports the five measurements of a bead's work (lpe-55h).

The metrics come from the beads database and from GitHub. Each test copies the
script into a scratch project with a fake bd and a fake gh on PATH, so no test
reads the real queue or the network.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
METRICS = ROOT / "loop/metrics.py"
PROJECT = """# Project

```bash
CODER=Ralph
REVIEWER=Alice
GITHUB_ACCOUNT=rbastian
```
"""


def bead(
    bead_id, *, notes="", status="open", labels=None, dependencies=None, closed_at=None
):
    row = {
        "id": bead_id,
        "title": f"Title of {bead_id}",
        "issue_type": "task",
        "status": status,
        "created_at": "2026-01-01T09:00:00Z",
        "notes": notes,
        "labels": labels or [],
        "dependencies": dependencies or [],
    }
    if closed_at:
        row["closed_at"] = closed_at
    return row


def event(event_id, parent, created_at):
    return {
        "id": event_id,
        "title": "State change: loop → coding",
        "issue_type": "event",
        "status": "closed",
        "created_at": created_at,
        "parent": parent,
        "dependencies": [
            {
                "issue_id": event_id,
                "depends_on_id": parent,
                "type": "parent-child",
            }
        ],
    }


def linked_bug(bug_id, original):
    return bead(
        bug_id,
        status="open",
        labels=["escaped"],
        dependencies=[
            {
                "issue_id": bug_id,
                "depends_on_id": original,
                "type": "discovered-from",
            }
        ],
    )


MERGED_AT = {"mergedAt": "2026-01-01T11:30:00Z"}


def merged_bead(notes, *extra, bead_id="lpe-a"):
    """One bead that started coding at 10:00 and merged at 11:30."""
    return [
        bead(bead_id, notes=notes),
        event(f"{bead_id}.1", bead_id, "2026-01-01T10:00:00Z"),
        *extra,
    ]


def run_metrics(tmp_path, beads, *, args=(), pr_result=None, gh_fails=False):
    """Run metrics.py in a scratch project with fake bd and gh commands."""
    project = tmp_path / "project"
    (project / "loop").mkdir(parents=True)
    (project / ".loop").mkdir()
    (project / ".loop/project.md").write_text(PROJECT)
    shutil.copy(METRICS, project / "loop/metrics.py")

    beads_file = project / "beads.json"
    beads_file.write_text(json.dumps(beads))
    pr_file = project / "pr.json"
    pr_file.write_text(json.dumps(pr_result or {}))

    bin_dir = project / "bin"
    bin_dir.mkdir()
    bd = bin_dir / "bd"
    bd.write_text(f'#!/bin/bash\ncat "{beads_file}"\n')
    bd.chmod(0o755)
    gh = bin_dir / "gh"
    if gh_fails:
        gh.write_text(
            '#!/bin/bash\necho "gh: authentication failed" >&2\nexit 1\n',
        )
    else:
        gh.write_text(
            "#!/bin/bash\n"
            'case "$*" in\n'
            '  "auth token --user rbastian") echo "gho_stubtoken"; exit 0 ;;\n'
            '  "pr view "*) cat ' + str(pr_file) + " ; exit 0 ;;\n"
            "esac\n"
            'echo "gh: unexpected call: $*" >&2\n'
            "exit 1\n",
        )
    gh.chmod(0o755)

    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": str(tmp_path),
        "PYTHONPATH": "",
    }
    return subprocess.run(
        [sys.executable, str(project / "loop/metrics.py"), *args],
        check=False,
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
    )


def run_json(tmp_path, beads, *, args=("--json",), **kwargs):
    result = run_metrics(tmp_path, beads, args=args, **kwargs)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


# Criterion 1: the five measurements of one bead.
def test_json_reports_human_time_lead_time_returns_escapes_and_cost(tmp_path):
    notes = (
        "Human time: 10m refine\n"
        "Human time: 15m troubleshoot\n"
        "Review round 1 failed: a test\n"
        "Session cost: Ralph, model, $1.36 est., 5m wall\n"
        "Session cost: Alice, model, $0.24 est., 2m wall\n"
        "PR opened: #7 https://example.test/pull/7\n"
    )
    beads = merged_bead(notes)
    data = run_json(tmp_path, beads, pr_result=MERGED_AT)

    row = data["beads"][0]
    assert row["id"] == "lpe-a"
    assert row["human_minutes"] == 25
    assert row["review_returns"] == 1
    assert row["escapes"] == 0
    assert row["cost"] == pytest.approx(1.60)
    assert row["lead_time_minutes"] == 90
    assert row["lead_time_estimated"] is False


# Criterion 2: no Human time note is null, not zero.
def test_a_bead_without_human_time_is_null(tmp_path):
    notes = "PR opened: #7 https://example.test/pull/7\n"
    data = run_json(tmp_path, merged_bead(notes), pr_result=MERGED_AT)

    assert data["beads"][0]["human_minutes"] is None
    assert data["totals"]["beads_without_human_time"] == 1


# Criterion 3: an escaped bug with a discovered-from dependency.
def test_an_escaped_bug_counts_one_escape_on_the_original(tmp_path):
    notes = "PR opened: #7 https://example.test/pull/7\n"
    beads = merged_bead(notes, linked_bug("lpe-b", "lpe-a"))
    data = run_json(tmp_path, beads, pr_result=MERGED_AT)

    row = data["beads"][0]
    assert row["id"] == "lpe-a"
    assert row["escapes"] == 1


# Criterion 4: no PR means closed_at and a mark.
def test_a_bead_without_a_pr_uses_closed_at_and_marks_the_lead_time(tmp_path):
    beads = [
        bead(
            "lpe-a",
            status="closed",
            closed_at="2026-01-01T12:00:00Z",
        ),
        event("lpe-a.1", "lpe-a", "2026-01-01T10:00:00Z"),
    ]
    data = run_json(tmp_path, beads)

    row = data["beads"][0]
    assert row["lead_time_minutes"] == 120
    assert row["lead_time_estimated"] is True


# Criterion 5: a gh failure warns, exits 0 and leaves the lead time empty.
def test_a_gh_failure_warns_and_leaves_the_lead_time_empty(tmp_path):
    notes = "PR opened: #7 https://example.test/pull/7\n"
    result = run_metrics(
        tmp_path, merged_bead(notes), args=("--json", "--all"), gh_fails=True
    )

    assert result.returncode == 0
    assert "warning" in result.stderr.lower()
    data = json.loads(result.stdout)
    assert data["beads"][0]["lead_time_minutes"] is None


# Criterion 7: an unknown cost adds a plus to the known sum.
def test_an_unknown_session_marks_the_cost_with_a_plus(tmp_path):
    notes = (
        "Session cost: Ralph, model, $1.45 est., 5m wall\n"
        "Session cost: cost unknown (fw)\n"
        "PR opened: #7 https://example.test/pull/7\n"
    )
    beads = merged_bead(notes)
    result = run_metrics(tmp_path, beads, args=("--all",), pr_result=MERGED_AT)

    assert result.returncode == 0, result.stderr
    assert "$1.45+" in result.stdout

    data = run_json(tmp_path / "json", beads, pr_result=MERGED_AT)
    row = data["beads"][0]
    assert row["cost"] == pytest.approx(1.45)
    assert row["unknown_cost_sessions"] == 1


# Criterion 6: both documents describe both conventions.
def test_the_documents_describe_both_conventions():
    for name in ("loop/interactive.template.md", "loop/README.md"):
        text = (ROOT / name).read_text()
        assert "Human time:" in text, name
        assert "discovered-from" in text, name


# The rest of the design: scope, --since, --all and --by-agent.
def test_by_default_only_merged_beads_are_shown(tmp_path):
    beads = merged_bead("PR opened: #7 u\n") + merged_bead(
        "PR opened: #8 u\n", bead_id="lpe-b"
    )
    data = run_json(tmp_path, beads, pr_result=MERGED_AT)

    # The fake gh answers the same for both numbers, so both are merged.
    assert {row["id"] for row in data["beads"]} == {"lpe-a", "lpe-b"}

    # With no merge, both are left out.
    data = run_json(tmp_path / "open", beads, pr_result={"mergedAt": None})
    assert data["beads"] == []


def test_all_shows_an_open_bead_with_blank_cells(tmp_path):
    beads = merged_bead("PR opened: #7 u\n")
    data = run_json(
        tmp_path, beads, args=("--json", "--all"), pr_result={"mergedAt": None}
    )

    row = data["beads"][0]
    assert row["human_minutes"] is None
    assert row["lead_time_minutes"] is None
    assert row["cost"] == 0


def test_since_limits_the_report_by_merge_date(tmp_path):
    beads = merged_bead("PR opened: #7 u\n")
    data = run_json(
        tmp_path,
        beads,
        args=("--json", "--since", "2026-01-02"),
        pr_result=MERGED_AT,
    )
    assert data["beads"] == []


def test_by_agent_separates_the_cost(tmp_path):
    notes = (
        "Session cost: Ralph, model, $1.00 est., 5m wall\n"
        "Session cost: Alice, model, $0.50 est., 2m wall\n"
        "PR opened: #7 u\n"
    )
    beads = merged_bead(notes)
    result = run_metrics(
        tmp_path,
        beads,
        args=("--json", "--by-agent"),
        pr_result=MERGED_AT,
    )

    assert result.returncode == 0, result.stderr
    row = json.loads(result.stdout)["beads"][0]
    assert row["cost_by_agent"]["Ralph"] == pytest.approx(1.00)
    assert row["cost_by_agent"]["Alice"] == pytest.approx(0.50)
