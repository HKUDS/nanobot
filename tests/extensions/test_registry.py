from nanobot.extensions import (
    ContributionKind,
    ExtensionCandidate,
    ExtensionContribution,
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
    replaces: tuple[str, ...] = (),
    trusted: bool = True,
) -> ExtensionCandidate:
    contributions = (
        ExtensionContribution(
            kind=ContributionKind.TOOL,
            name=contribution_name,
            replaces=replaces,
        ),
    ) if contribution_name else ()
    return ExtensionCandidate(
        manifest=ExtensionManifest(
            id=extension_id,
            name=extension_id,
            version="1.0.0",
            runtime=ExtensionRuntime.PYTHON,
            contributions=contributions,
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


def test_explicit_higher_scope_replacement_takes_ownership() -> None:
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
            replaces=("core",),
        )
    )

    snapshot = registry.snapshot()

    assert snapshot.contributions[0].owner.manifest.id == "replacement"
    assert snapshot.diagnostics == ()
