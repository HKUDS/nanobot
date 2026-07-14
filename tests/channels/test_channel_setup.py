import ast
import pkgutil
import subprocess
import sys
from pathlib import Path

import nanobot.channels._setup as channel_setup_module
import nanobot.channels.manifests as manifest_package
from nanobot.channels._setup import channel_setup_spec
from nanobot.channels.manifests import load_builtin_channel_plugin
from nanobot.channels.plugin import ChannelPlugin
from nanobot.channels.registry import channel_default_enabled

EXPECTED_SETUP_CHANNELS = {
    "dingtalk",
    "discord",
    "email",
    "feishu",
    "matrix",
    "mattermost",
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


def test_all_builtin_setup_contracts_are_dependency_free_manifests() -> None:
    legacy_manifest_names = {
        name
        for _, name, ispkg in pkgutil.iter_modules(
            [str(Path(manifest_package.__file__).parent)]
        )
        if not name.startswith("_") and not ispkg
    }
    channel_dir = Path(channel_setup_module.__file__).parent
    package_manifest_names = {
        path.parent.name
        for path in channel_dir.glob("*/manifest.py")
    }
    manifest_names = legacy_manifest_names | package_manifest_names

    assert not hasattr(channel_setup_module, "CHANNEL_SETUP_SPECS")
    assert manifest_names == EXPECTED_SETUP_CHANNELS
    assert all(channel_setup_spec(name) is not None for name in manifest_names)

    feishu = channel_setup_spec("feishu")
    assert feishu is not None and feishu.multi_instance is True
    assert feishu.simple_required_fields == ("appId", "appSecret")


def test_builtin_setup_manifests_only_import_contract_modules() -> None:
    manifest_dir = Path(manifest_package.__file__).parent
    channel_dir = Path(channel_setup_module.__file__).parent
    allowed_imports = {
        "nanobot.channels.contracts",
        "nanobot.channels.manifests._shared",
        "nanobot.channels.plugin",
    }

    for name in EXPECTED_SETUP_CHANNELS:
        package_manifest = channel_dir / name / "manifest.py"
        manifest_path = package_manifest if package_manifest.is_file() else manifest_dir / f"{name}.py"
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
        for name in EXPECTED_SETUP_CHANNELS
        if (spec := channel_setup_spec(name)) is not None and spec.multi_instance
    }
    runtime_multi: set[str] = set()
    for name in EXPECTED_SETUP_CHANNELS:
        package_runtime = channel_dir / name / "runtime.py"
        runtime_path = package_runtime if package_runtime.is_file() else channel_dir / f"{name}.py"
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
    package_dir = Path(channel_setup_module.__file__).parent / "feishu"

    assert plugin is not None
    assert plugin.runtime == "nanobot.channels.feishu.runtime:FeishuChannel"
    assert plugin.setup is channel_setup_spec("feishu")
    assert plugin.optional_extra == "feishu"
    assert plugin.capabilities == {"multi_instance", "qr_connect"}
    assert plugin.webui == "webui/index.tsx"
    assert (package_dir / plugin.webui).is_file()


def test_weixin_package_manifest_owns_runtime_and_webui_metadata() -> None:
    plugin = load_builtin_channel_plugin("weixin")
    package_dir = Path(channel_setup_module.__file__).parent / "weixin"

    assert plugin is not None
    assert plugin.runtime == "nanobot.channels.weixin.runtime:WeixinChannel"
    assert plugin.setup is channel_setup_spec("weixin")
    assert plugin.optional_extra == "weixin"
    assert plugin.capabilities == {"qr_connect"}
    assert plugin.webui == "webui/index.tsx"
    assert (package_dir / plugin.webui).is_file()


def test_package_manifests_do_not_import_runtimes() -> None:
    code = """
import sys
from nanobot.channels.manifests import load_builtin_channel_plugin

for name in ("feishu", "weixin"):
    plugin = load_builtin_channel_plugin(name)
    assert plugin is not None
assert "nanobot.channels.feishu.runtime" not in sys.modules
assert "nanobot.channels.weixin.runtime" not in sys.modules
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
        runtime="demo.runtime:DemoChannel",
        webui="webui\\index.tsx",
    )

    assert plugin.webui == "webui/index.tsx"


def test_channel_default_enabled_uses_package_manifest(monkeypatch) -> None:
    plugin = ChannelPlugin(
        name="demo",
        display_name="Demo",
        runtime="demo.runtime:DemoChannel",
        default_enabled=True,
    )
    monkeypatch.setattr(
        manifest_package,
        "load_builtin_channel_plugin",
        lambda name: plugin if name == "demo" else None,
    )

    assert channel_default_enabled("demo") is True
    assert channel_default_enabled("websocket") is True
    assert channel_default_enabled("missing") is False
