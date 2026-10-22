#!/bin/sh
set -eu

package="nanobot-ai"
install_target="$package"
install_source="PyPI"
dry_run="0"
nanobot_python=""
release_wheel=""
release_sha256=""
release_kind=""
expected_version=""
release_version=""
manifest_sha256=""

info() {
  printf '%s\n' "$*"
}

fail() {
  printf 'Error: %s\n' "$*" >&2
  exit 1
}

install_failure_hint() {
  printf '%s\n' "Error: could not install nanobot from $install_source." >&2
  if [ -n "$expected_version" ]; then
    printf '%s\n' "Inspect the original manager error and retry this exact handoff. No setup or other installation was attempted." >&2
    exit 1
  fi
  printf '%s\n' "If pip mentioned externally-managed-environment, use uv, pipx, or a virtual environment instead of system pip." >&2
  printf '%s\n' "You can also run manually:" >&2
  printf '  %s\n' "uv tool install --force --upgrade $install_target" >&2
  printf '  %s\n' "$python_bin -m venv ~/.nanobot/venv" >&2
  printf '  %s\n' "~/.nanobot/venv/bin/python -m pip install --upgrade $install_target" >&2
  printf '%s\n' "Then start setup with:" >&2
  printf '  %s\n' "nanobot onboard --wizard" >&2
  exit 1
}

usage() {
  cat <<'EOF'
Usage: install.sh [--dry-run] [--wheel PATH --sha256 HASH]
       install.sh [--dry-run] --release VERSION --manifest-sha256 HASH

By default this installs or upgrades nanobot-ai from PyPI.
Use --dry-run to print what would happen without installing or starting setup.
For a verified release handoff, use --wheel and --sha256 together. Keep that
downloaded wheel in place; your manager may record it as the installation source.
Stop affected gateways and back up their data before updating an existing install.
--release downloads the matching platform wheel from the official release using
its published manifest hash. This selects one version, not a Preview subscription.

For current main, clone the repository and run `python -m pip install -e .`.
EOF
}

find_python() {
  for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
      if "$candidate" - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY
      then
        printf '%s\n' "$candidate"
        return 0
      fi
    fi
  done
  return 1
}

python_is_virtual_env() {
  "$python_bin" - <<'PY'
import sys
raise SystemExit(0 if sys.prefix != sys.base_prefix else 1)
PY
}

select_install_method() {
  if python_is_virtual_env; then
    active_prefix="$("$python_bin" -I -c 'import sys; print(sys.prefix)')"
    if [ -f "$active_prefix/uv-receipt.toml" ] || [ -f "$active_prefix/pipx_metadata.json" ]; then
      fail "The active Python belongs to uv or pipx. Deactivate it and rerun this installer so its manager owns the update."
    fi
    install_method="python"
    return
  fi

  install_method=""
  existing_count=0
  if command -v uv >/dev/null 2>&1; then
    uv_dir="$(uv tool dir)" || fail "Could not inspect the uv tools directory"
    [ -n "$uv_dir" ] || fail "uv returned an empty tools directory"
    if [ -e "$uv_dir/$package" ]; then
      install_method="uv"
      existing_count=$((existing_count + 1))
    fi
  fi
  if command -v pipx >/dev/null 2>&1; then
    pipx_dir="$(pipx environment --value PIPX_LOCAL_VENVS)" || fail "Could not inspect the pipx environments directory"
    [ -n "$pipx_dir" ] || fail "pipx returned an empty environments directory"
    if [ -e "$pipx_dir/$package" ]; then
      install_method="pipx"
      existing_count=$((existing_count + 1))
    fi
  fi
  if [ -n "${NANOBOT_VENV:-}${HOME:-}" ] && [ -f "${NANOBOT_VENV:-${HOME:-}/.nanobot/venv}/pyvenv.cfg" ]; then
    install_method="managed"
    existing_count=$((existing_count + 1))
  fi
  [ "$existing_count" -le 1 ] || fail "Multiple nanobot installations were found. Use the intended environment's package manager; this installer changed none of them."
  if [ -z "$install_method" ]; then
    install_method="managed"
  fi
}

