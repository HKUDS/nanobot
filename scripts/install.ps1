param(
    [switch]$Dev,
    [switch]$DryRun,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$RemainingArgs
)

$ErrorActionPreference = "Stop"

$Package = "nanobot-ai"
$MainSource = "https://github.com/HKUDS/nanobot/archive/refs/heads/main.zip"
$InstallTarget = $Package
$InstallSource = "PyPI"

function Write-Info {
    param([string]$Message)
    Write-Host $Message
}

function Fail {
    param([string]$Message)
    throw "Error: $Message"
}

function Show-InstallFailureHint {
    [Console]::Error.WriteLine("Error: pip could not install nanobot from $InstallSource.")
    [Console]::Error.WriteLine("If pip mentioned externally-managed-environment, install in a virtual environment or use uv/pipx.")
    [Console]::Error.WriteLine("You can also run manually:")
    [Console]::Error.WriteLine("  $Python -m pip install --upgrade $InstallTarget")
    [Console]::Error.WriteLine("Then start setup with:")
    [Console]::Error.WriteLine("  $Python -m nanobot onboard --wizard")
    throw "pip could not install nanobot from $InstallSource"
}

function Show-Usage {
    Write-Host "Usage: install.ps1 [-Dev|--dev] [-DryRun|--dry-run]"
    Write-Host ""
    Write-Host "By default this installs or upgrades nanobot-ai from PyPI."
    Write-Host "Use --dev to install from the current main branch on GitHub."
    Write-Host "Use --dry-run to print what would happen without installing or starting the wizard."
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
        if (Get-Command $env:PYTHON -ErrorAction SilentlyContinue) {
            if (Test-Python $env:PYTHON) {
                return $env:PYTHON
            }
            Fail "PYTHON=$env:PYTHON is not Python 3.11 or newer."
        }
        Fail "PYTHON=$env:PYTHON was not found."
    }

    foreach ($Candidate in @("python", "py")) {
        if (Get-Command $Candidate -ErrorAction SilentlyContinue) {
            if (Test-Python $Candidate) {
                return $Candidate
            }
        }
    }

    Fail "Python 3.11 or newer was not found. Install Python first, then rerun this command."
}

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
    $InstallTarget = $MainSource
    $InstallSource = "GitHub main"
}

$Python = Find-Python
$Version = & $Python --version
Write-Info "Using Python: $Version"

try {
    & $Python -m pip --version *> $null
} catch {}

if ($LASTEXITCODE -ne 0) {
    if ($DryRun) {
        Write-Info "Dry run: pip was not found. Install would try: $Python -m ensurepip --upgrade"
    } else {
        Write-Info "pip was not found for this Python. Trying ensurepip..."
        & $Python -m ensurepip --upgrade *> $null
        if ($LASTEXITCODE -ne 0) {
            Fail "pip is not available. Install pip for $Python, then rerun this command."
        }
    }
}

if ($DryRun) {
    Write-Info "Dry run: would install or upgrade nanobot from $InstallSource."
    Write-Info "Dry run: would run: $Python -m pip install --upgrade $InstallTarget"
    Write-Info "Dry run: if that fails because system site-packages are not writable, would retry: $Python -m pip install --user --upgrade $InstallTarget"
    if ($env:NANOBOT_SKIP_WIZARD -eq "1") {
        Write-Info "Dry run: would skip setup wizard because NANOBOT_SKIP_WIZARD=1."
    } else {
        Write-Info "Dry run: would run: $Python -m nanobot onboard --wizard"
    }
    Write-Info "Dry run: no changes made."
    return
}

Write-Info "Installing or upgrading nanobot from $InstallSource..."
& $Python -m pip install --upgrade $InstallTarget
if ($LASTEXITCODE -ne 0) {
    Write-Info "Install failed. Retrying as a user install..."
    & $Python -m pip install --user --upgrade $InstallTarget
    if ($LASTEXITCODE -ne 0) {
        Show-InstallFailureHint
    }
}

Write-Info "Installed nanobot:"
& $Python -m nanobot --version
if ($LASTEXITCODE -ne 0) {
    Fail "nanobot was installed, but the command could not be started."
}

if ($env:NANOBOT_SKIP_WIZARD -eq "1") {
    Write-Info "Skipping setup wizard because NANOBOT_SKIP_WIZARD=1."
    Write-Info "Run this later: $Python -m nanobot onboard --wizard"
    return
}

Write-Info "Starting setup wizard..."
& $Python -m nanobot onboard --wizard
if ($LASTEXITCODE -ne 0) {
    Fail "Setup wizard did not complete."
}

Write-Info "Done. Try: $Python -m nanobot agent -m `"Hello!`""
