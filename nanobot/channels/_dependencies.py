"""Internal build entry point for preparing channel manifest dependencies."""

from __future__ import annotations

import sys
from collections.abc import Sequence

from nanobot.channels.registry import discover_plugins
from nanobot.optional_features import ensure_enabled_channel_dependencies


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

    failures = ensure_enabled_channel_dependencies(names, plugins)
    for name, message in sorted(failures.items()):
        print(f"{name}: {message}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
