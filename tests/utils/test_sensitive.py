"""Tests for nanobot.utils.sensitive — regex coverage for MIT-139 gaps."""

from __future__ import annotations

import pytest

from nanobot.utils.sensitive import (
    check_shell_command,
    is_sensitive_path,
)


# ---------------------------------------------------------------------------
# Shell command pre-screening — MIT-139 Gap A: absolute SSH paths
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        # Absolute paths (the bug MIT-139 fixes)
        "cat /home/mihai/.ssh/id_rsa",
        "cat /root/.ssh/id_rsa",
        "cat /Users/alice/.ssh/id_ed25519",
        # Home-relative
        "cat ~/.ssh/id_rsa",
        # Bare
        "cat .ssh/id_rsa",
        # Dot-relative
        "cat ./.ssh/id_rsa",
        # Case-insensitive command
        "CAT /home/mihai/.ssh/id_rsa",
        # Other reader tools — same gap, same fix
        "less /home/mihai/.ssh/id_rsa",
        "more /home/mihai/.ssh/config",
        "head /home/mihai/.ssh/id_rsa",
        "tail /root/.ssh/authorized_keys",
        "bat /home/mihai/.ssh/id_ed25519",
        "vim /home/mihai/.ssh/id_rsa",
        "vi /home/mihai/.ssh/id_rsa",
        "view /home/mihai/.ssh/id_rsa",
        "nano /home/mihai/.ssh/id_rsa",
        # Exfiltration variants
        "base64 /home/mihai/.ssh/id_rsa",
        "xxd /home/mihai/.ssh/id_rsa",
        "od /home/mihai/.ssh/id_rsa",
        "hexdump /home/mihai/.ssh/id_rsa",
    ],
)
def test_check_shell_command_blocks_ssh_paths(command: str) -> None:
    """All variants of reading .ssh/ — absolute, home, relative, bare — must be blocked."""
    result = check_shell_command(command)
    assert result is not None, f"Expected block for: {command!r}"
    assert "blocked by security policy" in result


@pytest.mark.parametrize(
    "command",
    [
        # Pre-MIT-139 cases must still block (regression guard)
        "cat ~/.ssh/id_rsa",
        "cat /etc/shadow",
        "cat .env",
        "cat /path/to/app.pem",
        "cat secrets.key",
        "cat /home/user/credentials.json",
        "less ~/.ssh/config",
        "less /etc/shadow",
        "base64 ~/.ssh/id_rsa",
        "base64 foo.pem",
        "base64 app.key",
        "xxd ~/.ssh/id_ed25519",
        "printenv",
        "env",
        "export -p",
        "declare -x",
        "ssh-add -l",
        "ssh-add -L",
        "gpg --export-secret-keys",
    ],
)
def test_check_shell_command_preserves_existing_blocks(command: str) -> None:
    """Existing MIT-123-era denials must keep working after MIT-139 widening."""
    assert check_shell_command(command) is not None, f"Regression: expected block for: {command!r}"


@pytest.mark.parametrize(
    "command",
    [
        # Ordinary commands must not be caught by the widened pattern
        "cat README.md",
        "cat /etc/hostname",
        "ls /home/mihai/.ssh",  # listing is out of scope — only content reads are blocked
        "echo hello",
        "grep TODO src/",
        "env VAR=value some_cmd",  # 'env' as prefix command, not dumper
        "cat /home/mihai/notes.txt",
        "less /var/log/syslog",
        "head -n 10 data.csv",
        # `.ssh` as a substring, not as a path segment, must not trigger
        "cat foo.sshkey",  # no '/' boundary
    ],
)
def test_check_shell_command_allows_benign_commands(command: str) -> None:
    """Widened patterns must not regress into false positives."""
    assert check_shell_command(command) is None, f"False positive for: {command!r}"


# ---------------------------------------------------------------------------
# Sensitive filename — MIT-139 Gap B: decision documented narrow
# ---------------------------------------------------------------------------


