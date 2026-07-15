import ast
import subprocess
import sys
from pathlib import Path

import pytest

import nanobot.channels._setup as channel_setup_module
import nanobot.channels.registry as registry_module
from nanobot.channels._setup import channel_setup_spec
from nanobot.channels.plugin import ChannelPlugin, load_builtin_channel_plugin
from nanobot.channels.registry import channel_default_enabled, discover_builtin_plugins

EXPECTED_CHANNELS = {
    "dingtalk",
    "discord",
    "email",
    "feishu",
    "matrix",
    "mattermost",
    "mochat",
    "msteams",
    "napcat",
    "qq",
    "signal",
    "slack",
    "telegram",
    "websocket",
    "wecom",
    "weixin",
    "whatsapp",
}


def test_channel_setup_spec_derives_route_and_secret_metadata() -> None:
    slack = channel_setup_spec("slack")

    assert slack is not None
    assert slack.secrets == {"appToken", "botToken"}
    assert slack.route_field_types == {
        "appToken": "secret",
        "botToken": "secret",
        "groupPolicy": ("enum", {"mention", "open", "allowlist"}),
    }
    assert slack.simple_required_fields == ("appToken", "botToken")
    assert slack.fields["groupPolicy"].default == "mention"
    group_policy = next(
        field
        for field in slack.to_public_dict("slack")["fields"]
        if field["field"] == "groupPolicy"
    )
    assert group_policy["default_value"] == "mention"


def test_matrix_setup_requires_one_complete_login_method() -> None:
    matrix = channel_setup_spec("matrix")

    assert matrix is not None
    base = {
        "homeserver": "https://matrix.example",
        "userId": "@nanobot:matrix.example",
    }
    assert matrix.is_configured(base | {"password": "secret"})
    assert matrix.is_configured(base | {"accessToken": "token", "deviceId": "DEVICE"})
    assert not matrix.is_configured(base | {"accessToken": "token"})


def test_channel_setup_spec_separates_writable_and_snapshot_fields() -> None:
    matrix = channel_setup_spec("matrix")
    discord = channel_setup_spec("discord")

    assert matrix is not None
    assert discord is not None
    assert "allowFrom" not in matrix.route_field_types
    assert "allowFrom" in matrix.snapshot_fields
    assert "allowFrom" in discord.route_field_types
    assert "allowFrom" not in discord.snapshot_fields


def test_webui_forms_have_writable_mattermost_and_whatsapp_contracts() -> None:
    mattermost = channel_setup_spec("mattermost")
    whatsapp = channel_setup_spec("whatsapp")

    assert mattermost is not None
    assert whatsapp is not None
    assert mattermost.route_field_types["serverUrl"] == "string"
    assert mattermost.route_field_types["token"] == "secret"
    assert whatsapp.route_field_types["allowFrom"] == "list"
    assert whatsapp.route_field_types["groupPolicy"] == (
        "enum",
        {"mention", "open"},
    )


def test_every_builtin_channel_is_a_self_contained_package() -> None:
    channel_dir = Path(channel_setup_module.__file__).parent
    package_names = {path.parent.name for path in channel_dir.glob("*/manifest.py")}

    assert not hasattr(channel_setup_module, "CHANNEL_SETUP_SPECS")
    assert package_names == EXPECTED_CHANNELS
    assert set(discover_builtin_plugins()) == EXPECTED_CHANNELS
    for name in EXPECTED_CHANNELS:
        package_dir = channel_dir / name
        assert (package_dir / "__init__.py").is_file()
        assert (package_dir / "manifest.py").is_file()
        assert (package_dir / "runtime.py").is_file()
        assert not (channel_dir / f"{name}.py").exists()

        plugin = load_builtin_channel_plugin(name)
        assert plugin is not None
        assert plugin.name == name
        assert plugin.runtime.startswith(f"nanobot.channels.{name}.runtime:")
        assert plugin.setup is channel_setup_spec(name)
        if plugin.webui is not None:
            assert (package_dir / plugin.webui).is_file()


