"""Real offline seed/install checks for disposable integration environments."""

import ensurepip
import json
import os
import subprocess
from importlib.resources import files
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

_PROBE = """
import importlib.metadata as metadata
import json
import os
import sys
from pathlib import Path
import pip

distribution = metadata.distribution('pip')
script = 'pip.exe' if os.name == 'nt' else 'pip'
print(json.dumps({
    'prefix': sys.prefix,
    'python': sys.executable,
    'pip': pip.__file__,
    'pip_version': pip.__version__,
    'creation_command': dict(line.split(' = ', 1) for line in
                             (Path(sys.prefix) / 'pyvenv.cfg').read_text(encoding='utf-8').splitlines())['command'],
    'versions': {dist.metadata['Name']: dist.version for dist in metadata.distributions()},
    'pip_scripts': [str(distribution.locate_file(path)) for path in distribution.files
                    if Path(distribution.locate_file(path)).name == script],
}))
"""


def _run(*command):
    return subprocess.run(command, check=True, capture_output=True, text=True, timeout=30).stdout


def _assert_stdlib_seed(state):
    bundled = files("ensurepip").joinpath("_bundled")
    versions = {wheel.name.split("-")[0]: wheel.name.split("-")[1]
                for wheel in bundled.iterdir() if wheel.name.endswith(".whl")}
    assert state["versions"] == versions
    pip = bundled.joinpath(f"pip-{ensurepip.version()}-py3-none-any.whl")
    site = Path(state["pip"]).parent.parent
    with ZipFile(BytesIO(pip.read_bytes())) as archive:
        for member in archive.infolist():
            if member.filename.startswith("pip/") and not member.is_dir():
                assert (site / member.filename).read_bytes() == archive.read(member)


def _wheel(directory: Path, version: str) -> Path:
    dist = f"seed_probe-{version}.dist-info"
    files = {
        "seed_probe/__init__.py": (
            "def main():\n"
            "    import importlib.metadata as metadata, json, sys\n"
            "    print(json.dumps([sys.prefix, sys.executable, metadata.version('seed-probe')]))\n"
        ),
        f"{dist}/METADATA": f"Metadata-Version: 2.1\nName: seed-probe\nVersion: {version}\n",
        f"{dist}/WHEEL": "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        f"{dist}/entry_points.txt": "[console_scripts]\nseed-probe = seed_probe:main\n",
    }
    record = f"{dist}/RECORD"
    files[record] = "".join(f"{name},,\n" for name in [*files, record])
    path = directory / f"seed_probe-{version}-py3-none-any.whl"
    with ZipFile(path, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return path


def test_seeded_pip_and_installed_scripts_use_independent_prefixes(create_integration_env, tmp_path, monkeypatch):
    for name in tuple(os.environ):
        if name.startswith("PIP_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("PIP_CONFIG_FILE", os.devnull)
    monkeypatch.setenv("PIP_NO_INDEX", "1")
    monkeypatch.setenv("PIP_DISABLE_PIP_VERSION_CHECK", "1")
    monkeypatch.setenv("PIP_NO_CACHE_DIR", "1")
    monkeypatch.delenv("PYTHONPATH", raising=False)

    first = create_integration_env(tmp_path / "first prefix with spaces")
    first_state = json.loads(_run(str(first), "-I", "-c", _PROBE))
    _assert_stdlib_seed(first_state)
    _run(str(first), "-I", "-m", "pip", "install", "--no-deps", str(_wheel(tmp_path, "1.0.0")))

    # Update integration cases deliberately rewrite this entrypoint. The next
    # prefix must still be seeded from an unchanged image, not that live pip.
    entrypoint = Path(first_state["pip"]).with_name("__main__.py")
    entrypoint.write_text("raise SystemExit('test-owned pip mutation')\n", encoding="utf-8")
    changed = subprocess.run([str(first), "-I", "-m", "pip", "--version"],
                             capture_output=True, text=True, timeout=30)
    assert changed.returncode != 0 and "test-owned pip mutation" in changed.stderr

    second = create_integration_env(tmp_path / "second prefix with spaces")
    second_state = json.loads(_run(str(second), "-I", "-c", _PROBE))
    _assert_stdlib_seed(second_state)
    assert "seed-probe" not in second_state["versions"]
    assert _run(str(second), "-I", "-m", "pip", "--version").startswith(f"pip {ensurepip.version()} ")
    for python, state in ((first, first_state), (second, second_state)):
        assert Path(state["prefix"]).resolve() == python.parent.parent.resolve()
        assert Path(state["python"]).resolve() == python.resolve()
        assert Path(state["pip"]).resolve().is_relative_to(python.parent.parent.resolve())
        assert state["pip_version"] == state["versions"]["pip"] == ensurepip.version()
        assert " -m venv " in state["creation_command"]
        pip = python.parent / ("pip.exe" if os.name == "nt" else "pip")
        assert [Path(path).resolve() for path in state["pip_scripts"]] == [pip.resolve()]
        assert _run(str(pip), "--version").startswith(f"pip {ensurepip.version()} from {Path(state['pip']).parent}")
        assert f"sys.executable: {python}" in _run(str(pip), "debug")

    _run(str(second), "-I", "-m", "pip", "install", "--no-deps", str(_wheel(tmp_path, "2.0.0")))
    for python, version in ((first, "1.0.0"), (second, "2.0.0")):
        command = python.parent / ("seed-probe.exe" if os.name == "nt" else "seed-probe")
        prefix, executable, installed = json.loads(_run(str(command)))
        assert Path(prefix).resolve() == python.parent.parent.resolve()
        assert Path(executable).resolve() == python.resolve()
        assert installed == version
