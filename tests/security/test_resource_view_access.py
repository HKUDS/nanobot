from pathlib import Path

import pytest

from nanobot.resource_links import ensure_resource_view
from nanobot.security.workspace_policy import WorkspaceBoundaryError, resolve_allowed_path


@pytest.fixture
def resource_targets(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    data_dir = tmp_path / "data"
    workspace = tmp_path / "agent"
    package = tmp_path / "package" / "nanobot"
    project = tmp_path / "project"
    (workspace / "skills" / "custom").mkdir(parents=True)
    (workspace / "memory").mkdir()
    (package / "skills" / "builtin").mkdir(parents=True)
    (package / "templates").mkdir()
    project.mkdir()
    (workspace / "skills" / "custom" / "SKILL.md").write_text("custom", encoding="utf-8")
    (workspace / "memory" / "history.jsonl").write_text("{}\n", encoding="utf-8")
    (package / "skills" / "builtin" / "SKILL.md").write_text("builtin", encoding="utf-8")
    (package / "templates" / "identity.md").write_text("identity", encoding="utf-8")
    return data_dir, workspace, package, project


def _view_for(targets: tuple[Path, Path, Path, Path]):
    data_dir, workspace, package, _ = targets
    view = ensure_resource_view(
        data_dir=data_dir,
        config_path=data_dir / "config.json",
        agent_workspace=workspace,
        package_root=package,
    )
    if view.agent is None or view.media is None or view.package is None:
        pytest.skip(f"directory links unavailable: {view.warnings}")
    return view


def test_restricted_access_follows_resource_alias_targets(
    resource_targets: tuple[Path, Path, Path, Path],
) -> None:
    _, workspace, package, project = resource_targets
    view = _view_for(resource_targets)

    custom_skill = resolve_allowed_path(
        view.agent / "skills" / "custom" / "SKILL.md",
        workspace=project,
        allowed_root=project,
        extra_allowed_roots=[workspace / "skills", package / "skills"],
        strict=True,
    )
    builtin_skill = resolve_allowed_path(
        view.package / "skills" / "builtin" / "SKILL.md",
        workspace=project,
        allowed_root=project,
        extra_allowed_roots=[workspace / "skills", package / "skills"],
        strict=True,
    )
    media_root = resolve_allowed_path(
        view.media,
        workspace=project,
        allowed_root=project,
        extra_allowed_roots=[resource_targets[0] / "media"],
        strict=True,
    )

    assert custom_skill == (workspace / "skills" / "custom" / "SKILL.md").resolve()
    assert builtin_skill == (package / "skills" / "builtin" / "SKILL.md").resolve()
    assert media_root == (resource_targets[0] / "media").resolve()


def test_alias_does_not_expand_restricted_package_or_agent_access(
    resource_targets: tuple[Path, Path, Path, Path],
) -> None:
    _, workspace, _, project = resource_targets
    view = _view_for(resource_targets)

    with pytest.raises(WorkspaceBoundaryError):
        resolve_allowed_path(
            view.package / "templates" / "identity.md",
            workspace=project,
            allowed_root=project,
            extra_allowed_roots=[workspace / "skills"],
            strict=True,
        )

    history = workspace / "memory" / "history.jsonl"
    with pytest.raises(WorkspaceBoundaryError):
        resolve_allowed_path(
            view.agent / "memory" / "history.jsonl",
            workspace=project,
            allowed_root=project,
            extra_allowed_files=[history],
            strict=True,
        )

    assert resolve_allowed_path(
        history,
        workspace=project,
        allowed_root=project,
        extra_allowed_files=[history],
        strict=True,
    ) == history.resolve()
