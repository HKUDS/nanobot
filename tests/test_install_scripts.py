"""Exercise the public installers against real, offline package managers.

The tiny wheel reports its runtime identity; it is not the nanobot application.
No gateway, model, user configuration or public package index is used by these tests.
"""

import base64
import hashlib
import io
import json
import os
import platform
import re
import shlex
import shutil
import ssl
import subprocess
import sys
import sysconfig
import tempfile
import threading
import tomllib
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from zipfile import ZipFile

import pytest
from packaging.tags import sys_tags

from nanobot import releases
from scripts.release_install_guide import (
    bootstrap_commands,
    install_command,
    render_install_command,
    verification_command,
)

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
WINDOWS = os.name == "nt"
BASE_PYTHON = sys._base_executable


def _wheel(directory, version, *, platform="any", package="nanobot-ai", extras=(), installer_receipt=False):
    module = package.replace("-", "_") if package != "nanobot-ai" else "nanobot"
    wheel_name = package.replace("-", "_")
    metadata = f"{wheel_name}-{version}.dist-info"
    files = {
        "nanobot/__init__.py": f'__version__ = "{version}"\n',
        "nanobot/__main__.py": """
import json
import sys
import nanobot

def main():
    print("INSTALLER_PROBE " + json.dumps({
        "version": nanobot.__version__, "package": nanobot.__file__,
        "python": sys.executable, "prefix": sys.prefix,
        "isolated": sys.flags.isolated, "args": sys.argv[1:],
    }))

if __name__ == "__main__":
    main()
""",
        f"{metadata}/METADATA": f"Metadata-Version: 2.1\nName: nanobot-ai\nVersion: {version}\nRequires-Python: >=3.11\n",
        f"{metadata}/WHEEL": "Wheel-Version: 1.0\nGenerator: installer-test\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        f"{metadata}/entry_points.txt": "[console_scripts]\nnanobot = nanobot.__main__:main\n",
    }
    files = {name.replace("nanobot/", f"{module}/"): content for name, content in files.items()}
    files[f"{module}/__main__.py"] = files[f"{module}/__main__.py"].replace("nanobot", module)
    files[f"{metadata}/METADATA"] = files[f"{metadata}/METADATA"].replace("Name: nanobot-ai", f"Name: {package}")
    files[f"{metadata}/METADATA"] += "".join(f"Provides-Extra: {extra}\n" for extra in extras)
    files[f"{metadata}/WHEEL"] = files[f"{metadata}/WHEEL"].replace("py3-none-any", f"py3-none-{platform}")
    files[f"{metadata}/entry_points.txt"] = f"[console_scripts]\n{module} = {module}.__main__:main\n"
    if installer_receipt:
        files["nanobot/installation_receipt.py"] = (SCRIPTS.parent / "nanobot/installation_receipt.py").read_text()
        files["nanobot/utils/__init__.py"] = ""
        files["nanobot/utils/atomic_file.py"] = (SCRIPTS.parent / "nanobot/utils/atomic_file.py").read_text()
    record = []
    path = directory / f"{wheel_name}-{version}-py3-none-{platform}.whl"
    with ZipFile(path, "w") as wheel:
        for name, content in files.items():
            data = content.encode()
            wheel.writestr(name, data)
            digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
            record.append(f"{name},sha256={digest},{len(data)}\n")
        wheel.writestr(f"{metadata}/RECORD", "".join(record) + f"{metadata}/RECORD,,\n")
    return path


def _python(environment):
    return environment / ("Scripts/python.exe" if WINDOWS else "bin/python")


def _run(command, sandbox, *, check=True, timeout=90):
    # Installer subprocesses may inherit output handles. Bound the command's
    # lifetime, not pipe EOF, and retain partial output when the command times out.
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        try:
            process = subprocess.run(command, cwd=sandbox["cwd"], env=sandbox["env"],
                                     stdout=stdout, stderr=stderr, timeout=timeout)
        except subprocess.TimeoutExpired:
            stdout.seek(0)
            stderr.seek(0)
            output = stdout.read().decode("utf-8", errors="replace")
            error = stderr.read().decode("utf-8", errors="replace")
            pytest.fail(f"Installer command exceeded {timeout}s: {command!r}\n"
                        f"stdout:\n{output}\nstderr:\n{error}", pytrace=False)
        stdout.seek(0)
        stderr.seek(0)
        result = subprocess.CompletedProcess(command, process.returncode,
                                             stdout.read().decode("utf-8", errors="replace"),
                                             stderr.read().decode("utf-8", errors="replace"))
    if check:
        assert result.returncode == 0, result.stdout + result.stderr
    return result


def _installer(sandbox, *args, check=True):
    if WINDOWS:
        shell = shutil.which("powershell")
        if not shell:
            pytest.skip("Windows PowerShell is required")
        command = [shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                   "-File", str(SCRIPTS / "install.ps1")]
    else:
        command = ["/bin/sh", str(SCRIPTS / "install.sh")]
    return _run([*command, *args], sandbox, check=check)


def _identity(result):
    reports = [json.loads(line.removeprefix("INSTALLER_PROBE "))
               for line in result.stdout.splitlines() if line.startswith("INSTALLER_PROBE ")]
    assert len(reports) == 1, result.stdout
    return reports[0]


def _expose(sandbox, name):
    source = os.environ.get(f"NANOBOT_TEST_{name.upper()}") or shutil.which(name)
    if not source:
        pytest.skip(f"{name} is required for this real installer check")
    destination = sandbox["bin"] / (f"{name}.exe" if WINDOWS else name)
    if WINDOWS:
        shutil.copy2(source, destination)
    else:
        destination.symlink_to(source)
    return str(destination)