ensure_pip() {
  target_python="$1"
  if "$target_python" -m pip --version >/dev/null 2>&1; then
    return 0
  fi

  info "pip was not found for $target_python. Trying ensurepip..."
  "$target_python" -m ensurepip --upgrade >/dev/null 2>&1
}

select_installed_python() {
  # Keep the venv interpreter path (resolving its symlink would select base Python).
  # Isolated mode also prevents a checkout/PYTHONPATH from shadowing the new package.
  nanobot_python="$("$1" -I - "$2" "$expected_version" <<'PY'
import sys
from importlib.metadata import distribution
from pathlib import Path

import nanobot

prefix = Path(sys.prefix).resolve()
package = Path(nanobot.__file__).resolve()
expected = sys.argv[1]
if sys.prefix == sys.base_prefix or (expected and prefix != Path(expected).resolve()):
    raise SystemExit("The installed interpreter does not belong to the expected virtual environment")
if not package.is_relative_to(prefix) or package != Path(distribution("nanobot-ai").locate_file("nanobot/__init__.py")).resolve():
    raise SystemExit("nanobot imports from outside the installed package")
if sys.argv[2] and distribution("nanobot-ai").version != sys.argv[2]:
    raise SystemExit("The requested version was not installed. Check manager pins or locks; no setup was started.")
print(Path(sys.executable).absolute())
PY
  )" || fail "The installed nanobot environment could not be verified. No setup or other installation was attempted."
}

run_nanobot() {
  "$nanobot_python" -I -m nanobot "$@"
}

nanobot_try_command() {
  "$python_bin" -I -c 'import shlex, sys; print(shlex.quote(sys.argv[1]) + " -I -m nanobot")' "$nanobot_python"
}

is_fresh_nanobot_install() {
  [ -n "${HOME:-}" ] || return 1
  [ ! -e "$HOME/.nanobot/config.json" ]
}

has_browser_session() {
  if [ -n "${SSH_CONNECTION:-}${SSH_TTY:-}" ]; then
    return 1
  fi
  if ! : 2>/dev/null < /dev/tty; then
    return 1
  fi

  case "$(uname -s)" in
    Darwin)
      command -v launchctl >/dev/null 2>&1 &&
        launchctl print "gui/$(id -u)" >/dev/null 2>&1
      ;;
    *)
      [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]
      ;;
  esac
}

install_with_active_python() {
  info "Detected an active virtual environment. Installing into it..."
  ensure_pip "$python_bin" || return 1
  "$python_bin" -m pip install --upgrade "$install_target" || return 1
  select_installed_python "$python_bin" ""
}

install_with_uv() {
  info "Installing or upgrading nanobot from $install_source with uv tool..."
  tool_dir="$(uv tool dir)" || fail "Could not locate the uv tools directory"
  [ -n "$tool_dir" ] || fail "uv returned an empty tools directory"
  if [ -f "$tool_dir/$package/uv-receipt.toml" ]; then
    uv tool upgrade "$install_target" || fail "uv could not upgrade nanobot. Resolve the error above and retry; no other installation was attempted."
  elif [ -e "$tool_dir/$package" ]; then
    fail "The uv environment exists without its installation record. Repair it with uv before rerunning this installer."
  else
    uv tool install --python "$python_bin" "$install_target" ||
      fail "uv could not install nanobot. Resolve the error above and retry; no other installation was attempted."
  fi
  select_installed_python "$tool_dir/$package/bin/python" "$tool_dir/$package"
}

