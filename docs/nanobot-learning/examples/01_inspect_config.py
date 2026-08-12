"""Inspect the resolved local nanobot configuration without printing secrets."""

from pathlib import Path

from nanobot.config.loader import load_config, resolve_config_env_vars


def main() -> None:
    path = Path.home() / ".nanobot" / "config.json"
    config = resolve_config_env_vars(load_config(path), config_path=path)
    preset = config.resolve_preset()
    print(f"model={preset.model}")
    print(f"provider={preset.provider}")
    print(f"workspace={config.workspace_path}")
    print(f"api_base_configured={bool(config.get_api_base())}")


if __name__ == "__main__":
    main()
