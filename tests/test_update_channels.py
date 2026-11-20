import sys
import time
from pathlib import Path
from uuid import uuid4

import pytest

from nanobot.config.home import get_selected_home_path, set_home_path
from nanobot.installation_lock import file_access, installation_state_dir, pending_update_path
from nanobot.update_channel import (
    UpdateChannelRequest,
    read_update_channel,
    validate_channel_revision,
)
from nanobot.update_service import UpdateJobService
from nanobot.update_worker import JobStatus, Phase


@pytest.fixture
def environment(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "account"))
    monkeypatch.setattr(sys, "prefix", str(tmp_path / "installation"))
    return installation_state_dir()


def change(channel, revision):
    return UpdateJobService().change_channel(UpdateChannelRequest(channel=channel, revision=revision))


def test_channel_is_installation_owned_persistent_and_revision_bound(environment, tmp_path, monkeypatch):
    assert read_update_channel().channel == "stable"
    assert not (environment / "channel.json").exists()
    selected = change("preview", 0)
    assert (selected.channel, selected.revision) == ("preview", 1)
    original_home = get_selected_home_path()
    try:
        set_home_path(tmp_path / "another-profile")
        assert read_update_channel() == selected
    finally:
        set_home_path(original_home)
    assert change("preview", 1) == selected
    with pytest.raises(ValueError, match="another client"):
        change("stable", 0)
    assert change("stable", 1).revision == 2
    with pytest.raises(ValueError, match="channel changed"):
        validate_channel_revision(0, sys.prefix)
    monkeypatch.setattr(sys, "prefix", str(tmp_path / "other-installation"))
    assert read_update_channel().revision == 0
    assert not (environment / "jobs").exists(), "Changing channels must not create an installation job"


@pytest.mark.parametrize("lock", ["channel.lock", "preparation-controller.lock"])
def test_channel_change_does_not_race_an_active_preparer(environment, lock):
    with file_access(environment / lock, exclusive=True), pytest.raises(BlockingIOError):
        change("preview", 0)
    assert read_update_channel().revision == 0
    assert change("preview", 0).revision == 1


@pytest.mark.parametrize("phase,mutation", [(Phase.PREPARING, False), (Phase.CHECKING, False),
                                          (Phase.STOPPING, False), (Phase.FAILED, True),
                                          (Phase.RESTART_FAILED, True)])
def test_active_and_failed_mutation_jobs_require_recovery_before_switch(environment, phase, mutation):
    identifier = str(uuid4())
    directory = environment / "jobs" / identifier
    directory.mkdir(parents=True)
    JobStatus(identifier, phase, 1, mutation, "Private diagnostic", int(time.time())).save(directory)
    before = (directory / "status.json").read_bytes()
    with pytest.raises(ValueError, match="recover"):
        change("preview", 0)
    assert read_update_channel().revision == 0
    assert (directory / "status.json").read_bytes() == before


def test_incomplete_install_and_corrupt_preference_are_not_silently_reset(environment):
    pending = pending_update_path()
    pending.parent.mkdir(parents=True)
    pending.write_text("interrupted")
    with pytest.raises(ValueError, match="Recover"):
        change("preview", 0)
    pending.unlink()
    (environment / "channel.json").write_text('{"channel":"unknown"}')
    with pytest.raises(ValueError):
        read_update_channel()
    with pytest.raises(ValueError):
        change("preview", 0)
