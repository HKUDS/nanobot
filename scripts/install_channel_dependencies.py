"""Install channel manifest dependencies for repository build and CI jobs."""

from __future__ import annotations

import sys
from collections.abc import Sequence

from nanobot.channels.plugin import ChannelPlugin
from nanobot.channels.registry import discover_plugins
from nanobot.optional_features import (
    ensure_enabled_channel_dependencies,
    extra_installed,
    install_args_for_extra,
    install_extra,
)

_DEPENDENCY_FAILURE = "Channel dependencies could not be installed. Check gateway logs."


def ensure_repository_channel_dependencies(
    names: set[str],
    plugins: dict[str, ChannelPlugin],
) -> dict[str, str]:
    """Batch repository dependency installs, then verify every channel independently."""
    requirements_by_name: dict[str, list[str]] = {}
    pending: dict[str, list[str]] = {}
    install_args: list[str] = []
    seen_args: set[str] = set()

    for name in sorted(names):
        plugin = plugins.get(name)
        if plugin is None:
            continue
        dependencies = list(plugin.dependencies)
        if not dependencies:
            continue
        requirements_by_name[name] = dependencies
        if extra_installed(name, dependencies):
            continue
        pending[name] = dependencies
        channel_args, _label = install_args_for_extra(name, dependencies)
        for requirement in channel_args:
            if requirement not in seen_args:
                seen_args.add(requirement)
                install_args.append(requirement)

    if not pending:
        return {}

    if install_args:
        result = install_extra("channel-dependencies", install_args)
        if result.ok:
            unresolved = {
                name
                for name, dependencies in requirements_by_name.items()
                if not extra_installed(name, dependencies)
            }
        else:
            unresolved = set(requirements_by_name)
    else:
        unresolved = set(requirements_by_name)

    if not unresolved:
        return {}

    failures = ensure_enabled_channel_dependencies(unresolved, plugins)
    for name, dependencies in requirements_by_name.items():
        if name not in failures and not extra_installed(name, dependencies):
            failures[name] = _DEPENDENCY_FAILURE
    return failures


def main(argv: Sequence[str] | None = None) -> int:
    """Install selected channel dependencies without changing channel configuration."""
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("Pass channel names or --all-channels.", file=sys.stderr)
        return 2
    if "--all-channels" in args and args != ["--all-channels"]:
        print("Pass channel names or --all-channels, not both.", file=sys.stderr)
        return 2

    plugins = discover_plugins()
    names = set(plugins) if args == ["--all-channels"] else set(args)
    unknown = sorted(names - set(plugins))
    if unknown:
        print(f"Unknown channels: {', '.join(unknown)}", file=sys.stderr)
        return 2

    failures = ensure_repository_channel_dependencies(names, plugins)
    for name, message in sorted(failures.items()):
        print(f"{name}: {message}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