@pytest.fixture
def sandbox(tmp_path):
    root = tmp_path.resolve() / "user's 数据 $safe"
    root.mkdir()
    command_bin = root / "commands"
    command_bin.mkdir()
    wheels = root / "wheels"
    wheels.mkdir()
    checkout = root / "checkout"
    (checkout / "nanobot").mkdir(parents=True)
    (checkout / "nanobot/__init__.py").write_text('raise RuntimeError("wrong checkout imported")\n')
    env = {key: value for key, value in os.environ.items()
           if key.upper() in {"SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT"}}
    system_path = (str(Path(env["SYSTEMROOT"]) / "System32") if WINDOWS else "/usr/bin:/bin")
    env.update({
        "HOME": str(root), "USERPROFILE": str(root),
        "PATH": str(command_bin) + os.pathsep + system_path,
        "PYTHON": BASE_PYTHON, "PYTHONPATH": str(checkout), "PYTHONUTF8": "1",
        "NANOBOT_SKIP_WIZARD": "1", "NANOBOT_VENV": str(root / "managed"),
        "NANOBOT_BIN_DIR": str(root / "launchers"),
        "XDG_CONFIG_HOME": str(root / "config"), "XDG_CACHE_HOME": str(root / "cache"),
        "XDG_DATA_HOME": str(root / "data"), "APPDATA": str(root / "config"),
        "LOCALAPPDATA": str(root / "data"), "TMPDIR": str(root), "TMP": str(root), "TEMP": str(root),
        "UV_TOOL_DIR": str(root / "uv-tools"), "UV_TOOL_BIN_DIR": str(root / "uv-bin"),
        "UV_CACHE_DIR": str(root / "uv-cache"), "UV_NO_CONFIG": "1", "UV_NO_INDEX": "1",
        "UV_OFFLINE": "1", "UV_PYTHON_DOWNLOADS": "never", "UV_FIND_LINKS": wheels.as_uri(),
        "PIPX_HOME": str(root / "pipx"), "PIPX_BIN_DIR": str(root / "pipx-bin"),
        "PIPX_MAN_DIR": str(root / "man"), "PIPX_DEFAULT_BACKEND": "pip",
        "PIPX_DISABLE_SHARED_LIBS_AUTO_UPGRADE": "1", "PIPX_DEFAULT_PYTHON": BASE_PYTHON,
        "PIP_CONFIG_FILE": os.devnull, "PIP_NO_INDEX": "1", "PIP_FIND_LINKS": wheels.as_uri(),
        "PIP_DISABLE_PIP_VERSION_CHECK": "1", "PIP_NO_INPUT": "1",
    })
    return {"root": root, "bin": command_bin, "wheels": wheels, "cwd": checkout, "env": env}


@pytest.mark.parametrize("manager", ["uv", "pipx"])
def test_installer_starts_and_upgrades_same_persistent_manager_environment(sandbox, manager):
    executable = _expose(sandbox, manager)
    _wheel(sandbox["wheels"], "0.0.1")
    _run([executable, *(["tool"] if manager == "uv" else []), "install", "--python", BASE_PYTHON, "nanobot-ai"], sandbox)
    prefix = (sandbox["root"] / "uv-tools/nanobot-ai" if manager == "uv"
              else sandbox["root"] / "pipx/venvs/nanobot-ai")
    for version in ("0.0.1", "0.0.2"):
        if version == "0.0.2":
            _wheel(sandbox["wheels"], version)
        identity = _identity(_installer(sandbox))
        assert identity["version"] == version
        assert Path(identity["prefix"]).resolve() == prefix
        assert Path(identity["package"]).resolve().is_relative_to(prefix)
        assert Path(identity["python"]).absolute() == _python(prefix)
        assert identity["isolated"] == 1
        assert identity["args"] == ["--version"]
    assert not (sandbox["root"] / "managed").exists()


@pytest.mark.skipif(not WINDOWS, reason="Windows PowerShell command discovery")
def test_powershell_manager_discovery_keeps_session_functions_without_importing_modules(sandbox):
    shell = shutil.which("powershell")
    if not shell:
        pytest.skip("Windows PowerShell is required")
    uv = Path(_expose(sandbox, "uv"))
    _wheel(sandbox["wheels"], "0.0.1")
    _run([str(uv), "tool", "install", "--python", BASE_PYTHON, "nanobot-ai"], sandbox)
    prefix = sandbox["root"] / "uv-tools/nanobot-ai"
    native = sandbox["root"] / "native"
    native.mkdir()
    uv = uv.rename(native / "uv.exe")
    _wheel(sandbox["wheels"], "0.0.2")

    def ps_literal(value):
        return "'" + str(value).replace("'", "''") + "'"

    modules = sandbox["root"] / "modules"
    decoy = modules / "InstallerDecoy"
    decoy.mkdir(parents=True)
    marker = sandbox["root"] / "module-imported"
    (decoy / "InstallerDecoy.psd1").write_text(
        "@{ RootModule = 'InstallerDecoy.psm1'; ModuleVersion = '1.0'; FunctionsToExport = @('pipx') }\n",
        encoding="utf-8-sig",
    )
    (decoy / "InstallerDecoy.psm1").write_text(
        f"[IO.File]::WriteAllText({ps_literal(marker)}, 'imported')\n"
        "function pipx { throw 'Manager discovery imported an unrelated module' }\n",
        encoding="utf-8-sig",
    )
    sandbox["env"]["PSModuleAnalysisCachePath"] = str(sandbox["root"] / "module-analysis-cache")
    command = (
        f"$env:PSModulePath = {ps_literal(modules)} + ';' + $PSHOME + '\\Modules'\n"
        f"function uv {{ & {ps_literal(uv)} @args }}\n"
        f"& {ps_literal(SCRIPTS / 'install.ps1')}"
    )
    result = _run([shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                   "-Command", command], sandbox, check=False)
    assert not marker.exists(), result.stdout + result.stderr
    assert result.returncode == 0, result.stdout + result.stderr
    identity = _identity(result)
    assert identity["version"] == "0.0.2"
    assert Path(identity["prefix"]).resolve() == prefix
    assert identity["isolated"] == 1
    assert not (sandbox["root"] / "managed").exists()


