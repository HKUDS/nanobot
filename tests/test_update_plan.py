import hashlib
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
import typer
from packaging.tags import Tag
from rich.text import Text
from typer.testing import CliRunner

from nanobot.cli.update import update as update_command
from nanobot.installation_lock import InstallationBusyError, installation_access
from nanobot.release_feed import ReleaseFeed, ReleaseTarget
from nanobot.releases import ReleaseArtifact, release_filenames
from nanobot.update_manager import ManagerPolicy
from nanobot.update_plan import InstallationSnapshot, UpdatePlan, UpdatePlans, inspect_installation


def installation(version="0.3.4", running=None, **changes):
    return InstallationSnapshot(
        environment="/test/venv", python="/test/venv/bin/python", installed_version=version,
        package_path="/test/venv/lib/nanobot/__init__.py", running_version=running or version,
        running_package="/test/venv/lib/nanobot/__init__.py", owner="venv", records=changes,
    )


def target():
    name = "nanobot_ai-0.3.5-py3-none-win_amd64.whl"
    return ReleaseTarget(version="0.3.5", source="pypi", url=f"https://files.pythonhosted.org/packages/{name}",
                         artifact=ReleaseArtifact(filename=name, size=123, sha256="a" * 64))


def plan(snapshot=None):
    return UpdatePlan(id=str(uuid4()), installation=snapshot or installation(), channel="stable",
                      target=target(), created_at=100, expires_at=1000)


@pytest.mark.parametrize("installed,running,action", [
    ("0.3.4", "0.3.4", "upgrade"), ("0.3.5", "0.3.5", "none"),
    ("0.3.5", "0.3.4", "restart"), ("0.3.6.dev1", "0.3.6.dev1", "downgrade"),
    ("0.3.4", "0.3.6.dev1", "downgrade"),
])
def test_action_reports_actual_installed_and_running_versions(installed, running, action):
    assert plan(installation(installed, running)).action == action


def test_saved_plan_survives_a_new_store_and_cannot_be_replaced(tmp_path):
    original = plan()
    store = UpdatePlans(tmp_path / "plans")
    store.save(original)
    assert UpdatePlans(store.directory).load(original.id) == original
    assert store.save(original) == original
    changed = original.model_copy(update={"expires_at": 999})
    with pytest.raises(ValueError, match="cannot be replaced"):
        store.save(changed)
    if sys.platform != "win32":
        assert (store.directory / f"{original.id}.json").stat().st_mode & 0o777 == 0o600


def test_plan_expiry_environment_and_owner_receipt_are_binding():
    original = plan()
    original.validate_for(installation(), now=999)
    with pytest.raises(ValueError, match="expired"):
        original.validate_for(installation(), now=1000)
    with pytest.raises(ValueError, match="Installation changed"):
        original.validate_for(installation("0.3.5"), now=200)
    with pytest.raises(ValueError, match="Installation changed"):
        original.validate_for(installation(**{"uv-receipt.toml": "b" * 64}), now=200)
    other = installation().model_copy(update={"environment": "/other/venv"})
    with pytest.raises(ValueError, match="Installation changed"):
        original.validate_for(other, now=200)


def test_plan_id_cannot_escape_private_directory(tmp_path):
    with pytest.raises(ValueError):
        UpdatePlans(tmp_path).load("../../config")


@pytest.mark.asyncio
async def test_prepare_and_revalidate_cross_the_same_feed_interface_without_installer(tmp_path, monkeypatch):
    monkeypatch.setattr(ReleaseFeed, "_authorize", AsyncMock())
    requests = []

    def handler(request):
        requests.append(str(request.url))
        return httpx.Response(200, json={
            "info": {"name": "nanobot-ai", "version": "0.3.5", "requires_python": ">=3.11"},
            "urls": [{"filename": name, "size": 123, "digests": {"sha256": "a" * 64},
                      "url": f"https://files.pythonhosted.org/packages/{name}", "yanked": False}
                     for name in release_filenames("0.3.5") if name.endswith((".whl", ".tar.gz"))],
        })

    async with ReleaseFeed(tmp_path / "cache", transport=httpx.MockTransport(handler),
                           supported_tags=[Tag("py3", "none", "win_amd64")]) as feed:
        store = UpdatePlans(tmp_path / "plans")
        saved = await store.prepare(installation(), "stable", feed, now=100)
        assert saved.target == target()
        assert await store.revalidate(saved.id, installation(), feed, now=101) == saved
    assert requests == ["https://pypi.org/pypi/nanobot-ai/json", "https://pypi.org/pypi/nanobot-ai/0.3.5/json"]


