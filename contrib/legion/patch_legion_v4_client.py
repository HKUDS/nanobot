#!/usr/bin/env python3
"""Patch: Legion V4 — inject onAnyEvent() into NanobotClient (v0.2.0).

Targets (pre-compile, before hatch_build runs npm):
  - /app/webui/src/lib/types.ts          → add peers to BootstrapResponse (kept for typing)
  - /app/webui/src/lib/nanobot-client.ts → add onAnyEvent() + peers field (unused, backward compat)
  - /app/webui/src/App.tsx               → (no-op — V6 sidebar uses legion_update events)

Dual-target NOT required: WebUI .ts/.tsx patches are compiled into dist/,
only the /app/webui/src/ copy matters before the Vite build step.

Architecture note (since 2026-05-19):
  The V6 sidebar (patch_legion_v6_sidebar.py) reads agent roster from
  ``legion_update`` WS events injected by the Gatekeeper, not from
  bootstrap ``peers``.  This keeps the human-facing bootstrap endpoint
  (PR #3854) decoupled from machine-to-machine service discovery,
  aligning with upstream reviewer chengyongru's architectural feedback.
"""

from pathlib import Path

PATCH_LABEL = "legion-v4-client"

TYPES = Path("/app/webui/src/lib/types.ts")
CLIENT = Path("/app/webui/src/lib/nanobot-client.ts")
APP = Path("/app/webui/src/App.tsx")


def patch_types():
    """Add ``peers`` field to BootstrapResponse interface."""
    content = TYPES.read_text()

    anchor = "model_name?: string | null;"
    if anchor not in content:
        print(f"⚠ [{PATCH_LABEL}] types.ts anchor '{anchor}' not found — skip")
        return False

    new_field = (
        "  /** Legion: squad peer roster — keyed by agent name. */\n"
        "  peers?: Record<string, { id: string; name: string; gateway_port: number; ws_port: number }>;"
    )

    if new_field.strip() in content:
        print(f"  [{PATCH_LABEL}] types.ts already has peers field")
        return True

    content = content.replace(anchor, anchor + "\n" + new_field, 1)
    TYPES.write_text(content)
    print(f"✓ [{PATCH_LABEL}] types.ts — added peers to BootstrapResponse")
    return True


def patch_client():
    """Inject legion fields, onAnyEvent(), and any-event dispatch into NanobotClient."""
    content = CLIENT.read_text()

    # ── Injection A: fields (after errorHandlers) ──
    anchor_a = "private errorHandlers = new Set<ErrorHandler>();"
    if anchor_a not in content:
        print(f"⚠ [{PATCH_LABEL}] client anchor A '{anchor_a}' not found — skip")
        return False

    legion_fields = (
        "  /* Legion: generic event listeners for all inbound events (fires before dispatch). */\n"
        "  private anyEventHandlers = new Set<(ev: InboundEvent) => void>();\n"
        "  /* Legion: squad peer roster — kept for backward compat; V6 sidebar uses legion_update events instead. */\n"
        "  public peers: Record<string, { id: string; name: string; gateway_port: number; ws_port: number }> | null = null;"
    )

    if "anyEventHandlers" not in content:
        content = content.replace(anchor_a, anchor_a + "\n" + legion_fields, 1)
        print(f"  [{PATCH_LABEL}] client — added anyEventHandlers + peers fields")
    else:
        print(f"  [{PATCH_LABEL}] client — fields already present")

    # ── Injection B: onAnyEvent() method (after onError() closing brace) ──
    anchor_b = (
        "  onError(handler: ErrorHandler): Unsubscribe {\n"
        "    this.errorHandlers.add(handler);\n"
        "    return () => {\n"
        "      this.errorHandlers.delete(handler);\n"
        "    };\n"
        "  }"
    )
    if anchor_b not in content:
        print(f"⚠ [{PATCH_LABEL}] client anchor B not found — skip")
        return False

    on_any_event_method = (
        "\n"
        "  /** Legion: subscribe to ALL inbound events (fires before per-chat dispatch).\n"
        "   *  Use for legion_update / legion_peer_heartbeat events injected by gatekeeper. */\n"
        "  onAnyEvent(handler: (ev: InboundEvent) => void): Unsubscribe {\n"
        "    this.anyEventHandlers.add(handler);\n"
        "    return () => {\n"
        "      this.anyEventHandlers.delete(handler);\n"
        "    };\n"
        "  }"
    )

    if "onAnyEvent(handler" not in content:
        content = content.replace(anchor_b, anchor_b + on_any_event_method, 1)
        print(f"  [{PATCH_LABEL}] client — added onAnyEvent() method")
    else:
        print(f"  [{PATCH_LABEL}] client — onAnyEvent() already present")

    # ── Injection C: any-event dispatch in handleMessage (before ready check) ──
    anchor_c = "if (parsed.event === \"ready\") {"
    if anchor_c not in content:
        print(f"⚠ [{PATCH_LABEL}] client anchor C not found — skip")
        return False

    dispatch_block = (
        "    /* Legion: fire any-event handlers before standard routing. */\n"
        "    for (const handler of this.anyEventHandlers) {\n"
        "      try { handler(parsed); } catch (_) { /* guard */ }\n"
        "    }\n\n"
        "    "
    )

    if "for (const handler of this.anyEventHandlers)" not in content:
        content = content.replace(anchor_c, dispatch_block + anchor_c, 1)
        print(f"  [{PATCH_LABEL}] client — added any-event dispatch in handleMessage()")
    else:
        print(f"  [{PATCH_LABEL}] client — dispatch already present")

    CLIENT.write_text(content)
    return True


def patch_app():
    """(Architecture cleanup) V6 sidebar no longer reads bootstrap peers.

    Legacy: Exposed ``boot.peers`` → client.peers for the V4 sidebar component.
    Since V6 migration, agent roster flows exclusively through ``legion_update``
    WS events, keeping human-facing bootstrap decoupled from service discovery.

    The TypeScript field ``client.peers`` (null by default) is kept in
    nanobot-client.ts for backward compatibility but is intentionally unset.
    """
    print(f"  [{PATCH_LABEL}] skip — V6 uses legion_update events, not bootstrap peers")
    return True


def main():
    ok = True
    if TYPES.is_file():
        ok &= patch_types()
    else:
        print(f"⚠ [{PATCH_LABEL}] {TYPES} not found (upstream may have moved types)")
    if CLIENT.is_file():
        ok &= patch_client()
    else:
        print(f"⚠ [{PATCH_LABEL}] {CLIENT} not found (upstream may have renamed)")
    if APP.is_file():
        ok &= patch_app()
    else:
        print(f"⚠ [{PATCH_LABEL}] {APP} not found — check upstream path")
    if ok:
        print(f"✅ [{PATCH_LABEL}] complete")
    else:
        print(f"❌ [{PATCH_LABEL}] failed (some targets missing) — check upstream changes")


if __name__ == "__main__":
    main()