def test_rerunning_installer_preserves_uv_version_constraint(sandbox):
    uv = _expose(sandbox, "uv")
    _wheel(sandbox["wheels"], "0.0.1")
    _wheel(sandbox["wheels"], "0.0.2")
    _run([uv, "tool", "install", "--python", BASE_PYTHON, "nanobot-ai==0.0.1"], sandbox)
    assert _identity(_installer(sandbox))["version"] == "0.0.1"
    receipt = sandbox["root"] / "uv-tools/nanobot-ai/uv-receipt.toml"
    assert "==0.0.1" in receipt.read_text(encoding="utf-8")


@pytest.mark.parametrize("exact", [False, True], ids=["registry", "exact-wheel"])
@pytest.mark.parametrize("custom", ["constraint", "pip-options"])
def test_installer_never_discards_pipx_install_policy(sandbox, exact, custom):
    pipx = _expose(sandbox, "pipx")
    _wheel(sandbox["wheels"], "0.0.1")
    requirement = "nanobot-ai>=0.0.1,<0.1" if custom == "constraint" else "nanobot-ai"
    options = ["--pip-args=--no-deps"] if custom == "pip-options" else []
    _run([pipx, "install", "--python", BASE_PYTHON, *options, requirement], sandbox)
    prefix = sandbox["root"] / "pipx/venvs/nanobot-ai"
    receipt = prefix / "pipx_metadata.json"
    original = receipt.read_bytes()
    if exact:
        _, artifact = _preview_manifest(sandbox)
        arguments = _wheel_arguments(sandbox, artifact)
    else:
        _wheel(sandbox["wheels"], "0.0.2")
        arguments = []
    result = _installer(sandbox, *arguments, check=False)
    assert result.returncode != 0
    assert "pipx installation settings" in result.stdout + result.stderr
    assert receipt.read_bytes() == original
    assert _verify_owner(sandbox, "pipx", prefix)["version"] == "0.0.1"
    assert not (sandbox["root"] / "managed").exists()


def test_fresh_default_records_dedicated_environment_even_with_uv_available(sandbox):
    _expose(sandbox, "uv")
    _wheel(sandbox["wheels"], "0.0.1", installer_receipt=True)
    identity = _identity(_installer(sandbox))
    prefix = sandbox["root"] / "managed"
    assert Path(identity["prefix"]).resolve() == prefix
    receipt = prefix / "nanobot-install.json"
    original = receipt.read_bytes()
    assert json.loads(original) == {"schema_version": 1, "owner": "nanobot-installer",
                                    "environment": str(prefix), "extras": []}
    _wheel(sandbox["wheels"], "0.0.2", installer_receipt=True)
    assert _identity(_installer(sandbox))["version"] == "0.0.2"
    assert receipt.read_bytes() == original
    assert not (sandbox["root"] / "uv-tools/nanobot-ai").exists()


@pytest.mark.parametrize("original", ["pipx", "managed"])
def test_existing_owner_wins_when_uv_is_installed_later(sandbox, original):
    if original == "pipx":
        executable = _expose(sandbox, "pipx")
    _wheel(sandbox["wheels"], "0.0.1")
    if original == "pipx":
        _run([executable, "install", "--python", BASE_PYTHON, "nanobot-ai"], sandbox)
    before = _identity(_installer(sandbox))
    _expose(sandbox, "uv")
    _wheel(sandbox["wheels"], "0.0.2")
    after = _identity(_installer(sandbox))
    assert after["version"] == "0.0.2"
    assert after["prefix"] == before["prefix"]
    assert after["python"] == before["python"]
    assert not (sandbox["root"] / "uv-tools/nanobot-ai").exists()


def test_multiple_existing_installations_need_an_explicit_owner(sandbox):
    uv, pipx = _expose(sandbox, "uv"), _expose(sandbox, "pipx")
    _wheel(sandbox["wheels"], "0.0.1")
    _run([uv, "tool", "install", "--python", BASE_PYTHON, "nanobot-ai"], sandbox)
    _run([pipx, "install", "--python", BASE_PYTHON, "nanobot-ai"], sandbox)
    _wheel(sandbox["wheels"], "0.0.2")
    result = _installer(sandbox, check=False)
    assert result.returncode != 0
    assert "Multiple nanobot installations" in result.stdout + result.stderr
    for prefix in (sandbox["root"] / "uv-tools/nanobot-ai", sandbox["root"] / "pipx/venvs/nanobot-ai"):
        identity = _identity(_run([str(_python(prefix)), "-I", "-m", "nanobot", "--version"], sandbox))
        assert identity["version"] == "0.0.1"


def test_activated_manager_environment_is_not_updated_with_pip(sandbox):
    executable = _expose(sandbox, "uv")
    _wheel(sandbox["wheels"], "0.0.1")
    _run([executable, "tool", "install", "--python", BASE_PYTHON, "nanobot-ai"], sandbox)
    before = _identity(_installer(sandbox))
    sandbox["env"]["PYTHON"] = before["python"]
    _wheel(sandbox["wheels"], "0.0.2")
    result = _installer(sandbox, check=False)
    assert result.returncode != 0
    assert "active Python belongs to uv or pipx" in result.stdout + result.stderr
    assert _identity(_run([before["python"], "-I", "-m", "nanobot", "--version"], sandbox))["version"] == "0.0.1"


