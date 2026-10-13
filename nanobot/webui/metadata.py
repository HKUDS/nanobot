"""Shared WebUI metadata keys."""

from nanobot.bus.events import INBOUND_META_TURN_ID

WEBUI_TURN_METADATA_KEY = INBOUND_META_TURN_ID
WEBUI_SYSTEM_COMMAND_TURN_PREFIX = "webui-system:"
# Set by authenticated WebUI ingress, never copied from an envelope's metadata.
WEBUI_RESTART_CONTROL_METADATA_KEY = "_webui_restart_control"
WEBSOCKET_TURN_OWNER_METADATA_KEY = "_websocket_turn_owner"
WEBUI_MESSAGE_SOURCE_METADATA_KEY = "_webui_message_source"
