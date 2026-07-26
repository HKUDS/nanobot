"""Transactional activation of external extensions at existing registry edges."""

from __future__ import annotations

import importlib
import shutil
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
from nanobot.extensions.manifest import DependencyKind
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
        config: Config,
        hook_factories: list[AgentTurnHookFactory] | None = None,
    ) -> None:
        self._tools = tools
        self._commands = commands
        self._config = config
        self._active: list[ActivatedExtension] = []
        self._hook_factories = hook_factories if hook_factories is not None else []

    async def activate(self, snapshot: ExtensionSnapshot) -> ActivationResult:
        diagnostics: list[ExtensionDiagnostic] = []
        activated_ids = {
            candidate.manifest.id
            for candidate in snapshot.extensions
            if candidate.location is None
        }
        for candidate in snapshot.extensions:
            if candidate.location is None:
                continue
            missing = [
                dependency.name
                for dependency in candidate.manifest.dependencies
                if not dependency.optional
                and dependency.kind is DependencyKind.EXTENSION
                and dependency.name not in activated_ids
            ]
            if missing:
                diagnostics.append(
                    ExtensionDiagnostic(
                        code="dependency_activation_failed",
                        extension_id=candidate.manifest.id,
                        message=(
                            "Required extensions did not activate: "
                            + ", ".join(sorted(missing))
                        ),
                    )
                )
                continue
            try:
                active = await self._activate_candidate(candidate)
                if active is not None:
                    self._active.append(active)
                    activated_ids.add(candidate.manifest.id)
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
        raw_entry = candidate.manifest.activation_entries[0]
        module_name, separator, attribute = raw_entry.partition(":")
        if not separator:
            module_name = raw_entry
            attribute = "register"
        assert candidate.location is not None
        importlib.invalidate_caches()
        _unload_modules_under(candidate.location)
        _reject_module_collision(module_name, candidate.location)
        sys.path.insert(0, str(candidate.location))
        try:
            module = importlib.import_module(module_name)
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
            _unload_modules_under(candidate.location)
            raise
        finally:
            sys.path.remove(str(candidate.location))

    def _register_compatible(
        self,
        candidate: ExtensionCandidate,
        compatible: CompatibleExtension,
    ) -> None:
        owner = candidate.manifest.id
        for tool in compatible.tools:
            if not self._tools.register_if_absent(tool, owner=owner):
                existing = self._tools.owner(tool.name) or "unknown"
                raise ValueError(
                    f"tool '{tool.name}' is already registered by '{existing}'"
                )
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
        self._hook_factories[:] = [
            factory
            for factory in self._hook_factories
            if getattr(factory, "__nanobot_extension_owner__", None) != owner
        ]
        if active and active.compatible:
            await active.compatible.close()
        if (
            active
            and active.candidate.manifest.runtime.value == "python"
            and active.candidate.location
        ):
            _unload_modules_under(active.candidate.location)


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


def _reject_module_collision(module_name: str, root: Path) -> None:
    package_root = root.resolve()
    parts = module_name.split(".")
    for index in range(1, len(parts) + 1):
        loaded = sys.modules.get(".".join(parts[:index]))
        loaded_path = getattr(loaded, "__file__", None)
        if loaded is not None and (
            not loaded_path
            or not Path(loaded_path).resolve().is_relative_to(package_root)
        ):
            raise ValueError(
                f"Python extension entry conflicts with loaded module: "
                f"{'.'.join(parts[:index])}"
            )
