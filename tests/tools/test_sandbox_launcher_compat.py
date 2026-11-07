"""Regression coverage for nonstandard sandbox launcher installations."""

import os

from nanobot.agent.tools.shell import ExecTool


async def test_nonstandard_bwrap_is_not_silently_run_without_sandbox(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    extra_bin = tmp_path / "extra-bin"
    extra_bin.mkdir()
    default_bin = tmp_path / "system-bin"
    default_bin.mkdir()
    launcher = extra_bin / "bwrap"
    launcher.write_text("#!/bin/sh\nprintf launched > \"$1\"\n")
    launcher.chmod(0o700)
    marker = workspace / "command-ran"

    monkeypatch.setattr("nanobot.agent.tools.shell._IS_WINDOWS", False)
    monkeypatch.setattr(os, "defpath", str(default_bin))
    monkeypatch.setenv("PATH", str(extra_bin))
    monkeypatch.setattr("nanobot.agent.tools.sandbox.get_media_dir", lambda: workspace)
    tool = ExecTool(working_dir=str(workspace), sandbox="bwrap")

    result = await tool.execute(command="printf ran > command-ran")

    assert "sandbox launcher not found: bwrap" in result
    assert not marker.exists()
