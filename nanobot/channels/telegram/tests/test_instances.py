from __future__ import annotations

import pytest

from nanobot.channels.contracts import (
    channel_feature_instances,
    channel_instance_specs,
    channel_runtime_name,
)
from nanobot.channels.registry import load_channel_plugin
from nanobot.channels.telegram.config import telegram_default_config
from nanobot.channels.telegram.instances import (
    PROXY_CLEAR_VALUE,
    canonical_telegram_section,
    telegram_instance_specs,
    update_managed_telegram_instance,
    upsert_telegram_instance,
)


def test_legacy_flat_config_becomes_the_default_instance() -> None:
    token = "123456:abcdefghijklmnopqrstuvwxyz"
    plugin = load_channel_plugin("telegram")
    legacy = {
        "enabled": True,
        "token": token,
        "allowFrom": ["approved-user"],
    }

    specs = channel_instance_specs(plugin, legacy, enabled_only=False)

    assert plugin.management.multi_instance is True
    assert len(specs) == 1
    assert specs[0].instance_id == "default"
    assert specs[0].config["token"] == token
    assert specs[0].config["allowFrom"] == ["approved-user"]
    assert channel_runtime_name(plugin, specs[0].instance_id) == "telegram"


def test_feature_instances_list_each_bot_without_exposing_tokens() -> None:
    first_token = "123456:abcdefghijklmnopqrstuvwxyz"
    second_token = "654321:zyxwvutsrqponmlkjihgfedcba"
    proxy = "http://proxy-user:proxy-pass@127.0.0.1:7890"
    plugin = load_channel_plugin("telegram")
    section = {
        "instances": [
            {
                "id": "default",
                "name": "Support bot",
                "enabled": True,
                "token": first_token,
                "proxy": proxy,
            },
            {
                "id": "product",
                "name": "Product bot",
                "enabled": False,
                "token": second_token,
                "groupPolicy": "open",
            },
        ]
    }

    instances = channel_feature_instances(plugin, section, setup_spec=plugin.setup)

    assert instances is not None
    assert [(instance["id"], instance["name"]) for instance in instances] == [
        ("default", "Support bot"),
        ("product", "Product bot"),
    ]
    assert [instance["configured"] for instance in instances] == [True, True]
    assert instances[0]["enabled"] is True
    assert instances[1]["enabled"] is False
    assert instances[1]["config_values"]["channels.telegram.groupPolicy"] == "open"
    assert "channels.telegram.token" in instances[0]["configured_fields"]
    assert "channels.telegram.proxy" in instances[0]["configured_fields"]
    assert first_token not in str(instances)
    assert second_token not in str(instances)
    assert proxy not in str(instances)
    assert channel_runtime_name(plugin, "product") == "telegram.product"


def test_upsert_migrates_legacy_config_and_adds_a_named_bot() -> None:
    defaults = telegram_default_config()
    legacy_token = "123456:abcdefghijklmnopqrstuvwxyz"
    product_token = "654321:zyxwvutsrqponmlkjihgfedcba"
    legacy = {
        "enabled": True,
        "token": legacy_token,
        "allowFrom": ["approved-user"],
    }

    updated = upsert_telegram_instance(
        legacy,
        defaults,
        "product",
        {
            "name": "Product bot",
            "token": product_token,
            "enabled": True,
        },
    )

    assert set(updated) == {"instances"}
    assert [instance["id"] for instance in updated["instances"]] == ["default", "product"]
    assert updated["instances"][0]["token"] == legacy_token
    assert updated["instances"][0]["allowFrom"] == ["approved-user"]
    assert updated["instances"][1]["token"] == product_token
    assert updated["instances"][1]["instanceId"] == "product"


def test_managed_update_can_remove_a_saved_proxy_without_persisting_sentinel() -> None:
    section = {
        "instances": [
            {
                "id": "default",
                "enabled": True,
                "token": "123456:abcdefghijklmnopqrstuvwxyz",
                "proxy": "http://127.0.0.1:7890",
            }
        ]
    }

    updated = update_managed_telegram_instance(
        section,
        {"proxy": PROXY_CLEAR_VALUE},
        instance_id="default",
    )

    assert updated["instances"][0]["proxy"] is None
    assert PROXY_CLEAR_VALUE not in str(updated)


def test_upsert_rejects_one_token_shared_by_multiple_bots() -> None:
    token = "123456:abcdefghijklmnopqrstuvwxyz"
    section = {
        "instances": [{"id": "default", "enabled": True, "token": token}],
    }

    with pytest.raises(ValueError, match="already used") as exc_info:
        upsert_telegram_instance(
            section,
            telegram_default_config(),
            "product",
            {"enabled": True, "token": token},
        )

    assert token not in str(exc_info.value)


