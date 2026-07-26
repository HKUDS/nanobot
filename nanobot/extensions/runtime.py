"""Transactional activation of external extensions at existing registry edges."""

from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nanobot.agent.hook import AgentHook, AgentTurnHookFactory
from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.command.router import CommandRouter, Handler
from nanobot.config.schema import Config
from nanobot.extensions.compatibility import CompatibleExtension
from nanobot.extensions.node_host import NodeSidecar
from nanobot.extensions.registry import (
    ExtensionCandidate,
    ExtensionDiagnostic,
    ExtensionSnapshot,
)


@dataclass(frozen=True, slots=True)
class ActivatedExtension:
    """One active runtime and the resources needed to deactivate it."""

    candidate: ExtensionCandidate
    compatible: CompatibleExtension | None = None
    diagnostics: tuple[ExtensionDiagnostic, ...] = ()


@dataclass(frozen=True, slots=True)
class ActivationResult:
    """Immutable activation outcome consumed by the agent assembly layer."""

    extensions: tuple[ActivatedExtension, ...]
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
        self._tools.register(tool, owner=self.owner)

    def register_command(
        self,
        command: str,
        handler: Handler,
        *,
        prefix: bool = False,
    ) -> None:
        register = self._commands.prefix if prefix else self._commands.exact
        register(command, handler, owner=self.owner)

    def register_hook_factory(self, factory: AgentTurnHookFactory) -> None:
        self._hook_factories.append(factory)


class ExtensionRuntimeManager:
    """Activate a resolved snapshot and roll back failed registrations."""

    def __init__(
        self,
        *,
        tools: ToolRegistry,
        commands: CommandRouter,
        config: Config,
    ) -> None:
        self._tools = tools
        self._commands = commands
        self._config = config
        self._active: list[ActivatedExtension] = []
        self._hook_factories: list[AgentTurnHookFactory] = []

    async def activate(self, snapshot: ExtensionSnapshot) -> ActivationResult:
        diagnostics: list[ExtensionDiagnostic] = []
        for candidate in snapshot.extensions:
            if candidate.location is None:
                continue
            try:
                active = await self._activate_candidate(candidate)
                if active is not None:
                    self._active.append(active)
                    diagnostics.extend(active.diagnostics)
            except Exception as exc:
                await self._rollback_owner(candidate.manifest.id)
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
            await self._rollback_owner(active.candidate.manifest.id, active)
        self._active.clear()
        self._hook_factories.clear()

    async def _activate_candidate(
        self,
        candidate: ExtensionCandidate,
    ) -> ActivatedExtension | None:
        runtime = candidate.manifest.runtime.value
        if runtime == "declarative":
            return ActivatedExtension(candidate)
        entries = _resolve_entries(candidate)
        if runtime == "python":
            self._activate_python(candidate)
            return ActivatedExtension(candidate)
        if runtime not in {"pi", "openclaw"}:
            raise ValueError(f"unsupported extension runtime: {runtime}")

        host = NodeSidecar()
        try:
            entry_config = self._config.extensions.entries.get(candidate.manifest.id)
            result = await host.load(
                runtime=runtime,
                entries=entries,
                root=candidate.location,
                extension_id=candidate.manifest.id,
                name=candidate.manifest.name,
                version=candidate.manifest.version,
                config=entry_config.config if entry_config else {},
                workspace=self._config.workspace_path,
            )
            compatible = CompatibleExtension(
                host=host,
                runtime=runtime,
                owner=candidate.manifest.id,
                result=result,
            )
            self._register_compatible(candidate, compatible)
            diagnostics = [
                ExtensionDiagnostic(
                    code="compatibility_notice",
                    extension_id=candidate.manifest.id,
                    message=message,
                )
                for message in result.diagnostics
            ]
            diagnostics.extend(
                ExtensionDiagnostic(
                    code="unsupported_compatible_contribution",
                    extension_id=candidate.manifest.id,
                    message=(
                        f"{item.kind} '{item.name}' is visible in the catalog but "
                        "is not executable through this compatibility adapter"
                    ),
                )
                for item in result.registrations
                if item.kind not in {"tool", "command", "hook"}
            )
            return ActivatedExtension(candidate, compatible, tuple(diagnostics))
        except Exception:
            await host.close()
            raise

    def _activate_python(self, candidate: ExtensionCandidate) -> None:
        if len(candidate.manifest.activation_entries) != 1:
            raise ValueError("Python extensions must declare exactly one entry")
        module_name, separator, attribute = candidate.manifest.entry.partition(":")
        if not separator:
            module_name = candidate.manifest.entry
            attribute = "register"
        assert candidate.location is not None
        sys.path.insert(0, str(candidate.location))
        try:
            register = getattr(importlib.import_module(module_name), attribute)
            api = PythonExtensionApi(
                owner=candidate.manifest.id,
                tools=self._tools,
                commands=self._commands,
                hook_factories=self._hook_factories,
            )
            result = register(api)
            if result is not None:
                raise TypeError("Python extension register function must return None")
        finally:
            sys.path.remove(str(candidate.location))

    def _register_compatible(
        self,
        candidate: ExtensionCandidate,
        compatible: CompatibleExtension,
    ) -> None:
        owner = candidate.manifest.id
        for tool in compatible.tools:
            existing = self._tools.owner(tool.name)
            if existing and existing != owner:
                raise ValueError(
                    f"tool '{tool.name}' is already registered by '{existing}'"
                )
            self._tools.register(tool, owner=owner)
        compatible.register_commands(self._commands)
        if hook := compatible.hook:
            self._hook_factories.append(_constant_hook_factory(hook, owner))

    async def _rollback_owner(
        self,
        owner: str,
        active: ActivatedExtension | None = None,
    ) -> None:
        self._tools.unregister_owner(owner)
        self._commands.unregister_owner(owner)
        self._hook_factories = [
            factory
            for factory in self._hook_factories
            if getattr(factory, "__nanobot_extension_owner__", None) != owner
        ]
        if active and active.compatible:
            await active.compatible.close()


def _resolve_entries(candidate: ExtensionCandidate) -> tuple[Path, ...]:
    manifest = candidate.manifest
    location = candidate.location
    entries = manifest.activation_entries
    if location is None or not entries:
        raise ValueError(f"extension '{manifest.id}' does not declare any entries")
    if manifest.runtime.value == "python":
        return (location,)
    resolved: list[Path] = []
    for raw_entry in entries:
        entry = (location / raw_entry).resolve()
        if not entry.is_relative_to(location.resolve()):
            raise ValueError(f"extension '{manifest.id}' entry escapes its package")
        if not entry.is_file():
            raise ValueError(
                f"extension '{manifest.id}' entry does not exist: {entry}"
            )
        resolved.append(entry)
    return tuple(resolved)


def _constant_hook_factory(hook: AgentHook, owner: str) -> AgentTurnHookFactory:
    def factory(_context: Any) -> AgentHook:
        return hook

    setattr(factory, "__nanobot_extension_owner__", owner)
    return factory
