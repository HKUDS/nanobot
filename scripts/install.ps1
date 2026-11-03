param(
    [switch]$Dev,
    [switch]$DryRun,
    [string]$Wheel,
    [string]$Sha256,
    [string]$Release,
    [string]$ManifestSha256,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$RemainingArgs
)

$ErrorActionPreference = "Stop"

$Package = "nanobot-ai"
$InstallTarget = $Package
$InstallSource = "PyPI"
$script:NanobotPython = $null
$ExpectedVersion = ""

function Write-Info {
    param([string]$Message)
    Write-Host $Message
}

function Fail {
    param([string]$Message)
    throw "Error: $Message"
}

function Show-InstallFailureHint {
    [Console]::Error.WriteLine("Error: could not install nanobot from $InstallSource.")
    if ($ExpectedVersion) {
        Fail "Inspect the original manager error and retry this exact handoff. No setup or other installation was attempted."
    }
    [Console]::Error.WriteLine("If pip mentioned externally-managed-environment, use uv, pipx, or a virtual environment instead of system pip.")
    [Console]::Error.WriteLine("You can also run manually:")
    [Console]::Error.WriteLine("  uv tool install --force --upgrade $InstallTarget")
    [Console]::Error.WriteLine("  $Python -m venv `$HOME\.nanobot\venv")
    [Console]::Error.WriteLine("  `$HOME\.nanobot\venv\Scripts\python.exe -m pip install --upgrade $InstallTarget")
    [Console]::Error.WriteLine("Then start setup with:")
    [Console]::Error.WriteLine("  nanobot onboard --wizard")
    throw "could not install nanobot from $InstallSource"
}

function Show-Usage {
    Write-Host "Usage: install.ps1 [-DryRun|--dry-run] [-Wheel PATH -Sha256 HASH]"
    Write-Host "       install.ps1 [-DryRun|--dry-run] -Release VERSION -ManifestSha256 HASH"
    Write-Host ""
    Write-Host "By default this installs or upgrades nanobot-ai from PyPI."
    Write-Host "Use --dry-run to print what would happen without installing or starting setup."
    Write-Host "Use -Wheel and -Sha256 together for a verified release handoff; retain the downloaded wheel."
    Write-Host "Stop affected gateways and back up their data before updating an existing install."
    Write-Host "-Release downloads the matching official wheel; it is one version, not a Preview subscription."
    Write-Host ""
    Write-Host "For current main, clone the repository and run 'python -m pip install -e .'."
}

function Test-AvailableCommand {
    param([string]$Name)
    # Get-Command can import modules for missing tools, even with an application filter.
    # Enumerate session/PATH commands instead, retaining existing functions and aliases.
    foreach ($Command in $ExecutionContext.InvokeCommand.GetCommands(
        $Name, [System.Management.Automation.CommandTypes]::All, $false)) {
        return $true
    }
    return $false
}

function Test-Python {
    param([string]$Command)
    try {
        & $Command -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" *> $null
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    }
}

function Find-Python {
    if ($env:PYTHON) {
        if (Test-AvailableCommand $env:PYTHON) {
            if (Test-Python $env:PYTHON) {
                return $env:PYTHON
            }
            Fail "PYTHON=$env:PYTHON is not Python 3.11 or newer."
        }
        Fail "PYTHON=$env:PYTHON was not found."
    }

    foreach ($Candidate in @("python", "py")) {
        if (Test-AvailableCommand $Candidate) {
            if (Test-Python $Candidate) {
                return $Candidate
            }
        }
    }

    Fail "Python 3.11 or newer was not found. Install Python first, then rerun this command."
}

function Test-VirtualEnv {
    param([string]$Command)
    try {
        & $Command -c "import sys; raise SystemExit(0 if sys.prefix != sys.base_prefix else 1)" *> $null
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    }
}

