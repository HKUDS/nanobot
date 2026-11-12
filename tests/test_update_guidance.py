import shlex
from pathlib import Path

import pytest

from nanobot import update_guidance
from nanobot.update_guidance import installation_method, shell_command, update_guide
from nanobot.update_manager import ManagerPolicy
from nanobot.update_plan import InstallationSnapshot


def installation(tmp_path, owner="venv", **policy):
    environment = tmp_path / "tools" / "nanobot-ai" if owner == "uv" else tmp_path / "pipx" / "venvs" / "nanobot-ai-work"
    return InstallationSnapshot(
        environment=str(environment), python=str(environment / "bin" / "python"),
        package_path=str(tmp_path / "checkout" / "nanobot" / "__init__.py"),
        installed_version="0.3.6", running_version="0.3.6", running_package=str(tmp_path / "checkout" / "nanobot" / "__init__.py"),
        owner=owner, records={}, manager=ManagerPolicy(
            manager=owner, backend="uv" if owner == "uv" else "pip", extras=["matrix"], source="registry", **policy,
        ) if owner in {"uv", "pipx"} else None,
    )


@pytest.mark.parametrize("owner", ["uv", "pipx"])
def test_registry_commands_bind_manager_environment_and_preserve_suffix(tmp_path, monkeypatch, owner):
    binary = str(tmp_path / "bin" / owner)
    monkeypatch.setattr(update_guidance.shutil, "which", lambda _: binary)
    snapshot = installation(tmp_path, owner)
    guide = update_guide(snapshot, "0.3.7", extras=["matrix"])
    assert guide.method == owner
    assert guide.reason == "registry"
    assert binary in guide.update_command
    assert Path(snapshot.environment).name in guide.update_command
    assert ("UV_TOOL_DIR" if owner == "uv" else "PIPX_HOME") in guide.update_command
    assert guide.inspect_command and "list" in guide.inspect_command
    assert snapshot.python in guide.verify_command
    assert "--force" not in guide.update_command and "pip install" not in guide.update_command


@pytest.mark.parametrize("policy", [{"pinned": True}, {"locked": True}, {"version_constraint": "<0.3.7"}])
@pytest.mark.parametrize("owner", ["uv", "pipx"])
def test_restricted_manager_has_inspection_but_no_update(tmp_path, monkeypatch, owner, policy):
    monkeypatch.setattr(update_guidance.shutil, "which", lambda name: name)
    guide = update_guide(installation(tmp_path, owner, **policy), "0.3.7", extras=[])
    assert guide.reason == "policy" and guide.inspect_command and guide.update_command is None


@pytest.mark.parametrize("policy", [{"version_constraint": ">=0.3.4,<0.4"}, {"custom_pip_args": True}])
def test_pipx_in_range_target_still_requires_preserving_owner_options(tmp_path, monkeypatch, policy):
    monkeypatch.setattr(update_guidance.shutil, "which", lambda name: name)
    guide = update_guide(installation(tmp_path, "pipx", **policy), "0.3.7", extras=[])
    assert guide.reason == "policy" and guide.update_command is None
    assert guide.inspect_command and guide.verify_command


@pytest.mark.parametrize("owner", ["uv", "pipx"])
def test_preview_fixed_source_and_missing_manager_never_guess_upgrade(tmp_path, monkeypatch, owner):
    monkeypatch.setattr(update_guidance.shutil, "which", lambda name: name)
    snapshot = installation(tmp_path, owner)
    assert update_guide(snapshot, "0.3.7.dev1", extras=[]).reason == "preview"
    assert update_guide(snapshot, "0.3.7.dev1", extras=[]).update_command is None
    snapshot = snapshot.model_copy(update={"manager": snapshot.manager.model_copy(update={"source": "artifact"})})
    assert update_guide(snapshot, "0.3.7", extras=[]).update_command is None
    monkeypatch.setattr(update_guidance.shutil, "which", lambda _: None)
    assert update_guide(snapshot, "0.3.7", extras=[]).reason == "manager"


def test_pip_requires_known_extras_and_uses_exact_interpreter(tmp_path):
    snapshot = installation(tmp_path)
    assert installation_method(snapshot) == "pip"
    unknown = update_guide(snapshot, "0.3.7", extras=None)
    assert unknown.reason == "extras" and unknown.update_command is None
    assert "importlib.metadata" in unknown.inspect_command
    assert "-m pip" not in unknown.inspect_command
    known = update_guide(snapshot, "0.3.7", extras=["matrix"])
    assert snapshot.python in known.update_command
    assert "nanobot-ai[matrix]==0.3.7" in known.update_command
    snapshot.records["nanobot-install.json"] = "a" * 64
    assert installation_method(snapshot) == "managed"


@pytest.mark.parametrize("owner", ["source", "container", "system"])
def test_deployments_do_not_get_guessed_install_or_restart_commands(tmp_path, owner):
    guide = update_guide(installation(tmp_path, owner), "0.3.7", extras=[])
    assert guide.reason == owner and guide.update_command is None
    if owner == "container":
        assert guide.verify_command is None
    if owner == "source":
        assert "status" in guide.inspect_command and str(tmp_path / "checkout") in guide.inspect_command


def test_source_guide_inspects_the_running_checkout_not_a_different_installed_package(tmp_path):
    snapshot = installation(tmp_path, "source").model_copy(update={"package_path": str(tmp_path / "site-packages" / "nanobot" / "__init__.py")})
    guide = update_guide(snapshot, "0.3.7", extras=[])
    assert str(tmp_path / "checkout") in guide.inspect_command
    assert "site-packages" not in guide.inspect_command


def test_stale_review_and_non_upgrade_cannot_generate_install_commands(tmp_path):
    snapshot = installation(tmp_path)
    assert update_guide(snapshot, "0.3.7", extras=[], current=False).update_command is None
    for target in ["0.3.6", "0.3.5"]:
        assert update_guide(snapshot, target, extras=[]).update_command is None


def test_updated_files_with_old_running_gateway_only_offer_restart_verification(tmp_path):
    snapshot = installation(tmp_path).model_copy(update={"installed_version": "0.3.7"})
    guide = update_guide(snapshot, "0.3.7", extras=[])
    assert guide.reason == "restart" and guide.verify_command and guide.update_command is None


def test_shell_rendering_quotes_paths_and_restores_powershell_environment():
    args = ["/a b/$not-expanded/python", "-m", "pip", "show", "nanobot-ai"]
    environment = ("PIPX_HOME", "/some one's/$directory")
    assert shlex.split(shell_command(args, windows=False, environment=environment)) == ["env", "PIPX_HOME=/some one's/$directory", *args]
    command = shell_command(args, windows=True, environment=environment)
    assert "'/some one''s/$directory'" in command
    assert "finally { $env:PIPX_HOME = $nanobotPrevious }" in command
    assert "& '/a b/$not-expanded/python'" in command