def test_builtin_setup_manifests_only_import_contract_modules() -> None:
    channel_dir = Path(channel_setup_module.__file__).parent
    allowed_imports = {
        "nanobot.channels._manifest",
        "nanobot.channels.contracts",
        "nanobot.channels.plugin",
    }

    for name in EXPECTED_CHANNELS:
        manifest_path = channel_dir / name / "manifest.py"
        tree = ast.parse(manifest_path.read_text(encoding="utf-8"))
        imports: set[str] = set()
        for node in tree.body:
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
        assert imports <= allowed_imports, f"{name} imports runtime dependencies: {imports}"


def test_builtin_multi_instance_manifests_match_runtime_declarations() -> None:
    channel_dir = Path(channel_setup_module.__file__).parent
    manifest_multi = {
        name
        for name in EXPECTED_CHANNELS
        if (spec := channel_setup_spec(name)) is not None and spec.multi_instance
    }
    runtime_multi: set[str] = set()
    for name in EXPECTED_CHANNELS:
        runtime_path = channel_dir / name / "runtime.py"
        tree = ast.parse(runtime_path.read_text(encoding="utf-8"))
        if any(
            isinstance(node, ast.ClassDef)
            and any(
                isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                and item.name == "instance_specs"
                for item in node.body
            )
            for node in tree.body
        ):
            runtime_multi.add(name)

    assert manifest_multi == runtime_multi


def test_feishu_package_manifest_owns_runtime_and_webui_metadata() -> None:
    plugin = load_builtin_channel_plugin("feishu")

    assert plugin is not None
    assert plugin.runtime == "nanobot.channels.feishu.runtime:FeishuChannel"
    assert plugin.optional_extra == "feishu"
    assert plugin.capabilities == {"multi_instance", "qr_connect"}
    assert plugin.webui == "webui/index.tsx"


def test_weixin_package_manifest_owns_runtime_and_webui_metadata() -> None:
    plugin = load_builtin_channel_plugin("weixin")

    assert plugin is not None
    assert plugin.runtime == "nanobot.channels.weixin.runtime:WeixinChannel"
    assert plugin.optional_extra == "weixin"
    assert plugin.capabilities == {"qr_connect"}
    assert plugin.webui == "webui/index.tsx"


def test_package_manifests_do_not_import_runtimes() -> None:
    code = f"""
import sys
from nanobot.channels.plugin import load_builtin_channel_plugin

for name in {sorted(EXPECTED_CHANNELS)!r}:
    plugin = load_builtin_channel_plugin(name)
    assert plugin is not None
    assert f"nanobot.channels.{{name}}.runtime" not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_channel_plugin_normalizes_webui_entry() -> None:
    plugin = ChannelPlugin(
        name="demo",
        display_name="Demo",
        runtime="example.demo.runtime:DemoChannel",
        webui="webui\\index.tsx",
    )

    assert plugin.webui == "webui/index.tsx"


def test_channel_plugin_rejects_invalid_runtime_import_path() -> None:
    with pytest.raises(ValueError, match="absolute import path"):
        ChannelPlugin(
            name="demo",
            display_name="Demo",
            runtime="../runtime:DemoChannel",
        )


def test_channel_default_enabled_uses_package_manifest(monkeypatch) -> None:
    plugin = ChannelPlugin(
        name="demo",
        display_name="Demo",
        runtime="example.demo.runtime:DemoChannel",
        default_enabled=True,
    )
    monkeypatch.setattr(
        registry_module,
        "load_channel_plugin",
        lambda name: plugin if name == "demo" else (_ for _ in ()).throw(ImportError()),
    )

    assert channel_default_enabled("demo") is True
    assert channel_default_enabled("missing") is False


def test_websocket_manifest_declares_the_only_default_enabled_channel() -> None:
    enabled = {
        name
        for name in EXPECTED_CHANNELS
        if (plugin := load_builtin_channel_plugin(name)) is not None and plugin.default_enabled
    }

    assert enabled == {"websocket"}
