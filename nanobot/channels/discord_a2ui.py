"""A2UI (Agent-to-UI) engine for Discord Components V2.

Parses structured JSON envelopes from agent output and manages stateful
surfaces with data-binding and template re-rendering.  This module is
Discord-agnostic — it only cares about parsing and state.  The actual
Discord REST rendering lives in discord_renderer.py.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_A2UI_ENVELOPES = 8
_MAX_UI_BUTTONS = 3
_MAX_OUTPUT_IMAGES = 4
_MAX_OUTPUT_FILES = 4

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ButtonIntent:
    """A single button to render."""

    label: str  # Max 80 chars
    style: str  # primary|secondary|success|danger|link
    action: str | None = None  # Callback action name
    url: str | None = None  # Required for link style
    payload: str | None = None  # Arbitrary payload string


@dataclass(frozen=True)
class UiIntent:
    """Simple button-based UI intent."""

    buttons: tuple[ButtonIntent, ...] = ()


@dataclass(frozen=True)
class SurfaceDirective:
    """Instruction to create/update/delete a surface message."""

    type: str  # createsurface|updatecomponents|updatedatamodel|deletesurface
    surface_id: str


@dataclass(frozen=True)
class StructuredReply:
    """Parsed agent reply with rich content."""

    markdown: str  # Rendered text content
    ui_intent: UiIntent | None = None
    image_urls: tuple[str, ...] = ()
    file_paths: tuple[str, ...] = ()
    a2ui_components: tuple[dict[str, Any], ...] = ()  # Raw component dicts
    surface_directives: tuple[SurfaceDirective, ...] = ()


@dataclass
class SurfaceState:
    """Mutable state for a live A2UI surface."""

    rendered: StructuredReply
    template_components: tuple[dict[str, Any], ...]
    data_model: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# JSON extraction
# ---------------------------------------------------------------------------

_FENCED_JSON_RE = re.compile(r"```(?:json)?\s*\n?(\{[\s\S]*?\})\s*```", re.IGNORECASE)
_MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*\]\((https?://[^)]+)\)")


def _extract_json_object_text(raw: str) -> str | None:
    """Try to extract a JSON object string from raw text.

    Strategy 1: entire string is a JSON object (starts with { ends with }).
    Strategy 2: fenced ```json ... ``` block.
    """
    stripped = raw.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped
    m = _FENCED_JSON_RE.search(raw)
    if m:
        return m.group(1)
    return None


def _normalize_image_url(value: Any) -> str | None:
    """Validate and normalise an image URL."""
    if not isinstance(value, str) or not value.strip():
        return None
    url = value.strip()
    if not url.startswith(("http://", "https://")):
        return None
    return url


def _extract_markdown_images(text: str) -> list[str]:
    """Pull ![alt](url) image URLs from markdown text."""
    return [u for u in _MARKDOWN_IMAGE_RE.findall(text) if _normalize_image_url(u)]


# ---------------------------------------------------------------------------
# A2UI envelope extraction
# ---------------------------------------------------------------------------


def _extract_a2ui_messages(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract valid A2UI envelopes from a parsed JSON payload."""
    candidates = payload.get("a2ui")
    if not isinstance(candidates, list):
        candidates = payload.get("messages")
    if not isinstance(candidates, list):
        return []
    messages: list[dict[str, Any]] = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        msg_type = str(item.get("type", "")).strip()
        if not msg_type:
            continue
        messages.append(item)
        if len(messages) >= _MAX_A2UI_ENVELOPES:
            break
    return messages


# ---------------------------------------------------------------------------
# Data-binding engine
# ---------------------------------------------------------------------------

_DATA_BIND_RE = re.compile(r"\{\{\s*([A-Za-z0-9_.-]+)\s*\}\}")


def _lookup_data_value(data_model: dict[str, Any], dotpath: str) -> Any:
    """Walk a dot-separated path through nested dicts."""
    current: Any = data_model
    for key in dotpath.split("."):
        if isinstance(current, dict):
            current = current.get(key)
        else:
            return None
    return current


