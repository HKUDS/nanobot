from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from nanobot.apps.cli.service import CliAppError, CliAppManager, CliAppsRuntimeConfig


def _write_cache(path: Path, registry: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"_cached_at": time.time(), "data": registry}),
        encoding="utf-8",
    )


def _manager(tmp_path: Path) -> CliAppManager:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return CliAppManager(
        workspace=workspace,
        data_dir=tmp_path / "data",
        runtime=CliAppsRuntimeConfig(catalog_ttl_seconds=3600, install_timeout=5, run_timeout=5),
    )


def _seed_catalog(manager: CliAppManager) -> None:
    harness = {
        "meta": {"updated": "2026-04-16"},
        "clis": [
            {
                "name": "gimp",
                "display_name": "GIMP",
                "version": "1.0.0",
                "description": "Image editing",
                "category": "image",
                "requires": "Python 3.10+",
                "install_cmd": "pip install cli-anything-gimp",
                "entry_point": "cli-anything-gimp",
                "skill_md": "skills/cli-anything-gimp/SKILL.md",
            }
        ],
    }
    public = {
        "meta": {"updated": "2026-04-18"},
        "clis": [
            {
                "name": "gimp",
                "display_name": "GIMP",
                "description": "Public duplicate entry",
            },
            {
                "name": "jimeng",
                "display_name": "Jimeng",
                "version": "latest",
                "description": "Script install",
                "category": "ai",
                "install_strategy": "script",
                "install_cmd": "curl -fsSL https://example.invalid/install.sh | bash",
                "entry_point": "dreamina",
            },
            {
                "name": "feishu",
                "display_name": "Feishu/Lark CLI",
                "version": "latest",
                "description": "Official Lark CLI",
                "category": "communication",
                "package_manager": "npm",
                "npm_package": "@larksuite/cli",
                "install_cmd": "npm install -g @larksuite/cli",
                "entry_point": "lark-cli",
            },
            {
                "name": "dify-workflow",
                "display_name": "Dify Workflow",
                "version": "latest",
                "description": "Run Dify workflows",
                "category": "ai",
                "install_cmd": "pip install cli-anything-dify-workflow",
                "entry_point": "cli-anything-dify-workflow",
            },
            {
                "name": "shopify",
                "display_name": "Shopify CLI",
                "version": "latest",
                "description": "Shopify",
                "category": "web",
                "package_manager": "npm",
                "npm_package": "@shopify/cli",
                "install_cmd": "npm install -g @shopify/cli",
                "entry_point": "shopify",
            },
            {
                "name": "clibrowser",
                "display_name": "clibrowser",
                "version": "latest",
                "description": "Cargo install",
                "category": "web",
                "install_cmd": "cargo install --git https://example.invalid/clibrowser.git",
                "entry_point": "clibrowser",
            },
            {
                "name": "suno",
                "display_name": "Suno CLI",
                "version": "latest",
                "description": "python3 pip install",
                "category": "music",
                "package_manager": "pip",
                "install_strategy": "command",
                "install_cmd": "python3 -m pip install git+https://example.invalid/suno-cli.git",
                "uninstall_cmd": "python3 -m pip uninstall -y suno-cli",
                "entry_point": "suno",
            },
        ],
    }
    _write_cache(manager._cache_path("harness"), harness)
    _write_cache(manager._cache_path("public"), public)
    _write_cache(manager._cache_path("extensions"), {"meta": {}, "clis": []})


