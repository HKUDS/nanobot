"""Discord REST API renderer for Components V2.

Builds JSON payloads for the Discord REST API from A2UI StructuredReply
objects.  No discord.py library — everything is raw JSON matching the
Discord API v10 component specification.

Discord Component Types (integer IDs):
  1  = ActionRow
  2  = Button
  3  = StringSelect
  9  = Section
 10  = TextDisplay
 11  = Thumbnail
 12  = MediaGallery
 14  = Separator
 17  = Container
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from loguru import logger

from nanobot.channels.discord_a2ui import (
    StructuredReply,
    SurfaceDirective,
    _component_type,
    _normalize_image_url,
)

# ---------------------------------------------------------------------------
# Discord component type IDs
# ---------------------------------------------------------------------------

ACTION_ROW = 1
BUTTON = 2
STRING_SELECT = 3
SECTION = 9
TEXT_DISPLAY = 10
THUMBNAIL = 11
MEDIA_GALLERY = 12
SEPARATOR = 14
CONTAINER = 17

# Discord button style IDs
BUTTON_STYLE_MAP = {
    "primary": 1,
    "secondary": 2,
    "success": 3,
    "danger": 4,
    "link": 5,
}

_MAX_LAYOUT_ITEMS = 25

# Top-level component types that can appear directly in the components array
_LAYOUT_TOP_LEVEL_TYPES = {
    "text", "textdisplay", "markdown", "separator", "thumbnail",
    "media_gallery", "mediagallery", "container", "section",
    "button", "action", "select", "string_select",
}


# ---------------------------------------------------------------------------
# custom_id encoding
# ---------------------------------------------------------------------------


def _encode_custom_id(
    owner_id: str,
    action: str | None,
    payload: str | None,
) -> str:
    """Encode a custom_id for a button/select interaction.

    Format: a2ui:{owner_id}:{action}:{payload_hash}
    Max 100 chars (Discord limit).
    """
    action_str = action or "_"
    payload_hash = ""
    if payload:
        payload_hash = hashlib.sha256(payload.encode()).hexdigest()[:8]
    raw = f"a2ui:{owner_id}:{action_str}:{payload_hash}"
    return raw[:100]


def _decode_custom_id(custom_id: str) -> tuple[str, str | None, str | None]:
    """Decode owner_id, action, payload_hash from custom_id.

    Returns (owner_id, action, payload_hash).
    """
    if not custom_id.startswith("a2ui:"):
        return ("", None, None)
    parts = custom_id.split(":", 3)
    owner_id = parts[1] if len(parts) > 1 else ""
    action = parts[2] if len(parts) > 2 else None
    payload_hash = parts[3] if len(parts) > 3 else None
    if action == "_":
        action = None
    return (owner_id, action, payload_hash or None)


# ---------------------------------------------------------------------------
# Component builders
# ---------------------------------------------------------------------------


def _build_text_display(comp: dict[str, Any]) -> dict[str, Any]:
    """Build a TextDisplay (type 10) component."""
    content = comp.get("markdown") or comp.get("content") or ""
    return {"type": TEXT_DISPLAY, "content": str(content)}


def _build_button(comp: dict[str, Any], owner_id: str) -> dict[str, Any]:
    """Build a Button (type 2) component."""
    label = str(comp.get("label", "")).strip()[:80]
    style_str = str(comp.get("style", "secondary")).lower()
    url = _normalize_image_url(comp.get("url"))
    action = (comp.get("action") or "").strip() or None
    payload = (comp.get("payload") or "").strip() or None

    # Auto-detect link buttons
    if url is not None and action is None:
        style_str = "link"

    style_id = BUTTON_STYLE_MAP.get(style_str, 2)  # default secondary

    button: dict[str, Any] = {
        "type": BUTTON,
        "label": label or "Button",
        "style": style_id,
    }

    if style_id == 5:  # link
        if not url:
            return {}  # invalid link button
        button["url"] = url
    else:
        button["custom_id"] = _encode_custom_id(owner_id, action, payload)

    return button


def _build_select(comp: dict[str, Any], owner_id: str) -> dict[str, Any]:
    """Build a StringSelect (type 3) component."""
    action = (comp.get("action") or "").strip() or "_"
    payload = (comp.get("payload") or "").strip() or None
    placeholder = str(comp.get("placeholder", ""))[:150] or None
    disabled = bool(comp.get("disabled", False))
    min_values = int(comp.get("min_values", 1))
    max_values = int(comp.get("max_values", 1))

    options = []
    for raw in (comp.get("options") or []):
        if not isinstance(raw, dict):
            continue
        label = str(raw.get("label", ""))[:100]
        if not label:
            continue
        value = str(raw.get("value", label))[:100]
        desc = str(raw.get("description", ""))[:100] or None
        default = bool(raw.get("default", False))
        opt: dict[str, Any] = {"label": label, "value": value}
        if desc:
            opt["description"] = desc
        if default:
            opt["default"] = True
        options.append(opt)

    if not options:
        return {}

    select: dict[str, Any] = {
        "type": STRING_SELECT,
        "custom_id": _encode_custom_id(owner_id, action, payload),
        "options": options[:25],  # Discord max 25 options
        "min_values": min_values,
        "max_values": min(max_values, len(options)),
        "disabled": disabled,
    }
    if placeholder:
        select["placeholder"] = placeholder

    return select


def _build_thumbnail(comp: dict[str, Any]) -> dict[str, Any]:
    """Build a Thumbnail (type 11) component."""
    url = _normalize_image_url(comp.get("url"))
    if not url:
        return {}
    thumb: dict[str, Any] = {
        "type": THUMBNAIL,
        "media": {"url": url},
    }
    desc = comp.get("description")
    if desc:
        thumb["description"] = str(desc)[:256]
    return thumb


def _build_media_gallery(comp: dict[str, Any]) -> dict[str, Any]:
    """Build a MediaGallery (type 12) component."""
    items = []
    for raw in (comp.get("items") or []):
        if not isinstance(raw, dict):
            continue
        url = _normalize_image_url(raw.get("url"))
        if not url:
            continue
        item: dict[str, Any] = {"media": {"url": url}}
        desc = raw.get("description")
        if desc:
            item["description"] = str(desc)[:256]
        items.append(item)
        if len(items) >= 10:
            break
    if not items:
        return {}
    return {"type": MEDIA_GALLERY, "items": items}


def _build_separator() -> dict[str, Any]:
    """Build a Separator (type 14) component."""
    return {"type": SEPARATOR}


def _build_section(comp: dict[str, Any], owner_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Build a Section (type 9) component and any promoted selects.

    Discord doesn't allow selects inside sections, so selects found in
    section children are "promoted" to separate ActionRows that follow
    the section.

    Returns (section_dict, promoted_action_rows).
    """
    children_raw = comp.get("components") or comp.get("children") or []
    accessory_raw = comp.get("accessory")

    section_components = []
    promoted: list[dict[str, Any]] = []

    for child in children_raw:
        if not isinstance(child, dict):
            continue
        ctype = _component_type(child)
        if ctype in ("select", "string_select"):
            # Promote to ActionRow after section
            select = _build_select(child, owner_id)
            if select:
                promoted.append({"type": ACTION_ROW, "components": [select]})
        elif ctype in ("text", "textdisplay", "markdown"):
            section_components.append(_build_text_display(child))
        if len(section_components) >= 3:
            break

    section: dict[str, Any] = {"type": SECTION}
    if section_components:
        section["components"] = section_components

    # Build accessory (button or thumbnail)
    if isinstance(accessory_raw, dict):
        acc_type = _component_type(accessory_raw)
        if acc_type in ("button", "action"):
            btn = _build_button(accessory_raw, owner_id)
            if btn:
                section["accessory"] = btn
        elif acc_type == "thumbnail":
            thumb = _build_thumbnail(accessory_raw)
            if thumb:
                section["accessory"] = thumb

    return section, promoted