@pytest.mark.parametrize("active", [True, False], ids=["active-venv", "managed-venv"])
def test_python_install_uses_same_environment_and_quoted_launcher(sandbox, active):
    _wheel(sandbox["wheels"], "0.0.1")
    prefix = sandbox["root"] / ("active" if active else "managed")
    if active:
        _run([BASE_PYTHON, "-I", "-m", "venv", str(prefix)], sandbox)
        sandbox["env"]["PYTHON"] = str(_python(prefix))
    identity = _identity(_installer(sandbox))
    assert Path(identity["prefix"]).resolve() == prefix
    assert identity["isolated"] == 1
    if not WINDOWS and not active:
        wrapper = sandbox["root"] / "launchers/nanobot"
        launched = _identity(_run([str(wrapper), "--version"], sandbox))
        assert launched == identity


@pytest.mark.parametrize("manager", ["uv", "pipx"])
def test_failed_default_install_does_not_fall_through_to_available_manager(sandbox, manager):
    _expose(sandbox, manager)
    result = _installer(sandbox, check=False)
    assert result.returncode != 0
    assert (sandbox["root"] / "managed").exists()
    assert not (sandbox["root"] / "uv-tools/nanobot-ai").exists()
    assert not (sandbox["root"] / "pipx/venvs/nanobot-ai").exists()
    assert "INSTALLER_PROBE" not in result.stdout
    receipt = sandbox["root"] / "managed/nanobot-install.json"
    selection = receipt.read_bytes()
    _wheel(sandbox["wheels"], "0.0.1", installer_receipt=True)
    retried = _identity(_installer(sandbox))
    assert Path(retried["prefix"]).resolve() == sandbox["root"] / "managed"
    assert receipt.read_bytes() == selection
    assert json.loads(selection)["extras"] == []
    assert not (sandbox["root"] / "uv-tools/nanobot-ai").exists()
    assert not (sandbox["root"] / "pipx/venvs/nanobot-ai").exists()


def test_dry_run_does_not_create_tool_environment(sandbox):
    _expose(sandbox, "uv")
    result = _installer(sandbox, "--dry-run")
    assert "dedicated virtual environment" in result.stdout
    assert not (sandbox["root"] / "uv-tools").exists()
    assert "INSTALLER_PROBE" not in result.stdout


def _preview_manifest(sandbox, *, damaged_hash=False, extras=()):
    version = "0.0.2.dev1"
    platform = next(tag.platform for tag in sys_tags()
                    if tag.platform in releases.PLATFORMS.values())
    wheel = _wheel(sandbox["cwd"], version, platform=platform, extras=extras)
    digest = "0" * 64 if damaged_hash else hashlib.sha256(wheel.read_bytes()).hexdigest()
    artifacts = [releases.ReleaseArtifact(
        filename=name, size=wheel.stat().st_size if name == wheel.name else 123,
        sha256=digest if name == wheel.name else "c" * 64,
    ) for name in sorted(releases.release_filenames(version))]
    manifest = releases.ReleaseManifest(version=version, source_commit="a" * 40,
                                         candidate_commit="b" * 40, requires_python=">=3.11",
                                         artifacts=artifacts)
    return manifest, next(item for item in artifacts if item.filename == wheel.name)


def _owner_environment(sandbox, owner, *, existing):
    _wheel(sandbox["wheels"], "0.0.1")
    if owner == "pip":
        prefix = sandbox["root"] / "ordinary-venv"
        _run([BASE_PYTHON, "-I", "-m", "venv", str(prefix)], sandbox)
        executable = str(_python(prefix))
        if existing:
            _run([executable, "-I", "-m", "pip", "install", "nanobot-ai"], sandbox)
    else:
        executable = _expose(sandbox, owner)
        prefix = sandbox["root"] / ("uv-tools/nanobot-ai" if owner == "uv" else "pipx/venvs/nanobot-ai")
        sandbox["env"]["UV_PYTHON"] = BASE_PYTHON
        if existing:
            _run([executable, *(["tool"] if owner == "uv" else []), "install", "--python", BASE_PYTHON, "nanobot-ai"], sandbox)
    return executable, prefix


def _verify_owner(sandbox, owner, prefix):
    if owner == "pip":
        return _identity(_run([str(_python(prefix)), "-I", "-m", "nanobot", "--version"], sandbox))
    command = verification_command(owner, windows=WINDOWS)
    shell = ["powershell", "-NoProfile", "-NonInteractive", "-Command"] if WINDOWS else ["/bin/sh", "-c"]
    return _identity(_run([*shell, command], sandbox))


def _run_guide_command(sandbox, command, python, *, check=True):
    """Run the same multiline command users copy, including shell quoting."""
    if WINDOWS:
        value = str(python).replace("'", "''")
        prelude = f"Set-Alias -Name python -Value '{value}'\n"
        shell = ["powershell", "-NoProfile", "-NonInteractive", "-Command"]
    else:
        prelude = f'python() {{ {shlex.quote(str(python))} "$@"; }}\n'
        shell = ["/bin/sh", "-c"]
    return _run([*shell, prelude + render_install_command(command, windows=WINDOWS)], sandbox, check=check)


@pytest.mark.parametrize("owner", ["uv", "pipx", "pip"])
@pytest.mark.parametrize("existing", [False, True], ids=["fresh", "existing"])
def test_generated_exact_preview_commands_use_persistent_owner(sandbox, owner, existing):
    _, prefix = _owner_environment(sandbox, owner, existing=existing)
    manifest, artifact = _preview_manifest(sandbox)
    command = install_command(manifest, artifact, owner=owner, existing=existing)
    _run_guide_command(sandbox, command, _python(prefix) if owner == "pip" else BASE_PYTHON)
    identity = _verify_owner(sandbox, owner, prefix)
    assert identity["version"] == manifest.version
    assert Path(identity["prefix"]).resolve() == prefix
    assert Path(identity["package"]).resolve().is_relative_to(prefix)
    assert identity["isolated"] == 1


