# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for nanobot gateway sidecar binary."""

import os
import sys
from pathlib import Path

block_cipher = None

# Project root
ROOT = Path(SPECPATH).parent
NANOBOT_PKG = ROOT / "nanobot"

# All channel modules (needed because pkgutil.iter_modules doesn't work frozen)
channel_modules = [
    "nanobot.channels.desktop",
    "nanobot.channels.telegram",
    "nanobot.channels.discord",
    "nanobot.channels.slack",
    "nanobot.channels.whatsapp",
    "nanobot.channels.dingtalk",
    "nanobot.channels.feishu",
    "nanobot.channels.email",
    "nanobot.channels.matrix",
    "nanobot.channels.mochat",
    "nanobot.channels.qq",
    "nanobot.channels.wecom",
]

# Agent tools
tool_modules = [
    "nanobot.agent.tools.filesystem",
    "nanobot.agent.tools.shell",
    "nanobot.agent.tools.web",
    "nanobot.agent.tools.cron",
    "nanobot.agent.tools.message",
    "nanobot.agent.tools.mcp",
    "nanobot.agent.tools.spawn",
]

# Providers
provider_modules = [
    "nanobot.providers.litellm_provider",
    "nanobot.providers.custom_provider",
    "nanobot.providers.azure_openai_provider",
    "nanobot.providers.openai_codex_provider",
    "nanobot.providers.transcription",
]

# Core hidden imports
core_hidden = [
    "nanobot",
    "nanobot.cli",
    "nanobot.cli.commands",
    "nanobot.config",
    "nanobot.config.schema",
    "nanobot.config.loader",
    "nanobot.config.paths",
    "nanobot.bus",
    "nanobot.bus.queue",
    "nanobot.bus.events",
    "nanobot.agent",
    "nanobot.agent.loop",
    "nanobot.agent.context",
    "nanobot.agent.memory",
    "nanobot.agent.subagent",
    "nanobot.session",
    "nanobot.session.manager",
    "nanobot.cron",
    "nanobot.cron.service",
    "nanobot.heartbeat",
    "nanobot.channels",
    "nanobot.channels.base",
    "nanobot.channels.manager",
    "nanobot.channels.registry",
    "nanobot.providers",
    "nanobot.providers.base",
    "nanobot.providers.registry",
    "nanobot.agent.tools",
    "nanobot.agent.tools.base",
    "nanobot.agent.tools.registry",
]

# Third-party hidden imports
third_party_hidden = [
    "typer",
    "click",
    "litellm",
    "pydantic",
    "pydantic_settings",
    "pydantic.alias_generators",
    "httpx",
    "websockets",
    "websocket",
    "loguru",
    "rich",
    "prompt_toolkit",
    "croniter",
    "tiktoken",
    "tiktoken_ext",
    "tiktoken_ext.openai_public",
    "json_repair",
    "openai",
    "anyio",
    "sniffio",
    "certifi",
    "charset_normalizer",
    "idna",
    "h11",
    "httpcore",
    "distro",
]

hiddenimports = (
    core_hidden
    + channel_modules
    + tool_modules
    + provider_modules
    + third_party_hidden
)

# Collect data files (templates, skills)
datas = []
templates_dir = NANOBOT_PKG / "templates"
if templates_dir.exists():
    datas.append((str(templates_dir), "nanobot/templates"))

skills_dir = NANOBOT_PKG / "skills"
if skills_dir.exists():
    datas.append((str(skills_dir), "nanobot/skills"))

a = Analysis(
    [str(ROOT / "scripts" / "gateway_entry.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude heavy optional deps to reduce binary size
        "matplotlib",
        "numpy",
        "pandas",
        "scipy",
        "sklearn",
        "torch",
        "tensorflow",
        "PIL",
        "cv2",
        "IPython",
        "notebook",
        "jupyter",
        "tkinter",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="nanobot-gateway",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