function Get-InstallMethod {
    if (Test-VirtualEnv $Python) {
        $ActivePrefix = & $Python -I -c "import json, sys; print(json.dumps(sys.prefix))" | ConvertFrom-Json
        if ((Test-Path -LiteralPath (Join-Path $ActivePrefix "uv-receipt.toml")) -or
            (Test-Path -LiteralPath (Join-Path $ActivePrefix "pipx_metadata.json"))) {
            Fail "The active Python belongs to uv or pipx. Deactivate it and rerun this installer so its manager owns the update."
        }
        return "python"
    }

    $Existing = @()
    if (Test-AvailableCommand uv) {
        $ToolDir = & uv tool dir
        if ($LASTEXITCODE -ne 0 -or -not $ToolDir) { Fail "Could not inspect the uv tools directory." }
        if (Test-Path -LiteralPath (Join-Path $ToolDir $Package)) { $Existing += "uv" }
    }
    if (Test-AvailableCommand pipx) {
        $ToolDir = & pipx environment --value PIPX_LOCAL_VENVS
        if ($LASTEXITCODE -ne 0 -or -not $ToolDir) { Fail "Could not inspect the pipx environments directory." }
        if (Test-Path -LiteralPath (Join-Path $ToolDir $Package)) { $Existing += "pipx" }
    }
    $ProfileDir = if ($env:HOME) { $env:HOME } else { $env:USERPROFILE }
    if ($env:NANOBOT_VENV -or $ProfileDir) {
        $Environment = if ($env:NANOBOT_VENV) { $env:NANOBOT_VENV } else { Join-Path $ProfileDir ".nanobot\venv" }
        if (Test-Path -LiteralPath (Join-Path $Environment "pyvenv.cfg")) { $Existing += "managed" }
    }
    if ($Existing.Count -gt 1) {
        Fail "Multiple nanobot installations were found. Use the intended environment's package manager; this installer changed none of them."
    }
    if ($Existing.Count -eq 1) { return $Existing[0] }
    return "managed"
}

function Ensure-Pip {
    param([string]$Command)

    try {
        & $Command -m pip --version *> $null
    } catch {}

    if ($LASTEXITCODE -eq 0) {
        return
    }

    Write-Info "pip was not found for $Command. Trying ensurepip..."
    & $Command -m ensurepip --upgrade *> $null
    if ($LASTEXITCODE -ne 0) {
        Fail "pip is not available. Install pip for $Command, then rerun this command."
    }
}

function Select-InstalledPython {
    param([string]$Command, [string]$ExpectedEnvironment = "")

    $Probe = @'
import json
import sys
from importlib.metadata import distribution
from pathlib import Path

import nanobot

prefix = Path(sys.prefix).resolve()
package = Path(nanobot.__file__).resolve()
expected = sys.argv[1] if len(sys.argv) > 1 else ""
if sys.prefix == sys.base_prefix or (expected not in ("", "-") and prefix != Path(expected).resolve()):
    raise SystemExit("The installed interpreter does not belong to the expected virtual environment")
if not package.is_relative_to(prefix) or package != Path(distribution("nanobot-ai").locate_file("nanobot/__init__.py")).resolve():
    raise SystemExit("nanobot imports from outside the installed package")
if len(sys.argv) > 2 and sys.argv[2] and distribution("nanobot-ai").version != sys.argv[2]:
    raise SystemExit("The requested version was not installed. Check manager pins or locks; no setup was started.")
print(json.dumps(str(Path(sys.executable).absolute())))
'@
    # Do not resolve the interpreter symlink or launch a new pipx/uv run environment.
    # Send code on stdin so Windows PowerShell preserves its embedded quotes.
    $ExpectedRoot = if ($ExpectedEnvironment) { $ExpectedEnvironment } else { "-" }
    $Result = $Probe | & $Command -I - $ExpectedRoot $ExpectedVersion
    if ($LASTEXITCODE -ne 0 -or -not $Result) {
        Fail "The installed nanobot environment could not be verified. No setup or other installation was attempted."
    }
    $script:NanobotPython = [string]($Result | ConvertFrom-Json)
}

function Invoke-Nanobot {
    param([string[]]$NanobotArgs)
    & $script:NanobotPython -I -m nanobot @NanobotArgs
}

function Get-NanobotCommand {
    return "& '" + $script:NanobotPython.Replace("'", "''") + "' -I -m nanobot"
}

function Test-FreshNanobotInstall {
    $HomeDir = [Environment]::GetFolderPath([Environment+SpecialFolder]::UserProfile)
    if (-not $HomeDir) {
        return $false
    }
    return -not (Test-Path -LiteralPath (Join-Path $HomeDir ".nanobot\config.json"))
}

function Test-BrowserSession {
    if ($env:SSH_CONNECTION -or $env:SSH_TTY -or -not [Environment]::UserInteractive) {
        return $false
    }

    $CurrentSessionId = (Get-Process -Id $PID).SessionId
    return @(
        Get-Process -Name explorer -ErrorAction SilentlyContinue |
            Where-Object { $_.SessionId -eq $CurrentSessionId }
    ).Count -gt 0
}

function Install-WithActivePython {
    Write-Info "Detected an active virtual environment. Installing into it..."
    Ensure-Pip $Python
    & $Python -m pip install --upgrade $InstallTarget
    if ($LASTEXITCODE -ne 0) {
        Show-InstallFailureHint
    }
    Select-InstalledPython $Python
}

