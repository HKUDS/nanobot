"""Tests for nanobot.agent.tools.sandbox."""

import shlex
from pathlib import Path

import pytest

from nanobot.agent.tools.sandbox import _sbpl_quote, _seatbelt_is_within, wrap_command


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

    def test_home_env_points_to_workspace(self, tmp_path):
        ws = str(tmp_path / "project")
        result = wrap_command("bwrap", "echo $HOME", ws, ws)
        tokens = _parse(result)

        setenv_idx = [i for i, t in enumerate(tokens) if t == "--setenv"]
        assert any(
            tokens[i + 1] == "HOME" and tokens[i + 2] == str(tmp_path / "project")
            for i in setenv_idx
        )

    def test_parent_dir_masked_with_tmpfs(self, tmp_path):
        ws = tmp_path / "project"
        result = wrap_command("bwrap", "ls", str(ws), str(ws))
        tokens = _parse(result)

        tmpfs_indices = [i for i, t in enumerate(tokens) if t == "--tmpfs"]
        tmpfs_targets = {tokens[i + 1] for i in tmpfs_indices}
        assert str(ws.parent) in tmpfs_targets

    def test_tmp_dir_mounted_as_tmpfs(self, tmp_path):
        """Regression coverage for #1948: commands need writable scratch space."""
        ws = tmp_path / "project"
        result = wrap_command("bwrap", "touch /tmp/probe", str(ws), str(ws))
        tokens = _parse(result)

        tmpfs_indices = [i for i, t in enumerate(tokens) if t == "--tmpfs"]
        tmpfs_targets = {tokens[i + 1] for i in tmpfs_indices}
        assert "/tmp" in tmpfs_targets

    def test_parent_mask_precedes_workspace_recreation(self, tmp_path):
        ws = tmp_path / "project"
        result = wrap_command("bwrap", "ls", str(ws), str(ws))
        tokens = _parse(result)

        parent_mask = next(
            i for i, t in enumerate(tokens)
            if t == "--tmpfs" and tokens[i + 1] == str(ws.parent)
        )
        workspace_dir = next(
            i for i, t in enumerate(tokens)
            if t == "--dir" and tokens[i + 1] == str(ws)
        )
        workspace_bind = next(
            i for i, t in enumerate(tokens)
            if t == "--bind" and tokens[i + 1] == str(ws) and tokens[i + 2] == str(ws)
        )
        chdir = tokens.index("--chdir")

        assert parent_mask < workspace_dir < workspace_bind < chdir

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

    def test_custom_read_only_binds_use_ro_bind_try(self, tmp_path):
        ws = tmp_path / "project"
        tool_bin = tmp_path / "home" / ".local" / "bin"

        result = wrap_command(
            "bwrap",
            "uv --version",
            str(ws),
            str(ws),
            sandbox_ro_binds=[str(tool_bin)],
        )
        tokens = _parse(result)

        try_indices = [i for i, t in enumerate(tokens) if t == "--ro-bind-try"]
        try_pairs = {(tokens[i + 1], tokens[i + 2]) for i in try_indices}
        assert (str(tool_bin.resolve(strict=False)), str(tool_bin.resolve(strict=False))) in try_pairs

    def test_custom_read_write_binds_use_bind_try(self, tmp_path):
        ws = tmp_path / "project"
        cache_dir = tmp_path / "cache"

        result = wrap_command(
            "bwrap",
            "touch cache/file",
            str(ws),
            str(ws),
            sandbox_rw_binds=[str(cache_dir)],
        )
        tokens = _parse(result)

        bind_try_indices = [i for i, t in enumerate(tokens) if t == "--bind-try"]
        bind_try_pairs = {(tokens[i + 1], tokens[i + 2]) for i in bind_try_indices}
        resolved = str(cache_dir.resolve(strict=False))
        assert (resolved, resolved) in bind_try_pairs

    def test_custom_relative_bind_paths_are_ignored(self, tmp_path):
        ws = tmp_path / "project"

        result = wrap_command(
            "bwrap",
            "ls",
            str(ws),
            str(ws),
            sandbox_ro_binds=["relative/bin"],
            sandbox_rw_binds=["relative/cache"],
        )
        tokens = _parse(result)

        assert "relative/bin" not in tokens
        assert "relative/cache" not in tokens

    def test_custom_workspace_parent_binds_are_ignored(self, tmp_path):
        ws = tmp_path / "private" / "project"
        parent = ws.parent.resolve(strict=False)

        result = wrap_command(
            "bwrap",
            "cat ../config.json",
            str(ws),
            str(ws),
            sandbox_ro_binds=[str(parent)],
            sandbox_rw_binds=[str(parent)],
        )
        tokens = _parse(result)

        ro_try_indices = [i for i, token in enumerate(tokens) if token == "--ro-bind-try"]
        ro_try_pairs = {(tokens[i + 1], tokens[i + 2]) for i in ro_try_indices}
        bind_try_indices = [i for i, token in enumerate(tokens) if token == "--bind-try"]
        bind_try_pairs = {(tokens[i + 1], tokens[i + 2]) for i in bind_try_indices}
        assert (str(parent), str(parent)) not in ro_try_pairs
        assert (str(parent), str(parent)) not in bind_try_pairs