install_with_pipx() {
  info "Installing or upgrading nanobot from $install_source with pipx..."
  tool_dir="$(pipx environment --value PIPX_LOCAL_VENVS)" || fail "Could not locate the pipx environments directory"
  [ -n "$tool_dir" ] || fail "pipx returned an empty environments directory"
  if [ -f "$tool_dir/$package/pipx_metadata.json" ]; then
    # Bootstrap must not import the installed application or expose private options.
    "$python_bin" -I - "$tool_dir/$package/pipx_metadata.json" "$expected_version" <<'PY' || fail "Review the original pipx installation settings; no installation was attempted."
import json
import re
import sys
from pathlib import Path

try:
    path = Path(sys.argv[1])
    if path.is_symlink() or path.stat().st_size > 1024 * 1024:
        raise ValueError
    record = json.loads(path.read_text(encoding="utf-8"))
    main = record["main_package"]
    name = r"(?i)nanobot[-_.]ai(?:\[[a-z0-9_., -]+\])?"
    spec = main["package_or_url"]
    # An explicit wheel may replace an earlier wheel source, but not discard
    # registry constraints, lock workflows or recorded installer options.
    allowed = re.fullmatch(name, spec) or (sys.argv[2] and re.fullmatch(name + r"\s*@\s*\S+\.whl", spec))
    if record["pipx_metadata_version"] not in {"0.5", "0.12"} or not allowed or main.get("pip_args") or main.get("lock_file"):
        raise ValueError
except (OSError, ValueError, KeyError, TypeError):
    raise SystemExit("Cannot safely reuse pipx installation settings; inspect the original requirement and options.") from None
PY
    if [ -n "$expected_version" ]; then
      pipx install --skip-maintenance --upgrade "$install_target" || fail "pipx could not upgrade nanobot. Resolve the error above and retry; no other installation was attempted."
    else
      pipx upgrade "$package" || fail "pipx could not upgrade nanobot. Resolve the error above and retry; no other installation was attempted."
    fi
  elif [ -e "$tool_dir/$package" ]; then
    fail "The pipx environment exists without its installation record. Repair it with pipx before rerunning this installer."
  else
    pipx install --python "$python_bin" "$install_target" ||
      fail "pipx could not install nanobot. Resolve the error above and retry; no other installation was attempted."
  fi
  select_installed_python "$tool_dir/$package/bin/python" "$tool_dir/$package"
}

write_managed_wrapper() {
  bin_dir="${NANOBOT_BIN_DIR:-$HOME/.local/bin}"
  wrapper="$bin_dir/nanobot"
  mkdir -p "$bin_dir" || return 0

  if [ -e "$wrapper" ] && ! grep -q "Generated by nanobot installer" "$wrapper" 2>/dev/null; then
    info "Not updating $wrapper because it already exists."
    return 0
  fi

  nanobot_command="$(nanobot_try_command)"
  cat > "$wrapper" <<EOF
#!/bin/sh
# Generated by nanobot installer.
exec $nanobot_command "\$@"
EOF
  chmod +x "$wrapper" || return 0

  if ! command -v nanobot >/dev/null 2>&1; then
    info "Installed a nanobot launcher at $wrapper."
    info "Add $bin_dir to PATH to run nanobot directly."
  fi
}

