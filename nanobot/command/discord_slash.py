"""Discord slash command 注册。

职责单一：构造命令定义 + 调 Discord API 批量注册。
不处理 interaction 接收和响应（那是 discord channel 的事）。
"""

from __future__ import annotations

import base64

import httpx
from loguru import logger

DISCORD_API_BASE = "https://discord.com/api/v10"

# ── App ID 提取 ──────────────────────────────────────────────

def extract_app_id(token: str) -> str:
    """从 bot token 第一段 base64 decode 得到 application id。

    Discord bot token 格式: {base64(app_id)}.{timestamp}.{hmac}
    """
    first_segment = token.split(".")[0]
    # 补齐 base64 padding
    padded = first_segment + "=" * (-len(first_segment) % 4)
    return base64.b64decode(padded).decode("utf-8")


# ── Builtin 命令定义 ─────────────────────────────────────────

def build_builtin_commands() -> list[dict]:
    """构造 builtin commands 的 Discord Application Command payload。"""
    return [
        {
            "name": "status",
            "description": "Show bot status",
            "type": 1,  # CHAT_INPUT
        },
        {
            "name": "new",
            "description": "Start a new conversation",
            "type": 1,
        },
        {
            "name": "stop",
            "description": "Stop the current task",
            "type": 1,
        },
        {
            "name": "help",
            "description": "Show available commands",
            "type": 1,
        },
        {
            "name": "tts",
            "description": "Toggle text-to-speech",
            "type": 1,
            "options": [
                {
                    "name": "mode",
                    "description": "on or off",
                    "type": 3,  # STRING
                    "required": False,
                    "choices": [
                        {"name": "on", "value": "on"},
                        {"name": "off", "value": "off"},
                    ],
                }
            ],
        },
    ]


# ── 注册 API ─────────────────────────────────────────────────

async def register_guild_commands(
    http: httpx.AsyncClient,
    app_id: str,
    guild_id: str,
    token: str,
    commands: list[dict],
) -> bool:
    """批量覆盖 guild 级 slash commands（PUT = 幂等）。"""
    url = f"{DISCORD_API_BASE}/applications/{app_id}/guilds/{guild_id}/commands"
    headers = {"Authorization": f"Bot {token}"}
    try:
        resp = await http.put(url, headers=headers, json=commands)
        resp.raise_for_status()
        logger.info("Registered {} slash commands for guild {}", len(commands), guild_id)
        return True
    except Exception as e:
        logger.warning("Failed to register slash commands for guild {}: {}", guild_id, e)
        return False


async def register_all_commands(
    http: httpx.AsyncClient,
    token: str,
    guild_ids: list[str],
) -> None:
    """注册所有命令到所有已知 guild。启动时调用一次。"""
    try:
        app_id = extract_app_id(token)
    except Exception as e:
        logger.error("Failed to extract app_id from token: {}", e)
        return

    commands = build_builtin_commands()
    for gid in guild_ids:
        await register_guild_commands(http, app_id, gid, token, commands)
