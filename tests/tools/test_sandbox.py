"""Tests for nanobot.agent.tools.sandbox."""

import shlex

import pytest

from nanobot.agent.tools.sandbox import wrap_command


def _parse(cmd: str) -> list[str]:
    """Split a wrapped command back into tokens for assertion."""
    return shlex.split(cmd)


class TestBwrapBackend:
    def test_basic_structure(self, tmp_path):
        ws = str(tmp_path / "project")
        result = wrap_command("bwrap", "echo hi", ws, ws)
        tokens = _parse(result)

        assert tokens[0] == "bwrap"
        assert "--new-session" in tokens
        assert "--die-with-parent" in tokens
        assert "--ro-bind" in tokens
        assert "--proc" in tokens
        assert "--dev" in tokens
        assert "--tmpfs" in tokens

        sep = tokens.index("--")
        assert tokens[sep + 1:] == ["sh", "-c", "echo hi"]

    def test_workspace_bind_mounted_rw(self, tmp_path):
        ws = str(tmp_path / "project")
        result = wrap_command("bwrap", "ls", ws, ws)
        tokens = _parse(result)

        bind_idx = [i for i, t in enumerate(tokens) if t == "--bind"]
        assert any(tokens[i + 1] == ws and tokens[i + 2] == ws for i in bind_idx)

    def test_parent_dir_masked_with_tmpfs(self, tmp_path):
        ws = tmp_path / "project"
        result = wrap_command("bwrap", "ls", str(ws), str(ws))
        tokens = _parse(result)

        tmpfs_indices = [i for i, t in enumerate(tokens) if t == "--tmpfs"]
        tmpfs_targets = {tokens[i + 1] for i in tmpfs_indices}
        assert str(ws.parent) in tmpfs_targets

    def test_cwd_inside_workspace(self, tmp_path):
        ws = tmp_path / "project"
        sub = ws / "src" / "lib"
        result = wrap_command("bwrap", "pwd", str(ws), str(sub))
        tokens = _parse(result)

        chdir_idx = tokens.index("--chdir")
        assert tokens[chdir_idx + 1] == str(sub)

    def test_cwd_outside_workspace_falls_back(self, tmp_path):
        ws = tmp_path / "project"
        outside = tmp_path / "other"
        result = wrap_command("bwrap", "pwd", str(ws), str(outside))
        tokens = _parse(result)

        chdir_idx = tokens.index("--chdir")
        assert tokens[chdir_idx + 1] == str(ws.resolve())

    def test_command_with_special_characters(self, tmp_path):
        ws = str(tmp_path / "project")
        cmd = "echo 'hello world' && cat \"file with spaces.txt\""
        result = wrap_command("bwrap", cmd, ws, ws)
        tokens = _parse(result)

        sep = tokens.index("--")
        assert tokens[sep + 1:] == ["sh", "-c", cmd]

    def test_system_dirs_ro_bound(self, tmp_path):
        ws = str(tmp_path / "project")
        result = wrap_command("bwrap", "ls", ws, ws)
        tokens = _parse(result)

        ro_bind_indices = [i for i, t in enumerate(tokens) if t == "--ro-bind"]
        ro_targets = {tokens[i + 1] for i in ro_bind_indices}
        assert "/usr" in ro_targets

    def test_optional_dirs_use_ro_bind_try(self, tmp_path):
        ws = str(tmp_path / "project")
        result = wrap_command("bwrap", "ls", ws, ws)
        tokens = _parse(result)

        try_indices = [i for i, t in enumerate(tokens) if t == "--ro-bind-try"]
        try_targets = {tokens[i + 1] for i in try_indices}
        assert "/bin" in try_targets
        assert "/etc/ssl/certs" in try_targets

    def test_media_dir_ro_bind(self, tmp_path, monkeypatch):
        """Media directory should be read-only mounted inside the sandbox."""
        fake_media = tmp_path / "media"
        fake_media.mkdir()
        monkeypatch.setattr(
            "nanobot.agent.tools.sandbox.get_media_dir",
            lambda: fake_media,
        )
        ws = str(tmp_path / "project")
        result = wrap_command("bwrap", "ls", ws, ws)
        tokens = _parse(result)

        try_indices = [i for i, t in enumerate(tokens) if t == "--ro-bind-try"]
        try_pairs = {(tokens[i + 1], tokens[i + 2]) for i in try_indices}
        assert (str(fake_media), str(fake_media)) in try_pairs


class TestUnknownBackend:
    def test_raises_value_error(self, tmp_path):
        ws = str(tmp_path / "project")
        with pytest.raises(ValueError, match="Unknown sandbox backend"):
            wrap_command("nonexistent", "ls", ws, ws)

    def test_empty_string_raises(self, tmp_path):
        ws = str(tmp_path / "project")
        with pytest.raises(ValueError):
            wrap_command("", "ls", ws, ws)
