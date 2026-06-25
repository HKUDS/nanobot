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
$script:NanobotRunner = $null
$script:NanobotPython = $null
$script:LastInstallSucceeded = $false

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

function Test-VirtualEnv {
    param([string]$Command)
    try {
        & $Command -c "import sys; raise SystemExit(0 if sys.prefix != sys.base_prefix else 1)" *> $null
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    }
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

function Invoke-Nanobot {
    param([string[]]$NanobotArgs)

    switch ($script:NanobotRunner) {
        "uv" {
            & uv tool run --from $InstallTarget nanobot @NanobotArgs
        }
        "pipx" {
            & pipx run --spec $InstallTarget nanobot @NanobotArgs
        }
        "python" {
            & $script:NanobotPython -m nanobot @NanobotArgs
        }
        default {
            Fail "nanobot was installed, but no runner was configured."
        }
    }
}

function Get-NanobotCommand {
    switch ($script:NanobotRunner) {
        "uv" { return "uv tool run --from $InstallTarget nanobot" }
        "pipx" { return "pipx run --spec $InstallTarget nanobot" }
        "python" { return "$script:NanobotPython -m nanobot" }
        default { return "nanobot" }
    }
}

function Install-WithActivePython {
    Write-Info "Detected an active virtual environment. Installing into it..."
    Ensure-Pip $Python
    & $Python -m pip install --upgrade $InstallTarget
    if ($LASTEXITCODE -ne 0) {
        Show-InstallFailureHint
    }
    $script:NanobotRunner = "python"
    $script:NanobotPython = $Python
}

function Install-WithUv {
    $script:LastInstallSucceeded = $false
    Write-Info "Installing or upgrading nanobot from $InstallSource with uv tool..."
    & uv tool install --python $Python --force --upgrade $InstallTarget
    if ($LASTEXITCODE -ne 0) {
        return
    }
    $script:NanobotRunner = "uv"
    $script:LastInstallSucceeded = $true
}

function Install-WithPipx {
    $script:LastInstallSucceeded = $false
    Write-Info "Installing or upgrading nanobot from $InstallSource with pipx..."
    & pipx install --python $Python --force $InstallTarget
    if ($LASTEXITCODE -ne 0) {
        return
    }
    $script:NanobotRunner = "pipx"
    $script:LastInstallSucceeded = $true
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

    $script:NanobotRunner = "python"
    $script:NanobotPython = $VenvPython
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

if ($DryRun) {
    Write-Info "Dry run: would install or upgrade nanobot from $InstallSource."
    if (Test-VirtualEnv $Python) {
        Write-Info "Dry run: active virtual environment detected; would run: $Python -m pip install --upgrade $InstallTarget"
        Write-Info "Dry run: would run nanobot as: $Python -m nanobot"
    } elseif (Get-Command uv -ErrorAction SilentlyContinue) {
        Write-Info "Dry run: would run: uv tool install --python $Python --force --upgrade $InstallTarget"
        Write-Info "Dry run: would run nanobot as: uv tool run --from $InstallTarget nanobot"
    } elseif (Get-Command pipx -ErrorAction SilentlyContinue) {
        Write-Info "Dry run: would run: pipx install --python $Python --force $InstallTarget"
        Write-Info "Dry run: would run nanobot as: pipx run --spec $InstallTarget nanobot"
    } else {
        $HomeDir = if ($env:HOME) { $env:HOME } elseif ($env:USERPROFILE) { $env:USERPROFILE } else { "~" }
        $VenvDir = if ($env:NANOBOT_VENV) { $env:NANOBOT_VENV } else { Join-Path $HomeDir ".nanobot\venv" }
        Write-Info "Dry run: would create or reuse a dedicated virtual environment: $VenvDir"
        Write-Info "Dry run: would run: $VenvDir\Scripts\python.exe -m pip install --upgrade $InstallTarget"
        Write-Info "Dry run: would run nanobot as: $VenvDir\Scripts\python.exe -m nanobot"
    }
    if ($env:NANOBOT_SKIP_WIZARD -eq "1") {
        Write-Info "Dry run: would skip setup wizard because NANOBOT_SKIP_WIZARD=1."
    } else {
        Write-Info "Dry run: would run the setup wizard."
    }
    Write-Info "Dry run: no changes made."
    return
}

if (Test-VirtualEnv $Python) {
    Install-WithActivePython
} else {
    $Installed = $false

    if (Get-Command uv -ErrorAction SilentlyContinue) {
        Install-WithUv
        $Installed = $script:LastInstallSucceeded
        if (-not $Installed) {
            Write-Info "uv tool install failed. Trying the next isolated install method..."
        }
    }

    if (-not $Installed -and (Get-Command pipx -ErrorAction SilentlyContinue)) {
        Install-WithPipx
        $Installed = $script:LastInstallSucceeded
        if (-not $Installed) {
            Write-Info "pipx install failed. Trying the managed virtual environment..."
        }
    }

    if (-not $Installed) {
        Write-Info "Using a dedicated virtual environment to avoid system pip."
        Install-WithManagedVenv
    }
}

Write-Info "Installed nanobot:"
Invoke-Nanobot @("--version")
if ($LASTEXITCODE -ne 0) {
    Fail "nanobot was installed, but the command could not be started."
}

if ($env:NANOBOT_SKIP_WIZARD -eq "1") {
    Write-Info "Skipping setup wizard because NANOBOT_SKIP_WIZARD=1."
    Write-Info "Run this later: $(Get-NanobotCommand) onboard --wizard"
    return
}

Write-Info "Starting setup wizard..."
Invoke-Nanobot @("onboard", "--wizard")
if ($LASTEXITCODE -ne 0) {
    Fail "Setup wizard did not complete."
}

Write-Info "Done. Try: $(Get-NanobotCommand) agent -m `"Hello!`""