@pytest.mark.parametrize("owner", ["uv", "pipx", "pip"])
def test_generated_command_hash_failure_leaves_existing_version(sandbox, owner):
    _, prefix = _owner_environment(sandbox, owner, existing=True)
    manifest, artifact = _preview_manifest(sandbox, damaged_hash=True)
    command = install_command(manifest, artifact, owner=owner, existing=True)
    result = _run_guide_command(sandbox, command, _python(prefix) if owner == "pip" else BASE_PYTHON, check=False)
    assert result.returncode != 0
    assert "no package manager was started" in result.stderr
    assert _verify_owner(sandbox, owner, prefix)["version"] == "0.0.1"


@pytest.mark.parametrize("owner", ["uv", "pipx"])
def test_exact_preview_does_not_silently_remove_manager_pin(sandbox, owner):
    executable, prefix = _owner_environment(sandbox, owner, existing=False)
    if owner == "uv":
        _run([executable, "tool", "install", "nanobot-ai==0.0.1"], sandbox)
    else:
        _run([executable, "install", "--skip-maintenance", "nanobot-ai"], sandbox)
        _run([executable, "pin", "nanobot-ai"], sandbox)
    manifest, artifact = _preview_manifest(sandbox)
    command = install_command(manifest, artifact, owner=owner, existing=True)
    result = _run_guide_command(sandbox, command, BASE_PYTHON, check=False)
    # uv rejects the constraint conflict; pipx successfully skips a pinned tool.
    assert (result.returncode == 0) == (owner == "pipx")
    assert _verify_owner(sandbox, owner, prefix)["version"] == "0.0.1"


def test_exact_pipx_target_preserves_injected_package_and_records_new_spec(sandbox):
    pipx, prefix = _owner_environment(sandbox, "pipx", existing=True)
    _wheel(sandbox["wheels"], "1.0.0", package="fixture-helper")
    _run([pipx, "inject", "--skip-maintenance", "nanobot-ai", "fixture-helper"], sandbox)
    receipt = prefix / "pipx_metadata.json"
    before = json.loads(receipt.read_text(encoding="utf-8"))
    manifest, artifact = _preview_manifest(sandbox)
    command = install_command(manifest, artifact, owner="pipx", existing=True)
    _run_guide_command(sandbox, command, BASE_PYTHON)
    after = json.loads(receipt.read_text(encoding="utf-8"))
    assert after["injected_packages"] == before["injected_packages"]
    assert after["source_interpreter"] == before["source_interpreter"]
    assert after["main_package"]["package_or_url"] == f"nanobot-ai @ {(sandbox['cwd'] / artifact.filename).as_uri()}"
    _run([str(_python(prefix)), "-I", "-c", "import fixture_helper"], sandbox)
    assert _verify_owner(sandbox, "pipx", prefix)["version"] == manifest.version


def _wheel_arguments(sandbox, artifact):
    return ["-Wheel" if WINDOWS else "--wheel", str(sandbox["cwd"] / artifact.filename),
            "-Sha256" if WINDOWS else "--sha256", artifact.sha256]


@pytest.mark.parametrize("owner", ["uv", "pipx", "pip", "managed"])
@pytest.mark.parametrize("existing", [False, True], ids=["fresh", "existing"])
def test_public_installer_accepts_verified_exact_preview(sandbox, owner, existing):
    if owner == "managed":
        prefix = sandbox["root"] / "managed"
        if existing:
            _wheel(sandbox["wheels"], "0.0.1")
            _installer(sandbox)
    else:
        executable, prefix = _owner_environment(sandbox, owner, existing=existing)
        if owner == "pip":
            sandbox["env"]["PYTHON"] = executable
        elif not existing:
            prefix = sandbox["root"] / "managed"
    manifest, artifact = _preview_manifest(sandbox)
    result = _installer(sandbox, *_wheel_arguments(sandbox, artifact))
    identity = _identity(result)
    assert identity["version"] == manifest.version
    assert Path(identity["prefix"]).resolve() == prefix
    assert Path(identity["python"]).absolute() == _python(prefix)
    assert (sandbox["cwd"] / artifact.filename).is_file()


def test_public_installer_rejects_damaged_wheel_before_environment_creation(sandbox):
    _expose(sandbox, "uv")
    _, artifact = _preview_manifest(sandbox, damaged_hash=True)
    result = _installer(sandbox, *_wheel_arguments(sandbox, artifact), check=False)
    assert result.returncode != 0
    assert "SHA-256 mismatch" in result.stdout + result.stderr
    assert not (sandbox["root"] / "uv-tools/nanobot-ai").exists()
    assert not (sandbox["root"] / "managed").exists()


def test_public_installer_does_not_report_pinned_skip_as_preview_success(sandbox):
    pipx, prefix = _owner_environment(sandbox, "pipx", existing=True)
    _run([pipx, "pin", "nanobot-ai"], sandbox)
    _, artifact = _preview_manifest(sandbox)
    result = _installer(sandbox, *_wheel_arguments(sandbox, artifact), check=False)
    assert result.returncode != 0
    assert "requested version was not installed" in result.stdout + result.stderr
    assert "INSTALLER_PROBE" not in result.stdout
    assert _verify_owner(sandbox, "pipx", prefix)["version"] == "0.0.1"


def test_public_installer_wheel_dry_run_validates_but_does_not_install(sandbox):
    _expose(sandbox, "uv")
    manifest, artifact = _preview_manifest(sandbox)
    result = _installer(sandbox, "--dry-run", *_wheel_arguments(sandbox, artifact))
    assert f"verified wheel {manifest.version}" in result.stdout
    assert not (sandbox["root"] / "uv-tools/nanobot-ai").exists()


