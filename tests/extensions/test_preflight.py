from pathlib import Path

from nanobot.extensions import (
    DependencyKind,
    ExtensionCandidate,
    ExtensionDependency,
    ExtensionManifest,
    ExtensionRuntime,
    ExtensionScope,
)
from nanobot.extensions.preflight import evaluate_dependencies


def _candidate(
    dependency: ExtensionDependency,
    *,
    location: Path | None = None,
) -> ExtensionCandidate:
    return ExtensionCandidate(
        manifest=ExtensionManifest(
            id="preflight.test",
            name="Preflight test",
            version="1.0.0",
            runtime=ExtensionRuntime.DECLARATIVE,
            dependencies=(dependency,),
        ),
        scope=ExtensionScope.USER,
        location=location,
        trusted=True,
    )


def test_missing_environment_dependency_disables_extension(
    monkeypatch,
) -> None:
    monkeypatch.delenv("NANOBOT_EXTENSION_TEST_KEY", raising=False)
    candidate = _candidate(
        ExtensionDependency(
            kind=DependencyKind.ENVIRONMENT,
            name="NANOBOT_EXTENSION_TEST_KEY",
        )
    )

    candidates, diagnostics = evaluate_dependencies((candidate,))

    assert not candidates[0].enabled
    assert diagnostics[0].code == "dependency_missing"
    assert "NANOBOT_EXTENSION_TEST_KEY" in diagnostics[0].message


def test_installed_npm_dependency_satisfies_preflight(tmp_path: Path) -> None:
    package = tmp_path / "node_modules" / "openclaw"
    package.mkdir(parents=True)
    (package / "package.json").write_text('{"version":"2026.7.1"}')
    candidate = _candidate(
        ExtensionDependency(
            kind=DependencyKind.NPM,
            name="openclaw",
            specifier=">=2026.7.0",
        ),
        location=tmp_path,
    )

    candidates, diagnostics = evaluate_dependencies((candidate,))

    assert candidates[0].enabled
    assert diagnostics == ()


def test_npm_dist_tag_is_left_to_npm_resolution(tmp_path: Path) -> None:
    package = tmp_path / "node_modules" / "openclaw"
    package.mkdir(parents=True)
    (package / "package.json").write_text('{"version":"2026.7.1"}')
    candidate = _candidate(
        ExtensionDependency(
            kind=DependencyKind.NPM,
            name="openclaw",
            specifier="latest",
        ),
        location=tmp_path,
    )

    candidates, diagnostics = evaluate_dependencies((candidate,))

    assert candidates[0].enabled
    assert diagnostics == ()
