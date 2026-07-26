"""Project existing nanobot registries into the extension control plane."""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Iterable

from packaging.requirements import Requirement

from nanobot import __version__
from nanobot.extensions.discovery import ExtensionDiscoveryResult
from nanobot.extensions.manifest import (
    ContributionKind,
    DependencyKind,
    ExtensionContribution,
    ExtensionDependency,
    ExtensionManifest,
    ExtensionRuntime,
)
from nanobot.extensions.registry import ExtensionCandidate, ExtensionScope

if TYPE_CHECKING:
    from nanobot.agent.skills import SkillsLoader
    from nanobot.agent.tools.registry import ToolRegistry
    from nanobot.command.router import CommandRouter
    from nanobot.config.schema import Config

_NON_ID_CHARACTER = re.compile(r"[^a-z0-9._-]+")


def discover_native_extensions(
    config: Config,
    *,
    skills: SkillsLoader | None = None,
    tools: ToolRegistry | None = None,
    commands: CommandRouter | None = None,
) -> ExtensionDiscoveryResult:
    """Return built-in, workspace, and configured capabilities as extensions."""
    candidates = [
        *_channel_candidates(),
        *_provider_candidates(),
        *_transcription_candidates(),
        *_image_generation_candidates(),
        *_mcp_candidates(config),
    ]
    if skills is not None:
        candidates.extend(_skill_candidates(skills))
    if tools is not None:
        candidates.extend(_tool_candidates(tools))
    if commands is not None:
        candidates.extend(_command_candidates(commands))
    return ExtensionDiscoveryResult(candidates=_merge_candidates(candidates))


def _channel_candidates() -> list[ExtensionCandidate]:
    from nanobot.channels.registry import discover_plugins

    candidates = []
    for name, plugin in sorted(discover_plugins().items()):
        contributions = [
            ExtensionContribution(
                kind=ContributionKind.CHANNEL,
                name=name,
                target=plugin.runtime,
                description=plugin.display_name,
            )
        ]
        if plugin.webui:
            contributions.append(
                ExtensionContribution(
                    kind=ContributionKind.WEBUI,
                    name=f"channel-{name}",
                    target=plugin.webui,
                )
            )
        candidates.append(
            _candidate(
                f"nanobot.channel.{name}",
                plugin.display_name,
                contributions,
                dependencies=_python_dependencies(plugin.dependencies),
            )
        )
    return candidates


def _provider_candidates() -> list[ExtensionCandidate]:
    from nanobot.providers.registry import PROVIDERS

    candidates = []
    for spec in PROVIDERS:
        if spec.settings_alias_for or spec.is_transcription_only:
            continue
        candidates.append(
            _candidate(
                f"nanobot.provider.{spec.name}",
                spec.label,
                (
                    ExtensionContribution(
                        kind=ContributionKind.LLM_PROVIDER,
                        name=spec.name,
                        target=spec.backend,
                    ),
                ),
            )
        )
    return candidates


def _transcription_candidates() -> list[ExtensionCandidate]:
    from nanobot.audio.transcription_registry import TRANSCRIPTION_PROVIDERS

    return [
        _candidate(
            f"nanobot.transcription.{spec.name}",
            f"{spec.name} transcription",
            (
                ExtensionContribution(
                    kind=ContributionKind.TRANSCRIPTION_PROVIDER,
                    name=spec.name,
                    target=spec.adapter,
                ),
            ),
        )
        for spec in TRANSCRIPTION_PROVIDERS
    ]


def _image_generation_candidates() -> list[ExtensionCandidate]:
    from nanobot.providers.image_generation import image_gen_provider_names

    return [
        _candidate(
            f"nanobot.image-generation.{name}",
            f"{name} image generation",
            (
                ExtensionContribution(
                    kind=ContributionKind.IMAGE_GENERATION_PROVIDER,
                    name=name,
                ),
            ),
        )
        for name in image_gen_provider_names()
    ]


def _mcp_candidates(config: Config) -> list[ExtensionCandidate]:
    return [
        _candidate(
            f"nanobot.mcp.{_identifier(name)}",
            name,
            (
                ExtensionContribution(
                    kind=ContributionKind.MCP_SERVER,
                    name=_identifier(name),
                    target=name,
                ),
            ),
            scope=ExtensionScope.USER,
        )
        for name in sorted(config.tools.mcp_servers)
    ]