def test_public_installer_pipx_preview_preserves_requested_extras(sandbox):
    pipx = _expose(sandbox, "pipx")
    prefix = sandbox["root"] / "pipx/venvs/nanobot-ai"
    _wheel(sandbox["wheels"], "0.0.1", extras=("feature",))
    _run([pipx, "install", "--skip-maintenance", "nanobot-ai[feature]"], sandbox)
    _, artifact = _preview_manifest(sandbox, extras=("feature",))
    _installer(sandbox, *_wheel_arguments(sandbox, artifact))
    record = json.loads((prefix / "pipx_metadata.json").read_text(encoding="utf-8"))
    assert record["main_package"]["package_or_url"].startswith("nanobot-ai[feature] @ ")


def test_public_installer_uv_preview_preserves_requested_extras(sandbox):
    uv = _expose(sandbox, "uv")
    prefix = sandbox["root"] / "uv-tools/nanobot-ai"
    _wheel(sandbox["wheels"], "0.0.1", extras=("feature",))
    _run([uv, "tool", "install", "--python", BASE_PYTHON, "nanobot-ai[feature]"], sandbox)
    _, artifact = _preview_manifest(sandbox, extras=("feature",))
    _installer(sandbox, *_wheel_arguments(sandbox, artifact))
    record = tomllib.loads((prefix / "uv-receipt.toml").read_text(encoding="utf-8"))
    assert any(item.get("extras") == ["feature"] for item in record["tool"]["requirements"])


def test_public_installer_refuses_missing_previously_requested_pipx_extra(sandbox):
    pipx = _expose(sandbox, "pipx")
    prefix = sandbox["root"] / "pipx/venvs/nanobot-ai"
    _wheel(sandbox["wheels"], "0.0.1", extras=("feature",))
    _run([pipx, "install", "--skip-maintenance", "nanobot-ai[feature]"], sandbox)
    _, artifact = _preview_manifest(sandbox)
    result = _installer(sandbox, *_wheel_arguments(sandbox, artifact), check=False)
    assert result.returncode != 0
    assert "does not provide all existing pipx extras" in result.stdout + result.stderr
    assert _verify_owner(sandbox, "pipx", prefix)["version"] == "0.0.1"


def test_public_installer_incomplete_wheel_request_never_falls_back_to_pypi(sandbox):
    _wheel(sandbox["wheels"], "0.0.1")
    flag = "-Wheel" if WINDOWS else "--wheel"
    result = _installer(sandbox, flag, "missing.whl", check=False)
    assert result.returncode != 0
    assert "supplied together" in result.stdout + result.stderr
    assert not (sandbox["root"] / "managed").exists()


def test_public_installer_wrong_platform_keeps_original_environment(sandbox):
    python, prefix = _owner_environment(sandbox, "pip", existing=True)
    sandbox["env"]["PYTHON"] = python
    foreign = "macosx_13_0_arm64" if WINDOWS else "win_amd64"
    wheel = _wheel(sandbox["cwd"], "0.0.2.dev1", platform=foreign)
    artifact = releases.ReleaseArtifact(filename=wheel.name, size=wheel.stat().st_size,
                                        sha256=hashlib.sha256(wheel.read_bytes()).hexdigest())
    result = _installer(sandbox, *_wheel_arguments(sandbox, artifact), check=False)
    assert result.returncode != 0
    assert "retry this exact handoff" in result.stdout + result.stderr
    assert "uv tool install --force" not in result.stdout + result.stderr
    assert _verify_owner(sandbox, "pip", prefix)["version"] == "0.0.1"


def _bootstrap_program(script):
    source = (SCRIPTS / script).read_text(encoding="utf-8")
    if script.endswith(".sh"):
        match = re.search(r"wheel_identity=[^\n]*<<'PY'\n(.*?)\nPY\n", source, re.S)
        assert match is not None
        return match[1]
    return source.split("$Verify = @'\n", 1)[1].split("\n'@", 1)[0]


@pytest.fixture
def published_release(tmp_path, monkeypatch):
    version = "0.0.2.dev1"
    base = f"{releases.RELEASE_DOWNLOAD}/v{version}/"
    payloads = {}
    artifacts = []
    for name in sorted(releases.release_filenames(version)):
        if name.endswith(".whl"):
            tag = name.removeprefix(f"nanobot_ai-{version}-py3-none-").removesuffix(".whl")
            body = _wheel(tmp_path, version, platform=tag).read_bytes()
        else:
            body = b"not downloaded by the installer"
        payloads[base + name] = body
        artifacts.append(releases.ReleaseArtifact(filename=name, size=len(body),
                                                  sha256=hashlib.sha256(body).hexdigest()))
    manifest = releases.ReleaseManifest(version=version, source_commit="a" * 40,
                                         candidate_commit="b" * 40, requires_python=">=3.11",
                                         artifacts=artifacts)
    payloads[base + "release-manifest.json"] = manifest.model_dump_json().encode()
    requests = []

    class Opener:
        def open(self, request, *, timeout):
            assert timeout == 20
            requests.append(request.full_url)
            return io.BytesIO(payloads[request.full_url])

    monkeypatch.setattr(urllib.request, "build_opener", lambda *_: Opener())
    cache = tmp_path / "download cache 数据"

    def run(script, *, dry_run=False, manifest_hash=None):
        digest = manifest_hash or hashlib.sha256(payloads[base + "release-manifest.json"]).hexdigest()
        monkeypatch.setattr(sys, "argv", ["verify", "-", "-", "-", version, digest,
                                         str(cache), "1" if dry_run else "0"])
        namespace = {}
        try:
            exec(compile(_bootstrap_program(script), script, "exec"), namespace)
        except SystemExit as exc:
            if exc.code != 0:
                raise
        return namespace

    return run, manifest, payloads, requests, cache