def _bind_text(text: str, data_model: dict[str, Any]) -> str:
    """Replace {{path}} placeholders in text with data model values."""

    def _repl(match: re.Match) -> str:
        value = _lookup_data_value(data_model, match.group(1))
        if value is None:
            return ""
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        return str(value)

    return _DATA_BIND_RE.sub(_repl, text)


def _bind_component(component: Any, data_model: dict[str, Any]) -> Any:
    """Recursively bind data model values into a component tree."""
    if isinstance(component, str):
        return _bind_text(component, data_model)
    if isinstance(component, list):
        return [_bind_component(item, data_model) for item in component]
    if isinstance(component, dict):
        return {k: _bind_component(v, data_model) for k, v in component.items()}
    return component


# ---------------------------------------------------------------------------
# Component → StructuredReply rendering
# ---------------------------------------------------------------------------

_BUTTON_STYLES = {"primary", "secondary", "success", "danger", "link"}


def _component_type(comp: dict[str, Any]) -> str:
    return str(comp.get("type", "")).strip().lower()


def _render_from_components(
    components: list[dict[str, Any]],
) -> StructuredReply:
    """Walk the component tree (BFS) and extract markdown, buttons, images."""
    markdown_parts: list[str] = []
    buttons: list[ButtonIntent] = []
    image_urls: list[str] = []

    queue = list(components)
    while queue:
        comp = queue.pop(0)
        if not isinstance(comp, dict):
            continue
        ctype = _component_type(comp)

        if ctype in ("text", "textdisplay", "markdown"):
            md = comp.get("markdown") or comp.get("content") or ""
            if md:
                markdown_parts.append(str(md))
        elif ctype in ("button", "action"):
            label = str(comp.get("label", "")).strip()[:80]
            style = str(comp.get("style", "secondary")).lower()
            if style not in _BUTTON_STYLES:
                style = "secondary"
            url = _normalize_image_url(comp.get("url"))
            action = (comp.get("action") or "").strip() or None
            payload = (comp.get("payload") or "").strip() or None
            # Auto-detect link buttons
            if url is not None and action is None:
                style = "link"
            if style == "link" and not url:
                continue  # skip invalid link button
            if label and len(buttons) < _MAX_UI_BUTTONS:
                buttons.append(ButtonIntent(
                    label=label, style=style, action=action,
                    url=url, payload=payload,
                ))
        elif ctype in ("image", "img"):
            url = _normalize_image_url(comp.get("url"))
            if url and len(image_urls) < _MAX_OUTPUT_IMAGES:
                image_urls.append(url)
        elif ctype in ("media_gallery", "mediagallery"):
            for item in (comp.get("items") or []):
                url = _normalize_image_url(
                    item.get("url") if isinstance(item, dict) else None
                )
                if url and len(image_urls) < _MAX_OUTPUT_IMAGES:
                    image_urls.append(url)

        # Recurse into children
        for key in ("components", "children", "items"):
            children = comp.get(key)
            if isinstance(children, list):
                queue.extend(children)

        # Section accessory
        accessory = comp.get("accessory")
        if isinstance(accessory, dict):
            queue.append(accessory)

    return StructuredReply(
        markdown="\n\n".join(markdown_parts),
        ui_intent=UiIntent(buttons=tuple(buttons)) if buttons else None,
        image_urls=tuple(image_urls),
    )


# ---------------------------------------------------------------------------
# Simple (non-A2UI) JSON parsing
# ---------------------------------------------------------------------------


def _parse_simple_ui_intent(payload: dict[str, Any]) -> UiIntent | None:
    """Parse ui_intent.buttons from simple JSON shape."""
    ui_raw = payload.get("ui_intent")
    if not isinstance(ui_raw, dict):
        return None
    buttons_raw = ui_raw.get("buttons")
    if not isinstance(buttons_raw, list):
        return None
    buttons: list[ButtonIntent] = []
    for b in buttons_raw:
        if not isinstance(b, dict):
            continue
        label = str(b.get("label", "")).strip()[:80]
        if not label:
            continue
        style = str(b.get("style", "secondary")).lower()
        if style not in _BUTTON_STYLES:
            style = "secondary"
        url = _normalize_image_url(b.get("url"))
        action = (b.get("action") or "").strip() or None
        payload_str = (b.get("payload") or "").strip() or None
        if url and not action:
            style = "link"
        if style == "link" and not url:
            continue
        buttons.append(ButtonIntent(
            label=label, style=style, action=action,
            url=url, payload=payload_str,
        ))
        if len(buttons) >= _MAX_UI_BUTTONS:
            break
    return UiIntent(buttons=tuple(buttons)) if buttons else None


