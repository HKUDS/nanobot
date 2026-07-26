import json
from pathlib import Path

from nanobot.extensions import (
    ContributionKind,
    DependencyKind,
    ExtensionRuntime,
    adapt_package,
)


def test_adapts_pi_package_metadata(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        json.dumps(
            {
                "name": "@acme/pi-tools",
                "version": "1.2.3",
                "description": "Pi tools",
                "pi": {"extensions": ["./index.ts", "./review.ts"]},
            }
        )
    )

    result = adapt_package(tmp_path)

    assert result.generated
    assert result.manifest.id == "pi.acme.pi-tools"
    assert result.manifest.runtime is ExtensionRuntime.PI
    assert result.manifest.activation_entries == ("./index.ts", "./review.ts")


def test_adapts_openclaw_contracts_without_loading_code(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        json.dumps(
            {
                "name": "@openclaw/search-plugin",
                "version": "2.0.0",
                "peerDependencies": {"openclaw": ">=2.0.0"},
                "openclaw": {
                    "extensions": ["./index.ts"],
                    "runtimeExtensions": ["./dist/index.js"],
                },
            }
        )
    )
    (tmp_path / "openclaw.plugin.json").write_text(
        json.dumps(
            {
                "id": "search",
                "name": "Search",
                "contracts": {
                    "tools": ["search_tool"],
                    "webSearchProviders": ["private-search"],
                    "speechProviders": ["speech"],
                },
            }
        )
    )

    result = adapt_package(tmp_path)

    assert result.manifest.id == "openclaw.search"
    assert result.manifest.activation_entries == ("./dist/index.js",)
    assert result.manifest.dependencies[0].kind is DependencyKind.NPM
    assert result.manifest.dependencies[0].specifier == ">=2.0.0"
    assert {
        (item.kind, item.name) for item in result.manifest.contributions
    } == {
        (ContributionKind.TOOL, "search_tool"),
        (ContributionKind.WEB_SEARCH_PROVIDER, "private-search"),
    }
    assert "speechProviders" in result.diagnostics[0]