install_with_managed_venv() {
  [ -n "${HOME:-}" ] || fail "HOME is not set; cannot create a managed virtual environment"

  venv_dir="${NANOBOT_VENV:-$HOME/.nanobot/venv}"
  venv_python="$venv_dir/bin/python"
  if [ ! -x "$venv_python" ]; then
    info "Creating a dedicated virtual environment at $venv_dir..."
    mkdir -p "$(dirname "$venv_dir")"
    # Persist selection before venv/pip work, so a failed first install can
    # resume as the same managed environment. This is not an installed claim.
    "$python_bin" -I - "$venv_dir" <<'PY' || return 1
import json, os, sys
from pathlib import Path
prefix = Path(sys.argv[1]).resolve()
if any((prefix / name).exists() for name in ('uv-receipt.toml', 'pipx_metadata.json')):
    raise SystemExit('This environment belongs to another package manager.')
prefix.mkdir(parents=True, exist_ok=True)
path = prefix / 'nanobot-install.json'
record = {'schema_version': 1, 'owner': 'nanobot-installer', 'environment': str(prefix), 'extras': []}
if path.is_symlink():
    raise SystemExit('The installation selection is invalid; no receipt was replaced.')
if path.exists():
    if path.stat().st_size > 4096 or json.loads(path.read_bytes()) != record:
        raise SystemExit('The installation selection changed; no receipt was replaced.')
else:
    with path.open('x', encoding='utf-8') as stream:
        json.dump(record, stream, sort_keys=True)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    path.chmod(0o600)
PY
    "$python_bin" -m venv "$venv_dir" || return 1
  fi

  "$venv_python" - <<'PY' >/dev/null 2>&1 || fail "The managed venv uses Python older than 3.11. Remove it or set NANOBOT_VENV to a new path."
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY

  info "Installing or upgrading nanobot from $install_source in $venv_dir..."
  ensure_pip "$venv_python" || return 1
  "$venv_python" -m pip install --upgrade "$install_target" || return 1

  select_installed_python "$venv_python" "$venv_dir"
  write_managed_wrapper
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --wheel|--sha256|--release|--manifest-sha256)
      [ "$#" -ge 2 ] || fail "$1 requires a value"
      case "$1" in --wheel|--sha256) wanted_kind="wheel" ;; *) wanted_kind="release" ;; esac
      [ -z "$release_kind" ] || [ "$release_kind" = "$wanted_kind" ] || fail "Choose --release or --wheel, not both"
      release_kind="$wanted_kind"
      case "$1" in
        --wheel) release_wheel="$2" ;;
        --sha256) release_sha256="$2" ;;
        --release) release_version="$2" ;;
        --manifest-sha256) manifest_sha256="$2" ;;
      esac
      shift
      ;;
    --dev)
      fail "--dev installed an untracked main snapshot and is no longer supported; clone the repository and run 'python -m pip install -e .' instead"
      ;;
    --dry-run)
      dry_run="1"
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail "Unknown option: $1"
      ;;
  esac
  shift
done

python_bin="${PYTHON:-}"

if [ -n "$python_bin" ]; then
  command -v "$python_bin" >/dev/null 2>&1 || fail "PYTHON=$python_bin was not found"
  "$python_bin" - <<'PY' >/dev/null 2>&1 || fail "nanobot requires Python 3.11 or newer"
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY
else
  python_bin="$(find_python)" || fail "Python 3.11 or newer was not found. Install Python first, then rerun this command."
fi

info "Using Python: $("$python_bin" --version 2>&1)"
select_install_method

if [ -n "$release_kind" ]; then
  if [ "$release_kind" = "release" ]; then
    [ -n "$release_version" ] && [ -n "$manifest_sha256" ] || fail "--release and --manifest-sha256 must be supplied together"
    [ -z "$release_wheel$release_sha256" ] || fail "Choose --release or --wheel, not both"
    [ -n "${HOME:-}" ] || fail "HOME is required to retain the downloaded release"
  else
    [ -n "$release_wheel" ] && [ -n "$release_sha256" ] || fail "--wheel and --sha256 must be supplied together"
  fi
  target_python="$python_bin"
  case "$install_method" in
    uv) [ ! -x "$uv_dir/$package/bin/python" ] || target_python="$uv_dir/$package/bin/python" ;;
    pipx) [ ! -x "$pipx_dir/$package/bin/python" ] || target_python="$pipx_dir/$package/bin/python" ;;
    managed)
      candidate_python="${NANOBOT_VENV:-${HOME:-}/.nanobot/venv}/bin/python"
      [ ! -x "$candidate_python" ] || target_python="$candidate_python"
      ;;
  esac
  owner_record="-"
  if [ "$install_method" = "pipx" ]; then owner_record="$pipx_dir/$package/pipx_metadata.json"; fi
  wheel_identity="$("$target_python" -I - "$release_wheel" "$release_sha256" "$owner_record" "$release_version" "$manifest_sha256" "${NANOBOT_RELEASE_CACHE:-${HOME:-}/.nanobot/downloads/releases}" "$dry_run" <<'PY'
import hashlib
import json
import re
import sys
from email.parser import BytesParser
from pathlib import Path
from zipfile import ZipFile

import os
import platform
import struct
import sysconfig
import tempfile
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

