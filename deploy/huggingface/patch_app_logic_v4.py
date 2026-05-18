#!/usr/bin/env python3
"""
Squad App Logic Patch v4.1 — MessageEvent Layer Fix (Audit-Safe)
===================================================
V4 -> V4.1 Fix:
  Ensured 'logs', 'messages', and 'history' fields are preserved in 
  the squad_update event payload to prevent front-end .slice() errors.

Original Logic by Neo. 
Patch for fields by Gemini.
"""

import os
import sys

possible_paths = [
    "webui/src/App.tsx",
    "src/App.tsx",
]
target = None
for p in possible_paths:
    if os.path.exists(p):
        target = p
        break

if not target:
    for root, dirs, files in os.walk("."):
        for f in files:
            if f == "App.tsx":
                target = os.path.join(root, f)
                break

if not target:
    print("❌ App.tsx not found")
    sys.exit(1)

print(f"📄 Target: {target}")

with open(target, "r") as f:
    content = f.read()

original = content

# ── Guard: skip if V4.1 already applied ─────────────────────────
if "Squad Neural Bridge v4.1" in content:
    print("✅ V4.1 already present — skipping")
    sys.exit(0)

# ── Cleanup stale blocks (Including problematic v4) ─────────────
markers = [
    "// --- [Squad Monitor Neural Bridge] ---",
    "// ═══ [Squad Neural Bridge v2] ═══",
    "// ═══ [Squad Neural Bridge v3] ═══",
    "// ═══ [Squad Neural Bridge v4] ═══", # 清理旧版 v4
]

for marker in markers:
    if marker in content:
        lines = content.split("\n")
        new_lines = []
        skip = False
        brace_depth = 0
        for i, line in enumerate(lines):
            if marker in line:
                skip = True
                brace_depth = 0
                continue
            if skip:
                brace_depth += line.count("{") - line.count("}")
                if brace_depth <= 0 and ("}, []);" in line or "}, [token]);" in line or "}, [wscUrl, token]);" in line):
                    skip = False
                    continue
            else:
                new_lines.append(line)
        content = "\n".join(new_lines)
        print(f"🧹 Removed stale block: {marker}")

# ── V4.1 Interceptor ────────────────────────────────────────────
interceptor = """
          // ═══ [Squad Neural Bridge v4.1] ═══
          const clientAny = client as any;
          if (typeof clientAny.handleMessage === "function") {
            const rawHandler = clientAny.handleMessage.bind(clientAny);
            let _squadV4First = true;
            clientAny.handleMessage = (rawEvent: any) => {
              let parsed: any;
              try {
                const raw = typeof rawEvent.data === "string" ? rawEvent.data : "";
                if (!raw) return rawHandler(rawEvent);
                parsed = JSON.parse(raw);
              } catch {
                return rawHandler(rawEvent);
              }

              if (
                parsed &&
                (parsed.type === "cluster_update" ||
                  parsed.type === "legion_update")
              ) {
                const status = parsed.data || {};
                const online = Object.values(status).filter(
                  (v: any) => v === "online"
                ).length;
                
                // 🛠️ V4.1 FIX: Explicitly include logs/messages to prevent UI crash
                const payload = { 
                    ...status, 
                    active_clusters: online, 
                    _roster: parsed.roster || {},
                    logs: parsed.logs || [],
                    messages: parsed.messages || [],
                    history: parsed.history || []
                };

                if (_squadV4First) {
                  console.log(
                    "[SquadBridge v4.1] active — first status update:",
                    online, "online",
                    payload
                  );
                  _squadV4First = false;
                }

                window.dispatchEvent(
                  new CustomEvent("squad_update", { detail: payload })
                );
                window.dispatchEvent(
                  new CustomEvent("squad_log_update", { detail: parsed })
                );
                return; 
              }

              if (parsed && parsed.type === "cluster_log") {
                window.dispatchEvent(
                  new CustomEvent("squad_log_update", { detail: parsed })
                );
                return;
              }

              try {
                return rawHandler(rawEvent);
              } catch (err) {
                console.error("[SquadBridge] rawHandler crashed:", err);
              }
            };
          } else {
            console.warn(
              "[SquadBridge v4.1] handleMessage not found on client — patch skipped",
              typeof clientAny.handleMessage
            );
          }
          // ═════════════════════════════════════"""

# Anchor: inject right before client.connect()
anchor = "client.connect();"
if anchor in content:
    content = content.replace(
        anchor,
        interceptor + "\n          " + anchor,
    )
    print("✅ V4.1 interceptor injected before client.connect()")
else:
    print("❌ anchor 'client.connect();' not found")
    sys.exit(1)

if content != original:
    with open(target, "w") as f:
        f.write(content)
    print(f"🎯 App logic patch v4.1 applied to {target}")
else:
    print("⚠️  No changes made")

# ── Diff preview (Ensures audit visibility) ────────────────────
import difflib
diff = difflib.unified_diff(
    original.splitlines(keepends=True),
    content.splitlines(keepends=True),
    fromfile="original",
    tofile="patched",
)
print("\n─── Diff Preview ───")
count = 0
for line in diff:
    if count > 100:
        print("... (truncated)")
        break
    print(line, end="")
    count += 1