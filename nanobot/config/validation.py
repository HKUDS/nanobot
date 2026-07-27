"""Side-effect-free validation beyond the root configuration schema."""

from __future__ import annotations

from pydantic import ValidationError

from nanobot.channels.contracts import (
    channel_default_config,
    channel_instance_specs,
)
from nanobot.channels.registry import discover_plugins
from nanobot.config.errors import ConfigIssue, validation_issues
from nanobot.config.schema import Config


def channel_config_issues(config: Config) -> tuple[ConfigIssue, ...]:
    """Validate configured channel sections without constructing channel runtimes."""
    issues: list[ConfigIssue] = []
    for name, plugin in discover_plugins().items():
        section = getattr(config.channels, name, None)
        if section is None:
            if not plugin.default_enabled:
                continue
            section = channel_default_config(plugin)

        try:
            specs = channel_instance_specs(plugin, section, enabled_only=False)
        except ValidationError as exc:
            issues.extend(validation_issues(exc, prefix=("channels", name)))
            continue
        except (TypeError, ValueError):
            issues.append(
                ConfigIssue(
                    path=("channels", name),
                    message="Unable to inspect this channel configuration.",
                    code="channel_config",
                )
            )
            continue
        if not specs:
            continue

        try:
            config_model = plugin.load_config_model()
        except ImportError:
            # Optional channel dependencies are installed by the normal gateway path.
            # A missing runtime package is not a configuration-file error.
            continue
        if config_model is None:
            continue

        for spec in specs:
            prefix: tuple[str, ...] = ("channels", name)
            if spec.instance_id != "default":
                prefix = (*prefix, "instances", spec.instance_id)
            try:
                config_model.model_validate(spec.config)
            except ValidationError as exc:
                issues.extend(validation_issues(exc, prefix=prefix))
    return tuple(issues)
