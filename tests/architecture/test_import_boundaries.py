"""Regression coverage for the executable Python import boundaries."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from scripts.check_import_boundaries import Violation, find_violations


def test_repository_respects_import_boundaries() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "scripts.check_import_boundaries"],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("source", "target", "line"),
    [
        ("import nanobot.webui.metadata", "nanobot.webui.metadata", 1),
        ("from nanobot import webui", "nanobot.webui", 1),
        ("from nanobot.webui import metadata", "nanobot.webui.metadata", 1),
        ("from .. import webui", "nanobot.webui", 1),
        ("from ..webui import metadata", "nanobot.webui.metadata", 1),
        (
            "def load():\n    from nanobot.cli import gateway",
            "nanobot.cli.gateway", 2,
        ),
        (
            "import importlib\nimportlib.import_module('nanobot.webui.metadata')",
            "nanobot.webui.metadata", 2,
        ),
        (
            "import importlib as modules\n"
            "modules.import_module(name='nanobot.webui.metadata')",
            "nanobot.webui.metadata", 2,
        ),
        (
            "from importlib import import_module as load\n"
            "load('..webui.metadata', __package__)",
            "nanobot.webui.metadata", 2,
        ),
        (
            "from importlib import import_module\n"
            "import_module('..webui.metadata', package='nanobot.agent')",
            "nanobot.webui.metadata", 2,
        ),
        ("__import__('nanobot.webui.metadata')", "nanobot.webui.metadata", 1),
        (
            "import builtins as imports\nimports.__import__('nanobot.webui.metadata')",
            "nanobot.webui.metadata", 2,
        ),
    ],
)
def test_core_rejects_adapter_imports_in_supported_spellings(
    source: str, target: str, line: int,
) -> None:
    assert find_violations(source, "nanobot.agent.loop") == [
        Violation("core-execution", target, line),
    ]


@pytest.mark.parametrize(
    "source",
    [
        "from typing import TYPE_CHECKING as TC\n"
        "if TC:\n    from nanobot.webui import metadata",
        "import typing as t\n"
        "if t.TYPE_CHECKING:\n    from nanobot.webui import metadata",
    ],
)
def test_core_boundary_includes_type_dependencies(source: str) -> None:
    assert find_violations(source, "nanobot.agent.runner") == [
        Violation("core-execution", "nanobot.webui.metadata", 3),
    ]


@pytest.mark.parametrize(
    ("module", "rule"),
    [
        ("nanobot.session.manager", "session-storage"),
        ("nanobot.session.recovery", "session-storage"),
        ("nanobot.security.workspace_policy", "security-primitives"),
        ("nanobot.agent.turn_delivery", "core-execution"),
        ("nanobot.channels.notification_routes", "channel-routing-contracts"),
        ("nanobot.config.schema", "configuration-contracts"),
        ("nanobot.agent.tools.cli_apps_config", "tool-configuration-contracts"),
        ("nanobot.utils.file_io", "shared-primitives"),
    ],
)
def test_storage_and_security_do_not_depend_on_adapters(module: str, rule: str) -> None:
    assert find_violations("from nanobot.cli import gateway", module) == [
        Violation(rule, "nanobot.cli.gateway", 1),
    ]


def test_websocket_only_permits_progress_event_as_a_type_dependency() -> None:
    source = (
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    from nanobot.bus.outbound_events import ProgressEvent\n"
        "    from nanobot.command import router\n"
        "else:\n"
        "    from nanobot.bus.outbound_events import ProgressEvent\n"
    )
    assert find_violations(source, "nanobot.channels.websocket.runtime") == [
        Violation("websocket-transport", "nanobot.command.router", 4),
        Violation("websocket-transport", "nanobot.bus.outbound_events.ProgressEvent", 6),
    ]


@pytest.mark.parametrize(
    "source",
    [
        "from nanobot.config.schema import Base",
        "from ...config.schema import Base as ConfigBase",
    ],
)
def test_tool_configs_import_the_shared_base_directly(source: str) -> None:
    assert find_violations(source, "nanobot.agent.tools.shell") == [
        Violation("tool-config-base", "nanobot.config.schema.Base", 1),
    ]
    assert find_violations(
        "from nanobot.config_base import Base", "nanobot.agent.tools.shell",
    ) == []


def test_configuration_imports_the_six_tool_owned_config_contracts() -> None:
    source = (
        "from nanobot.agent.tools.cli_apps_config import CliAppsToolConfig\n"
        "from nanobot.agent.tools.filesystem_config import FileToolsConfig\n"
        "from nanobot.agent.tools.image_generation_config import ImageGenerationToolConfig\n"
        "from nanobot.agent.tools.self_config import MyToolConfig\n"
        "from nanobot.agent.tools.shell_config import ExecToolConfig\n"
        "from nanobot.agent.tools.web_config import WebToolsConfig\n"
    )
    assert find_violations(source, "nanobot.config.schema") == []


@pytest.mark.parametrize(
    ("module", "source"),
    [
        ("nanobot.agent.loop", "from nanobot.session.recovery import RecoveryAdmission"),
        ("nanobot.session.manager", "from nanobot.providers.base import ProviderConversationState"),
        ("nanobot.session.webui_turns", "from nanobot.webui import transcript"),
        ("nanobot.cli.gateway_runtime", "from nanobot.agent.loop import AgentLoop"),
        ("nanobot.channels.websocket.runtime", "from nanobot.webui import inbound_commands"),
        ("nanobot.agent.tools.cli_apps_config", "from nanobot.config_base import Base"),
        (
            "nanobot.agent.turn_delivery",
            "from nanobot.channels.notification_routes import notification_metadata",
        ),
    ],
)
def test_existing_runtime_and_composition_dependencies_remain_allowed(
    module: str, source: str,
) -> None:
    assert find_violations(source, module) == []


@pytest.mark.parametrize(
    ("relative", "source", "rule", "target", "line"),
    [
        (
            "nanobot/agent/runner.py", "import nanobot.webui.metadata",
            "core-execution", "nanobot.webui.metadata", 1,
        ),
        (
            "nanobot/agent/loop.py",
            "import importlib\nif importlib.import_module('nanobot.webui.metadata'):\n    pass",
            "core-execution", "nanobot.webui.metadata", 2,
        ),
        (
            "nanobot/agent/loop.py", "if __import__('nanobot.webui.metadata'):\n    pass",
            "core-execution", "nanobot.webui.metadata", 1,
        ),
        (
            "nanobot/session/manager.py", "from nanobot.cli import gateway",
            "session-storage", "nanobot.cli.gateway", 1,
        ),
        (
            "nanobot/channels/notification_routes.py",
            "from nanobot.channels.slack.runtime import SlackChannel",
            "channel-routing-contracts", "nanobot.channels.slack.runtime.SlackChannel", 1,
        ),
        (
            "nanobot/channels/notification_routes.py",
            "from nanobot.agent.turn_delivery import TurnRoute",
            "channel-routing-contracts", "nanobot.agent.turn_delivery.TurnRoute", 1,
        ),
        (
            "nanobot/security/__init__.py", "from ..cli import gateway",
            "security-primitives", "nanobot.cli.gateway", 1,
        ),
        (
            "nanobot/channels/websocket/runtime.py",
            "import importlib as modules\nmodules.import_module('nanobot.command.router')",
            "websocket-transport", "nanobot.command.router", 2,
        ),
        (
            "nanobot/agent/tools/shell.py", "from ...config.schema import Base as ConfigBase",
            "tool-config-base", "nanobot.config.schema.Base", 1,
        ),
        (
            "nanobot/channels/telegram/runtime.py", "from nanobot.config.schema import Base",
            "tool-config-base", "nanobot.config.schema.Base", 1,
        ),
        (
            "nanobot/config/schema.py", "from nanobot.agent.tools.shell import ExecTool",
            "configuration-contracts", "nanobot.agent.tools.shell.ExecTool", 1,
        ),
        (
            "nanobot/agent/tools/cli_apps_config.py", "from .cli_apps import CliAppsTool",
            "tool-configuration-contracts", "nanobot.agent.tools.cli_apps.CliAppsTool", 1,
        ),
        (
            "nanobot/agent/tools/web_config.py", "from nanobot.config.schema import Config",
            "tool-configuration-contracts", "nanobot.config.schema.Config", 1,
        ),
        (
            "nanobot/providers/oauth_catalog_cache.py",
            "from nanobot.providers import openai_codex_provider",
            "oauth-catalog-cache", "nanobot.providers.openai_codex_provider", 1,
        ),
    ],
)
def test_cli_rejects_a_violation_and_reports_its_source_location(
    tmp_path: Path, relative: str, source: str, rule: str, target: str, line: int,
) -> None:
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.write_text(source + "\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "scripts.check_import_boundaries", "--root", str(tmp_path)],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert result.stderr.strip() == f"{relative}:{line}: [{rule}] must not import {target}"


def test_cli_accepts_a_tool_owned_config_import(tmp_path: Path) -> None:
    path = tmp_path / "nanobot/config/schema.py"
    path.parent.mkdir(parents=True)
    path.write_text(
        "from nanobot.agent.tools.cli_apps_config import CliAppsToolConfig\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, "-m", "scripts.check_import_boundaries", "--root", str(tmp_path)],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
