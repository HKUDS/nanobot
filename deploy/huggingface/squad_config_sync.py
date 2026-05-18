#!/usr/bin/env python3
"""
军团端口配置中心 (Squad Config Sync) v4.0
=============================================
模块化设计 — 内存传递替代磁盘中介。

- get_roster() → 返回 dict，供 gatekeeper 直接导入（零磁盘）
- sync_configs() → 写 agent config.json，供 entrypoint.sh 调用
"""

import os, json, glob, sys
from pathlib import Path
from datetime import datetime
from copy import deepcopy

TEMPLATE = "/data/instances/_template/config.json"
INSTANCES_ROOT = "/data/instances"

def _log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

# ═══ 1. 纯函数：env → squad dict（无副作用） ═══════════════════

def _parse_squad():
    """从 NANOBOT_PEER_* env vars 解析 roster。"""
    squad = {}
    for key in sorted(k for k in os.environ if k.startswith("NANOBOT_PEER_")):
        name = key.replace("NANOBOT_PEER_", "").lower()
        try:
            data = json.loads(os.environ[key])
        except json.JSONDecodeError:
            continue
        gw = data.get("gateway_port")
        ws = data.get("ws_port")
        if not gw or not ws:
            continue
        squad[name] = {
            "id": data.get("id", ""),
            "gateway_port": int(gw),
            "ws_port": int(ws),
        }
    return squad

# ═══ 2. 导出：gatekeeper 内存读取 ═══════════════════════════════

def get_roster():
    """
    供 gatekeeper.py 直接导入 — 全部在内存中，无磁盘 IO。
    返回: (roster: dict, webui_agent: str)
    """
    squad = _parse_squad()
    if not squad:
        return {}, "neo"

    webui_target = os.environ.get("WEBUI_AGENT", "").strip().lower()
    if not webui_target or webui_target not in squad:
        webui_target = "neo"

    return squad, webui_target

# ═══ 2.5 动态 env key 收集 — 运行时注入 allowed_env_keys ═══════

def _build_allowed_env_keys():
    """Collect all dynamic env keys that squad agents should have access to."""
    keys = set()
    for key in os.environ:
        if key.startswith('NANOBOT_PEER_'):
            keys.add(key)
    # Squad operational keys
    keys.update([
        'SQUAD_LEGION',
        'NANOBOT_TOKEN',
        'COMMANDER_WHITELIST',
        'USER_AGENT_MAP',
        'SQUAD_ROSTER',
        'SQUAD_RELAY_TOKEN',
    ])
    return sorted(keys)

# ═══ 3. 导出：entrypoint.sh 调用 — 写 agent config.json ═══════

