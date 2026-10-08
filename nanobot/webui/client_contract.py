"""The contract between a shipped WebUI and an independently updated gateway.

Package versions are display metadata, not compatibility decisions. Adding an
optional capability must not raise the protocol floor for unrelated features.
See .agent/review-guide.md before changing this contract.
"""

from __future__ import annotations

from typing import Literal, TypedDict, cast

from nanobot import __version__
from nanobot.apps.cua_driver import CAPABILITY as CUA_CAPABILITY
from nanobot.apps.cua_driver import SETUP_CAPABILITY as CUA_SETUP_CAPABILITY

WEBUI_PROTOCOL = 1
CORE_CAPABILITY = "webui.core.v1"
SUBAGENT_CAPABILITY = "webui.subagents.v1"
SUBAGENT_EVENTS_CAPABILITY = "webui.subagents.events.v1"
SUBAGENT_HISTORY_CAPABILITY = "webui.subagents.history.v1"
AUTOMATION_CHAT_CAPABILITY = "webui.automation-chat.v1"
BINARY_ATTACHMENTS_CAPABILITY = "webui.attachments.binary.v1"


class Compatibility(TypedDict):
    status: Literal["compatible", "unknown", "update_host", "update_client"]
    client_version: str
    host_version: str


def webui_contract() -> dict[str, object]:
    return {
        "version": __version__,
        "min_protocol": WEBUI_PROTOCOL,
        "max_protocol": WEBUI_PROTOCOL,
        "capabilities": [
            CORE_CAPABILITY, SUBAGENT_CAPABILITY, SUBAGENT_EVENTS_CAPABILITY,
            SUBAGENT_HISTORY_CAPABILITY, AUTOMATION_CHAT_CAPABILITY,
            BINARY_ATTACHMENTS_CAPABILITY, CUA_CAPABILITY, CUA_SETUP_CAPABILITY,
        ],
    }


def gateway_identity(gateway_id: str) -> dict[str, object]:
    # protocolVersion belongs to the pre-existing terminal transport contract.
    # Do not overload it with the version of the independently shipped WebUI.
    return {"protocolVersion": 1, "gatewayId": gateway_id, "webui": webui_contract()}


def assess_webui_contract(value: object) -> Compatibility:
    result: Compatibility = {
        "status": "unknown", "client_version": __version__, "host_version": "",
    }
    if not isinstance(value, dict):
        return result
    # Only the mapping shape is established here; validate each value below.
    data = cast(dict[object, object], value)
    version = data.get("version")
    if isinstance(version, str) and len(version) <= 80 and version.isprintable():
        result["host_version"] = version
    minimum, maximum = data.get("min_protocol"), data.get("max_protocol")
    capabilities = data.get("capabilities")
    if (type(minimum) is not int or type(maximum) is not int
            or not 1 <= minimum <= maximum
            or not isinstance(capabilities, list)
            or not all(isinstance(item, str) for item in cast(list[object], capabilities))):
        return result
    if minimum > WEBUI_PROTOCOL:
        result["status"] = "update_client"
    elif maximum < WEBUI_PROTOCOL or CORE_CAPABILITY not in capabilities:
        result["status"] = "update_host"
    else:
        result["status"] = "compatible"
    return result


def compatibility_error(report: Compatibility) -> str:
    return {
        "compatible": "", "unknown": "webui_compatibility_unknown",
        "update_host": "host_update_required", "update_client": "client_update_required",
    }[report["status"]]
