"""Narrow, shell-free adapter for safe Himalaya operations."""

from __future__ import annotations

import json
import subprocess
import tempfile
import time
from typing import Any, cast

from nanobot_mail_watcher.config import WorkerConfig


class HimalayaError(RuntimeError):
    """A Himalaya invocation failed or returned an invalid response."""


class MessageTooLargeError(HimalayaError):
    """A message exceeded the configured local processing limit."""


class HimalayaClient:
    """Expose only read, status, and move; never send, delete, or invoke a shell."""

    def __init__(self, config: WorkerConfig) -> None:
        self.binary = config.himalaya_binary
        self.config_path = config.himalaya_config
        self.timeout = config.command_timeout_seconds
        self.max_message_bytes = config.max_message_bytes
        self.reconcile_max_messages = config.reconcile_max_messages
        self.reconcile_max_response_bytes = config.reconcile_max_response_bytes
        self.reconcile_max_folders = config.reconcile_max_folders

    def check_version(self) -> str:
        output = self._run([], account=None, extra_global=["--version"], max_bytes=64_000)
        return output.decode("utf-8", errors="replace").strip()

    def list_mailboxes(self, account: str) -> tuple[str, ...]:
        """Discover selectable folders using LIST, not subscription-only LSUB.

        Himalaya 2.1's JSON contract is {mailboxes: [{name, attributes, delimiter}]}.
        Never interpolate names into shell commands; fail closed on unsafe rows.
        """
        output = self._run(
            ["imap", "list", "--all"], account=account, extra_global=["--json"],
            max_bytes=self.reconcile_max_response_bytes,
        )
        try:
            value = cast(object, json.loads(output))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise HimalayaError("Himalaya returned invalid JSON for IMAP LIST") from exc
        if not isinstance(value, dict):
            raise HimalayaError("Himalaya IMAP LIST result is not an object")
        # json.loads guarantees string keys, while values remain untrusted objects.
        result = cast(dict[str, object], value)
        raw_rows = result.get("mailboxes")
        if not isinstance(raw_rows, list):
            raise HimalayaError("Himalaya IMAP LIST has no mailboxes array")
        rows = cast(list[object], raw_rows)
        if len(rows) > self.reconcile_max_folders:
            raise HimalayaError("Himalaya IMAP LIST exceeded the configured folder limit")
        folders: list[str] = []
        for raw_row in rows:
            if not isinstance(raw_row, dict):
                raise HimalayaError("Himalaya IMAP LIST contains an invalid row")
            row = cast(dict[str, object], raw_row)
            name, attributes = row.get("name"), row.get("attributes")
            if (not isinstance(name, str) or not name.strip() or len(name) > 1024
                    or name.startswith("-") or any(ord(char) < 32 for char in name)
                    or not isinstance(attributes, list)):
                raise HimalayaError("Himalaya IMAP LIST contains an unsafe mailbox")
            raw_attributes = cast(list[object], attributes)
            attributes = [attribute for attribute in raw_attributes if isinstance(attribute, str)]
            if len(attributes) != len(raw_attributes):
                raise HimalayaError("Himalaya IMAP LIST contains invalid attributes")
            if any(attribute.casefold() in {"\\noselect", "\\nonexistent"} for attribute in attributes):
                continue
            # INBOX alone is case-insensitive under IMAP; other folder IDs aren't.
            name = "INBOX" if name.casefold() == "inbox" else name
            if name not in folders:
                folders.append(name)
        return tuple(folders)

    def uid_validity(self, account: str, mailbox: str) -> str:
        output = self._run(
            ["imap", "status", mailbox],
            account=account,
            extra_global=["--json"],
            max_bytes=1_000_000,
        )
        try:
            value = cast(object, json.loads(output))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise HimalayaError("Himalaya returned invalid JSON for IMAP STATUS") from exc
        if not isinstance(value, dict):
            raise HimalayaError("Himalaya IMAP STATUS result is not an object")
        status = cast(dict[str, Any], value)
        raw = status.get("uid_validity")
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
            raise HimalayaError("Himalaya IMAP STATUS did not return UIDVALIDITY")
        return str(raw)

    def search_uids(self, account: str, mailbox: str) -> tuple[str, ...]:
        """Return bounded UID-mode results from Himalaya's IMAP SEARCH JSON table."""
        output = self._run(
            ["imap", "search", f"--mailbox={mailbox}"],
            account=account,
            extra_global=["--json"],
            max_bytes=self.reconcile_max_response_bytes,
        )
        try:
            value = cast(object, json.loads(output))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise HimalayaError("Himalaya returned invalid JSON for IMAP SEARCH") from exc
        if not isinstance(value, dict):
            raise HimalayaError("Himalaya IMAP SEARCH result is not an object")
        result = cast(dict[str, Any], value)
        if result.get("uid_mode") is not True:
            raise HimalayaError("Himalaya IMAP SEARCH did not return UID-mode results")
        raw_ids = result.get("ids")
        if not isinstance(raw_ids, list):
            raise HimalayaError("Himalaya IMAP SEARCH result has no ids array")
        ids = cast(list[object], raw_ids)  # JSON array checked above, rows checked below
        if len(ids) > self.reconcile_max_messages:
            raise HimalayaError(
                "Himalaya IMAP SEARCH returned more than the configured "
                f"{self.reconcile_max_messages} message limit"
            )
        uids: list[str] = []
        seen: set[int] = set()
        for raw_item in ids:
            if not isinstance(raw_item, dict):
                raise HimalayaError("Himalaya IMAP SEARCH contains an invalid id row")
            raw_id = cast(dict[str, Any], raw_item).get("id")
            if (
                isinstance(raw_id, bool)
                or not isinstance(raw_id, int)
                or not 1 <= raw_id <= 4_294_967_295
                or raw_id in seen
            ):
                raise HimalayaError("Himalaya IMAP SEARCH contains an invalid or duplicate UID")
            seen.add(raw_id)
            uids.append(str(raw_id))
        return tuple(uids)

    def read_raw(self, account: str, mailbox: str, uid: str) -> bytes:
        _validate_uid(uid)
        return self._run(
            ["message", "read", uid, f"--mailbox={mailbox}", "--raw"],
            account=account,
            extra_global=["--backend=imap"],
            max_bytes=self.max_message_bytes,
        )

    def move(self, account: str, source: str, destination: str, uid: str) -> None:
        _validate_uid(uid)
        self._run(
            ["message", "move", uid, f"--from={source}", f"--to={destination}"],
            account=account,
            extra_global=["--backend=imap"],
            max_bytes=1_000_000,
        )

    def _run(
        self,
        command: list[str],
        *,
        account: str | None,
        max_bytes: int,
        extra_global: list[str] | None = None,
    ) -> bytes:
        argv = [self.binary]
        if self.config_path is not None:
            argv.append(f"--config={self.config_path}")
        if account is not None:
            argv.append(f"--account={account}")
        argv.extend(extra_global or [])
        argv.extend(command)

        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            try:
                process = subprocess.Popen(  # noqa: S603 - executable is administrator config
                    argv,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout,
                    stderr=stderr,
                    shell=False,
                )
            except OSError as exc:
                raise HimalayaError(f"cannot start Himalaya: {exc}") from exc

            deadline = time.monotonic() + self.timeout
            exceeded = False
            while process.poll() is None:
                if time.monotonic() >= deadline:
                    process.kill()
                    process.wait()
                    raise HimalayaError(f"Himalaya timed out after {self.timeout:g}s")
                if stdout.tell() > max_bytes or stderr.tell() > 1_000_000:
                    exceeded = True
                    process.kill()
                    process.wait()
                    break
                time.sleep(0.02)

            stdout_size = stdout.tell()
            stderr_size = stderr.tell()
            stdout.seek(0)
            output = stdout.read(max_bytes + 1)
            if stdout_size > max_bytes:
                raise MessageTooLargeError(
                    f"Himalaya output exceeds configured limit of {max_bytes} bytes"
                )
            if exceeded or stderr_size > 1_000_000:
                raise HimalayaError("Himalaya diagnostic output exceeded the safety limit")
            if process.returncode != 0:
                # stderr can contain addresses, server names, paths, or provider diagnostics.
                # Keep it out of SQLite and journald; operators can reproduce manually.
                raise HimalayaError(f"Himalaya exited with status {process.returncode}")
            return output


def _validate_uid(uid: str) -> None:
    if not uid.isascii() or not uid.isdigit() or len(uid) > 20 or int(uid) < 1:
        raise ValueError("uid must be a positive decimal IMAP UID")