def sync_configs():
    """
    从 NANOBOT_PEER_* 创建/同步各 agent 的 config.json。
    - 新 agent：从模板 deepcopy → patch 端口 → 写入
    - 已有 agent：同步 gateway.port
    无返回值 — 结果直接落盘到 /data/instances/{name}/config.json
    """
    _log("🛡️ Squad Config Sync v4.0 — 军团端口配置中心")
    print()

    squad = _parse_squad()
    if not squad:
        _log("❌ 无有效 NANOBOT_PEER_* 变量，退出")
        sys.exit(1)

    # 诊断表
    print(f"  {'Agent':<12} {'gateway':>8} {'ws':>8}")
    print(f"  {'─'*12} {'─'*8} {'─'*8}")
    for name, info in squad.items():
        print(f"  {name:<12} {info['gateway_port']:>8} {info['ws_port']:>8}")
    print()

    # ═══ 动态编制：新 agent 从模板创建 ═══════════════════════
    template = None
    if os.path.isfile(TEMPLATE):
        try:
            template = json.loads(Path(TEMPLATE).read_text())
        except Exception as e:
            _log(f"  ❌ 模板读取失败: {e}")
            template = None

        if template:
            for name, info in squad.items():
                inst_dir = Path(INSTANCES_ROOT) / name
                cfg_path = inst_dir / "config.json"

                if cfg_path.exists():
                    continue

                _log(f"  🆕 {name}: 新 agent，从模板创建...")
                try:
                    # Clean stale file shadows before mkdir
                    if inst_dir.exists() and not inst_dir.is_dir():
                        _log(f"     ⚠️  清理残留文件: {inst_dir}")
                        inst_dir.unlink()
                    inst_dir.mkdir(parents=True, exist_ok=True)
                    (inst_dir / "workspace").mkdir(exist_ok=True)

                    cfg = deepcopy(template)
                    cfg["gateway"]["port"] = info["gateway_port"]
                    cfg["channels"]["websocket"]["port"] = info["ws_port"]
                    cfg["agents"]["defaults"]["instructions"] = (
                        f"【{name.upper()}】Squad agent {name}. "
                        f"Configure your role via Web UI."
                    )

                    # Inject dynamic allowed_env_keys
                    allowed = _build_allowed_env_keys()
                    cfg.setdefault("tools", {}).setdefault("exec", {})["allowed_env_keys"] = allowed

                    cfg_path.write_text(
                        json.dumps(cfg, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8"
                    )
                    _log(f"     ✅ gw={info['gateway_port']} ws={info['ws_port']}")
                except Exception as e:
                    _log(f"     ❌ 创建失败: {e}")
    else:
        _log(f"  ⚠️  模板缺失: {TEMPLATE}")

    # ═══ 同步已有 agent config.json（排除模板自身）══════
    cfg_files = [
        f for f in glob.glob(f"{INSTANCES_ROOT}/*/config.json")
        if os.path.basename(os.path.dirname(f)) != "_template"
    ]

    for cfg_path in sorted(cfg_files):
        inst_name = os.path.basename(os.path.dirname(cfg_path))

        try:
            # Atomic write: read → patch → write to .tmp → os.replace
            with open(cfg_path, "r") as f:
                cfg = json.load(f)

            # --- Squad config sanitization ---
            # Fix corrupted configs that may have root-level keys from hotfix mismatches.
            # Known corruption: "exec" at root level — belongs at tools.exec only.
            _bad_keys_removed = []
            for _bad_key in ["exec"]:
                if _bad_key in cfg:
                    del cfg[_bad_key]
                    _bad_keys_removed.append(_bad_key)
            if _bad_keys_removed:
                _log(f"   🧹 {inst_name}: cleaned corrupted root keys: {_bad_keys_removed}")
            # --- End sanitization ---

            if inst_name in squad:
                cfg.setdefault("gateway", {})["port"] = squad[inst_name]["gateway_port"]
                port_mark = f"→ gw={squad[inst_name]['gateway_port']}"
            else:
                port_mark = "(not in roster)"

            # Merge dynamic allowed_env_keys
            allowed = _build_allowed_env_keys()
            tools_cfg = cfg.setdefault("tools", {})
            exec_cfg = tools_cfg.setdefault("exec", {})
            existing = set(exec_cfg.get("allowed_env_keys", []))
            merged = sorted(existing | set(allowed))
            exec_cfg["allowed_env_keys"] = merged

            # Sync provider/model from template (ensure template updates reach running agents)
            if template:
                default_provider = template.get("agents", {}).get("defaults", {}).get("provider")
                default_model = template.get("agents", {}).get("defaults", {}).get("model")
                providers = template.get("providers", {})
                agents_cfg = cfg.setdefault("agents", {}).setdefault("defaults", {})
                if default_provider:
                    agents_cfg["provider"] = default_provider
                if default_model:
                    agents_cfg["model"] = default_model
                if providers:
                    cfg["providers"] = providers

            tmp_path = cfg_path + ".tmp"
            with open(tmp_path, "w") as f:
                json.dump(cfg, f, indent=2, ensure_ascii=False)
            os.replace(tmp_path, cfg_path)

            _log(f"   ✅ {inst_name}: config 已同步 {port_mark}")
        except Exception as e:
            _log(f"   ❌ {inst_name}: 写入失败 — {e}")

    if not cfg_files:
        _log("   ⚠️  未检测到任何实例 config.json")

    print()
    _log("🏁 完成 — gatekeeper 通过 import 读取 roster（内存）")

# ═══ CLI 入口（向后兼容） ════════════════════════════════════

if __name__ == "__main__":
    sync_configs()
