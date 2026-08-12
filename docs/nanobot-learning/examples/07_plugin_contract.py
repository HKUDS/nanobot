"""Inspect dependency-free channel plugin descriptors."""

from nanobot.channels.registry import discover_plugins


def main() -> None:
    plugins = discover_plugins()
    names = sorted(plugins)
    print(f"plugin_count={len(names)}")
    print("websocket_discovered={}".format("websocket" in names))
    print("first_plugins=" + ",".join(names[:5]))


if __name__ == "__main__":
    main()
