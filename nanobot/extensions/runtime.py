"""Transactional activation at nanobot's tool, command, and hook seams."""

from __future__ import annotations

import importlib
import shutil
import sys
from dataclasses import dataclass
from importlib.machinery import ModuleSpec
from pathlib import Path
from types import ModuleType
from typing import Any

from nanobot.agent.hook import AgentHook, AgentTurnHookFactory
from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.command.router import CommandRouter, Handler
from nanobot.extensions.registry import (
    ExtensionCandidate,
    ExtensionDiagnostic,
    ExtensionSnapshot,
)


@dataclass(frozen=True, slots=True)
class ActivationResult:
    """Immutable activation outcome consumed by the agent assembly layer."""

    extensions: tuple[ExtensionCandidate, ...]
    hook_factories: tuple[AgentTurnHookFactory, ...]
    diagnostics: tuple[ExtensionDiagnostic, ...]


class PythonExtensionApi:
    """Small native API; extensions register into existing nanobot interfaces."""

    def __init__(
        self,
        *,
        owner: str,
        tools: ToolRegistry,
        commands: CommandRouter,
        hook_factories: list[AgentTurnHookFactory],
    ) -> None:
        self.owner = owner
        self._tools = tools
        self._commands = commands
        self._hook_factories = hook_factories

    def register_tool(self, tool: Tool) -> None:
        if not self._tools.register_if_absent(tool, owner=self.owner):
            existing = self._tools.owner(tool.name) or "unknown"
            raise ValueError(
                f"tool '{tool.name}' is already registered by '{existing}'"
            )

    def register_command(
        self,
        command: str,
        handler: Handler,
        *,
        prefix: bool = False,
    ) -> None:
        command = f"/{command.lstrip('/')}"
        if prefix:
            command = f"{command} "
        register = self._commands.prefix if prefix else self._commands.exact
        tier = "prefix" if prefix else "exact"
        if existing := self._commands.owner(tier, command):
            raise ValueError(
                f"command '{command}' is already registered by '{existing}'"
            )
        register(command, handler, owner=self.owner)

    def register_hook_factory(self, factory: AgentTurnHookFactory) -> None:
        self._hook_factories.append(_owned_hook_factory(factory, self.owner))


class ExtensionRuntimeManager:
    """Activate a resolved snapshot and roll back failed registrations."""

    def __init__(
        self,
        *,
        tools: ToolRegistry,
        commands: CommandRouter,
        hook_factories: list[AgentTurnHookFactory] | None = None,
    ) -> None:
        self._tools = tools
        self._commands = commands
        self._active: list[ExtensionCandidate] = []
        self._hook_factories = hook_factories if hook_factories is not None else []

    async def activate(self, snapshot: ExtensionSnapshot) -> ActivationResult:
        diagnostics: list[ExtensionDiagnostic] = []
        for candidate in snapshot.extensions:
            try:
                active = self._activate_candidate(candidate)
                self._active.append(active)
            except Exception as exc:
                self._rollback_owner(candidate.manifest.id)
                diagnostics.append(
                    ExtensionDiagnostic(
                        code="activation_failed",
                        extension_id=candidate.manifest.id,
                        message=str(exc),
                    )
                )
        return ActivationResult(
            tuple(self._active),
            tuple(self._hook_factories),
            tuple(diagnostics),
        )

    async def close(self) -> None:
        for active in reversed(self._active):
            self._rollback_owner(active.manifest.id)
            _unload_extension_modules(active)
        self._active.clear()

    def _activate_candidate(
        self,
        candidate: ExtensionCandidate,
    ) -> ExtensionCandidate:
        self._activate_python(candidate)
        return candidate

    def _activate_python(self, candidate: ExtensionCandidate) -> None:
        raw_entry = candidate.manifest.entry
        module_name, separator, attribute = raw_entry.partition(":")
        if not separator:
            module_name = raw_entry
            attribute = "register"
        assert candidate.location is not None
        importlib.invalidate_caches()
        module_prefix = _module_prefix(candidate.manifest.id)
        _unload_extension_modules(candidate)
        package = ModuleType(module_prefix)
        package.__package__ = module_prefix
        package.__path__ = [str(candidate.location)]
        package.__spec__ = ModuleSpec(module_prefix, loader=None, is_package=True)
        sys.modules[module_prefix] = package
        try:
            module = importlib.import_module(f"{module_prefix}.{module_name}")
            module_path = getattr(module, "__file__", None)
            if not module_path or not Path(module_path).resolve().is_relative_to(
                candidate.location.resolve()
            ):
                raise ValueError(
                    f"Python extension entry resolves outside its package: {module_name}"
                )
            register = getattr(module, attribute)
            api = PythonExtensionApi(
                owner=candidate.manifest.id,
                tools=self._tools,
                commands=self._commands,
                hook_factories=self._hook_factories,
            )
            result = register(api)
            if result is not None:
                raise TypeError("Python extension register function must return None")
        except Exception:
            _unload_extension_modules(candidate)
            raise

    def _rollback_owner(
        self,
        owner: str,
    ) -> None:
        self._tools.unregister_owner(owner)
        self._commands.unregister_owner(owner)
        self._hook_factories[:] = [
            factory
            for factory in self._hook_factories
            if getattr(factory, "__nanobot_extension_owner__", None) != owner
        ]


def _owned_hook_factory(
    factory: AgentTurnHookFactory,
    owner: str,
) -> AgentTurnHookFactory:
    def owned(context: Any) -> AgentHook | None:
        return factory(context)

    setattr(owned, "__nanobot_extension_owner__", owner)
    return owned


def _modules_under(root: Path) -> tuple[str, ...]:
    package_root = root.resolve()
    return tuple(
        name
        for name, module in tuple(sys.modules.items())
        if (raw_path := getattr(module, "__file__", None))
        and Path(raw_path).resolve().is_relative_to(package_root)
    )


def _unload_modules_under(root: Path) -> None:
    package_root = root.resolve()
    for module_name in _modules_under(package_root):
        sys.modules.pop(module_name, None)
    for cache in package_root.rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)


def _module_prefix(extension_id: str) -> str:
    return "_nanobot_extension_" + extension_id.encode().hex()


def _unload_extension_modules(candidate: ExtensionCandidate) -> None:
    assert candidate.location is not None
    prefix = _module_prefix(candidate.manifest.id)
    for name in tuple(sys.modules):
        if name == prefix or name.startswith(f"{prefix}."):
            sys.modules.pop(name, None)
    _unload_modules_under(candidate.location)
