import json

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
                "entry": "extension:register",
            }
        )
    )


def test_discovery_reads_metadata_without_importing_runtime(tmp_path) -> None:
    _write_manifest(tmp_path, "one", "one")
    _write_manifest(tmp_path, "two", "two")

    result = discover_manifest_root(tmp_path)

    assert [candidate.manifest.id for candidate in result.candidates] == ["one", "two"]
    assert result.diagnostics == ()


def test_discovery_reports_bad_manifest_without_hiding_good_packages(tmp_path) -> None:
    _write_manifest(tmp_path, "good", "good")
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "nanobot.extension.json").write_text("{")

    result = discover_manifest_root(tmp_path)

    assert [candidate.manifest.id for candidate in result.candidates] == ["good"]
    assert result.diagnostics[0].code == "invalid_manifest"