def test_probe_reads_fresh_interpreter_and_owner_receipt(tmp_path, monkeypatch):
    import venv

    from nanobot import update_plan, update_process

    account = tmp_path / "private account"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: account))
    monkeypatch.setattr(update_process, "_INSPECTION_BOOTSTRAP", (
        "from pathlib import Path\n"
        f"Path.home = classmethod(lambda cls: Path({str(account)!r}))\n"
    ) + update_process._INSPECTION_BOOTSTRAP)

    root = tmp_path / "env with spaces"
    venv.EnvBuilder(with_pip=False).create(root)
    executable = root / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    site = Path(subprocess.check_output([str(executable), "-I", "-c",
                                       "import sysconfig; print(sysconfig.get_path('purelib'))"], text=True).strip())
    (site / "nanobot").mkdir()
    (site / "nanobot/__init__.py").write_text("__version__='0.3.5'\n")
    dist = site / "nanobot_ai-0.3.5.dist-info"
    dist.mkdir()
    (dist / "METADATA").write_text("Metadata-Version: 2.1\nName: nanobot-ai\nVersion: 0.3.5\n")
    receipt = {"pipx_metadata_version": "0.12", "main_package": {
        "package": "nanobot-ai", "package_or_url": "nanobot-ai[webui]", "pinned": False,
    }}
    (root / "pipx_metadata.json").write_text(json.dumps(receipt))
    monkeypatch.setattr(sys, "prefix", str(root))
    monkeypatch.setattr(sys, "executable", str(executable))
    monkeypatch.setattr(update_plan.nanobot, "__version__", "0.3.4")
    monkeypatch.setattr(update_plan.nanobot, "__file__", str(site / "nanobot/__init__.py"))
    monkeypatch.delenv("RENDER", raising=False)
    snapshot = inspect_installation()
    assert snapshot.installed_version == "0.3.5"
    assert snapshot.running_version == "0.3.4"
    assert snapshot.owner == ("container" if Path("/.dockerenv").exists() else "pipx")
    assert snapshot.records["pipx_metadata.json"] == hashlib.sha256((root / "pipx_metadata.json").read_bytes()).hexdigest()
    if snapshot.owner == "pipx":
        assert snapshot.manager.extras == ["webui"]
    before = snapshot.fingerprint
    receipt["main_package"]["pinned"] = True
    (root / "pipx_metadata.json").write_text(json.dumps(receipt))
    assert inspect_installation().fingerprint != before


@pytest.mark.asyncio
@pytest.mark.parametrize("manager", ["uv", "pipx"])
async def test_managed_plan_preserves_extras_and_reports_owner_constraints(tmp_path, manager):
    policy = ManagerPolicy(manager=manager, backend="uv" if manager == "uv" else "pip",
                           source="registry", extras=["webui"], version_constraint="<0.3.5")
    snapshot = installation().model_copy(update={"owner": manager, "manager": policy})

    class Feed:
        async def latest(self, channel):
            assert channel == "stable"
            return target()

    saved = await UpdatePlans(tmp_path).prepare(snapshot, "stable", Feed(), now=100)
    assert saved.extras == ["webui"]
    assert saved.action == "upgrade"
    assert "constraints" in saved.owner_restriction
    assert UpdatePlans(tmp_path).load(saved.id) == saved
    changed = saved.model_dump()
    changed["extras"] = []
    with pytest.raises(ValueError, match="recorded extras"):
        UpdatePlan.model_validate(changed)


