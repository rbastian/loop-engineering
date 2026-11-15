"""loop/config.py: read and check .loop/loop.toml (lpe-umq.1)."""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config.py"

_spec = importlib.util.spec_from_file_location("loop_config", CONFIG)
config = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(config)

NAMES = [
    "PRIMARY",
    "BEAD_PREFIX",
    "HUMAN",
    "SHIP_MODE",
    "GITHUB_ACCOUNT",
    "CODER",
    "CODER_ENGINE",
    "CODER_MODEL",
    "CODER_WORKTREE",
    "REVIEWER",
    "REVIEWER_ENGINE",
    "REVIEWER_MODEL",
    "REVIEWER_WORKTREE",
]

VALID = """\
[project]
primary = "/work/project"
bead_prefix = "lpe"
human = "Rob Bastian"

[ship]
mode = "pr"
github_account = "rbastian"

[coder]
name = "Ralph"
engine = "claude"
model = "claude-opus-5-5"
worktree = "/work/project-ralph"

[reviewer]
name = "Alice"
engine = "codex"
model = "gpt-5.5"
worktree = "/work/project-alice"
"""

MINIMAL = """\
[project]
primary = "/work/project"
bead_prefix = "lpe"
human = "Rob Bastian"

[ship]
mode = "local"

[coder]
name = "Ralph"
worktree = "/work/project-ralph"

[reviewer]
name = "Alice"
worktree = "/work/project-alice"
"""


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "loop.toml"
    path.write_text(text)
    return path


def run(path: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CONFIG), "--file", str(path), *args],
        check=False,
        capture_output=True,
        text=True,
    )


def errors_for(tmp_path: Path, text: str) -> list[str]:
    with pytest.raises(config.ConfigError) as info:
        config.load(write(tmp_path, text))
    return info.value.errors


# Criterion 1: standard library only, runs with uv.


def test_is_a_uv_script_with_no_dependencies():
    text = CONFIG.read_text()
    assert "# /// script" in text
    assert 'requires-python = ">=3.13"' in text
    assert "# dependencies = []" in text


def test_imports_only_the_standard_library():
    imported = set()
    for line in CONFIG.read_text().splitlines():
        words = line.split()
        if words[:1] in (["import"], ["from"]):
            imported.add(words[1].split(".")[0])
    assert imported <= set(sys.stdlib_module_names) | {"__future__"}