@pytest.mark.parametrize("script", ["install.sh", "install.ps1"])
@pytest.mark.parametrize("system,machine,expected", [
    ("darwin", "arm64", "macosx_13_0_arm64"),
    ("darwin", "x86_64", "macosx_13_0_x86_64"),
    ("linux", "aarch64", "manylinux_2_17_aarch64"),
    ("linux", "x86_64", "manylinux_2_17_x86_64"),
    ("win32", "AMD64", "win_amd64"),
])
def test_bootstrap_downloads_only_target_wheel(published_release, monkeypatch, capsys, script, system, machine, expected):
    run, manifest, payloads, requests, cache = published_release
    monkeypatch.setattr(sys, "platform", system)
    monkeypatch.setattr(platform, "machine", lambda: machine)
    monkeypatch.setattr(platform, "mac_ver", lambda: ("15.0", ("", "", ""), machine))
    monkeypatch.setattr(os, "confstr", lambda _: "glibc 2.17", raising=False)
    monkeypatch.setattr(sysconfig, "get_platform", lambda: "win-amd64")
    run(script)
    filename = f"nanobot_ai-{manifest.version}-py3-none-{expected}.whl"
    assert len(requests) == 2 and requests[-1].endswith("/" + filename)
    files = list(cache.rglob("*.whl"))
    assert len(files) == 1 and files[0].name == filename
    assert files[0].read_bytes() == payloads[requests[-1]]
    assert capsys.readouterr().out.strip() == f"nanobot-ai @ {files[0].as_uri()}|{manifest.version}"
    run(script)
    assert len(requests) == 3 and requests[-1].endswith("release-manifest.json")
    assert not list(cache.rglob("*.part"))


@pytest.mark.parametrize("script", ["install.sh", "install.ps1"])
def test_bootstrap_dry_run_has_no_wheel_or_cache_writes(published_release, capsys, script):
    run, manifest, _, requests, cache = published_release
    namespace = run(script, dry_run=True)
    assert len(requests) == 1 and not cache.exists()
    assert f"|{manifest.version}" in capsys.readouterr().out
    assert namespace["native_platform"]() in {tag.platform for tag in sys_tags()}


@pytest.mark.parametrize("script", ["install.sh", "install.ps1"])
def test_bootstrap_bad_manifest_hash_never_downloads_wheel(published_release, script):
    run, _, _, requests, cache = published_release
    with pytest.raises(SystemExit, match="manifest size or SHA-256"):
        run(script, manifest_hash="0" * 64)
    assert len(requests) == 1 and not cache.exists()


@pytest.mark.parametrize("script", ["install.sh", "install.ps1"])
def test_bootstrap_damaged_download_is_not_retained(published_release, script):
    run, manifest, payloads, requests, cache = published_release
    for artifact in manifest.artifacts:
        if artifact.filename.endswith(".whl"):
            payloads[manifest.artifact_url(artifact).split("#")[0]] = b"truncated"
    with pytest.raises(SystemExit, match="wheel size or SHA-256"):
        run(script)
    assert len(requests) == 2
    assert not list(cache.rglob("*.whl")) and not list(cache.rglob("*.part"))


@pytest.mark.parametrize("libc", ["", "glibc 2.16"])
def test_bootstrap_does_not_download_a_glibc_wheel_for_incompatible_linux(published_release, monkeypatch, libc):
    run, _, _, requests, cache = published_release
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(os, "confstr", lambda _: libc, raising=False)
    with pytest.raises(SystemExit, match="glibc 2.17"):
        run("install.sh")
    assert not requests and not cache.exists()


@pytest.mark.parametrize("url", ["http://github.com/file", "https://example.com/file", "https://github.com:8443/file",
                                 "https://user:password@github.com/file", "https://127.0.0.1/file"])
def test_bootstrap_rejects_download_redirects_outside_project_hosts(published_release, url):
    run, _, _, _, _ = published_release
    namespace = run("install.sh", dry_run=True)
    handler = namespace["ReleaseRedirect"]()
    with pytest.raises(SystemExit, match="approved HTTPS hosts"):
        handler.redirect_request(urllib.request.Request("https://github.com/file"), None, 302, "Found", {}, url)


