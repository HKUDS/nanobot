from nanobot.extensions import ExtensionDependency, ExtensionManifest
from nanobot.extensions.manifest import DependencyKind
from nanobot.extensions.preflight import evaluate_dependencies
from nanobot.extensions.registry import ExtensionCandidate


def _candidate(dependency: ExtensionDependency) -> ExtensionCandidate:
    return ExtensionCandidate(
        ExtensionManifest(
            id="preflight.test",
            name="Preflight test",
            version="1.0.0",
            dependencies=(dependency,),
        ),
        trusted=True,
    )


def test_missing_environment_dependency_disables_extension(monkeypatch) -> None:
    monkeypatch.delenv("NANOBOT_EXTENSION_TEST_KEY", raising=False)

    candidates, diagnostics = evaluate_dependencies(
        (
            _candidate(
                ExtensionDependency(
                    kind=DependencyKind.ENVIRONMENT,
                    name="NANOBOT_EXTENSION_TEST_KEY",
                )
            ),
        )
    )

    assert not candidates[0].enabled
    assert diagnostics[0].code == "dependency_missing"


def test_optional_dependency_does_not_disable_extension(monkeypatch) -> None:
    monkeypatch.delenv("NANOBOT_EXTENSION_TEST_KEY", raising=False)

    candidates, diagnostics = evaluate_dependencies(
        (
            _candidate(
                ExtensionDependency(
                    kind=DependencyKind.ENVIRONMENT,
                    name="NANOBOT_EXTENSION_TEST_KEY",
                    optional=True,
                )
            ),
        )
    )

    assert candidates[0].enabled
    assert diagnostics == ()