def _build_container(comp: dict[str, Any], owner_id: str) -> dict[str, Any]:
    """Build a Container (type 17) component with recursive children."""
    children_raw = comp.get("components") or comp.get("children") or []
    children = []
    for child in children_raw:
        if not isinstance(child, dict):
            continue
        built = _build_single_component(child, owner_id)
        if isinstance(built, list):
            children.extend(built)
        elif built:
            children.append(built)
    if not children:
        return {}
    return {"type": CONTAINER, "components": children}


def _build_single_component(
    comp: dict[str, Any], owner_id: str
) -> dict[str, Any] | list[dict[str, Any]] | None:
    """Build a single component, returning either a dict or list (for sections with promoted selects)."""
    ctype = _component_type(comp)

    if ctype in ("text", "textdisplay", "markdown"):
        return _build_text_display(comp)
    elif ctype in ("button", "action"):
        btn = _build_button(comp, owner_id)
        if btn:
            return {"type": ACTION_ROW, "components": [btn]}
        return None
    elif ctype in ("select", "string_select"):
        sel = _build_select(comp, owner_id)
        if sel:
            return {"type": ACTION_ROW, "components": [sel]}
        return None
    elif ctype == "section":
        section, promoted = _build_section(comp, owner_id)
        result = [section]
        result.extend(promoted)
        return result
    elif ctype == "container":
        cont = _build_container(comp, owner_id)
        return cont if cont else None
    elif ctype == "separator":
        return _build_separator()
    elif ctype == "thumbnail":
        return _build_thumbnail(comp)
    elif ctype in ("media_gallery", "mediagallery"):
        return _build_media_gallery(comp)
    else:
        logger.debug("Unknown A2UI component type: {}", ctype)
        return None