function Install-WithUv {
    Write-Info "Installing or upgrading nanobot from $InstallSource with uv tool..."
    $ToolDir = & uv tool dir
    if ($LASTEXITCODE -ne 0 -or -not $ToolDir) {
        Fail "Could not locate the uv tools directory."
    }
    $Environment = Join-Path $ToolDir $Package
    if (Test-Path -LiteralPath (Join-Path $Environment "uv-receipt.toml")) {
        & uv tool upgrade $InstallTarget
    } elseif (Test-Path -LiteralPath $Environment) {
        Fail "The uv environment exists without its installation record. Repair it with uv before rerunning this installer."
    } else {
        & uv tool install --python $Python $InstallTarget
    }
    if ($LASTEXITCODE -ne 0) {
        Fail "uv could not install or upgrade nanobot. Resolve the error above and retry; no other installation was attempted."
    }
    Select-InstalledPython (Join-Path $Environment "Scripts\python.exe") $Environment
}

function Install-WithPipx {
    Write-Info "Installing or upgrading nanobot from $InstallSource with pipx..."
    $ToolDir = & pipx environment --value PIPX_LOCAL_VENVS
    if ($LASTEXITCODE -ne 0 -or -not $ToolDir) {
        Fail "Could not locate the pipx environments directory."
    }
    $Environment = Join-Path $ToolDir $Package
    if (Test-Path -LiteralPath (Join-Path $Environment "pipx_metadata.json")) {
        $Inspect = @'
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
    allowed = re.fullmatch(name, spec) or (sys.argv[2] != "-" and re.fullmatch(name + r"\s*@\s*\S+\.whl", spec))
    if record["pipx_metadata_version"] not in {"0.5", "0.12"} or not allowed or main.get("pip_args") or main.get("lock_file"):
        raise ValueError
except (OSError, ValueError, KeyError, TypeError):
    raise SystemExit("Cannot safely reuse pipx installation settings; inspect the original requirement and options.") from None
'@
        $Exact = if ($ExpectedVersion) { $ExpectedVersion } else { "-" }
        $Inspect | & $Python -I - (Join-Path $Environment "pipx_metadata.json") $Exact
        if ($LASTEXITCODE -ne 0) { Fail "Review the original pipx installation settings; no installation was attempted." }
        if ($ExpectedVersion) {
            & pipx install --skip-maintenance --upgrade $InstallTarget
        } else {
            & pipx upgrade $Package
        }
    } elseif (Test-Path -LiteralPath $Environment) {
        Fail "The pipx environment exists without its installation record. Repair it with pipx before rerunning this installer."
    } else {
        & pipx install --python $Python $InstallTarget
    }
    if ($LASTEXITCODE -ne 0) {
        Fail "pipx could not install or upgrade nanobot. Resolve the error above and retry; no other installation was attempted."
    }
    Select-InstalledPython (Join-Path $Environment "Scripts\python.exe") $Environment
}

function Install-WithManagedVenv {
    $HomeDir = if ($env:HOME) { $env:HOME } elseif ($env:USERPROFILE) { $env:USERPROFILE } else { $null }
    if (-not $HomeDir) {
        Fail "HOME is not set; cannot create a managed virtual environment."
    }

    $VenvDir = if ($env:NANOBOT_VENV) { $env:NANOBOT_VENV } else { Join-Path $HomeDir ".nanobot\venv" }
    $VenvPython = Join-Path $VenvDir "Scripts\python.exe"
    if (-not (Test-Path $VenvPython)) {
        Write-Info "Creating a dedicated virtual environment at $VenvDir..."
        $Parent = Split-Path -Parent $VenvDir
        if ($Parent) {
            New-Item -ItemType Directory -Force -Path $Parent *> $null
        }
        # Selection survives a failed first venv/pip operation. It is not an
        # installed/readiness claim, nor adoption of an existing environment.
        $RecordSelection = @'
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
'@
        & $Python -I -c $RecordSelection $VenvDir
        if ($LASTEXITCODE -ne 0) { Fail "Could not record the new installation's update settings." }
        & $Python -m venv $VenvDir
        if ($LASTEXITCODE -ne 0) {
            Show-InstallFailureHint
        }
    }

    if (-not (Test-Python $VenvPython)) {
        Fail "The managed venv uses Python older than 3.11. Remove it or set NANOBOT_VENV to a new path."
    }

    Write-Info "Installing or upgrading nanobot from $InstallSource in $VenvDir..."
    Ensure-Pip $VenvPython
    & $VenvPython -m pip install --upgrade $InstallTarget
    if ($LASTEXITCODE -ne 0) {
        Show-InstallFailureHint
    }

    Select-InstalledPython $VenvPython $VenvDir
}