def test_runtime_expansion_skips_a_duplicate_enabled_bot_token() -> None:
    token = "123456:abcdefghijklmnopqrstuvwxyz"
    section = {
        "instances": [
            {"id": "default", "enabled": True, "token": token},
            {"id": "duplicate", "enabled": True, "token": token},
        ],
    }

    specs = telegram_instance_specs(
        section,
        telegram_default_config(),
        enabled_only=True,
    )

    assert [spec.instance_id for spec in specs] == ["default"]


def test_runtime_expansion_skips_a_duplicate_enabled_webhook_listener() -> None:
    section = {
        "instances": [
            {
                "id": "default",
                "enabled": True,
                "token": "123456:abcdefghijklmnopqrstuvwxyz",
                "mode": "webhook",
                "webhookListenHost": "127.0.0.1",
                "webhookListenPort": 8081,
            },
            {
                "id": "product",
                "enabled": True,
                "token": "654321:zyxwvutsrqponmlkjihgfedcba",
                "mode": "webhook",
                "webhookListenHost": "127.0.0.1",
                "webhookListenPort": 8081,
            },
        ],
    }

    specs = telegram_instance_specs(
        section,
        telegram_default_config(),
        enabled_only=True,
    )

    assert [spec.instance_id for spec in specs] == ["default"]


def test_runtime_expansion_treats_wildcard_webhook_host_as_a_conflict() -> None:
    section = {
        "instances": [
            {
                "id": "default",
                "enabled": True,
                "token": "123456:abcdefghijklmnopqrstuvwxyz",
                "mode": "webhook",
                "webhookListenHost": "0.0.0.0",
                "webhookListenPort": 8081,
            },
            {
                "id": "product",
                "enabled": True,
                "token": "654321:zyxwvutsrqponmlkjihgfedcba",
                "mode": "webhook",
                "webhookListenHost": "127.0.0.1",
                "webhookListenPort": 8081,
            },
        ],
    }

    specs = telegram_instance_specs(
        section,
        telegram_default_config(),
        enabled_only=True,
    )

    assert [spec.instance_id for spec in specs] == ["default"]


def test_upsert_rejects_an_enabled_webhook_listener_shared_by_multiple_bots() -> None:
    first_token = "123456:abcdefghijklmnopqrstuvwxyz"
    second_token = "654321:zyxwvutsrqponmlkjihgfedcba"
    section = {
        "instances": [
            {
                "id": "default",
                "enabled": True,
                "token": first_token,
                "mode": "webhook",
                "webhookListenPort": 8081,
            }
        ],
    }

    with pytest.raises(ValueError, match="webhook listener 127.0.0.1:8081") as exc_info:
        upsert_telegram_instance(
            section,
            telegram_default_config(),
            "product",
            {
                "enabled": True,
                "token": second_token,
                "mode": "webhook",
                "webhookListenPort": 8081,
            },
        )

    assert first_token not in str(exc_info.value)
    assert second_token not in str(exc_info.value)


def test_upsert_rejects_loopback_aliases_on_the_same_webhook_port() -> None:
    section = {
        "instances": [
            {
                "id": "default",
                "enabled": True,
                "token": "123456:abcdefghijklmnopqrstuvwxyz",
                "mode": "webhook",
                "webhookListenHost": "localhost",
                "webhookListenPort": 8081,
            }
        ],
    }

    with pytest.raises(ValueError, match="webhook listener 127.0.0.1:8081"):
        upsert_telegram_instance(
            section,
            telegram_default_config(),
            "product",
            {
                "enabled": True,
                "token": "654321:zyxwvutsrqponmlkjihgfedcba",
                "mode": "webhook",
                "webhookListenHost": "127.0.0.1",
                "webhookListenPort": 8081,
            },
        )


def test_upsert_allows_enabled_webhook_bots_on_different_ports() -> None:
    section = {
        "instances": [
            {
                "id": "default",
                "enabled": True,
                "token": "123456:abcdefghijklmnopqrstuvwxyz",
                "mode": "webhook",
                "webhookListenPort": 8081,
            }
        ],
    }

    updated = upsert_telegram_instance(
        section,
        telegram_default_config(),
        "product",
        {
            "enabled": True,
            "token": "654321:zyxwvutsrqponmlkjihgfedcba",
            "mode": "webhook",
            "webhookListenPort": 8082,
        },
    )

    assert [instance["webhookListenPort"] for instance in updated["instances"]] == [8081, 8082]


def test_canonical_config_rejects_duplicate_instance_ids() -> None:
    section = {
        "instances": [
            {"id": "support", "token": "123456:abcdefghijklmnopqrstuvwxyz"},
            {"id": "support", "token": "654321:zyxwvutsrqponmlkjihgfedcba"},
        ],
    }

    with pytest.raises(ValueError, match="duplicate Telegram instance id 'support'"):
        canonical_telegram_section(section, telegram_default_config())