# ---------------------------------------------------------------------------
# Top-level payload builders
# ---------------------------------------------------------------------------


def build_components_v2_payload(
    a2ui_components: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    owner_id: str,
) -> list[dict[str, Any]]:
    """Build the top-level components array for a Components V2 message.

    Returns a list of Discord component dicts ready for the REST API
    `components` field.
    """
    if not a2ui_components:
        return []

    components: list[dict[str, Any]] = []

    for comp in a2ui_components:
        if not isinstance(comp, dict):
            continue
        ctype = _component_type(comp)
        if ctype not in _LAYOUT_TOP_LEVEL_TYPES:
            continue

        built = _build_single_component(comp, owner_id)
        if isinstance(built, list):
            for item in built:
                if item:
                    components.append(item)
                    if len(components) >= _MAX_LAYOUT_ITEMS:
                        break
        elif built:
            components.append(built)

        if len(components) >= _MAX_LAYOUT_ITEMS:
            break

    return components


def build_image_embeds(image_urls: tuple[str, ...] | list[str]) -> list[dict[str, Any]]:
    """Build image embeds for the embeds field."""
    embeds = []
    for url in image_urls:
        if url:
            embeds.append({"image": {"url": url}})
    return embeds


def build_simple_buttons_payload(
    buttons: tuple,  # tuple[ButtonIntent, ...]
    owner_id: str,
) -> list[dict[str, Any]]:
    """Build a standard ActionRow with buttons (non-A2UI simple path)."""
    if not buttons:
        return []
    button_dicts = []
    for bi in buttons:
        style_id = BUTTON_STYLE_MAP.get(bi.style, 2)
        btn: dict[str, Any] = {
            "type": BUTTON,
            "label": bi.label,
            "style": style_id,
        }
        if style_id == 5:  # link
            if not bi.url:
                continue
            btn["url"] = bi.url
        else:
            btn["custom_id"] = _encode_custom_id(owner_id, bi.action, bi.payload)
        button_dicts.append(btn)
    if not button_dicts:
        return []
    return [{"type": ACTION_ROW, "components": button_dicts}]


def build_message_payload(
    structured: StructuredReply,
    owner_id: str,
) -> dict[str, Any]:
    """Build a complete Discord message payload from a StructuredReply.

    Returns a dict suitable for POST /channels/{id}/messages.
    The `flags` field is set to 32768 (IS_COMPONENTS_V2) when using
    Components V2 layout.
    """
    payload: dict[str, Any] = {}

    has_a2ui = bool(structured.a2ui_components)

    if has_a2ui:
        # Components V2 path — content must be omitted
        components = build_components_v2_payload(
            structured.a2ui_components, owner_id
        )
        if components:
            payload["components"] = components
            payload["flags"] = 32768  # IS_COMPONENTS_V2
            # Content is forbidden with Components V2
        else:
            # Fallback to text if component building failed
            payload["content"] = structured.markdown or " "
    elif structured.ui_intent and structured.ui_intent.buttons:
        # Simple buttons path
        payload["content"] = structured.markdown or " "
        components = build_simple_buttons_payload(
            structured.ui_intent.buttons, owner_id
        )
        if components:
            payload["components"] = components
    else:
        # Plain text path
        payload["content"] = structured.markdown or " "

    # Image embeds (only for non-Components V2, or as supplementary)
    if structured.image_urls and not has_a2ui:
        payload["embeds"] = build_image_embeds(structured.image_urls)

    return payload
