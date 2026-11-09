"""Tests for the fw launcher and its documentation (lpe-6v6.4)."""

import json
import os
import py_compile
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from test_review_method import section
from test_run_watchdog import write_exe

ROOT = Path(__file__).resolve().parents[2]
FW = ROOT / "tools" / "fw"
LOCAL_FW = Path.home() / ".local" / "bin" / "fw"
COMMENT_BLOCK = (
    b"# Session-only Fireworks launcher for the loop's fw engine.\n"
    b"# This repository's copy of ~/.local/bin/fw, copied 2026-11-09.\n"
)


def test_tools_fw_matches_the_local_launcher_apart_from_its_comment_block():
    if not LOCAL_FW.exists():
        pytest.skip("~/.local/bin/fw is not installed")

    shipped = FW.read_bytes()
    assert shipped.startswith(b"#!/usr/bin/env python3\n" + COMMENT_BLOCK)
    assert shipped.replace(COMMENT_BLOCK, b"", 1) == LOCAL_FW.read_bytes()


def test_tools_fw_is_executable_and_compiles(tmp_path):
    assert FW.stat().st_mode & stat.S_IXUSR
    py_compile.compile(str(FW), cfile=str(tmp_path / "fw.pyc"), doraise=True)


def run_fw_check(tmp_path, api_key):
    binary = tmp_path / "bin"
    binary.mkdir()
    write_exe(binary / "claude", "exit 0\n")
    env = os.environ.copy()
    env["PATH"] = str(binary)
    env["FIREWORKS_API_KEY"] = api_key

    return subprocess.run(
        [sys.executable, str(FW), "--model", "test-model", "--check"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_fw_check_accepts_a_fake_claude_and_an_api_key(tmp_path):
    result = run_fw_check(tmp_path, "test-key")

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["claude"] == str(tmp_path / "bin" / "claude")
    assert report["model"] == "test-model"
    assert report["keySource"] == "FIREWORKS_API_KEY"


def test_fw_check_reports_a_missing_key_when_nexus_is_missing(tmp_path):
    result = run_fw_check(tmp_path, "")

    assert result.returncode == 2
    assert "fw: Set FIREWORKS_API_KEY" in result.stderr
    assert "nexus login" in result.stderr


def test_setup_skill_offers_to_copy_fw_with_consent():
    skill = (ROOT / "skills" / "dev-env-setup" / "SKILL.md").read_text()

    assert "copy `tools/fw` to `~/.local/bin/fw`" in skill
    assert "Ask the user before the copy." in skill
    assert "Do not copy it without the user's consent." in skill


def test_fw_documentation_covers_configuration_costs_limits_and_trials():
    readme = (ROOT / "loop" / "README.md").read_text()
    text = section(readme, "Running an agent on Fireworks (fw)")

    for required in (
        "FIREWORKS_API_KEY",
        "tools/fw",
        "prices.json",
        "cc@fw",
        "kimi-k3p1-pro",
        "glm-fast-latest",
    ):
        assert required in text


def test_root_readme_links_to_the_fw_documentation():
    readme = (ROOT / "README.md").read_text()

    assert "loop/README.md#running-an-agent-on-fireworks-fw" in readme
