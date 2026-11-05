"""bootstrap.sh accepts the bead prefixes that bd and watch.py accept (lpe-7fn).

A prefix is lowercase letters, digits, - and _, and starts with a letter. bd
silently renames a prefix that starts with a digit to bd_<prefix>. A prefix
that ends with - or _, or that has two of them in a row, is rejected too.
"""

import pytest
from test_bootstrap_interactive import run_bootstrap


@pytest.mark.parametrize("prefix", ["my-app", "my_app", "app2", "abc"])
def test_a_valid_prefix_goes_into_project_md(tmp_path, prefix):
    project = tmp_path / "proj"
    run_bootstrap(tmp_path, project, prefix=prefix)
    text = (project / ".loop" / "project.md").read_text()
    assert f"\nBEAD_PREFIX={prefix}\n" in text
    assert "{{BEAD_PREFIX}}" not in text


@pytest.mark.parametrize(
    "prefix", ["2app", "My-App", "my--app", "my-app-", "-app", "", "my_-app", "a_"]
)
def test_an_invalid_prefix_stops_before_any_file_changes(tmp_path, prefix):
    project = tmp_path / "proj"
    result = run_bootstrap(tmp_path, project, check=False, prefix=prefix)
    assert result.returncode == 1
    assert "BEAD_PREFIX" in result.stdout + result.stderr
    assert not project.exists()