def _skill_candidates(skills: SkillsLoader) -> list[ExtensionCandidate]:
    candidates = []
    for entry in skills.list_skills(filter_unavailable=False):
        name = entry["name"]
        metadata = skills.get_skill_metadata(name) or {}
        requirements = skills.get_skill_requirements(name)
        dependencies = tuple(
            ExtensionDependency(DependencyKind.EXECUTABLE, value)
            for value in requirements["bins"]
        ) + tuple(
            ExtensionDependency(DependencyKind.ENVIRONMENT, value)
            for value in requirements["env"]
        )
        scope = (
            ExtensionScope.WORKSPACE
            if entry["source"] == "workspace"
            else ExtensionScope.BUILTIN
        )
        candidates.append(
            _candidate(
                f"nanobot.skill.{_identifier(name)}",
                name,
                (
                    ExtensionContribution(
                        kind=ContributionKind.SKILL,
                        name=_identifier(name),
                        target=entry["path"],
                        description=str(metadata.get("description") or name),
                    ),
                ),
                dependencies=dependencies,
                scope=scope,
                location=Path(entry["path"]).parent,
            )
        )
    return candidates


def _tool_candidates(tools: ToolRegistry) -> list[ExtensionCandidate]:
    grouped: dict[str, list[ExtensionContribution]] = defaultdict(list)
    for name in tools.tool_names:
        owner = tools.owner(name) or "nanobot.core"
        tool = tools.get(name)
        grouped[owner].append(
            ExtensionContribution(
                kind=ContributionKind.TOOL,
                name=_identifier(name),
                description=tool.description if tool is not None else "",
            )
        )
    return [
        _candidate(
            owner,
            owner,
            contributions,
            scope=(
                ExtensionScope.USER
                if owner.startswith(("legacy.", "nanobot.mcp."))
                else ExtensionScope.BUILTIN
            ),
        )
        for owner, contributions in sorted(grouped.items())
    ]


def _command_candidates(commands: CommandRouter) -> list[ExtensionCandidate]:
    grouped: dict[str, list[ExtensionContribution]] = defaultdict(list)
    for _tier, command, owner in commands.registrations():
        grouped[owner].append(
            ExtensionContribution(
                kind=ContributionKind.COMMAND,
                name=_identifier(command.lstrip("/").rstrip()),
                target=command,
            )
        )
    return [
        _candidate(owner, owner, contributions)
        for owner, contributions in sorted(grouped.items())
    ]


def _candidate(
    extension_id: str,
    name: str,
    contributions: Iterable[ExtensionContribution],
    *,
    dependencies: tuple[ExtensionDependency, ...] = (),
    scope: ExtensionScope = ExtensionScope.BUILTIN,
    location: Path | None = None,
) -> ExtensionCandidate:
    return ExtensionCandidate(
        manifest=ExtensionManifest(
            id=_identifier(extension_id),
            name=name,
            version=__version__,
            runtime=ExtensionRuntime.PYTHON,
            contributions=tuple(contributions),
            dependencies=dependencies,
        ),
        scope=scope,
        location=location,
        enabled=True,
        trusted=True,
    )


def _python_dependencies(
    requirements: tuple[str, ...],
) -> tuple[ExtensionDependency, ...]:
    dependencies = []
    for raw in requirements:
        requirement = Requirement(raw)
        name = requirement.name
        if requirement.extras:
            name += f"[{','.join(sorted(requirement.extras))}]"
        specifier = str(requirement.specifier)
        if requirement.marker:
            specifier += f"; {requirement.marker}"
        dependencies.append(
            ExtensionDependency(
                kind=DependencyKind.PYTHON,
                name=name,
                specifier=specifier,
            )
        )
    return tuple(dependencies)


def _merge_candidates(
    candidates: Iterable[ExtensionCandidate],
) -> tuple[ExtensionCandidate, ...]:
    merged: dict[tuple[str, ExtensionScope], ExtensionCandidate] = {}
    for candidate in candidates:
        key = (candidate.manifest.id, candidate.scope)
        existing = merged.get(key)
        if existing is None:
            merged[key] = candidate
            continue
        manifest = existing.manifest
        incoming = candidate.manifest
        merged[key] = ExtensionCandidate(
            manifest=ExtensionManifest(
                id=manifest.id,
                name=manifest.name,
                version=manifest.version,
                runtime=manifest.runtime,
                contributions=manifest.contributions + incoming.contributions,
                description=manifest.description or incoming.description,
                dependencies=tuple(
                    dict.fromkeys(manifest.dependencies + incoming.dependencies)
                ),
                permissions=tuple(
                    dict.fromkeys(manifest.permissions + incoming.permissions)
                ),
                homepage=manifest.homepage or incoming.homepage,
                license=manifest.license or incoming.license,
            ),
            scope=existing.scope,
            location=existing.location or candidate.location,
            enabled=existing.enabled and candidate.enabled,
            trusted=existing.trusted and candidate.trusted,
        )
    return tuple(
        sorted(
            merged.values(),
            key=lambda item: (item.scope, item.manifest.id),
        )
    )


def _identifier(value: str) -> str:
    normalized = _NON_ID_CHARACTER.sub("-", value.strip().lower()).strip("._-")
    return normalized or "unnamed"