def _parse_image_urls(payload: dict[str, Any]) -> tuple[str, ...]:
    """Extract validated image URLs from JSON payload."""
    raw = payload.get("images")
    if not isinstance(raw, list):
        return ()
    urls = []
    for item in raw:
        url = _normalize_image_url(item)
        if url and len(urls) < _MAX_OUTPUT_IMAGES:
            urls.append(url)
    return tuple(urls)


def _parse_file_paths(payload: dict[str, Any]) -> tuple[str, ...]:
    """Extract file paths from JSON payload."""
    paths: list[str] = []
    for key in ("files", "file_paths", "attachments"):
        raw = payload.get(key)
        if not isinstance(raw, list):
            continue
        for item in raw:
            if isinstance(item, str) and item.strip():
                paths.append(item.strip())
            elif isinstance(item, dict):
                p = item.get("path")
                if isinstance(p, str) and p.strip():
                    paths.append(p.strip())
            if len(paths) >= _MAX_OUTPUT_FILES:
                break
        if paths:
            break
    return tuple(paths[:_MAX_OUTPUT_FILES])


# ---------------------------------------------------------------------------
# A2UI envelope processing (surface state machine)
# ---------------------------------------------------------------------------


def _process_a2ui_envelopes(
    envelopes: list[dict[str, Any]],
    session_id: str,
    surfaces: dict[tuple[str, str], SurfaceState],
) -> StructuredReply | None:
    """Process A2UI envelopes against the surface state store.

    Returns a StructuredReply for the *last* createSurface/updateComponents/
    updateDataModel envelope, or None if only deleteSurface envelopes.
    """
    last_reply: StructuredReply | None = None
    directives: list[SurfaceDirective] = []

    for env in envelopes:
        env_type = str(env.get("type", "")).strip().lower()
        surface_id = str(env.get("surfaceId", env.get("surface_id", ""))).strip()
        if not surface_id:
            continue
        key = (session_id, surface_id)

        if env_type == "createsurface":
            raw_components = env.get("components")
            if not isinstance(raw_components, list):
                raw_components = []
            data_model = env.get("dataModel") or env.get("data_model") or {}
            if not isinstance(data_model, dict):
                data_model = {}

            template = tuple(raw_components)
            bound = [_bind_component(c, data_model) for c in raw_components]
            rendered = _render_from_components(bound)
            rendered = StructuredReply(
                markdown=rendered.markdown,
                ui_intent=rendered.ui_intent,
                image_urls=rendered.image_urls,
                file_paths=rendered.file_paths,
                a2ui_components=tuple(bound),
                surface_directives=(SurfaceDirective(type="createsurface", surface_id=surface_id),),
            )
            surfaces[key] = SurfaceState(
                rendered=rendered,
                template_components=template,
                data_model=data_model,
            )
            directives.append(SurfaceDirective(type="createsurface", surface_id=surface_id))
            last_reply = rendered

        elif env_type == "updatecomponents":
            raw_components = env.get("components")
            if not isinstance(raw_components, list):
                continue
            existing = surfaces.get(key)
            data_model = existing.data_model if existing else {}

            template = tuple(raw_components)
            bound = [_bind_component(c, data_model) for c in raw_components]
            rendered = _render_from_components(bound)
            rendered = StructuredReply(
                markdown=rendered.markdown,
                ui_intent=rendered.ui_intent,
                image_urls=rendered.image_urls,
                file_paths=rendered.file_paths,
                a2ui_components=tuple(bound),
                surface_directives=(SurfaceDirective(type="updatecomponents", surface_id=surface_id),),
            )
            surfaces[key] = SurfaceState(
                rendered=rendered,
                template_components=template,
                data_model=data_model,
            )
            directives.append(SurfaceDirective(type="updatecomponents", surface_id=surface_id))
            last_reply = rendered

        elif env_type == "updatedatamodel":
            new_model = env.get("dataModel") or env.get("data_model") or {}
            if not isinstance(new_model, dict):
                continue
            existing = surfaces.get(key)
            if not existing:
                continue

            bound = [_bind_component(c, new_model) for c in existing.template_components]
            rendered = _render_from_components(bound)
            rendered = StructuredReply(
                markdown=rendered.markdown,
                ui_intent=rendered.ui_intent,
                image_urls=rendered.image_urls,
                file_paths=rendered.file_paths,
                a2ui_components=tuple(bound),
                surface_directives=(SurfaceDirective(type="updatedatamodel", surface_id=surface_id),),
            )
            existing.rendered = rendered
            existing.data_model = new_model
            directives.append(SurfaceDirective(type="updatedatamodel", surface_id=surface_id))
            last_reply = rendered

        elif env_type == "deletesurface":
            surfaces.pop(key, None)
            directives.append(SurfaceDirective(type="deletesurface", surface_id=surface_id))

    if not directives:
        return None

    # Build a combined reply with all directives
    if last_reply is not None:
        return StructuredReply(
            markdown=last_reply.markdown,
            ui_intent=last_reply.ui_intent,
            image_urls=last_reply.image_urls,
            file_paths=last_reply.file_paths,
            a2ui_components=last_reply.a2ui_components,
            surface_directives=tuple(directives),
        )
    # Only delete directives — return empty reply with directives
    return StructuredReply(
        markdown="",
        surface_directives=tuple(directives),
    )


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------


