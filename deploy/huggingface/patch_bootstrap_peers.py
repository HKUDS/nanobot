#!/usr/bin/env python3
"""Patch bootstrap_peers for squad v4.2 — adapted for upstream refactor (May 2026).

Upstream refactored bootstrap model-name resolution:
  _read_webui_model_name → _default_model_name_from_config + _resolve_bootstrap_model_name
Anchors updated accordingly.

v4.2: patch BOTH site-packages AND /app (PYTHONPATH=/app causes agents to load
      from /app/nanobot/ instead of site-packages — root cause of missing peers)
v4.1: cache-bust + defensive str() hardening
"""
import shutil


# PYTHONPATH="/app:..." means agents load from /app first — patch BOTH locations
TARGETS = [
    "/usr/local/lib/python3.12/site-packages/nanobot/channels/websocket.py",
    "/app/nanobot/channels/websocket.py",
]

total_patches = 0

for TARGET in TARGETS:
    # Check if target file exists
    try:
        with open(TARGET, "r") as f:
            _ = f.read(1)
    except FileNotFoundError:
        print(f"\n⏭️  {TARGET}: not found, skipping")
        continue

    # Backup
    shutil.copy2(TARGET, TARGET + ".bak")
    print(f"\n📦 backup: {TARGET}.bak")

    with open(TARGET, "r") as f:
        source = f.read()

    local_patches = 0

    # ── PATCH_0: import os ───────────────────────────────────────────────
    anchor_0 = "import binascii\n"
    if "import os\n" not in source:
        source = source.replace(anchor_0, anchor_0 + "import os\n", 1)
        print(f"  ✅ PATCH_0: import os")
        local_patches += 1
    else:
        print(f"  ⏭️  PATCH_0 skip: import os already present")

    # ── PATCH_1: insert _read_peers() before _parse_request_path ─────────
    anchor_1 = (
        "    return _default_model_name_from_config()\n"
        "\n"
        "\n"
        "def _parse_request_path"
    )
    peers_fn = (
        "    return _default_model_name_from_config()\n"
        "\n"
        "\n"
        "def _read_peers() -> dict | None:\n"
        '    """Read peers via squad_config_sync (v4.2 — defensive hardening).\n'
        "\n"
        "    Returns a dict of {name: {id}} for each squad member, or None when\n"
        "    no roster is available. The frontend uses this for agent discovery.\n"
        "    All values defensively coerced via str() to prevent frontend crashes.\n"
        '    """\n'
        "    try:\n"
        "        from squad_config_sync import get_roster\n"
        "        roster, _ = get_roster()\n"
        "        if not roster:\n"
        "            return None\n"
        "        peers = {}\n"
        "        for name, info in roster.items():\n"
        '            if "id" in info:\n'
        '                peers[str(name)] = {"id": str(info["id"])}\n'
        "        return peers or None\n"
        "    except Exception:\n"
        "        return None\n"
        "\n"
        "\n"
        "def _parse_request_path"
    )

    if "_read_peers()" not in source:
        if anchor_1 in source:
            source = source.replace(anchor_1, peers_fn, 1)
            print(f"  ✅ PATCH_1: _read_peers() inserted")
            local_patches += 1
        else:
            print(f"  ❌ PATCH_1 anchor not found")
            lines = source.split("\n")
            found = False
            for i, line in enumerate(lines):
                if "_parse_request_path" in line:
                    found = True
                    start = max(0, i - 12)
                    for j in range(start, min(len(lines), i + 3)):
                        marker = ">>>" if j == i else "   "
                        print(f"  {marker} {j+1}: {lines[j]}")
                    break
            if not found:
                print("  (_parse_request_path not found at all!)")
            raise SystemExit(1)
    else:
        print(f"  ⏭️  PATCH_1 skip: _read_peers already present")

    # ── PATCH_2: add "peers" to bootstrap response ───────────────────────
    anchor_2 = (
        '                "model_name": _resolve_bootstrap_model_name(self._runtime_model_name),\n'
        "            }\n"
    )
    replacement_2 = (
        '                "model_name": _resolve_bootstrap_model_name(self._runtime_model_name),\n'
        '                "peers": _read_peers(),\n'
        "            }\n"
    )

    if '"peers": _read_peers()' not in source:
        if anchor_2 in source:
            source = source.replace(anchor_2, replacement_2, 1)
            print(f"  ✅ PATCH_2: peers in bootstrap response")
            local_patches += 1
        else:
            print(f"  ❌ PATCH_2 anchor not found")
            for kw in ["_resolve_bootstrap_model_name", "_read_webui_model_name", "model_name"]:
                idx = source.find(kw)
                if idx >= 0:
                    print(f"     (found '{kw}' at offset {idx})")
                else:
                    print(f"     ('{kw}' NOT found!)")
            raise SystemExit(1)
    else:
        print(f"  ⏭️  PATCH_2 skip: peers already in bootstrap response")

    # Write
    with open(TARGET, "w") as f:
        f.write(source)

    print(f"  → {TARGET}: {local_patches} patch(es)")
    total_patches += local_patches

print(f"\n🎉 Done — {total_patches} total patch(es) applied across {len(TARGETS)} target(s)")