def test_runs_with_uv(tmp_path):
    result = subprocess.run(
        ["uv", "run", "--no-project", str(CONFIG), "--file", "x", "check"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )
    # The file does not exist, so check fails, but it fails in config.py.
    assert result.returncode == 1
    assert "x: " in result.stderr


def test_reads_loop_toml_in_its_own_directory_by_default(tmp_path):
    script = tmp_path / "config.py"
    script.write_text(CONFIG.read_text())
    (tmp_path / "loop.toml").write_text(VALID)
    result = subprocess.run(
        [sys.executable, str(script), "get", "coder.name"],
        cwd="/",
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "Ralph\n"


# Criterion 2: each validation rule, with the key path in each error.


def test_a_valid_file_has_no_errors(tmp_path):
    config.load(write(tmp_path, VALID))
    config.load(write(tmp_path, MINIMAL))


def test_unknown_table(tmp_path):
    errors = errors_for(tmp_path, VALID + '\n[extra]\nx = "1"\n')
    assert errors == ["loop.toml: extra: unknown table"]


def test_unknown_key(tmp_path):
    text = VALID.replace('name = "Ralph"', 'name = "Ralph"\nalias = "R"')
    assert errors_for(tmp_path, text) == ["loop.toml: coder.alias: unknown key"]


@pytest.mark.parametrize(
    "line, path",
    [
        ('primary = "/work/project"', "project.primary"),
        ('bead_prefix = "lpe"', "project.bead_prefix"),
        ('human = "Rob Bastian"', "project.human"),
        ('mode = "pr"', "ship.mode"),
        ('name = "Ralph"', "coder.name"),
        ('worktree = "/work/project-ralph"', "coder.worktree"),
        ('name = "Alice"', "reviewer.name"),
        ('worktree = "/work/project-alice"', "reviewer.worktree"),
    ],
)
def test_missing_required_key(tmp_path, line, path):
    errors = errors_for(tmp_path, VALID.replace(line + "\n", ""))
    assert f"loop.toml: {path}: missing required key" in errors


def test_missing_table_reports_its_required_keys(tmp_path):
    text = VALID.split("[reviewer]")[0]
    errors = errors_for(tmp_path, text)
    assert errors == [
        "loop.toml: reviewer.name: missing required key",
        "loop.toml: reviewer.worktree: missing required key",
    ]


def test_coder_engine_outside_allowed_values(tmp_path):
    text = VALID.replace('engine = "claude"', 'engine = "codex"')
    assert errors_for(tmp_path, text) == [
        "loop.toml: coder.engine: must be claude or fw (got: codex)"
    ]


def test_reviewer_engine_outside_allowed_values(tmp_path):
    text = VALID.replace('engine = "codex"', 'engine = "gemini"')
    assert errors_for(tmp_path, text) == [
        "loop.toml: reviewer.engine: must be claude, codex or fw (got: gemini)"
    ]


def test_ship_mode_outside_allowed_values(tmp_path):
    text = VALID.replace('mode = "pr"', 'mode = "push"')
    assert "loop.toml: ship.mode: must be pr or local (got: push)" in errors_for(
        tmp_path, text
    )


def test_template_placeholder(tmp_path):
    text = VALID.replace('"lpe"', '"{{BEAD_PREFIX}}"')
    assert errors_for(tmp_path, text) == [
        (
            "loop.toml: project.bead_prefix: contains a template placeholder "
            "(got: {{BEAD_PREFIX}})"
        )
    ]


@pytest.mark.parametrize("model", ['model = ""', None])
def test_fw_engine_needs_a_model(tmp_path, model):
    text = VALID.replace('engine = "claude"', 'engine = "fw"')
    old = 'model = "claude-opus-5-5"'
    text = text.replace(old, model) if model else text.replace(old + "\n", "")
    assert errors_for(tmp_path, text) == [
        "loop.toml: coder.model: must be set when engine is fw"
    ]


@pytest.mark.parametrize("account", ['github_account = ""', None])
def test_pr_mode_needs_a_github_account(tmp_path, account):
    old = 'github_account = "rbastian"'
    text = VALID.replace(old, account) if account else VALID.replace(old + "\n", "")
    assert errors_for(tmp_path, text) == [
        "loop.toml: ship.github_account: must be set in pr mode"
    ]


def test_local_mode_rejects_a_github_account(tmp_path):
    text = VALID.replace('mode = "pr"', 'mode = "local"')
    assert errors_for(tmp_path, text) == [
        "loop.toml: ship.github_account: must be empty in local mode (got: rbastian)"
    ]


def test_local_mode_accepts_an_empty_github_account(tmp_path):
    text = MINIMAL.replace('mode = "local"', 'mode = "local"\ngithub_account = ""')
    config.load(write(tmp_path, text))


@pytest.mark.parametrize(
    "old, path",
    [
        ('"/work/project"', "project.primary"),
        ('"/work/project-ralph"', "coder.worktree"),
        ('"/work/project-alice"', "reviewer.worktree"),
    ],
)
def test_relative_path(tmp_path, old, path):
    text = VALID.replace(old, '"work/x"')
    assert errors_for(tmp_path, text) == [
        f"loop.toml: {path}: must be an absolute path (got: work/x)"
    ]


def test_coder_and_reviewer_names_must_differ(tmp_path):
    text = VALID.replace('name = "Alice"', 'name = "Ralph"')
    assert errors_for(tmp_path, text) == [
        "loop.toml: reviewer.name: must differ from coder.name (got: Ralph)"
    ]


def test_toml_syntax_error_gives_the_line(tmp_path):
    text = VALID.replace('human = "Rob Bastian"', "human = Rob Bastian")
    errors = errors_for(tmp_path, text)
    assert len(errors) == 1
    assert errors[0].startswith("loop.toml: ")
    assert "line 4" in errors[0]


def test_a_value_must_be_a_string(tmp_path):
    text = VALID.replace('bead_prefix = "lpe"', "bead_prefix = 7")
    assert errors_for(tmp_path, text) == [
        "loop.toml: project.bead_prefix: must be a string (got: 7)"
    ]


def test_a_table_must_be_a_table(tmp_path):
    text = 'coder = "Ralph"\n' + VALID.replace("[coder]", "[unused]")
    errors = errors_for(tmp_path, text)
    assert "loop.toml: coder: must be a table" in errors


def test_missing_file(tmp_path):
    with pytest.raises(config.ConfigError) as info:
        config.load(tmp_path / "loop.toml")
    assert len(info.value.errors) == 1
    assert info.value.errors[0].startswith("loop.toml: cannot read the file")


def test_one_run_reports_several_errors(tmp_path):
    text = (
        VALID.replace('engine = "claude"', 'engine = "codex"')
        .replace('"/work/project"', '"relative"')
        .replace('name = "Alice"', 'name = "Ralph"')
        .replace('human = "Rob Bastian"\n', "")
    )
    assert errors_for(tmp_path, text) == [
        "loop.toml: project.primary: must be an absolute path (got: relative)",
        "loop.toml: project.human: missing required key",
        "loop.toml: coder.engine: must be claude or fw (got: codex)",
        "loop.toml: reviewer.name: must differ from coder.name (got: Ralph)",
    ]


def test_check_prints_all_the_errors(tmp_path):
    text = VALID.replace('engine = "claude"', 'engine = "codex"').replace(
        'mode = "pr"', 'mode = "push"'
    )
    result = run(write(tmp_path, text), "check")
    assert result.returncode == 1
    assert result.stderr.splitlines() == [
        "loop.toml: ship.mode: must be pr or local (got: push)",
        "loop.toml: coder.engine: must be claude or fw (got: codex)",
    ]


# Criterion 3: check.


def test_check_exits_0_with_no_output_for_a_valid_file(tmp_path):
    result = run(write(tmp_path, VALID), "check")
    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""


def test_check_exits_1_for_an_invalid_file(tmp_path):
    result = run(write(tmp_path, VALID + "[extra]\n"), "check")
    assert result.returncode == 1
    assert result.stderr == "loop.toml: extra: unknown table\n"


def test_file_option_also_works_after_the_subcommand(tmp_path):
    path = write(tmp_path, VALID)
    result = subprocess.run(
        [sys.executable, str(CONFIG), "check", "--file", str(path)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


# Criterion 4: get.


def test_get_prints_a_value(tmp_path):
    result = run(write(tmp_path, VALID), "get", "project.human")
    assert result.returncode == 0
    assert result.stdout == "Rob Bastian\n"


@pytest.mark.parametrize(
    "key, value",
    [
        ("coder.engine", "claude"),
        ("coder.model", ""),
        ("reviewer.engine", "claude"),
        ("reviewer.model", ""),
        ("ship.github_account", ""),
    ],
)
def test_get_applies_defaults(tmp_path, key, value):
    result = run(write(tmp_path, MINIMAL), "get", key)
    assert result.returncode == 0, result.stderr
    assert result.stdout == value + "\n"


@pytest.mark.parametrize("key", ["coder.alias", "extra.name", "coder", "x"])
def test_get_unknown_key_exits_1(tmp_path, key):
    result = run(write(tmp_path, VALID), "get", key)
    assert result.returncode == 1
    assert result.stdout == ""
    assert key in result.stderr


def test_get_validates_first(tmp_path):
    result = run(write(tmp_path, VALID + "[extra]\n"), "get", "coder.name")
    assert result.returncode == 1
    assert result.stdout == ""


# Criterion 5: export, with eval in bash 3.2.


def test_export_prints_the_thirteen_names_in_order(tmp_path):
    result = run(write(tmp_path, VALID), "export")
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert [line.split("=", 1)[0] for line in lines] == NAMES
    assert lines[0] == "PRIMARY='/work/project'"
    assert "HUMAN='Rob Bastian'" in lines


def test_export_round_trips_through_bash_3_2_eval(tmp_path):
    awkward = {
        "human": 'Rob O\'Brien [the human] $HOME `id` \\ "q"',
        "coder_model": "glm-fast-latest[1m]",
        "reviewer_model": "it's   two  spaces*",
    }
    text = (
        VALID.replace('human = "Rob Bastian"', f"human = '''{awkward['human']}'''")
        .replace('engine = "claude"', 'engine = "fw"')
        .replace('"claude-opus-5-5"', f'"{awkward["coder_model"]}"')
        .replace('"gpt-5.5"', f'"{awkward["reviewer_model"]}"')
    )
    path = write(tmp_path, text)
    script = (
        f'eval "$("{sys.executable}" "{CONFIG}" --file "{path}" export)" || exit 9\n'
        'printf "%s\\n" "$HUMAN" "$CODER_MODEL" "$REVIEWER_MODEL" "$CODER_ENGINE"\n'
    )
    bash = "/bin/bash" if Path("/bin/bash").exists() else "bash"
    result = subprocess.run(
        [bash, "--norc", "-c", script], check=False, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        awkward["human"],
        awkward["coder_model"],
        awkward["reviewer_model"],
        "fw",
    ]


def test_export_validates_first(tmp_path):
    result = run(write(tmp_path, VALID + "[extra]\n"), "export")
    assert result.returncode == 1
    assert result.stdout == ""


# Criterion 6: roles.


def test_roles_prints_the_heading_and_one_bash_block(tmp_path):
    result = run(write(tmp_path, VALID), "roles")
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert lines[0] == "## Roles and paths"
    assert lines[1] == ""
    assert lines[2] == "```bash"
    assert lines[-1] == "```"
    assert result.stdout.count("```") == 2
    body = lines[3:-1]
    assert [line.split("=", 1)[0] for line in body] == NAMES
    assert "HUMAN=Rob Bastian" in body
    assert "PRIMARY=/work/project" in body
    assert "REVIEWER_ENGINE=codex" in body


def test_roles_validates_first(tmp_path):
    result = run(write(tmp_path, VALID + "[extra]\n"), "roles")
    assert result.returncode == 1
    assert result.stdout == ""


# Criterion 7: the Python API.


def test_load_returns_defaults(tmp_path):
    loaded = config.load(write(tmp_path, MINIMAL))
    assert loaded == {
        "project": {
            "primary": "/work/project",
            "bead_prefix": "lpe",
            "human": "Rob Bastian",
        },
        "ship": {"mode": "local", "github_account": ""},
        "coder": {
            "name": "Ralph",
            "engine": "claude",
            "model": "",
            "worktree": "/work/project-ralph",
        },
        "reviewer": {
            "name": "Alice",
            "engine": "claude",
            "model": "",
            "worktree": "/work/project-alice",
        },
    }


def test_load_raises_config_error_with_the_error_list(tmp_path):
    text = VALID.replace('mode = "pr"', 'mode = "push"') + "[extra]\n"
    with pytest.raises(config.ConfigError) as info:
        config.load(write(tmp_path, text))
    assert info.value.errors == [
        "loop.toml: extra: unknown table",
        "loop.toml: ship.mode: must be pr or local (got: push)",
    ]
    assert str(info.value) == "\n".join(info.value.errors)


# Criterion 8: harness-files.


def test_harness_files_lists_config_py():
    names = (ROOT / "harness-files").read_text().split()
    assert "config.py" in names


# Criterion 9: the README.


def test_readme_documents_the_schema_and_subcommands():
    readme = (ROOT / "README.md").read_text()
    assert "## Configuration" in readme
    section = readme.split("## Configuration", 1)[1].split("\n## ", 1)[0]
    for table in ("[project]", "[ship]", "[coder]", "[reviewer]"):
        assert table in section
    for sub in ("check", "get", "export", "roles"):
        assert f"config.py {sub}" in section
