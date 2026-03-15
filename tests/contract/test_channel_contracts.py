"""Contract tests for channel adapter compliance.

These tests verify that:
1. All channel adapters subclass ``BaseChannel``.
2. All channels implement the required abstract methods (``start``, ``stop``, ``send``).
3. Channel classes have the expected ``name`` attribute.

These tests import classes statically — they do NOT start real connections.
"""

from __future__ import annotations

import inspect

import pytest

from nanobot.channels.base import BaseChannel

# ---------------------------------------------------------------------------
# Discover all channel adapter classes
# ---------------------------------------------------------------------------


def _get_channel_classes() -> list[tuple[str, type]]:
    """Import and return all concrete BaseChannel subclasses."""
    channels: list[tuple[str, type]] = []

    adapter_modules = [
        ("telegram", "TelegramChannel"),
        ("discord", "DiscordChannel"),
        ("slack", "SlackChannel"),
        ("whatsapp", "WhatsAppChannel"),
        ("email", "EmailChannel"),
    ]

    for module_name, class_name in adapter_modules:
        try:
            mod = __import__(f"nanobot.channels.{module_name}", fromlist=[class_name])
            cls = getattr(mod, class_name)
            channels.append((class_name, cls))
        except (ImportError, AttributeError):
            # Skip channels with unresolvable imports (e.g., missing optional deps)
            pass

    return channels


_CHANNEL_CLASSES = _get_channel_classes()


# ---------------------------------------------------------------------------
# Contract: All channels subclass BaseChannel
# ---------------------------------------------------------------------------


class TestChannelInheritanceContract:
    """Every channel adapter must be a subclass of BaseChannel."""

    @pytest.mark.parametrize("name,cls", _CHANNEL_CLASSES, ids=[c[0] for c in _CHANNEL_CLASSES])
    def test_is_subclass_of_base_channel(self, name: str, cls: type):
        assert issubclass(cls, BaseChannel), f"{name} must subclass BaseChannel"


# ---------------------------------------------------------------------------
# Contract: Required abstract methods are implemented
# ---------------------------------------------------------------------------


class TestChannelMethodContract:
    """Every channel adapter must implement start(), stop(), and send()."""

    @pytest.mark.parametrize("name,cls", _CHANNEL_CLASSES, ids=[c[0] for c in _CHANNEL_CLASSES])
    def test_has_start_method(self, name: str, cls: type):
        assert hasattr(cls, "start"), f"{name} must implement start()"
        assert callable(getattr(cls, "start")), f"{name}.start must be callable"
        assert inspect.iscoroutinefunction(cls.start), f"{name}.start must be async"

    @pytest.mark.parametrize("name,cls", _CHANNEL_CLASSES, ids=[c[0] for c in _CHANNEL_CLASSES])
    def test_has_stop_method(self, name: str, cls: type):
        assert hasattr(cls, "stop"), f"{name} must implement stop()"
        assert callable(getattr(cls, "stop")), f"{name}.stop must be callable"
        assert inspect.iscoroutinefunction(cls.stop), f"{name}.stop must be async"

    @pytest.mark.parametrize("name,cls", _CHANNEL_CLASSES, ids=[c[0] for c in _CHANNEL_CLASSES])
    def test_has_send_method(self, name: str, cls: type):
        assert hasattr(cls, "send"), f"{name} must implement send()"
        assert callable(getattr(cls, "send")), f"{name}.send must be callable"
        assert inspect.iscoroutinefunction(cls.send), f"{name}.send must be async"


# ---------------------------------------------------------------------------
# Contract: Channel has name attribute
# ---------------------------------------------------------------------------


class TestChannelNameContract:
    """Every channel adapter must define a name class attribute."""

    @pytest.mark.parametrize("name,cls", _CHANNEL_CLASSES, ids=[c[0] for c in _CHANNEL_CLASSES])
    def test_has_name_attribute(self, name: str, cls: type):
        assert hasattr(cls, "name"), f"{name} must have a 'name' attribute"
        channel_name = getattr(cls, "name")
        assert isinstance(channel_name, str), f"{name}.name must be a string"
        assert len(channel_name) > 0, f"{name}.name must not be empty"

    @pytest.mark.parametrize("name,cls", _CHANNEL_CLASSES, ids=[c[0] for c in _CHANNEL_CLASSES])
    def test_has_health_property(self, name: str, cls: type):
        """BaseChannel.health property must be inherited."""
        assert hasattr(cls, "health"), f"{name} must have 'health' property from BaseChannel"
