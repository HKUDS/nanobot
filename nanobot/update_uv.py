"""Private uv tool preparation; cache copies never change the owner's saved policy.

Keep this module stdlib-only: its verification/copy operations also run from the
frozen update worker after the installed application has stopped.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from nanobot.update_process import PreparationProcess

# Cache/receipt and exec-lease behavior must be exercised before expanding this
# internal native route to another manager release. Unsupported versions use
# the installation owner's workflow; they are never downgraded automatically.
UV_TRANSACTION_VERSION = "0.11.16"
_TRANSPORT_SETTINGS = {"UV_HTTP_TIMEOUT", "UV_HTTP_RETRIES", "UV_SYSTEM_CERTS", "UV_NATIVE_TLS"}


def _receipt_only_policy() -> None:
    locations = {"UV_TOOL_DIR", "UV_TOOL_BIN_DIR", "UV_CACHE_DIR", "UV_NO_CONFIG"}
    for key in os.environ:
        if (key.startswith("UV_") and key not in locations | _TRANSPORT_SETTINGS
                and not (key.startswith("UV_INDEX_") and key.endswith(("_USERNAME", "_PASSWORD")))):
            raise ValueError("External uv settings require the installation owner's update workflow")
    if os.environ.get("UV_NO_CONFIG", "").lower() in {"1", "true"}:
        return
    roots = [Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"), Path("/etc")]
    roots.extend(Path(value) for value in os.environ.get("XDG_CONFIG_DIRS", "/etc/xdg").split(":") if value)
    if any((root / "uv/uv.toml").exists() for root in roots):
        raise ValueError("External uv configuration requires the installation owner's update workflow")


def _record(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("Invalid uv preparation record")
    data = cast(dict[object, object], value)
    if not all(isinstance(key, str) for key in data):
        raise ValueError("Invalid uv preparation record")
    return cast(dict[str, object], data)


def _text(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 16_384:
        raise ValueError("Invalid uv preparation value")
    return value


def _hash_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _toml(value: object) -> str:
    if isinstance(value, (str, bool)) or type(value) is int:
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ", ".join(_toml(item) for item in cast(list[object], value)) + "]"
    if isinstance(value, dict):
        items = _record(cast(dict[object, object], value))
        return "{ " + ", ".join(f"{json.dumps(key)} = {_toml(item)}" for key, item in items.items()) + " }"
    raise ValueError("Unsupported uv receipt setting; use the installation owner")


def _requirement(value: object) -> str:
    item = _record(value)
    if item.keys() - {"name", "extras", "specifier", "url", "marker"}:
        raise ValueError("This uv requirement needs its owner's update workflow")
    name = _text(item.get("name"))
    extras = item.get("extras", [])
    if not isinstance(extras, list):
        raise ValueError("Invalid uv requirement extras")
    extra_values = cast(list[object], extras)
    if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name)
            or not all(isinstance(extra, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", extra)
                       for extra in extra_values)):
        raise ValueError("Invalid uv requirement identity")
    suffix = "[" + ",".join(cast(list[str], extras)) + "]" if extras else ""
    url = item.get("url")
    if url is not None:
        # Source/editable installs can run build children; they are not a wheel
        # transaction and must not be quietly converted into one.
        from urllib.parse import urlsplit

        parsed = urlsplit(_text(url))
        if parsed.scheme not in {"https", "http", "file"} or not parsed.path.endswith(".whl"):
            raise ValueError("Source requirements need the uv owner's update workflow")
        suffix += " @ " + _text(url)
    elif item.get("specifier"):
        suffix += _text(item["specifier"])
    if item.get("marker"):
        suffix += " ; " + _text(item["marker"])
    return name + suffix


def uv_environment(*, tools: Path, binaries: Path, cache: Path) -> dict[str, str]:
    """Use frozen receipt policy, retaining credentials and transport settings only."""
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith(("UV_", "PIP_", "PIPX_"))
           or key in _TRANSPORT_SETTINGS or (key.startswith("UV_INDEX_") and key.endswith(("_USERNAME", "_PASSWORD")))}
    env.update(UV_TOOL_DIR=str(tools), UV_TOOL_BIN_DIR=str(binaries), UV_CACHE_DIR=str(cache),
               UV_NO_PROGRESS="1", UV_PYTHON_DOWNLOADS="never", PYTHONDONTWRITEBYTECODE="1")
    return env


def _run(process: PreparationProcess, executable: str, arguments: list[str], *, env: dict[str, str], cwd: Path) -> str:
    result = process.run(executable, arguments, kind="native", env=env, cwd=cwd)
    if result.returncode:
        # Index URLs, raw resolver messages and TOML parse diagnostics may carry
        # credentials. The public job stores a stage, not these raw strings.
        raise ValueError("Could not prepare the uv transaction; inspect the installation's manager settings")
    return result.stdout.strip()


def cache_digest(source: Path, *, copy_to: Path | None = None) -> str:
    """Seal/copy a private cache without its absolute internal symlink locations.

    uv writes its working cache during apply. A fresh verified copy keeps both the
    original preparation and interrupted-update retries bound to the same inputs.
    No shared uv cache is read, moved, rewritten or cleared by this operation.
    """
    root = source.resolve(strict=True)
    if source.is_symlink() or not root.is_dir():
        raise ValueError("Invalid private uv cache")
    if copy_to is not None:
        copy_to.mkdir(mode=0o700)  # Never merge into an existing apply cache.
    digest = hashlib.sha256()
    count, size = 0, 0
    for current, directories, files in os.walk(root, followlinks=False):
        directories.sort()
        files.sort()
        for name in sorted(directories + files):
            path = Path(current) / name
            relative = path.relative_to(root)
            mode = path.lstat().st_mode
            output = copy_to / relative if copy_to is not None else None
            count += 1
            if count > 200_000:
                raise ValueError("Private uv cache exceeds its entry limit")
            if stat.S_ISLNK(mode):
                target = path.resolve(strict=True)
                if not target.is_relative_to(root):
                    raise ValueError("Private uv cache links outside its preparation")
                target_name = target.relative_to(root).as_posix()
                entry = [relative.as_posix(), "link", target_name]
                if output is not None and copy_to is not None:
                    output.symlink_to(os.path.relpath(copy_to / target_name, output.parent),
                                      target_is_directory=target.is_dir())
            elif stat.S_ISDIR(mode):
                entry = [relative.as_posix(), "directory"]
                if output is not None:
                    output.mkdir(mode=0o700)
            elif stat.S_ISREG(mode):
                size += path.stat().st_size
                if size > 4 * 1024**3:
                    raise ValueError("Private uv cache exceeds its size limit")
                entry = [relative.as_posix(), "file", str(mode & 0o111), _hash_file(path)]
                if output is not None:
                    shutil.copyfile(path, output)
                    output.chmod(0o600 | (mode & 0o111))
            else:
                raise ValueError("Private uv cache contains an unsupported file type")
            digest.update((json.dumps(entry, separators=(",", ":")) + "\n").encode())
    return digest.hexdigest()


def _versions(process: PreparationProcess, python: str, *, prepared: bool = False) -> dict[str, str]:
    result = process.run(python, ["-c",
        "import json,re; from importlib.metadata import distributions; "
        "print(json.dumps({re.sub(r'[-_.]+','-',d.metadata['Name']).lower():"
        "[d.version,json.loads(d.read_text('direct_url.json') or '{}')] for d in distributions()}))"],
        timeout=30)
    if result.returncode:
        raise ValueError("Could not inspect the prepared uv environment")
    from urllib.parse import urlsplit

    versions: dict[str, str] = {}
    for name, value in _record(json.loads(result.stdout)).items():
        if not isinstance(value, list):
            raise ValueError("Invalid prepared distribution record")
        fields = cast(list[object], value)
        if len(fields) != 2:
            raise ValueError("Invalid prepared distribution record")
        versions[name] = _text(fields[0])
        direct = _record(fields[1])
        if prepared and direct and name != "nanobot-ai":
            parsed = urlsplit(_text(direct.get("url")))
            if parsed.scheme not in {"https", "http"} or not parsed.path.endswith(".whl"):
                raise ValueError("Local or source dependencies need the uv owner's update workflow")
    return versions


def _remote_location(value: object) -> None:
    from urllib.parse import urlsplit

    if isinstance(value, list):
        for item in cast(list[object], value):
            _remote_location(item)
    elif isinstance(value, dict):
        _remote_location(_record(cast(dict[object, object], value)).get("url"))
    elif urlsplit(_text(value)).scheme not in {"https", "http"}:
        # --offline still reads local indexes/find-links. Such a directory can
        # change the resolved target after preparation even with a sealed cache.
        raise ValueError("Local package sources need their owner's update workflow")


@dataclass(frozen=True)
class UVPreparation:
    executable: str
    executable_sha256: str
    manager_version: str
    receipt_sha256: str
    cache: str
    cache_sha256: str
    binaries: str
    versions: dict[str, str]

    @classmethod
    def parse(cls, value: object) -> UVPreparation:
        data = _record(value)
        result = cls(_text(data["executable"]), _text(data["executable_sha256"]), _text(data["manager_version"]),
                     _text(data["receipt_sha256"]), _text(data["cache"]), _text(data["cache_sha256"]),
                     _text(data["binaries"]),
                     {name: _text(version) for name, version in _record(data["versions"]).items()})
        if any(not re.fullmatch(r"[0-9a-f]{64}", item) for item in (
            result.executable_sha256, result.receipt_sha256, result.cache_sha256,
        )) or len(result.versions) > 500 or not all(
            Path(path).is_absolute() for path in (result.executable, result.binaries)
        ):
            raise ValueError("Invalid uv preparation identity")
        cache = Path(result.cache)
        if (cache.is_absolute() or ".." in cache.parts or len(cache.parts) != 2
                or not cache.parts[0].startswith(".uv-prepare-") or cache.parts[1] != "cache"):
            raise ValueError("Invalid private uv cache location")
        return result

    def verify(self, environment: str, directory: Path) -> None:
        _receipt_only_policy()
        if _hash_file(Path(self.executable)) != self.executable_sha256:
            raise ValueError("The uv executable changed since preparation")
        receipt = Path(environment) / "uv-receipt.toml"
        if receipt.is_symlink() or _hash_file(receipt) != self.receipt_sha256:
            raise ValueError("The uv installation settings changed since preparation")
        cache = directory / self.cache
        if not cache.resolve().is_relative_to(directory.resolve()) or cache_digest(cache) != self.cache_sha256:
            raise ValueError("The prepared uv cache changed")

    def working_cache(self, directory: Path) -> Path:
        attempt = Path(tempfile.mkdtemp(prefix=".uv-apply-", dir=directory)) / "cache"
        if (cache_digest(directory / self.cache, copy_to=attempt) != self.cache_sha256
                or cache_digest(attempt) != self.cache_sha256):
            raise ValueError("The copied uv transaction does not match its preparation")
        return attempt


def prepare_uv(*, environment: str, python: str, receipt_sha256: str, app_wheel: Path,
               version: str, extras: list[str], directory: Path, executable: str,
               process: PreparationProcess) -> UVPreparation:
    """Resolve in a separate tool home; never change the user's tool or receipt."""
    _receipt_only_policy()
    if Path(environment).resolve().name != "nanobot-ai":
        raise ValueError("This tool layout needs the uv owner's update workflow")
    executable = str(Path(executable).resolve(strict=True))
    with Path(executable).open("rb") as stream:
        magic = stream.read(4)
    if (Path(executable).is_relative_to(Path(environment).resolve())
            or magic not in {b"\x7fELF", b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf",
                             b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca",
                             b"\xca\xfe\xba\xbf", b"\xbf\xba\xfe\xca"}):
        raise ValueError("The uv updater needs a native manager outside the environment being replaced")
    manager_sha = _hash_file(Path(executable))
    receipt_path = Path(environment) / "uv-receipt.toml"
    with receipt_path.open("rb") as stream:
        raw = stream.read(1024**2 + 1)
    if receipt_path.is_symlink() or len(raw) > 1024**2 or hashlib.sha256(raw).hexdigest() != receipt_sha256:
        raise ValueError("The uv receipt changed before preparation")
    try:
        receipt = _record(tomllib.loads(raw.decode()))
        tool = _record(receipt["tool"])
        if receipt.keys() != {"tool"} or tool.keys() - {"requirements", "python", "entrypoints", "options"}:
            raise ValueError("Unsupported receipt fields")
        requirements = tool["requirements"]
        entries = tool["entrypoints"]
        options = _record(tool.get("options", {}))
        if not isinstance(requirements, list) or not isinstance(entries, list):
            raise ValueError("Invalid receipt collections")
        injected: list[str] = []
        main = 0
        for item in cast(list[object], requirements):
            requirement = _record(item)
            rendered = _requirement(item)
            if re.sub(r"[-_.]+", "-", _text(requirement["name"])).lower() == "nanobot-ai":
                main += 1
            else:
                injected.extend(["--with", rendered])
        paths = [_text(_record(entry)["install-path"]) for entry in cast(list[object], entries)]
        parents = {str(Path(path).parent) for path in paths}
        if main != 1 or len(parents) != 1 or not all(Path(path).is_absolute() for path in paths):
            raise ValueError("Ambiguous tool ownership")
        if (options.get("compile-bytecode") or options.get("no-binary") or options.get("no-binary-package")
                or options.get("link-mode") == "symlink" or options.get("keyring-provider") == "subprocess"):
            raise ValueError("This policy requires a different native lifecycle")
        for name in ("index", "index-url", "default-index", "extra-index-url", "find-links"):
            if name in options:
                _remote_location(options[name])
        binaries = parents.pop()
        encoded_options = "\n".join(f"{json.dumps(key)} = {_toml(value)}" for key, value in options.items())
    except (ValueError, KeyError, TypeError):
        raise ValueError("These uv settings need the installation owner's update workflow") from None
    before = _versions(process, python)
    # Unique attempts prevent an orphan preparing process from writing a cache
    # reused by a subsequent request after its parent exits.
    staging = Path(tempfile.mkdtemp(prefix=".uv-prepare-", dir=directory))
    cache = staging / "cache"
    config = staging / "uv.toml"
    config.write_text(encoded_options, encoding="utf-8")
    config.chmod(0o600)
    env = uv_environment(tools=staging / "tools", binaries=staging / "bin", cache=cache)
    manager_version = _run(process, executable, ["--version"], env=env, cwd=staging)
    if manager_version.split()[:2] != ["uv", UV_TRANSACTION_VERSION]:
        raise ValueError("This uv version needs the installation owner's update workflow")
    target = "nanobot-ai" + (f"[{','.join(extras)}]" if extras else "") + " @ " + app_wheel.as_uri()
    # --no-build is private to this disposable receipt. Supplying it to the real
    # tool upgrade would permanently change the user's stored options.
    _run(process, executable, ["tool", "install", "--config-file", str(config), "--python", python,
                      "--no-build", *injected, target], env=env, cwd=staging)
    prepared_python = staging / "tools/nanobot-ai" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    versions = _versions(process, str(prepared_python), prepared=True)
    if versions.get("nanobot-ai") != version:
        raise ValueError("uv resolved a different application version")
    if _versions(process, python) != before or receipt_path.read_bytes() != raw:
        raise ValueError("The original uv installation changed during preparation")
    for source_cache in cache.glob("sdists-*"):
        if any(path.is_file() and path.stat().st_size for path in source_cache.rglob("*")):
            raise ValueError("Source-built dependencies cannot enter the offline uv transaction")
    for path in cache.rglob("*"):
        if path.is_file() and not path.is_symlink():
            with path.open("r+b") as stream:
                os.fsync(stream.fileno())
    result = UVPreparation(executable, manager_sha, manager_version, receipt_sha256,
                           cache.relative_to(directory).as_posix(), cache_digest(cache), binaries, versions)
    result.verify(environment, directory)
    return result