$PreviousOutputEncoding = [Console]::OutputEncoding
try {
# uv/pipx emit UTF-8 paths; Windows PowerShell otherwise uses the console code page.
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)

foreach ($Arg in $RemainingArgs) {
    switch ($Arg) {
        "--dev" {
            $Dev = $true
        }
        "--dry-run" {
            $DryRun = $true
        }
        "-h" {
            Show-Usage
            return
        }
        "--help" {
            Show-Usage
            return
        }
        default {
            Fail "Unknown option: $Arg"
        }
    }
}

if ($Dev) {
    Fail "--dev installed an untracked main snapshot and is no longer supported; clone the repository and run 'python -m pip install -e .' instead."
}

$Python = Find-Python
$Version = & $Python --version
Write-Info "Using Python: $Version"
$InstallMethod = Get-InstallMethod

if ($PSBoundParameters.ContainsKey("Wheel") -or $PSBoundParameters.ContainsKey("Sha256") -or
    $PSBoundParameters.ContainsKey("Release") -or $PSBoundParameters.ContainsKey("ManifestSha256")) {
    if ($PSBoundParameters.ContainsKey("Release") -or $PSBoundParameters.ContainsKey("ManifestSha256")) {
        if (-not $Release -or -not $ManifestSha256) { Fail "-Release and -ManifestSha256 must be supplied together." }
        if ($PSBoundParameters.ContainsKey("Wheel") -or $PSBoundParameters.ContainsKey("Sha256")) { Fail "Choose -Release or -Wheel, not both." }
    } elseif (-not $Wheel -or -not $Sha256) { Fail "-Wheel and -Sha256 must be supplied together." }
    $TargetPython = $Python
    $ToolEnvironment = ""
    if ($InstallMethod -eq "uv") {
        $ToolDir = & uv tool dir
        if ($LASTEXITCODE -ne 0 -or -not $ToolDir) { Fail "Could not inspect the uv tools directory." }
        $ToolEnvironment = Join-Path $ToolDir $Package
    } elseif ($InstallMethod -eq "pipx") {
        $ToolDir = & pipx environment --value PIPX_LOCAL_VENVS
        if ($LASTEXITCODE -ne 0 -or -not $ToolDir) { Fail "Could not inspect the pipx environments directory." }
        $ToolEnvironment = Join-Path $ToolDir $Package
    } elseif ($InstallMethod -eq "managed") {
        $ProfileDir = if ($env:HOME) { $env:HOME } else { $env:USERPROFILE }
        if (-not $ProfileDir) { Fail "A home directory is required to retain the downloaded release." }
        $ToolEnvironment = if ($env:NANOBOT_VENV) { $env:NANOBOT_VENV } else { Join-Path $ProfileDir ".nanobot\venv" }
    }
    if ($ToolEnvironment) {
        $CandidatePython = Join-Path $ToolEnvironment "Scripts\python.exe"
        if (Test-Path -LiteralPath $CandidatePython) { $TargetPython = $CandidatePython }
    }
    $ProfileDir = if ($env:HOME) { $env:HOME } else { $env:USERPROFILE }
    $ReleaseCache = if ($env:NANOBOT_RELEASE_CACHE) { $env:NANOBOT_RELEASE_CACHE } elseif ($ProfileDir) { Join-Path $ProfileDir ".nanobot\downloads\releases" } else { "-" }
    if ($Release -and $ReleaseCache -eq "-") { Fail "A home directory is required to retain the downloaded release." }
    $OwnerRecord = "-"
    if ($InstallMethod -eq "pipx") {
        $PipxDir = & pipx environment --value PIPX_LOCAL_VENVS
        if ($LASTEXITCODE -ne 0 -or -not $PipxDir) { Fail "Could not inspect the pipx environments directory." }
        $OwnerRecord = Join-Path (Join-Path $PipxDir $Package) "pipx_metadata.json"
    }
    $Verify = @'
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
'@
    # Nonempty sentinels keep positional arguments intact on Windows PowerShell 5.1.
    $WheelArg = if ($Wheel) { $Wheel } else { "-" }
    $HashArg = if ($Sha256) { $Sha256 } else { "-" }
    $ReleaseArg = if ($Release) { $Release } else { "-" }
    $ManifestHashArg = if ($ManifestSha256) { $ManifestSha256 } else { "-" }
    $DryRunArg = if ($DryRun) { "1" } else { "0" }
    $WheelIdentity = $Verify | & $TargetPython -I - $WheelArg $HashArg $OwnerRecord $ReleaseArg $ManifestHashArg $ReleaseCache $DryRunArg
    if ($LASTEXITCODE -ne 0 -or -not $WheelIdentity) { Fail "Release verification failed; no installation was attempted." }
    $InstallTarget, $ExpectedVersion = $WheelIdentity -split '\|', 2
    $InstallSource = "verified wheel $ExpectedVersion"
    if ($Release -and $DryRun) {
        Write-Info "Selected nanobot $ExpectedVersion from verified release metadata; its wheel was not downloaded."
    } else {
        Write-Info "Verified nanobot $ExpectedVersion. Keep the downloaded wheel at its current path."
    }
}