class TestSeatbeltBackend:
    """macOS Seatbelt policy generation.

    These parse the generated ``sandbox-exec`` command line, so they run on any
    platform — the profile is only ever executed on macOS.
    """

    @staticmethod
    def _profile(cmd: str) -> str:
        """Return the SBPL profile from a wrapped command."""
        tokens = _parse(cmd)
        return tokens[tokens.index("-p") + 1]

    @staticmethod
    def _quote(path: object) -> str:
        """Render *path* as expected in the generated SBPL profile."""
        return _sbpl_quote(str(path))

    @staticmethod
    def _metadata_rule(profile: str) -> str:
        return next(
            line
            for line in profile.splitlines()
            if line.startswith("(allow file-read-metadata ")
        )

    def test_basic_structure(self, tmp_path):
        ws = str(tmp_path / "project")
        result = wrap_command("seatbelt", "echo hi", ws, ws)
        tokens = _parse(result)

        assert tokens[0] == "/usr/bin/sandbox-exec"
        assert tokens[1] == "-p"
        assert tokens[-3] == "sh"
        assert tokens[-2] == "-c"
        assert tokens[-1].endswith("echo hi")

    def test_denies_by_default(self, tmp_path):
        profile = self._profile(wrap_command("seatbelt", "ls", str(tmp_path), str(tmp_path)))

        assert "(version 1)" in profile
        assert "(deny default)" in profile

    def test_root_directory_is_readable(self, tmp_path):
        """sh(1) stats `/` at startup; without this rule the shell aborts.

        `(subpath "/usr")` does not cover the root directory itself, so a
        profile listing only system subpaths kills every wrapped command
        before it runs.
        """
        profile = self._profile(wrap_command("seatbelt", "ls", str(tmp_path), str(tmp_path)))

        assert '(allow file-read* (literal "/"))' in profile

    def test_workspace_allowed_read_write(self, tmp_path):
        ws = (tmp_path / "project").resolve()
        profile = self._profile(wrap_command("seatbelt", "ls", str(ws), str(ws)))

        assert f"(allow file-read* file-write* (subpath {self._quote(ws)}))" in profile

    def test_config_dir_denied_before_workspace_allow(self, tmp_path):
        """Last matching rule wins, so the parent deny must come first.

        The parent holds `config.json`; the workspace allow that follows
        re-exposes only the workspace subtree.
        """
        ws = (tmp_path / "project").resolve()
        profile = self._profile(wrap_command("seatbelt", "ls", str(ws), str(ws)))

        parent_deny = profile.index(f"(deny file-read* file-write* (subpath {self._quote(ws.parent)})")
        workspace_allow = profile.index(f"(allow file-read* file-write* (subpath {self._quote(ws)})")
        assert parent_deny < workspace_allow

    def test_no_parent_deny_when_workspace_is_the_root(self):
        """Denying `/` would override the root read rule and break startup."""
        profile = self._profile(wrap_command("seatbelt", "ls", "/", "/"))

        assert "(deny file-read*" not in profile

    def test_workspace_ancestors_stay_searchable(self, tmp_path):
        """Masking the config dir must not break resolution into the workspace.

        Seatbelt checks every path component while resolving, so without
        metadata on the parent the wrapped command dies with ENOTDIR before it
        runs anything.
        """
        ws = (tmp_path / "project").resolve()
        profile = self._profile(wrap_command("seatbelt", "ls", str(ws), str(ws)))

        assert f"(literal {self._quote(ws.parent)})" in self._metadata_rule(profile)

    def test_config_dir_is_searchable_but_not_listable(self, tmp_path):
        """Metadata only: `cd workspace` works, `ls ..` and `cat ../config.json` do not."""
        ws = (tmp_path / "project").resolve()
        profile = self._profile(wrap_command("seatbelt", "ls", str(ws), str(ws)))

        assert f"(literal {self._quote(ws.parent)})" in self._metadata_rule(profile)
        assert f"(allow file-read* (subpath {self._quote(ws.parent)}))" not in profile
        assert f"(allow file-read* file-write* (subpath {self._quote(ws.parent)}))" not in profile

    def test_host_scratch_directories_are_not_shared(self, tmp_path):
        profile = self._profile(wrap_command("seatbelt", "ls", str(tmp_path), str(tmp_path)))

        for path in ("/tmp", "/private/tmp", "/var", "/private/var", "/var/folders",
                     "/private/var/folders", "/Library", "/etc", "/private/etc"):
            assert f'(subpath "{path}")' not in profile

    def test_home_and_tmpdir_use_workspace(self, tmp_path):
        ws = tmp_path.resolve()
        tokens = _parse(wrap_command("seatbelt", "mktemp", str(ws), str(ws)))
        assert tokens[3:6] == ["/usr/bin/env", f"HOME={ws}", f"TMPDIR={ws}"]

    def test_network_matches_bwrap_policy(self, tmp_path):
        profile = self._profile(wrap_command("seatbelt", "ls", str(tmp_path), str(tmp_path)))
        assert "(allow network*)" in profile

    def test_media_dir_read_only(self, tmp_path, monkeypatch):
        fake_media = (tmp_path / "media").resolve()
        fake_media.mkdir()
        monkeypatch.setattr(
            "nanobot.agent.tools.sandbox.get_media_dir",
            lambda: fake_media,
        )
        ws = (tmp_path / "project").resolve()
        profile = self._profile(wrap_command("seatbelt", "ls", str(ws), str(ws)))

        assert f"(allow file-read* (subpath {self._quote(fake_media)}))" in profile
        assert f"(deny file-write* (subpath {self._quote(fake_media)}))" in profile

    def test_cwd_inside_workspace(self, tmp_path):
        ws = (tmp_path / "project").resolve()
        sub = ws / "src" / "lib"
        result = wrap_command("seatbelt", "pwd", str(ws), str(sub))

        assert _parse(result)[-1] == f"cd {shlex.quote(str(sub))} || exit\npwd"

    def test_cwd_outside_workspace_falls_back(self, tmp_path):
        ws = (tmp_path / "project").resolve()
        outside = tmp_path / "other"
        result = wrap_command("seatbelt", "pwd", str(ws), str(outside))

        assert _parse(result)[-1] == f"cd {shlex.quote(str(ws))} || exit\npwd"

    def test_custom_read_only_binds(self, tmp_path):
        ws = (tmp_path / "project").resolve()
        tool_bin = (tmp_path / "home" / ".local" / "bin").resolve(strict=False)

        profile = self._profile(
            wrap_command(
                "seatbelt", "uv --version", str(ws), str(ws),
                sandbox_ro_binds=[str(tool_bin)],
            )
        )

        assert f"(allow file-read* (subpath {self._quote(tool_bin)}))" in profile
        assert f"(deny file-write* (subpath {self._quote(tool_bin)}))" in profile

    def test_read_only_bind_overrides_workspace_write(self, tmp_path):
        ws = tmp_path.resolve()
        ro = ws / "readonly"
        profile = self._profile(wrap_command(
            "seatbelt", "ls", str(ws), str(ws), sandbox_ro_binds=[str(ro)],
        ))
        assert profile.index(f"(allow file-read* file-write* (subpath {self._quote(ws)}))") < (
            profile.index(f"(deny file-write* (subpath {self._quote(ro)}))")
        )

    @pytest.mark.parametrize("source", ["bind", "media"])
    def test_readonly_ancestors_cannot_be_unlinked(self, tmp_path, monkeypatch, source):
        ws = (tmp_path / "workspace").resolve()
        ro = ws / 'tree with "quotes' / "branch" / "readonly"
        media = ro if source == "media" else tmp_path / "media"
        monkeypatch.setattr("nanobot.agent.tools.sandbox.get_media_dir", lambda: media)
        profile = self._profile(wrap_command(
            "seatbelt", "ls", str(ws), str(ws),
            sandbox_ro_binds=[str(ro)] if source == "bind" else [],
        ))

        rule = profile.splitlines()[-1]
        assert rule.startswith("(deny file-write-unlink ")
        for parent in ro.parents:
            assert f"(literal {self._quote(parent)})" in rule
        assert "subpath" not in rule

    @pytest.mark.parametrize("override", ["root", "parent", "child"])
    def test_rw_override_only_unlocks_fully_covered_roots(self, tmp_path, monkeypatch, override):
        ws = (tmp_path / "workspace").resolve()
        ro = ws / "tree" / "readonly"
        rw = {"root": ro, "parent": ro.parent, "child": ro / "cache"}[override]
        monkeypatch.setattr("nanobot.agent.tools.sandbox.get_media_dir", lambda: ro)
        profile = self._profile(wrap_command(
            "seatbelt", "ls", str(ws), str(ws),
            sandbox_ro_binds=[str(ro)], sandbox_rw_binds=[str(rw)],
        ))

        if override == "child":
            assert profile.splitlines()[-1].startswith("(deny file-write-unlink ")
            assert f"(literal {self._quote(ro.parent)})" in profile.splitlines()[-1]
        else:
            assert "(deny file-write-unlink " not in profile

    @pytest.mark.parametrize("same_directory", [True, False])
    def test_rw_coverage_uses_filesystem_identity(self, tmp_path, monkeypatch, same_directory):
        ro = tmp_path / "Tree" / "ReadOnly"
        rw = tmp_path / "tree"
        monkeypatch.setattr(
            Path, "samefile",
            lambda path, other: same_directory and path == ro.parent and other == rw,
        )
        assert _seatbelt_is_within(ro, rw) is same_directory

    def test_missing_rw_alias_does_not_unlock_readonly_root(self, tmp_path):
        ro = tmp_path / "missing" / "readonly"
        assert not _seatbelt_is_within(ro, tmp_path / "MISSING")
        assert _seatbelt_is_within(ro, ro.parent)

    def test_custom_read_write_binds(self, tmp_path):
        ws = (tmp_path / "project").resolve()
        cache_dir = (tmp_path / "cache").resolve(strict=False)

        profile = self._profile(
            wrap_command(
                "seatbelt", "touch cache/file", str(ws), str(ws),
                sandbox_rw_binds=[str(cache_dir)],
            )
        )

        assert f"(allow file-read* file-write* (subpath {self._quote(cache_dir)}))" in profile

    def test_custom_workspace_parent_binds_are_ignored(self, tmp_path):
        """A bind must not uncover the masked config directory."""
        ws = tmp_path / "private" / "project"
        parent = ws.parent.resolve(strict=False)

        profile = self._profile(
            wrap_command(
                "seatbelt", "cat ../config.json", str(ws), str(ws),
                sandbox_ro_binds=[str(parent)],
                sandbox_rw_binds=[str(parent)],
            )
        )

        assert f"(allow file-read* (subpath {self._quote(parent)}))" not in profile
        assert f"(allow file-read* file-write* (subpath {self._quote(parent)}))" not in profile

    def test_paths_with_quotes_are_escaped(self, tmp_path):
        """An unescaped quote would terminate the literal early and silently
        widen every rule that follows it."""
        ws = (tmp_path / 'pro"ject').resolve()
        profile = self._profile(wrap_command("seatbelt", "ls", str(ws), str(ws)))

        escaped = str(ws).replace("\\", "\\\\").replace('"', '\\"')
        assert f'(allow file-read* file-write* (subpath "{escaped}"))' in profile

    def test_sbpl_quote_escapes_special_characters(self):
        """Backslashes and double quotes must be escaped with C-style escaping."""
        assert _sbpl_quote(r'path\with"quotes') == r'"path\\with\"quotes"'


class TestUnknownBackend:
    def test_raises_value_error(self, tmp_path):
        ws = str(tmp_path / "project")
        with pytest.raises(ValueError, match="Unknown sandbox backend"):
            wrap_command("nonexistent", "ls", ws, ws)

    def test_empty_string_raises(self, tmp_path):
        ws = str(tmp_path / "project")
        with pytest.raises(ValueError):
            wrap_command("", "ls", ws, ws)
