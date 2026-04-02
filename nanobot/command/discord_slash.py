"""Discord slash command 注册。

职责单一：构造命令定义 + 调 Discord API 批量注册。
不处理 interaction 接收和响应（那是 discord channel 的事）。
"""

from __future__ import annotations

import base64
import re
from typing import TYPE_CHECKING

import httpx
from loguru import logger

if TYPE_CHECKING:
    from nanobot.agent.skills import SkillsLoader

DISCORD_API_BASE = "https://discord.com/api/v10"

# Discord 命令名限制：1-32 字符，小写字母/数字/连字符
_CMD_NAME_RE = re.compile(r"^[\w-]{1,32}$")

# builtin 命令名集合，skill 同名时跳过
_BUILTIN_NAMES = {"status", "new", "stop", "help", "tts"}


# ── App ID 提取 ──────────────────────────────────────────────

def extract_app_id(token: str) -> str:
    """从 bot token 第一段 base64 decode 得到 application id。

    Discord bot token 格式: {base64(app_id)}.{timestamp}.{hmac}
    """
    first_segment = token.split(".")[0]
    padded = first_segment + "=" * (-len(first_segment) % 4)
    return base64.b64decode(padded).decode("utf-8")


def _sanitize_command_name(name: str) -> str:
    """将 skill name 转为合法的 Discord 命令名。

    规则：小写，下划线转连字符，去非法字符，截断到 32 字符。
    """
    name = name.lower().replace("_", "-")
    name = re.sub(r"[^a-z0-9-]", "", name)
    name = re.sub(r"-{2,}", "-", name).strip("-")
    return name[:32]


# ── Builtin 命令定义 ─────────────────────────────────────────

def build_builtin_commands() -> list[dict]:
    """构造 builtin commands 的 Discord Application Command payload。"""
    return [
        {
            "name": "status",
            "description": "Show bot status",
            "type": 1,
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
                    "type": 3,
                    "required": False,
                    "choices": [
                        {"name": "on", "value": "on"},
                        {"name": "off", "value": "off"},
                    ],
                }
            ],
        },
    ]


# ── Skill 命令定义 ───────────────────────────────────────────

def build_skill_commands(skills_loader: SkillsLoader) -> list[dict]:
    """扫描 skills，构造 slash command payload。

    默认全部注册，除非 frontmatter 中显式 command: false。
    与 builtin 同名的 skill 自动跳过。
    每个 skill command 带一个可选 input 文本参数。
    """
    commands: list[dict] = []
    seen: set[str] = set(_BUILTIN_NAMES)

    for skill in skills_loader.list_skills(filter_unavailable=True):
        meta = skills_loader.get_skill_metadata(skill["name"]) or {}

        # 显式 command: false 跳过
        cmd_flag = str(meta.get("command", "true")).strip().lower()
        if cmd_flag == "false":
            continue

        # 命令名：优先 command_name，否则 sanitize skill name
        raw_name = meta.get("command_name") or skill["name"]
        cmd_name = _sanitize_command_name(raw_name)
        if not cmd_name or cmd_name in seen:
            continue
        seen.add(cmd_name)

        # 描述截断到 100 字符（Discord 限制）
        desc = (meta.get("description") or skill["name"])[:100]

        commands.append({
            "name": cmd_name,
            "description": desc,
            "type": 1,
            "options": [
                {
                    "name": "input",
                    "description": "Input for this skill",
                    "type": 3,
                    "required": False,
                }
            ],
        })

    return commands


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
    skills_loader: SkillsLoader | None = None,
) -> None:
    """注册所有命令（builtin + skills）到所有已知 guild。"""
    try:
        app_id = extract_app_id(token)
    except Exception as e:
        logger.error("Failed to extract app_id from token: {}", e)
        return

    commands = build_builtin_commands()
    if skills_loader:
        skill_cmds = build_skill_commands(skills_loader)
        commands.extend(skill_cmds)
        logger.info("Built {} skill commands for registration", len(skill_cmds))

    for gid in guild_ids:
        await register_guild_commands(http, app_id, gid, token, commands)
