"""Tests for channel reconnection backoff constants and logic."""

from blackcat.channels.utils import (
    RECONNECT_DELAY_INITIAL,
    RECONNECT_DELAY_MAX,
)

# ── Backoff constants ─────────────────────────────────────────────


def test_initial_delay_is_small():
    assert RECONNECT_DELAY_INITIAL == 5


def test_max_delay_is_one_hour():
    assert RECONNECT_DELAY_MAX == 3600


def test_backoff_sequence():
    """Verify the exponential backoff doubles up to the cap."""
    delay = RECONNECT_DELAY_INITIAL
    delays = []
    for _ in range(15):
        delays.append(delay)
        delay = min(delay * 2, RECONNECT_DELAY_MAX)

    # First few should double
    assert delays[0] == 5
    assert delays[1] == 10
    assert delays[2] == 20
    assert delays[3] == 40

    # Should eventually cap at 3600
    assert delays[-1] == RECONNECT_DELAY_MAX
    assert all(d <= RECONNECT_DELAY_MAX for d in delays)


def test_backoff_reaches_cap_in_reasonable_steps():
    """Should hit the 1-hour cap within ~10 doublings from 5s."""
    delay = RECONNECT_DELAY_INITIAL
    steps = 0
    while delay < RECONNECT_DELAY_MAX:
        delay = min(delay * 2, RECONNECT_DELAY_MAX)
        steps += 1
    assert steps <= 10  # 5 -> 10 -> 20 -> 40 -> 80 -> 160 -> 320 -> 640 -> 1280 -> 2560 -> 3600


# ── WhatsApp dedup ────────────────────────────────────────────────


def test_whatsapp_dedup_init():
    """WhatsApp channel should initialize with a dedup deque."""
    from unittest.mock import MagicMock

    from blackcat.channels.whatsapp import WhatsAppChannel

    config = MagicMock()
    config.allow_from = ["*"]
    config.bridge_url = "ws://localhost:3000"
    config.bridge_token = None
    config.typing_interval = 0
    bus = MagicMock()

    ch = WhatsAppChannel(config, bus)
    assert hasattr(ch, "_processed_message_ids")


# ── Manager allow_from validation ─────────────────────────────────


def test_manager_validates_empty_allow_from():
    """ChannelManager should fail fast on empty allow_from."""
    from unittest.mock import MagicMock

    from blackcat.channels.manager import ChannelManager

    mgr = ChannelManager.__new__(ChannelManager)
    mgr.channels = {}

    # Add a fake channel with empty allow_from
    fake_channel = MagicMock()
    fake_channel.config.allow_from = []
    mgr.channels["test"] = fake_channel

    import pytest
    with pytest.raises(SystemExit, match="empty allowFrom"):
        mgr._validate_allow_from()


def test_manager_allows_populated_allow_from():
    """Non-empty allow_from should pass validation."""
    from unittest.mock import MagicMock

    from blackcat.channels.manager import ChannelManager

    mgr = ChannelManager.__new__(ChannelManager)
    mgr.channels = {}

    fake_channel = MagicMock()
    fake_channel.config.allow_from = ["user1"]
    mgr.channels["test"] = fake_channel

    # Should not raise
    mgr._validate_allow_from()
