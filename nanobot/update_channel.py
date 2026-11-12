from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field

from nanobot.installation_lock import installation_state_dir
from nanobot.releases import Channel, ReleaseRecord
from nanobot.utils.atomic_file import atomic_write_lines, read_atomic_bytes


class UpdateChannel(ReleaseRecord):
    schema_version: Literal[1] = 1
    channel: Channel = "stable"
    revision: int = Field(default=0, ge=0)


class UpdateChannelRequest(ReleaseRecord):
    channel: Channel
    revision: int = Field(ge=0)


def read_update_channel(environment: str | Path | None = None) -> UpdateChannel:
    path = installation_state_dir(environment) / "channel.json"
    try:
        if path.is_symlink():
            raise ValueError("Invalid update channel record")
        return UpdateChannel.model_validate_json(read_atomic_bytes(path, max_bytes=4097))
    except FileNotFoundError:
        # Existing installations remain on Stable. A dev version is not consent.
        return UpdateChannel()


def write_update_channel(selection: UpdateChannel, environment: str | Path | None = None) -> None:
    """Caller holds channel.lock and has checked the active job lifecycle."""
    root = installation_state_dir(environment)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = root / "channel.json"
    atomic_write_lines(path, [selection.model_dump_json()])
    path.chmod(0o600)


def validate_channel_revision(revision: int | None, environment: str) -> None:
    if (revision or 0) != read_update_channel(environment).revision:
        raise ValueError("Update channel changed; review a new update before confirming")
