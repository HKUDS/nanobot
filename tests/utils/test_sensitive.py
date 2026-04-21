"""Tests for nanobot.utils.sensitive — regex coverage for MIT-139 gaps."""

from __future__ import annotations

import pytest

from nanobot.utils.sensitive import (
    check_shell_command,
    is_sensitive_path,
    redact_if_sensitive,
    scan_content,
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


# ---------------------------------------------------------------------------
# MIT-148: HTTP Authorization Bearer header detection
#
# The pre-MIT-148 labeled-credential regex matched `bearer=token` or
# `bearer: token` shapes, but NOT the real-world HTTP header
# `Authorization: Bearer <token>` — `Bearer` is the *prefix* of the token,
# not a label followed by `=` / `:`.  The new parallel pattern fills that
# gap without broadening the labeled regex (which, if widened, would catch
# too much ordinary prose / logs).
#
# Note on test fixtures: all Bearer-token literals below are deliberately
# synthetic and do NOT match any provider-specific secret shape (no
# `sk_live_`, `pk_`, `ghp_`, etc.). This avoids tripping GitHub's push
# protection secret scanner on what are clearly test-only strings.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        # Canonical HTTP header form with a JWT-shaped token
        "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.abc.def",
        # Header-less Bearer form (curl examples, middleware logs)
        "Bearer kid_abcdefghij1234567890",
        # Mid-line occurrence in a log line
        "2026-04-21 http POST /api Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9xxxxxxx 200",
        # With surrounding structured-output quotes — generic synthetic token
        'headers = {"Authorization": "Bearer tkn_fakefakefakefakefakefake"}',
    ],
)
def test_bearer_token_is_detected(text: str) -> None:
    """MIT-148: real-world Bearer-prefix tokens (20+ chars) must be flagged."""
    assert scan_content(text) == "bearer token", f"Expected bearer-token match for: {text!r}"


@pytest.mark.parametrize(
    "text",
    [
        # Documentation-style placeholders — too short to be a real token
        "Bearer short",
        "Bearer token",
        "Bearer xxx",
        "Bearer abc123",
        "Authorization: Bearer YOUR_TOKEN_HERE",  # 16 chars, under the 20-char floor
        # Prose usage of the word "bearer" unrelated to auth
        "The bearer of this letter is authorized to...",
        # Bearer followed by too-short token at end of string
        "Try: Bearer foo",
    ],
)
def test_bearer_placeholder_and_prose_not_flagged(text: str) -> None:
    """MIT-148: short placeholders (< 20 chars) and non-auth prose must not match."""
    # Either no match at all, or a match from a different pattern — just not "bearer token".
    assert scan_content(text) != "bearer token", f"False positive bearer-token for: {text!r}"


def test_bearer_redaction_output_shape() -> None:
    """The full redact_if_sensitive pipeline must replace the token with the REDACTED notice."""
    payload = "Authorization: Bearer eyJhbGciOiJIUzI1NiIs_abcdefghijklmnopqrst\n"
    result = redact_if_sensitive(payload)
    assert "eyJhbGciOiJIUzI1NiIs_abcdefghijklmnopqrst" not in result
    assert "REDACTED" in result
    assert "bearer token" in result


def test_existing_credential_patterns_still_match() -> None:
    """Regression: MIT-148 added a parallel pattern; existing detections must still fire."""
    # The labeled form — `bearer=<token>` — should still match (via the
    # pre-existing labeled-credential regex, now labeled "credential/token").
    # We only assert a match occurred; the label may be "credential/token"
    # OR "bearer token" depending on ordering, both are correct.
    assert scan_content("bearer=abcdefghij1234567890xxxx") is not None

    # AWS access key
    assert scan_content("AKIAABCDEFGHIJKLMNOP") == "AWS access key"
    # GitHub token
    assert scan_content("ghp_0123456789abcdef0123456789abcdef0123") == "GitHub token"
    # Private key blob
    assert scan_content("-----BEGIN RSA PRIVATE KEY-----\n...") == "private key"


def test_clean_text_not_flagged() -> None:
    """No false positives on ordinary prose (no secrets at all)."""
    assert scan_content("hello world") is None
    assert scan_content("The quick brown fox.") is None
    assert scan_content("Response headers: Content-Type: application/json") is None
