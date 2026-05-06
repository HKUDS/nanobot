"""Tests for nanobot.agent.tools.sandbox."""

import shlex
import sys

import pytest

from nanobot.agent.tools.sandbox import wrap_command

_SKIP_WINDOWS = pytest.mark.skipif(
    sys.platform == "win32",
    reason="bwrap sandbox is Linux-only",
)


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


@_SKIP_WINDOWS
class TestUserBinds:
    def test_default_no_extra_binds(self, tmp_path):
        ws = str(tmp_path / "project")
        result = wrap_command("bwrap", "ls", ws, ws)
        tokens = _parse(result)

        # Without extras, /opt/foo should not appear anywhere.
        assert "/opt/foo" not in tokens

    def test_ro_binds_appended_strict(self, tmp_path):
        ws = str(tmp_path / "project")
        result = wrap_command(
            "bwrap", "ls", ws, ws,
            binds_ro=["/opt/toolchain", "/etc/pip.conf"],
        )
        tokens = _parse(result)

        ro_pairs = {(tokens[i + 1], tokens[i + 2])
                    for i, t in enumerate(tokens) if t == "--ro-bind"}
        assert ("/opt/toolchain", "/opt/toolchain") in ro_pairs
        assert ("/etc/pip.conf",  "/etc/pip.conf")  in ro_pairs

        # Strict: user paths use --ro-bind, never --ro-bind-try.
        try_pairs = {(tokens[i + 1], tokens[i + 2])
                     for i, t in enumerate(tokens) if t == "--ro-bind-try"}
        assert ("/opt/toolchain", "/opt/toolchain") not in try_pairs

    def test_rw_binds_appended_strict(self, tmp_path):
        ws = str(tmp_path / "project")
        result = wrap_command(
            "bwrap", "ls", ws, ws,
            binds_rw=["/var/cache/builds"],
        )
        tokens = _parse(result)

        bind_pairs = {(tokens[i + 1], tokens[i + 2])
                      for i, t in enumerate(tokens) if t == "--bind"}
        assert ("/var/cache/builds", "/var/cache/builds") in bind_pairs

    def test_user_binds_before_chdir(self, tmp_path):
        """User binds must be emitted before --chdir so bwrap mounts before cd."""
        ws = str(tmp_path / "project")
        result = wrap_command(
            "bwrap", "ls", ws, ws,
            binds_ro=["/opt/x"], binds_rw=["/opt/y"],
        )
        tokens = _parse(result)
        chdir_idx = tokens.index("--chdir")
        # The bind targets appear at i+1; check they precede --chdir.
        ro_idx = next(i for i, t in enumerate(tokens)
                      if t == "--ro-bind" and tokens[i + 1] == "/opt/x")
        rw_idx = next(i for i, t in enumerate(tokens)
                      if t == "--bind" and tokens[i + 1] == "/opt/y")
        assert ro_idx < chdir_idx
        assert rw_idx < chdir_idx


class TestUnknownBackend:
    def test_raises_value_error(self, tmp_path):
        ws = str(tmp_path / "project")
        with pytest.raises(ValueError, match="Unknown sandbox backend"):
            wrap_command("nonexistent", "ls", ws, ws)

    def test_empty_string_raises(self, tmp_path):
        ws = str(tmp_path / "project")
        with pytest.raises(ValueError):
            wrap_command("", "ls", ws, ws)


@_SKIP_WINDOWS
class TestSandboxBindsConfig:
    """ExecToolConfig must reject relative or empty bind paths up front."""

    def test_relative_ro_path_rejected(self):
        from nanobot.config.schema import ExecToolConfig
        with pytest.raises(ValueError, match="must be absolute"):
            ExecToolConfig(sandbox_binds_ro=["relative/path"])

    def test_relative_rw_path_rejected(self):
        from nanobot.config.schema import ExecToolConfig
        with pytest.raises(ValueError, match="must be absolute"):
            ExecToolConfig(sandbox_binds_rw=["./cache"])

    def test_empty_string_rejected(self):
        from nanobot.config.schema import ExecToolConfig
        with pytest.raises(ValueError):
            ExecToolConfig(sandbox_binds_ro=[""])

    def test_absolute_paths_accepted(self):
        from nanobot.config.schema import ExecToolConfig
        cfg = ExecToolConfig(
            sandbox_binds_ro=["/opt/toolchain"],
            sandbox_binds_rw=["/var/cache/builds"],
        )
        assert cfg.sandbox_binds_ro == ["/opt/toolchain"]
        assert cfg.sandbox_binds_rw == ["/var/cache/builds"]

    def test_camel_case_alias(self):
        """Config files use camelCase keys via the Base alias generator."""
        from nanobot.config.schema import ExecToolConfig
        cfg = ExecToolConfig.model_validate({
            "sandboxBindsRo": ["/opt/x"],
            "sandboxBindsRw": ["/var/y"],
        })
        assert cfg.sandbox_binds_ro == ["/opt/x"]
        assert cfg.sandbox_binds_rw == ["/var/y"]
