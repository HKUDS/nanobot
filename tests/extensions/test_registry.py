from nanobot.extensions import (
    ContributionKind,
    DependencyKind,
    ExtensionCandidate,
    ExtensionContribution,
    ExtensionDependency,
    ExtensionManifest,
    ExtensionPermission,
    ExtensionPolicy,
    ExtensionRegistry,
    ExtensionRuntime,
    ExtensionScope,
)


def _candidate(
    extension_id: str,
    *,
    scope: ExtensionScope,
    contribution_name: str = "",
    trusted: bool = True,
    dependencies: tuple[ExtensionDependency, ...] = (),
) -> ExtensionCandidate:
    contributions = (
        ExtensionContribution(
            kind=ContributionKind.TOOL,
            name=contribution_name,
        ),
    ) if contribution_name else ()
    return ExtensionCandidate(
        manifest=ExtensionManifest(
            id=extension_id,
            name=extension_id,
            version="1.0.0",
            runtime=ExtensionRuntime.PYTHON,
            contributions=contributions,
            dependencies=dependencies,
        ),
        scope=scope,
        trusted=trusted,
    )


def test_workspace_copy_shadows_user_and_builtin_copy_of_same_extension() -> None:
    registry = ExtensionRegistry()
    registry.register(_candidate("acme", scope=ExtensionScope.BUILTIN))
    registry.register(_candidate("acme", scope=ExtensionScope.USER))
    registry.register(_candidate("acme", scope=ExtensionScope.WORKSPACE))

    snapshot = registry.snapshot()

    assert len(snapshot.extensions) == 1
    assert snapshot.extensions[0].scope is ExtensionScope.WORKSPACE


def test_policy_filters_extensions_before_contribution_resolution() -> None:
    registry = ExtensionRegistry(
        ExtensionPolicy(allow=frozenset({"allowed"}), deny=frozenset())
    )
    registry.register(
        _candidate(
            "allowed",
            scope=ExtensionScope.USER,
            contribution_name="allowed_tool",
        )
    )
    registry.register(
        _candidate(
            "hidden",
            scope=ExtensionScope.USER,
            contribution_name="hidden_tool",
        )
    )

    snapshot = registry.snapshot()

    assert [extension.manifest.id for extension in snapshot.extensions] == ["allowed"]
    assert [
        contribution.contribution.name for contribution in snapshot.contributions
    ] == ["allowed_tool"]


def test_untrusted_external_extension_is_visible_to_discovery_but_not_active() -> None:
    registry = ExtensionRegistry()
    registry.register(
        _candidate(
            "untrusted",
            scope=ExtensionScope.USER,
            contribution_name="unsafe_tool",
            trusted=False,
        )
    )

    snapshot = registry.snapshot()

    assert snapshot.extensions == ()
    assert snapshot.contributions == ()


def test_invalid_package_integrity_cannot_be_overridden_by_trust() -> None:
    registry = ExtensionRegistry()
    candidate = _candidate(
        "tampered",
        scope=ExtensionScope.USER,
        contribution_name="unsafe_tool",
    )
    registry.register(
        ExtensionCandidate(
            manifest=candidate.manifest,
            scope=candidate.scope,
            trusted=True,
            integrity_valid=False,
        )
    )

    snapshot = registry.snapshot()

    assert snapshot.extensions == ()
    assert snapshot.contributions == ()


def test_external_extension_requires_every_requested_permission() -> None:
    candidate = ExtensionCandidate(
        manifest=ExtensionManifest(
            id="permission.test",
            name="Permission test",
            version="1.0.0",
            runtime=ExtensionRuntime.DECLARATIVE,
            permissions=(
                ExtensionPermission(name="network", reason="Fetch data."),
                ExtensionPermission(
                    name="filesystem.read",
                    reason="Read input.",
                ),
            ),
        ),
        scope=ExtensionScope.USER,
        trusted=True,
        granted_permissions=frozenset({"network"}),
    )
    registry = ExtensionRegistry()
    registry.register(candidate)

    snapshot = registry.snapshot()

    assert snapshot.extensions == ()
    assert snapshot.diagnostics[0].code == "permission_required"
    assert "filesystem.read" in snapshot.diagnostics[0].message