if ($DryRun) {
    Write-Info "Dry run: would install or upgrade nanobot from $InstallSource."
    if ($InstallMethod -eq "python") {
        Write-Info "Dry run: active virtual environment detected; would run: $Python -m pip install --upgrade $InstallTarget"
        Write-Info "Dry run: would start nanobot with this environment's Python in isolated mode."
    } elseif ($InstallMethod -eq "uv") {
        Write-Info "Dry run: would install with uv tool install, or use uv tool upgrade for an existing installation."
        Write-Info "Dry run: would start nanobot from its persistent uv tool environment."
    } elseif ($InstallMethod -eq "pipx") {
        Write-Info "Dry run: would review pipx installation settings before upgrading an existing environment."
        Write-Info "Dry run: would start nanobot from its persistent pipx environment."
    } else {
        $HomeDir = if ($env:HOME) { $env:HOME } elseif ($env:USERPROFILE) { $env:USERPROFILE } else { "~" }
        $VenvDir = if ($env:NANOBOT_VENV) { $env:NANOBOT_VENV } else { Join-Path $HomeDir ".nanobot\venv" }
        Write-Info "Dry run: would create or reuse a dedicated virtual environment: $VenvDir"
        Write-Info "Dry run: would run: $VenvDir\Scripts\python.exe -m pip install --upgrade $InstallTarget"
        Write-Info "Dry run: would start nanobot with $VenvDir\Scripts\python.exe in isolated mode."
    }
    if ($env:NANOBOT_SKIP_WIZARD -eq "1") {
        Write-Info "Dry run: would skip automatic setup because NANOBOT_SKIP_WIZARD=1."
    } elseif ((Test-FreshNanobotInstall) -and (Test-BrowserSession)) {
        Write-Info "Dry run: would start the WebUI for this fresh desktop install."
        Write-Info "Dry run: would fall back to the setup wizard for older releases."
    } else {
        Write-Info "Dry run: would run the setup wizard."
    }
    Write-Info "Dry run: no changes made."
    return
}

if ($InstallMethod -eq "python") {
    Install-WithActivePython
} elseif ($InstallMethod -eq "uv") {
    Install-WithUv
} elseif ($InstallMethod -eq "pipx") {
    Install-WithPipx
} else {
    Write-Info "Using a dedicated virtual environment to avoid system pip."
    Install-WithManagedVenv
}

Write-Info "Installed nanobot:"
Invoke-Nanobot @("--version")
if ($LASTEXITCODE -ne 0) {
    Fail "nanobot was installed, but the command could not be started."
}

if ($env:NANOBOT_SKIP_WIZARD -eq "1") {
    Write-Info "Skipping automatic setup because NANOBOT_SKIP_WIZARD=1."
    Write-Info "Run this later: $(Get-NanobotCommand) webui"
    return
}

if ((Test-FreshNanobotInstall) -and (Test-BrowserSession)) {
    Invoke-Nanobot @("webui", "--help") *> $null
    if ($LASTEXITCODE -eq 0) {
        Write-Info "Starting nanobot WebUI..."
        Write-Info "Configure your first provider and model in Settings > Models."
        Write-Info "Run this later: $(Get-NanobotCommand) webui"
        Invoke-Nanobot @("webui", "--yes")
        if ($LASTEXITCODE -ne 0) {
            Fail "WebUI did not start."
        }
        return
    }
    Write-Info "The installed release does not support nanobot webui yet."
    Write-Info "Falling back to the setup wizard..."
}

Write-Info "Starting setup wizard..."
Invoke-Nanobot @("onboard", "--wizard")
if ($LASTEXITCODE -ne 0) {
    Fail "Setup wizard did not complete."
}

Write-Info "Done. Try: $(Get-NanobotCommand) agent -m `"Hello!`""
} finally {
    [Console]::OutputEncoding = $PreviousOutputEncoding
}