# Bootstrap has no installed nanobot/packaging dependency. This closed platform
# set matches the five published wheel tags; the owner still checks compatibility.
def native_platform():
    if struct.calcsize("P") != 8:
        raise SystemExit("No native release wheel is available for 32-bit Python")
    machine = platform.machine().lower()
    if sys.platform == "darwin":
        if int(platform.mac_ver()[0].split(".")[0]) < 13:
            raise SystemExit("The native release requires macOS 13 or newer")
        if machine in ("arm64", "x86_64"):
            return "macosx_13_0_" + machine
    elif sys.platform == "linux":
        try:
            libc = os.confstr("CS_GNU_LIBC_VERSION") or ""
        except (ValueError, OSError):
            libc = ""
        if not re.fullmatch(r"glibc \d+\.\d+", libc) or tuple(map(int, libc.split()[1].split("."))) < (2, 17):
            raise SystemExit("The native release requires glibc 2.17+; no musl wheel is published")
        if machine in ("aarch64", "x86_64"):
            return "manylinux_2_17_" + machine
    elif sys.platform == "win32" and sysconfig.get_platform() == "win-amd64":
        return "win_amd64"
    raise SystemExit("No native release wheel is published for this Python platform")

def checked_url(url):
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname not in
            {"github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"}
            or parsed.username is not None or parsed.password is not None
            or parsed.port not in (None, 443) or parsed.fragment):
        raise SystemExit("Release download redirected outside the approved HTTPS hosts")
    return url

class ReleaseRedirect(HTTPRedirectHandler):
    max_redirections = 4
    max_repeats = 1

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        checked_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)

def fetch_release(version, manifest_hash, cache, dry_run):
    number = r"(?:0|[1-9]\d*)"
    if not re.fullmatch(rf"{number}\.{number}\.{number}(?:\.dev{number}|\.post{number})?", version):
        raise SystemExit("Expected a canonical release version, not a branch or URL")
    if not re.fullmatch(r"[0-9a-f]{64}", manifest_hash):
        raise SystemExit("A trusted published manifest SHA-256 is required")
    selected_platform = native_platform()
    base = "https://github.com/HKUDS/nanobot/releases/download/v" + version + "/"
    opener = build_opener(ReleaseRedirect())
    with opener.open(Request(checked_url(base + "release-manifest.json"),
                             headers={"Accept-Encoding": "identity"}), timeout=20) as response:
        payload = response.read(64 * 1024 + 1)
    if len(payload) > 64 * 1024 or hashlib.sha256(payload).hexdigest() != manifest_hash:
        raise SystemExit("Release manifest size or SHA-256 mismatch")
    manifest = json.loads(payload)
    if (not isinstance(manifest, dict) or type(manifest.get("schema_version")) is not int
            or manifest["schema_version"] != 1 or manifest.get("version") != version
            or set(manifest) != {"schema_version", "version", "source_commit", "candidate_commit",
                                 "requires_python", "artifacts"}):
        raise SystemExit("Unsupported or mismatched release manifest")
    for key in ("source_commit", "candidate_commit"):
        if not isinstance(manifest[key], str) or not re.fullmatch(r"[0-9a-f]{40}", manifest[key]):
            raise SystemExit("Invalid release commit identity")
    if not isinstance(manifest["requires_python"], str) or not 0 < len(manifest["requires_python"]) <= 200:
        raise SystemExit("Invalid Python requirement in release manifest")
    targets = {"darwin-arm64": "macosx_13_0_arm64", "darwin-x64": "macosx_13_0_x86_64",
               "linux-arm64": "manylinux_2_17_aarch64", "linux-x64": "manylinux_2_17_x86_64",
               "win32-x64": "win_amd64"}
    expected = {f"nanobot_ai-{version}-py3-none-{tag}.whl" for tag in targets.values()}
    expected.add(f"nanobot_ai-{version}.tar.gz")
    for target in targets:
        name = "nanobot-tui-" + target + (".exe" if target == "win32-x64" else "") + ".zip"
        expected.update((name, name + ".sha256"))
    artifacts = manifest["artifacts"]
    if (not isinstance(artifacts, list) or len(artifacts) != 16
            or any(not isinstance(item, dict) or set(item) != {"filename", "size", "sha256"}
                   or not isinstance(item["filename"], str) or type(item["size"]) is not int
                   or not 0 < item["size"] <= 2 * 1024**3
                   or not isinstance(item["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"])
                   for item in artifacts)
            or {item["filename"] for item in artifacts} != expected):
        raise SystemExit("Release manifest does not contain the complete matching artifact set")
    filename = f"nanobot_ai-{version}-py3-none-{selected_platform}.whl"
    artifact = next(item for item in artifacts if item["filename"] == filename)
    if dry_run:
        print("nanobot-ai @ " + base + filename + "#sha256=" + artifact["sha256"] + "|" + version)
        raise SystemExit(0)
    directory = Path(cache).expanduser().absolute() / version / artifact["sha256"]
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination = directory / filename
    if destination.exists() or destination.is_symlink():
        if destination.is_symlink() or not destination.is_file() or destination.stat().st_size != artifact["size"]:
            raise SystemExit("Invalid cached release file; inspect the release download directory")
        return destination, artifact["sha256"]
    descriptor, name = tempfile.mkstemp(prefix=".download-", suffix=".part", dir=directory)
    temporary = Path(name)
    try:
        size = 0
        digest = hashlib.sha256()
        with os.fdopen(descriptor, "wb") as output:
            with opener.open(Request(checked_url(base + filename),
                                     headers={"Accept-Encoding": "identity"}), timeout=20) as response:
                while chunk := response.read(64 * 1024):
                    size += len(chunk)
                    if size > artifact["size"]:
                        raise SystemExit("Release wheel exceeds its verified size")
                    digest.update(chunk)
                    output.write(chunk)
        if size != artifact["size"] or digest.hexdigest() != artifact["sha256"]:
            raise SystemExit("Release wheel size or SHA-256 mismatch")
        try:
            os.link(temporary, destination)
        except FileExistsError:
            if destination.is_symlink() or not destination.is_file() or destination.stat().st_size != size:
                raise SystemExit("The cached release destination changed during download")
        return destination, artifact["sha256"]
    finally:
        temporary.unlink(missing_ok=True)