@pytest.fixture
def release_https(published_release, tmp_path):
    """Real HTTPS via a private CONNECT proxy; never contacts GitHub or other hosts."""
    openssl = shutil.which("openssl")
    if not openssl:
        pytest.skip("OpenSSL is required for the isolated HTTPS installer check")
    cert, key = tmp_path / "test-ca.pem", tmp_path / "test-ca-key.pem"
    subprocess.run([openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                    "-keyout", str(key), "-out", str(cert), "-days", "1", "-subj", "/CN=github.com",
                    "-addext", "subjectAltName=DNS:github.com,DNS:raw.githubusercontent.com"], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    _, manifest, payloads, _, _ = published_release
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_CONNECT(self):  # noqa: N802 -- stdlib protocol method
            if self.path not in {"github.com:443", "raw.githubusercontent.com:443"}:
                self.send_error(403)
                return
            self.send_response(200)
            self.end_headers()
            self.connection.settimeout(10)
            self.connection = context.wrap_socket(self.connection, server_side=True)
            self.rfile = self.connection.makefile("rb")
            self.wfile = self.connection.makefile("wb")
            self.handle_one_request()
            self.close_connection = True

        def do_GET(self):  # noqa: N802 -- stdlib protocol method
            url = "https://" + self.headers["Host"] + self.path
            requests.append(url)
            if url not in payloads:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Length", str(len(payloads[url])))
            self.end_headers()
            self.wfile.write(payloads[url])
            self.wfile.flush()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        digest = hashlib.sha256(payloads[f"{releases.RELEASE_DOWNLOAD}/v{manifest.version}/release-manifest.json"]).hexdigest()
        yield manifest, digest, payloads, requests, {
            "HTTPS_PROXY": f"http://127.0.0.1:{server.server_address[1]}",
            "SSL_CERT_FILE": str(cert), "NO_PROXY": "",
            "CURL_CA_BUNDLE": str(cert),
        }
    finally:
        server.shutdown()
        thread.join(timeout=10)
        server.server_close()


def _release_arguments(version, digest):
    return ["-Release" if WINDOWS else "--release", version,
            "-ManifestSha256" if WINDOWS else "--manifest-sha256", digest]


@pytest.mark.parametrize("owner", ["uv", "pipx", "managed"])
@pytest.mark.parametrize("existing", [False, True], ids=["fresh", "existing"])
def test_public_installer_download_to_owner_upgrade_over_https(sandbox, release_https, owner, existing):
    manifest, digest, _, requests, network = release_https
    if owner == "managed":
        prefix = sandbox["root"] / "managed"
        if existing:
            _wheel(sandbox["wheels"], "0.0.1")
            _installer(sandbox)
    else:
        _, prefix = _owner_environment(sandbox, owner, existing=existing)
        if not existing:
            prefix = sandbox["root"] / "managed"
    sandbox["env"].update(network)
    result = _installer(sandbox, *_release_arguments(manifest.version, digest))
    identity = _identity(result)
    assert identity["version"] == manifest.version
    assert Path(identity["prefix"]).resolve() == prefix
    assert len(requests) == 2
    cached = list((sandbox["root"] / ".nanobot/downloads/releases").rglob("*.whl"))
    assert len(cached) == 1 and requests[-1].endswith(cached[0].name)


def test_public_installer_release_dry_run_over_https_is_read_only(sandbox, release_https):
    manifest, digest, _, requests, network = release_https
    sandbox["env"].update(network)
    result = _installer(sandbox, "--dry-run", *_release_arguments(manifest.version, digest))
    assert "its wheel was not downloaded" in result.stdout
    assert len(requests) == 1
    assert not (sandbox["root"] / "managed").exists()
    assert not (sandbox["root"] / ".nanobot/downloads/releases").exists()


def test_public_installer_damaged_https_download_never_updates_existing_package(sandbox, release_https):
    manifest, digest, payloads, requests, network = release_https
    _, prefix = _owner_environment(sandbox, "uv", existing=True)
    for artifact in manifest.artifacts:
        if artifact.filename.endswith(".whl"):
            payloads[manifest.artifact_url(artifact).split("#")[0]] = b"damaged download"
    sandbox["env"].update(network)
    result = _installer(sandbox, *_release_arguments(manifest.version, digest), check=False)
    assert result.returncode != 0 and "wheel size or SHA-256 mismatch" in result.stdout + result.stderr
    assert len(requests) == 2
    assert _verify_owner(sandbox, "uv", prefix)["version"] == "0.0.1"
    cache = sandbox["root"] / ".nanobot/downloads/releases"
    assert not list(cache.rglob("*.whl")) and not list(cache.rglob("*.part"))


@pytest.mark.parametrize("owner", ["uv", "pipx"])
def test_release_bootstrap_preserves_explicit_manager_pin(sandbox, release_https, owner):
    executable, prefix = _owner_environment(sandbox, owner, existing=False)
    if owner == "uv":
        _run([executable, "tool", "install", "nanobot-ai==0.0.1"], sandbox)
        receipt = prefix / "uv-receipt.toml"
    else:
        _run([executable, "install", "--skip-maintenance", "nanobot-ai"], sandbox)
        _run([executable, "pin", "nanobot-ai"], sandbox)
        receipt = prefix / "pipx_metadata.json"
    before = receipt.read_bytes()
    manifest, digest, _, requests, network = release_https
    sandbox["env"].update(network)
    result = _installer(sandbox, *_release_arguments(manifest.version, digest), check=False)
    assert result.returncode != 0
    assert "INSTALLER_PROBE" not in result.stdout
    assert len(requests) == 2
    assert receipt.read_bytes() == before
    assert _verify_owner(sandbox, owner, prefix)["version"] == "0.0.1"
    assert not (sandbox["root"] / "managed").exists()


@pytest.mark.skipif(WINDOWS, reason="Unix bootstrap command; Windows installer is tested separately")
def test_generated_bootstrap_command_downloads_and_upgrades_original_owner(sandbox, release_https):
    manifest, digest, payloads, requests, network = release_https
    _expose(sandbox, "curl")
    _, prefix = _owner_environment(sandbox, "uv", existing=True)
    installer_url = f"https://raw.githubusercontent.com/HKUDS/nanobot/{manifest.candidate_commit}/scripts/install.sh"
    payloads[installer_url] = (SCRIPTS / "install.sh").read_bytes()
    sandbox["env"].update(network)
    unix, _ = bootstrap_commands(manifest, digest)
    identity = _identity(_run(["/bin/sh", "-c", unix], sandbox))
    assert identity["version"] == manifest.version
    assert Path(identity["prefix"]).resolve() == prefix
    assert requests[0] == installer_url and len(requests) == 3
    assert not list(sandbox["root"].glob("*/install.sh"))


def test_installer_command_timeout_preserves_partial_diagnostics(sandbox):
    command = [BASE_PYTHON, "-I", "-c",
               "import sys, time; print('installer-stage', flush=True); "
               "print('manager-stage', file=sys.stderr, flush=True); time.sleep(10)"]
    with pytest.raises(pytest.fail.Exception, match="(?s)installer-stage.*manager-stage"):
        _run(command, sandbox, timeout=1)
