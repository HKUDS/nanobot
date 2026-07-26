"""Version constraint checks shared by extension activation gates."""

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from nanobot.extensions.manifest import ExtensionDependency


def dependency_version_failure(
    dependency: ExtensionDependency,
    version: str,
    label: str,
) -> str:
    """Return a user-facing constraint failure, or an empty string on success."""
    if not dependency.specifier:
        return ""
    try:
        matches = Version(version) in SpecifierSet(dependency.specifier)
    except (InvalidSpecifier, InvalidVersion):
        return (
            f"{label} {dependency.name} has an unsupported version constraint: "
            f"{dependency.specifier}"
        )
    if matches:
        return ""
    return (
        f"{label} {dependency.name} {version} does not satisfy "
        f"{dependency.specifier}"
    )