expected_hash = sys.argv[2]
if sys.argv[4] not in ("", "-"):
    path, expected_hash = fetch_release(sys.argv[4], sys.argv[5], sys.argv[6], sys.argv[7] == "1")
else:
    path = Path(sys.argv[1]).absolute()
match = re.fullmatch(r"nanobot_ai-(\d+\.\d+\.\d+(?:\.dev\d+|\.post\d+)?)-py3-none-(macosx_13_0_(?:arm64|x86_64)|manylinux_2_17_(?:aarch64|x86_64)|win_amd64)\.whl", path.name)
if not match or path.is_symlink() or not path.is_file() or not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
    raise SystemExit("Expected a saved native nanobot wheel and its published SHA-256")
with path.open("rb") as stream:
    if hashlib.file_digest(stream, "sha256").hexdigest() != expected_hash:
        raise SystemExit("Wheel SHA-256 mismatch; no package manager was started")
version = match[1]
with ZipFile(path) as wheel:
    metadata_path = f"nanobot_ai-{version}.dist-info/METADATA"
    if wheel.getinfo(metadata_path).file_size > 256 * 1024:
        raise SystemExit("Wheel metadata exceeds its size limit")
    metadata = BytesParser().parsebytes(wheel.read(metadata_path))
    if metadata["Name"] != "nanobot-ai" or metadata["Version"] != version:
        raise SystemExit("Wheel identity does not match its filename")