def test_payload_merges_catalog_and_marks_unsupported_installs(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    _seed_catalog(manager)

    payload = manager.payload()

    assert payload["catalog_updated_at"] == "2026-04-18"
    apps = {app["name"]: app for app in payload["apps"]}
    assert set(apps) == {
        "clibrowser",
        "dify-workflow",
        "feishu",
        "gimp",
        "jimeng",
        "shopify",
        "suno",
    }
    assert apps["gimp"]["install_supported"] is True
    assert apps["gimp"]["source"] == "harness+public"
    assert apps["gimp"]["description"] == "Public duplicate entry"
    assert apps["feishu"]["description"] == "Lark CLI"
    assert apps["feishu"]["manifest"]["description"] == "Lark CLI"
    assert apps["clibrowser"]["install_supported"] is False
    assert apps["jimeng"]["install_supported"] is False
    assert apps["suno"]["install_supported"] is True
    assert apps["gimp"]["logo_url"]
    gimp_manifest = apps["gimp"]["manifest"]
    assert gimp_manifest["schema"] == "agent-app.v1"
    assert gimp_manifest["id"] == "gimp"
    assert gimp_manifest["source"] == "cli-anything:harness+public"
    assert gimp_manifest["capabilities"][0]["type"] == "cli"
    assert gimp_manifest["capabilities"][0]["entry_point"] == "cli-anything-gimp"
    assert gimp_manifest["install"]["verification"] == ["entry_point_available"]
    assert "entry_point_absent" in gimp_manifest["remove"]["verification"]
    assert gimp_manifest["trust"]["review_status"] == "catalog_entry"
    assert apps["dify-workflow"]["logo_url"] == "https://cdn.simpleicons.org/dify/155EEF"
    assert apps["feishu"]["logo_url"] == (
        "https://www.google.com/s2/favicons?domain=larksuite.com&sz=64"
    )
    assert apps["jimeng"]["logo_url"] == "https://cdn.simpleicons.org/bytedance/3C8CFF"
    assert apps["clibrowser"]["logo_url"] == (
        "https://www.google.com/s2/favicons?domain=github.com/allthingssecurity/clibrowser&sz=64"
    )


def test_payload_uses_anygen_official_domain_for_logo(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    _write_cache(manager._cache_path("harness"), {"meta": {"updated": "2026-04-16"}, "clis": []})
    _write_cache(
        manager._cache_path("public"),
        {
            "meta": {"updated": "2026-04-18"},
            "clis": [
                {
                    "name": "anygen",
                    "display_name": "AnyGen",
                    "description": "Generate docs, slides, websites and more via AnyGen cloud API",
                    "category": "generation",
                    "install_cmd": "pip install cli-anything-anygen",
                    "entry_point": "cli-anything-anygen",
                }
            ],
        },
    )
    _write_cache(manager._cache_path("extensions"), {"meta": {}, "clis": []})

    payload = manager.payload()

    app = payload["apps"][0]
    assert app["name"] == "anygen"
    assert app["logo_url"] == "https://www.google.com/s2/favicons?domain=anygen.io&sz=64"


def test_payload_includes_nanobot_extension_registry(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    _write_cache(manager._cache_path("harness"), {"meta": {"updated": "2026-04-16"}, "clis": []})
    _write_cache(manager._cache_path("public"), {"meta": {"updated": "2026-04-18"}, "clis": []})
    _write_cache(
        manager._cache_path("extensions"),
        {
            "meta": {"updated": "2026-05-29"},
            "clis": [
                {
                    "name": "hyperframes",
                    "display_name": "HyperFrames",
                    "version": "latest",
                    "description": "HTML-to-MP4 motion graphics CLI",
                    "category": "video",
                    "package_manager": "npm",
                    "npm_package": "hyperframes",
                    "install_cmd": "npm install -g hyperframes",
                    "entry_point": "hyperframes",
                    "logo_url": "https://raw.githubusercontent.com/heygen-com/hyperframes/main/assets/logo.png",
                    "brand_color": "#111827",
                    "skill_md": "skills/hyperframes/SKILL.md",
                }
            ],
        },
    )

    payload = manager.payload()

    assert payload["catalog_updated_at"] == "2026-05-29"
    app = payload["apps"][0]
    assert app["name"] == "hyperframes"
    assert app["source"] == "extensions"
    assert app["logo_url"] == "https://raw.githubusercontent.com/heygen-com/hyperframes/main/assets/logo.png"
    assert app["brand_color"] == "#111827"
    assert app["install_supported"] is True
    assert app["manifest"]["source"] == "nanobot-extension"
    assert app["manifest"]["trust"]["registry"] == "nanobot-extension"


def test_optional_extension_registry_failure_does_not_break_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _manager(tmp_path)
    _write_cache(
        manager._cache_path("harness"),
        {
            "meta": {"updated": "2026-04-16"},
            "clis": [
                {
                    "name": "gimp",
                    "display_name": "GIMP",
                    "description": "Image editing",
                    "install_cmd": "pip install cli-anything-gimp",
                    "entry_point": "cli-anything-gimp",
                }
            ],
        },
    )
    _write_cache(manager._cache_path("public"), {"meta": {"updated": "2026-04-18"}, "clis": []})

    def fail_get(*args, **kwargs):
        raise RuntimeError("network unavailable")

    monkeypatch.setattr("nanobot.apps.cli.service.httpx.get", fail_get)

    payload = manager.payload()

    assert payload["catalog_updated_at"] == "2026-04-18"
    assert [app["name"] for app in payload["apps"]] == ["gimp"]


def test_install_dispatches_safe_pip_and_installs_skill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _manager(tmp_path)
    _seed_catalog(manager)
    calls: list[list[str]] = []

    def fake_run(argv: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="ok", stderr="")

    monkeypatch.setattr(manager, "_run_argv", fake_run)
    monkeypatch.setattr(
        manager,
        "_fetch_skill_content",
        lambda app: "---\nname: cli-anything-gimp\ndescription: GIMP\n---\n# GIMP\n",
    )

    payload = manager.install("gimp")

    assert calls == [[sys.executable, "-m", "pip", "install", "cli-anything-gimp"]]
    assert payload["last_action"]["ok"] is True
    assert payload["last_action"]["installed"] is True
    assert "state_recorded" in payload["last_action"]["verification"]
    installed = json.loads(manager.installed_path.read_text(encoding="utf-8"))["apps"]
    assert installed["gimp"]["entry_point"] == "cli-anything-gimp"
    skill = manager.workspace / "skills" / "cli-app-gimp" / "SKILL.md"
    assert skill.is_file()
    assert 'run_cli_app` tool with `name="gimp"' in skill.read_text(encoding="utf-8")


def test_install_records_available_cli_without_reinstalling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _manager(tmp_path)
    _seed_catalog(manager)
    resolved = tmp_path / "bin" / "lark-cli"
    resolved.parent.mkdir()
    resolved.write_text("#!/bin/sh\n", encoding="utf-8")

    def fail_run(argv: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
        raise AssertionError(f"unexpected install command: {argv}")

    monkeypatch.setattr(manager, "_run_argv", fail_run)
    monkeypatch.setattr(
        "nanobot.apps.cli.service.shutil.which",
        lambda command: str(resolved) if command == "lark-cli" else None,
    )

    payload = manager.install("feishu")

    assert payload["last_action"]["ok"] is True
    assert payload["last_action"]["installed"] is True
    assert "entry_point_available" in payload["last_action"]["verification"]
    installed = json.loads(manager.installed_path.read_text(encoding="utf-8"))["apps"]
    assert installed["feishu"]["entry_point_path"] == str(resolved)
    skill = manager.workspace / "skills" / "cli-app-feishu" / "SKILL.md"
    assert skill.is_file()
    assert 'run_cli_app` tool with `name="feishu"' in skill.read_text(encoding="utf-8")


def test_install_recovers_stale_npm_global_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _manager(tmp_path)
    _write_cache(manager._cache_path("harness"), {"meta": {"updated": "2026-04-16"}, "clis": []})
    _write_cache(manager._cache_path("public"), {"meta": {"updated": "2026-04-18"}, "clis": []})
    _write_cache(
        manager._cache_path("extensions"),
        {
            "meta": {"updated": "2026-05-29"},
            "clis": [
                {
                    "name": "hyperframes",
                    "display_name": "HyperFrames",
                    "package_manager": "npm",
                    "npm_package": "hyperframes",
                    "install_cmd": "npm install -g hyperframes",
                    "entry_point": "hyperframes",
                    "skill_md": "skills/hyperframes/SKILL.md",
                }
            ],
        },
    )
    npm = str(tmp_path / "bin" / "npm")
    global_root = tmp_path / "global"
    stale_package = global_root / "hyperframes"
    stale_temp = global_root / ".hyperframes-broken"
    stale_package.mkdir(parents=True)
    stale_temp.mkdir()
    install_attempts = 0

    def fake_run(argv: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
        nonlocal install_attempts
        if argv == [npm, "root", "-g"]:
            return subprocess.CompletedProcess(argv, 0, stdout=str(global_root), stderr="")
        if argv == [npm, "install", "-g", "hyperframes"]:
            install_attempts += 1
            if install_attempts == 1:
                return subprocess.CompletedProcess(
                    argv,
                    1,
                    stdout="",
                    stderr="npm error ENOTEMPTY\nnpm error syscall rename",
                )
            return subprocess.CompletedProcess(argv, 0, stdout="ok", stderr="")
        raise AssertionError(f"unexpected command: {argv}")

    monkeypatch.setattr(manager, "_run_argv", fake_run)
    monkeypatch.setattr(
        "nanobot.apps.cli.service.shutil.which",
        lambda command: npm if command == "npm" else None,
    )

    payload = manager.install("hyperframes")

    assert install_attempts == 2
    assert not stale_package.exists()
    assert not stale_temp.exists()
    assert payload["last_action"]["ok"] is True
    installed = json.loads(manager.installed_path.read_text(encoding="utf-8"))["apps"]
    assert installed["hyperframes"]["strategy"] == "npm"


def test_install_records_entry_point_path_and_pip_distribution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _manager(tmp_path)
    _seed_catalog(manager)
    resolved = tmp_path / "bin" / "cli-anything-gimp"
    resolved.parent.mkdir()
    resolved.write_text("#!/bin/sh\n", encoding="utf-8")

    monkeypatch.setattr(
        manager,
        "_run_argv",
        lambda argv, *, timeout: subprocess.CompletedProcess(argv, 0, stdout="ok", stderr=""),
    )
    monkeypatch.setattr(
        manager,
        "_fetch_skill_content",
        lambda app: "---\nname: cli-anything-gimp\ndescription: GIMP\n---\n# GIMP\n",
    )
    monkeypatch.setattr(
        "nanobot.apps.cli.service.shutil.which",
        lambda command: str(resolved) if command == "cli-anything-gimp" else None,
    )
    monkeypatch.setattr(
        "nanobot.apps.cli.service.importlib_metadata.distributions",
        lambda: [
            SimpleNamespace(
                entry_points=[
                    SimpleNamespace(group="console_scripts", name="cli-anything-gimp"),
                ],
                metadata={"Name": "cli-anything-gimp"},
            )
        ],
    )

    manager.install("gimp")

    installed = json.loads(manager.installed_path.read_text(encoding="utf-8"))["apps"]
    assert installed["gimp"]["entry_point_path"] == str(resolved)
    assert installed["gimp"]["pip_distribution"] == "cli-anything-gimp"


def test_installed_state_writes_atomically_without_temp_leftovers(tmp_path: Path) -> None:
    manager = _manager(tmp_path)

    manager._save_installed({"gimp": {"entry_point": "cli-anything-gimp"}})
    manager._save_installed({"zoom": {"entry_point": "cli-anything-zoom"}})

    installed = json.loads(manager.installed_path.read_text(encoding="utf-8"))["apps"]
    assert set(installed) == {"zoom"}
    assert not list(manager.installed_path.parent.glob(".installed.json.*.tmp"))


def test_fetch_skill_content_rejects_untrusted_urls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _manager(tmp_path)

    def fail_get(*args, **kwargs):
        raise AssertionError("untrusted skill URL should not be fetched")

    monkeypatch.setattr("nanobot.apps.cli.service.httpx.get", fail_get)

    assert manager._fetch_skill_content({
        "name": "evil",
        "skill_md": "https://example.com/SKILL.md",
    }) is None
    assert manager._fetch_skill_content({
        "name": "evil",
        "skill_md": "skills/../evil/SKILL.md",
    }) is None


def test_fetch_skill_content_allows_cli_anything_raw_skill_url(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _manager(tmp_path)
    seen: list[str] = []

    class Response:
        text = "---\nname: cli-app-test\ndescription: Test\n---\n# Test\n"

        @staticmethod
        def raise_for_status() -> None:
            return None

    def fake_get(url: str, **kwargs):
        seen.append(url)
        return Response()

    monkeypatch.setattr("nanobot.apps.cli.service.httpx.get", fake_get)

    content = manager._fetch_skill_content({
        "name": "gimp",
        "skill_md": "https://raw.githubusercontent.com/HKUDS/CLI-Anything/main/skills/cli-anything-gimp/SKILL.md",
    })

    assert content and "# Test" in content
    assert seen == [
        "https://raw.githubusercontent.com/HKUDS/CLI-Anything/main/skills/cli-anything-gimp/SKILL.md"
    ]


def test_fetch_skill_content_uses_extension_raw_base_for_relative_skills(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _manager(tmp_path)
    seen: list[str] = []

    class Response:
        text = "---\nname: hyperframes\ndescription: HyperFrames\n---\n# HyperFrames\n"

        @staticmethod
        def raise_for_status() -> None:
            return None

    def fake_get(url: str, **kwargs):
        seen.append(url)
        return Response()

    monkeypatch.setattr("nanobot.apps.cli.service.httpx.get", fake_get)

    content = manager._fetch_skill_content({
        "name": "hyperframes",
        "skill_md": "skills/hyperframes/SKILL.md",
        "_raw_base": "https://raw.githubusercontent.com/Re-bin/nanobot-extension/main",
    })

    assert content and "# HyperFrames" in content
    assert seen == [
        "https://raw.githubusercontent.com/Re-bin/nanobot-extension/main/skills/hyperframes/SKILL.md"
    ]


def test_uninstall_removes_installed_state_and_generated_skill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _manager(tmp_path)
    _seed_catalog(manager)
    manager._save_installed({"gimp": {"entry_point": "cli-anything-gimp"}})
    skill_dir = manager.workspace / "skills" / "cli-app-gimp"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# GIMP\n", encoding="utf-8")
    monkeypatch.setattr(
        manager,
        "_run_argv",
        lambda argv, *, timeout: subprocess.CompletedProcess(argv, 0, stdout="ok", stderr=""),
    )

    payload = manager.uninstall("gimp")

    assert payload["last_action"]["ok"] is True
    assert "gimp" not in json.loads(manager.installed_path.read_text(encoding="utf-8"))["apps"]
    assert not skill_dir.exists()


def test_uninstall_uses_safe_python_m_pip_uninstall_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _manager(tmp_path)
    _seed_catalog(manager)
    manager._save_installed({"suno": {"entry_point": "suno"}})
    calls: list[list[str]] = []

    def fake_run(argv: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="ok", stderr="")

    monkeypatch.setattr(manager, "_run_argv", fake_run)

    payload = manager.uninstall("suno")

    assert calls == [[sys.executable, "-m", "pip", "uninstall", "-y", "suno-cli"]]
    assert payload["last_action"]["ok"] is True


def test_uninstall_uses_recorded_pip_distribution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _manager(tmp_path)
    _seed_catalog(manager)
    manager._save_installed({
        "gimp": {
            "entry_point": "cli-anything-gimp",
            "pip_distribution": "actual-dist-name",
            "entry_point_path": str(tmp_path / "bin" / "cli-anything-gimp"),
        }
    })
    calls: list[list[str]] = []

    def fake_run(argv: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="ok", stderr="")

    monkeypatch.setattr(manager, "_run_argv", fake_run)

    payload = manager.uninstall("gimp")

    assert calls == [[sys.executable, "-m", "pip", "uninstall", "-y", "actual-dist-name"]]
    assert payload["last_action"]["ok"] is True
    assert payload["last_action"]["removed"] is True
    assert "entry_point_absent" in payload["last_action"]["verification"]
    assert "gimp" not in json.loads(manager.installed_path.read_text(encoding="utf-8"))["apps"]


def test_uninstall_keeps_state_when_entry_point_still_available(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _manager(tmp_path)
    _seed_catalog(manager)
    manager._save_installed({"gimp": {"entry_point": "cli-anything-gimp"}})
    monkeypatch.setattr(
        manager,
        "_run_argv",
        lambda argv, *, timeout: subprocess.CompletedProcess(argv, 0, stdout="ok", stderr=""),
    )
    monkeypatch.setattr(
        "nanobot.apps.cli.service.shutil.which",
        lambda command: "/usr/local/bin/cli-anything-gimp" if command == "cli-anything-gimp" else None,
    )

    payload = manager.uninstall("gimp")

    assert payload["last_action"]["ok"] is False
    assert payload["last_action"]["removed"] is False
    assert payload["last_action"]["still_available"] is True
    assert payload["last_action"]["verification_failed"] == ["entry_point_absent"]
    assert "kept it installed" in payload["last_action"]["message"]
    assert "gimp" in json.loads(manager.installed_path.read_text(encoding="utf-8"))["apps"]


def test_uninstall_keeps_state_when_recorded_entry_point_still_exists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _manager(tmp_path)
    _seed_catalog(manager)
    resolved = tmp_path / "bin" / "cli-anything-gimp"
    resolved.parent.mkdir()
    resolved.write_text("#!/bin/sh\n", encoding="utf-8")
    manager._save_installed({
        "gimp": {
            "entry_point": "cli-anything-gimp",
            "entry_point_path": str(resolved),
        }
    })
    monkeypatch.setattr(
        manager,
        "_run_argv",
        lambda argv, *, timeout: subprocess.CompletedProcess(argv, 0, stdout="ok", stderr=""),
    )

    payload = manager.uninstall("gimp")

    assert payload["last_action"]["ok"] is False
    assert str(resolved) in payload["last_action"]["message"]
    assert "gimp" in json.loads(manager.installed_path.read_text(encoding="utf-8"))["apps"]


def test_mentioned_installed_apps_only_returns_installed_mentions(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    manager._save_installed(
        {
            "gimp": {"entry_point": "cli-anything-gimp", "source": "harness"},
            "zoom": {"entry_point": "cli-anything-zoom", "source": "public"},
        }
    )

    mentions = manager.mentioned_installed_apps("use @zoom and @krita, then @GIMP")

    assert mentions == [
        {
            "name": "zoom",
            "entry_point": "cli-anything-zoom",
            "source": "public",
            "skill": "skills/cli-app-zoom/SKILL.md",
            "tool": "run_cli_app",
        },
        {
            "name": "gimp",
            "entry_point": "cli-anything-gimp",
            "source": "harness",
            "skill": "skills/cli-app-gimp/SKILL.md",
            "tool": "run_cli_app",
        },
    ]


def test_install_rejects_unknown_and_script_strategy(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    _seed_catalog(manager)

    with pytest.raises(CliAppError, match="not found"):
        manager.install("missing")

    with pytest.raises(CliAppError, match="unsupported"):
        manager.install("jimeng")


def test_run_installed_cli_uses_argv_without_shell(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _manager(tmp_path)
    _seed_catalog(manager)
    resolved = str(tmp_path / "bin" / "cli-anything-gimp")
    monkeypatch.setattr(
        "nanobot.apps.cli.service.shutil.which",
        lambda entry: resolved if entry == "cli-anything-gimp" else None,
    )

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert "shell" not in kwargs or kwargs["shell"] is False
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout="ARGS=" + repr(argv[1:]),
            stderr="",
        )

    monkeypatch.setattr("nanobot.apps.cli.service.subprocess.run", fake_run)
    manager._save_installed(
        {
            "gimp": {
                "version": "1.0.0",
                "entry_point": "cli-anything-gimp",
                "source": "harness",
                "strategy": "pip",
            }
        }
    )

    result = manager.run("gimp", ["project", "list"], json_output=True)

    assert "CLI app 'gimp' exited 0" in result
    assert "['--json', 'project', 'list']" in result


def test_run_reports_created_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _manager(tmp_path)
    _seed_catalog(manager)
    resolved = str(tmp_path / "bin" / "cli-anything-gimp")
    monkeypatch.setattr(
        "nanobot.apps.cli.service.shutil.which",
        lambda entry: resolved if entry == "cli-anything-gimp" else None,
    )

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        cwd = Path(str(kwargs["cwd"]))
        (cwd / "diagram.png").write_bytes(b"\x89PNG\r\n\x1a\nimage")
        return subprocess.CompletedProcess(argv, 0, stdout="done", stderr="")

    monkeypatch.setattr("nanobot.apps.cli.service.subprocess.run", fake_run)
    manager._save_installed({"gimp": {"entry_point": "cli-anything-gimp"}})

    result = manager.run("gimp", ["render"])

    assert "Artifacts created or updated:" in result
    assert "diagram.png (previewable image" in result
    assert "![diagram](diagram.png)" in result


def test_run_blocks_working_dir_outside_workspace(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    _seed_catalog(manager)
    manager._save_installed({"gimp": {"entry_point": "cli-anything-gimp"}})

    with pytest.raises(CliAppError, match="outside the configured workspace"):
        manager.run("gimp", working_dir="/etc", restrict_to_workspace=True)