def test_dotenv_variants_blocked() -> None:
    """Files whose basename begins with .env — the canonical cases — must block."""
    assert is_sensitive_path(".env") is True
    assert is_sensitive_path("/home/mihai/project/.env") is True
    assert is_sensitive_path("/home/mihai/project/.env.local") is True
    assert is_sensitive_path("/home/mihai/project/.env.production") is True


def test_env_suffix_filenames_not_broadly_blocked() -> None:
    """MIT-139 decision: keep the `.env` regex narrow to filename-starts-with-.env.

    Widening to `*.env` would catch legitimate fixtures (`example.env`,
    `template.env`, documentation samples).  Operators who need to block
    custom-named dotenv files (e.g. `secrets/app.env`) should add the
    containing directory to `_SENSITIVE_PATH_PATTERNS` rather than broaden
    the filename regex.
    """
    # Not blocked by filename alone — documented as intentional
    assert is_sensitive_path("/tmp/example.env") is False
    assert is_sensitive_path("/tmp/template.env") is False


def test_sensitive_paths_still_caught() -> None:
    """Regression: unrelated sensitive paths must still be caught."""
    assert is_sensitive_path("/home/mihai/.ssh/id_rsa") is True
    assert is_sensitive_path("/etc/shadow") is True
    assert is_sensitive_path("/home/mihai/.aws/credentials") is True
    assert is_sensitive_path("/home/mihai/project/server.pem") is True
    assert is_sensitive_path("/home/mihai/project/server.key") is True


def test_ordinary_paths_not_flagged() -> None:
    """No false positives on regular source files."""
    assert is_sensitive_path("/home/mihai/project/main.py") is False
    assert is_sensitive_path("/home/mihai/project/README.md") is False


# ---------------------------------------------------------------------------
# MIT-140: narrow id_*.pub exclusion from sensitive filename patterns
#
# Public SSH keys (id_*.pub) are, by definition, safe to disclose — agents
# legitimately need to read them to deploy authorized_keys, configure CI
# runners, etc.  The filename-only regex must block bare private-key names
# while allowing `.pub` siblings.  Private keys *inside* `~/.ssh/` are still
# blocked by the separate `/.ssh/` path-prefix rule, which catches public
# AND private alike — callers who need to read `id_*.pub` should keep the
# file outside `~/.ssh/`, or the block will (correctly) fire anyway.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "filename",
    [
        "id_rsa",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
        "/tmp/keys/id_rsa",
        "/tmp/keys/id_ed25519",
    ],
)
def test_ssh_private_key_filenames_still_blocked(filename: str) -> None:
    """MIT-140: bare SSH private-key filenames remain blocked regardless of directory."""
    assert is_sensitive_path(filename) is True, f"Expected block for: {filename!r}"


@pytest.mark.parametrize(
    "filename",
    [
        "id_rsa.pub",
        "id_dsa.pub",
        "id_ecdsa.pub",
        "id_ed25519.pub",
        "/tmp/keys/id_rsa.pub",
        "/tmp/keys/id_ed25519.pub",
    ],
)
def test_ssh_public_key_filenames_allowed_outside_ssh_dir(filename: str) -> None:
    """MIT-140: `.pub` siblings of SSH keys are public info — filename regex must allow them.

    (Files under `~/.ssh/` are still caught by the `/.ssh/` path-prefix rule,
    which is intentional — the filename regex itself should not block `.pub`.)
    """
    assert is_sensitive_path(filename) is False, f"Unexpected block for: {filename!r}"


def test_ssh_public_key_inside_ssh_dir_still_blocked_by_path_rule() -> None:
    """Regression: `.pub` files inside `~/.ssh/` stay blocked via the path-prefix rule.

    The filename rule now permits `id_*.pub`, but the `/.ssh/` path prefix in
    `_SENSITIVE_PATH_PATTERNS` catches anything under the SSH directory.  This
    is the defence-in-depth split MIT-140 documents.
    """
    assert is_sensitive_path("/home/mihai/.ssh/id_rsa.pub") is True
    assert is_sensitive_path("/root/.ssh/id_ed25519.pub") is True