extras = []
record = Path(sys.argv[3])
if sys.argv[3] != "-" and record.is_file():
    if record.stat().st_size > 1024 * 1024:
        raise SystemExit("pipx installation record is too large; inspect it before updating")
    spec = json.loads(record.read_text(encoding="utf-8"))["main_package"]["package_or_url"]
    extra_match = re.match(r"(?i)^nanobot[-_.]ai\[([a-z0-9_., -]+)\]", spec)
    if extra_match:
        extras = sorted({re.sub(r"[-_.]+", "-", extra.strip().lower()) for extra in extra_match[1].split(",")})
        if any(not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", extra) for extra in extras):
            raise SystemExit("Cannot preserve pipx extras; review the installation manually")
    elif "[" in spec:
        raise SystemExit("Cannot preserve pipx extras; review the installation manually")
    provided = {re.sub(r"[-_.]+", "-", extra.lower()) for extra in metadata.get_all("Provides-Extra", [])}
    if not set(extras) <= provided:
        raise SystemExit("The target wheel does not provide all existing pipx extras")
requirement = "nanobot-ai" + ("[" + ",".join(extras) + "]" if extras else "")
print(requirement + " @ " + path.as_uri() + "|" + version)
PY
  )" || fail "Release verification failed; no installation was attempted."
  install_target="${wheel_identity%|*}"
  expected_version="${wheel_identity##*|}"
  install_source="verified wheel $expected_version"
  if [ "$release_kind" = "release" ] && [ "$dry_run" = "1" ]; then
    info "Selected nanobot $expected_version from verified release metadata; its wheel was not downloaded."
  else
    info "Verified nanobot $expected_version. Keep the downloaded wheel at its current path."
  fi
fi

if [ "$dry_run" = "1" ]; then
  info "Dry run: would install or upgrade nanobot from $install_source."
  if [ "$install_method" = "python" ]; then
    info "Dry run: active virtual environment detected; would run: $python_bin -m pip install --upgrade $install_target"
    info "Dry run: would start nanobot with this environment's Python in isolated mode."
  elif [ "$install_method" = "uv" ]; then
    info "Dry run: would install with uv tool install, or use uv tool upgrade for an existing installation."
    info "Dry run: would start nanobot from its persistent uv tool environment."
  elif [ "$install_method" = "pipx" ]; then
    info "Dry run: would review pipx installation settings before upgrading an existing environment."
    info "Dry run: would start nanobot from its persistent pipx environment."
  else
    venv_dir="${NANOBOT_VENV:-$HOME/.nanobot/venv}"
    info "Dry run: would create or reuse a dedicated virtual environment: $venv_dir"
    info "Dry run: would run: $venv_dir/bin/python -m pip install --upgrade $install_target"
    info "Dry run: would start nanobot with $venv_dir/bin/python in isolated mode."
  fi
  if [ "${NANOBOT_SKIP_WIZARD:-}" = "1" ]; then
    info "Dry run: would skip automatic setup because NANOBOT_SKIP_WIZARD=1."
  elif is_fresh_nanobot_install && has_browser_session; then
    info "Dry run: would start the WebUI for this fresh desktop install."
    info "Dry run: would fall back to the setup wizard for older releases."
  else
    info "Dry run: would run the setup wizard."
  fi
  info "Dry run: no changes made."
  exit 0
fi

if [ "$install_method" = "python" ]; then
  install_with_active_python || install_failure_hint
elif [ "$install_method" = "uv" ]; then
  install_with_uv
elif [ "$install_method" = "pipx" ]; then
  install_with_pipx
else
  info "Using a dedicated virtual environment to avoid system pip."
  install_with_managed_venv || install_failure_hint
fi

info "Installed nanobot:"
run_nanobot --version

if [ "${NANOBOT_SKIP_WIZARD:-}" = "1" ]; then
  info "Skipping automatic setup because NANOBOT_SKIP_WIZARD=1."
  info "Run this later: $(nanobot_try_command) webui"
  exit 0
fi

if is_fresh_nanobot_install && has_browser_session; then
  if run_nanobot webui --help >/dev/null 2>&1; then
    info "Starting nanobot WebUI..."
    info "Configure your first provider and model in Settings > Models."
    info "Run this later: $(nanobot_try_command) webui"
    run_nanobot webui --yes
    exit 0
  fi
  info "The installed release does not support nanobot webui yet."
  info "Falling back to the setup wizard..."
fi

if [ -t 0 ]; then
  info "Starting setup wizard..."
  run_nanobot onboard --wizard
elif : 2>/dev/null < /dev/tty; then
  info "Starting setup wizard..."
  run_nanobot onboard --wizard < /dev/tty
else
  info "Skipping setup wizard because no interactive terminal is available."
  info "Run this later: $(nanobot_try_command) onboard --wizard"
fi

info "Done. Try: $(nanobot_try_command) agent -m \"Hello!\""