def test_conflicting_contribution_does_not_silently_replace_owner() -> None:
    registry = ExtensionRegistry()
    registry.register(
        _candidate(
            "core",
            scope=ExtensionScope.BUILTIN,
            contribution_name="shell",
        )
    )
    registry.register(
        _candidate(
            "third-party",
            scope=ExtensionScope.WORKSPACE,
            contribution_name="shell",
        )
    )

    snapshot = registry.snapshot()

    assert snapshot.contributions[0].owner.manifest.id == "core"
    assert snapshot.diagnostics[0].code == "contribution_conflict"


def test_higher_scope_extension_cannot_replace_another_owner() -> None:
    registry = ExtensionRegistry()
    registry.register(
        _candidate(
            "core",
            scope=ExtensionScope.BUILTIN,
            contribution_name="shell",
        )
    )
    registry.register(
        _candidate(
            "replacement",
            scope=ExtensionScope.WORKSPACE,
            contribution_name="shell",
        )
    )

    snapshot = registry.snapshot()

    assert snapshot.contributions[0].owner.manifest.id == "core"
    assert snapshot.diagnostics[0].code == "contribution_conflict"


def test_extension_dependency_must_be_active_and_starts_first() -> None:
    dependency = ExtensionDependency(
        kind=DependencyKind.EXTENSION,
        name="z-base",
    )
    registry = ExtensionRegistry()
    registry.register(
        _candidate(
            "a-dependent",
            scope=ExtensionScope.USER,
            dependencies=(dependency,),
        )
    )
    registry.register(_candidate("z-base", scope=ExtensionScope.USER))

    snapshot = registry.snapshot()

    assert [item.manifest.id for item in snapshot.extensions] == [
        "z-base",
        "a-dependent",
    ]


def test_inactive_extension_cannot_satisfy_dependency() -> None:
    dependency = ExtensionDependency(
        kind=DependencyKind.EXTENSION,
        name="base",
    )
    registry = ExtensionRegistry()
    registry.register(
        _candidate(
            "dependent",
            scope=ExtensionScope.USER,
            dependencies=(dependency,),
        )
    )
    registry.register(
        _candidate("base", scope=ExtensionScope.USER, trusted=False)
    )

    snapshot = registry.snapshot()

    assert snapshot.extensions == ()
    assert any(
        item.code == "dependency_missing"
        and item.extension_id == "dependent"
        for item in snapshot.diagnostics
    )


def test_extension_dependency_cycle_is_rejected() -> None:
    registry = ExtensionRegistry()
    registry.register(
        _candidate(
            "first",
            scope=ExtensionScope.USER,
            dependencies=(
                ExtensionDependency(
                    kind=DependencyKind.EXTENSION,
                    name="second",
                ),
            ),
        )
    )
    registry.register(
        _candidate(
            "second",
            scope=ExtensionScope.USER,
            dependencies=(
                ExtensionDependency(
                    kind=DependencyKind.EXTENSION,
                    name="first",
                ),
            ),
        )
    )

    snapshot = registry.snapshot()

    assert snapshot.extensions == ()
    assert {
        item.extension_id
        for item in snapshot.diagnostics
        if item.code == "dependency_cycle"
    } == {"first", "second"}


def test_optional_extension_dependency_cycle_is_allowed() -> None:
    registry = ExtensionRegistry()
    registry.register(
        _candidate(
            "first",
            scope=ExtensionScope.USER,
            dependencies=(
                ExtensionDependency(
                    kind=DependencyKind.EXTENSION,
                    name="second",
                    optional=True,
                ),
            ),
        )
    )
    registry.register(
        _candidate(
            "second",
            scope=ExtensionScope.USER,
            dependencies=(
                ExtensionDependency(
                    kind=DependencyKind.EXTENSION,
                    name="first",
                    optional=True,
                ),
            ),
        )
    )

    snapshot = registry.snapshot()

    assert {item.manifest.id for item in snapshot.extensions} == {
        "first",
        "second",
    }
    assert not any(
        item.code == "dependency_cycle" for item in snapshot.diagnostics
    )
