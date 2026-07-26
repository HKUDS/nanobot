import json

from nanobot.extensions import ExtensionScope
from nanobot.extensions.discovery import discover_manifest_root


def _write_manifest(root, name: str, extension_id: str) -> None:
    package = root / name
    package.mkdir()
    (package / "nanobot.extension.json").write_text(
        json.dumps(
            {
                "id": extension_id,
                "name": extension_id,
                "version": "1.0.0",
                "runtime": "declarative",
            }
        )
    )


def test_discovery_reads_metadata_without_importing_runtime(tmp_path) -> None:
    _write_manifest(tmp_path, "one", "one")
    _write_manifest(tmp_path, "two", "two")

    result = discover_manifest_root(
        tmp_path,
        scope=ExtensionScope.WORKSPACE,
        trusted=True,
    )

    assert [candidate.manifest.id for candidate in result.candidates] == ["one", "two"]
    assert all(candidate.trusted for candidate in result.candidates)
    assert result.diagnostics == ()


def test_discovery_reports_bad_manifest_without_hiding_good_packages(tmp_path) -> None:
    _write_manifest(tmp_path, "good", "good")
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "nanobot.extension.json").write_text("{")

    result = discover_manifest_root(tmp_path, scope=ExtensionScope.USER)

    assert [candidate.manifest.id for candidate in result.candidates] == ["good"]
    assert result.diagnostics[0].code == "invalid_manifest"


def test_discovery_can_leave_unselected_packages_disabled(tmp_path) -> None:
    _write_manifest(tmp_path, "one", "one")
    _write_manifest(tmp_path, "two", "two")

    result = discover_manifest_root(
        tmp_path,
        scope=ExtensionScope.USER,
        enabled_ids=frozenset({"two"}),
    )

    assert [(item.manifest.id, item.enabled) for item in result.candidates] == [
        ("one", False),
        ("two", True),
    ]