def structured_reply_from_text(
    raw_reply: str,
    session_id: str,
    surfaces: dict[tuple[str, str], SurfaceState],
) -> StructuredReply:
    """Parse raw agent reply text into a StructuredReply.

    Routes through A2UI envelope pipeline or simple JSON/plain-text path.
    """
    if not raw_reply or not raw_reply.strip():
        return StructuredReply(markdown="")

    text = raw_reply.strip()

    # Try to extract JSON
    json_text = _extract_json_object_text(text)
    if json_text:
        try:
            payload = json.loads(json_text)
        except (json.JSONDecodeError, ValueError):
            payload = None

        if isinstance(payload, dict):
            # Check for A2UI envelopes first
            a2ui_msgs = _extract_a2ui_messages(payload)
            if a2ui_msgs:
                result = _process_a2ui_envelopes(a2ui_msgs, session_id, surfaces)
                if result is not None:
                    return result

            # Simple JSON path
            markdown = str(payload.get("markdown", "")).strip() or text
            ui_intent = _parse_simple_ui_intent(payload)
            image_urls = list(_parse_image_urls(payload))
            file_paths = _parse_file_paths(payload)

            # Merge markdown images after JSON-specified ones
            for url in _extract_markdown_images(markdown):
                if url not in image_urls and len(image_urls) < _MAX_OUTPUT_IMAGES:
                    image_urls.append(url)

            return StructuredReply(
                markdown=markdown,
                ui_intent=ui_intent,
                image_urls=tuple(image_urls),
                file_paths=file_paths,
            )

    # Plain text path
    image_urls = _extract_markdown_images(text)
    return StructuredReply(
        markdown=text,
        image_urls=tuple(image_urls[:_MAX_OUTPUT_IMAGES]),
    )


def clear_session_surfaces(
    session_id: str,
    surfaces: dict[tuple[str, str], SurfaceState],
) -> None:
    """Remove all surface states for a given session."""
    to_remove = [k for k in surfaces if k[0] == session_id]
    for k in to_remove:
        del surfaces[k]


def get_session_id(
    guild_id: str | None,
    channel_id: str,
    user_id: str,
    thread_id: str | None = None,
) -> str:
    """Build a session ID following the deepbot pattern."""
    if thread_id:
        return f"thread:{thread_id}:user:{user_id}"
    if guild_id:
        return f"guild:{guild_id}:channel:{channel_id}:user:{user_id}"
    return f"dm:{user_id}"