def test_cli_plan_is_available_and_never_starts_install(monkeypatch):
    from nanobot import update, update_plan

    async def preview(channel):
        assert channel is None
        return plan()

    monkeypatch.setattr(update_plan, "preview_release_update", preview)
    monkeypatch.setattr(update, "update_installation", lambda **kwargs: pytest.fail("plan invoked installer"))
    app = typer.Typer()
    app.command()(update_command)
    result = CliRunner().invoke(app, ["--plan"])
    assert result.exit_code == 0, result.output
    output = json.loads(result.stdout)
    assert output["target"]["version"] == "0.3.5"
    assert output["action"] == "upgrade"


@pytest.mark.parametrize("channel", ["stable", "preview"])
def test_cli_channel_inspection_cannot_silently_run_stable_update(monkeypatch, channel):
    from nanobot import update

    monkeypatch.setattr(update, "update_installation", lambda **kwargs: pytest.fail("unexpected installer"))
    app = typer.Typer()
    app.command()(update_command)
    result = CliRunner().invoke(app, ["--channel", channel])
    assert result.exit_code != 0
    assert "requires --plan" in Text.from_ansi(result.output).plain


@pytest.mark.parametrize("retry", [False, True])
def test_saved_job_cli_uses_scoped_status_and_explicit_handoff_only(tmp_path, monkeypatch, retry):
    from nanobot import update, update_jobs
    from nanobot.update_jobs import UpdateJobView
    from nanobot.update_worker import Phase

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(sys, "prefix", str(tmp_path / "environment"))
    identifier, confirmation = str(uuid4()), uuid4().hex
    job = UpdateJobView(id=identifier, installation_id="a" * 64, host="test", previous_version="0.3.4",
                        target_version="0.3.5", channel="stable", recorded_phase=Phase.HANDOFF_FAILED,
                        attempt=0, mutation_started=False, updated_at=100, execution_confirmation_id=confirmation)
    calls = []

    def saved(plan_id):
        assert plan_id == identifier
        return job

    def handoff(directory, previous):
        assert directory.name == identifier and previous == confirmation
        with pytest.raises(InstallationBusyError):
            with installation_access(updating=True):
                pytest.fail("Recovery controller released its runtime too early")
        calls.append(identifier)

    monkeypatch.setattr(update_jobs, "read_update_job", saved)
    monkeypatch.setattr(update_jobs, "retry_handoff", handoff)
    monkeypatch.setattr(update, "update_installation", lambda **kwargs: pytest.fail("Unexpected legacy installer"))
    app = typer.Typer()
    app.command()(update_command)
    arguments = ["--job", identifier]
    if retry:
        arguments += ["--retry-handoff", "--previous-confirmation", confirmation, "--confirm-restart"]
    result = CliRunner().invoke(app, arguments)
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == job.model_dump(mode="json")
    assert calls == ([identifier] if retry else [])


@pytest.mark.parametrize("arguments", [
    ["--retry-handoff"], ["--job", "id", "--confirm-restart"],
    ["--job", "id", "--retry-handoff", "--confirm-restart"],
    ["--job", "id", "--previous-confirmation", "confirmation"],
    ["--job", "id", "--retry-handoff", "--previous-confirmation", "confirmation"],
    ["--job", "id", "--check"], ["--job", "id", "--dev"], ["--job", "id", "--plan"],
    ["--job", "id", "--channel", "preview"], ["--job", "id", "--allow-downgrade"],
])
def test_saved_job_cli_rejects_ambiguous_recovery_flags(monkeypatch, arguments):
    from nanobot.cli import update

    monkeypatch.setattr(update, "_saved_job", lambda *args: pytest.fail("Ambiguous recovery was executed"))
    app = typer.Typer()
    app.command()(update_command)
    assert CliRunner().invoke(app, arguments).exit_code != 0
