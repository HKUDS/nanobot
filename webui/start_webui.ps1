$ErrorActionPreference = "Stop"

$webuiDir = $PSScriptRoot
$repoRoot = Split-Path $webuiDir -Parent
$runPy = Join-Path $webuiDir "run.py"
$pidFile = Join-Path $webuiDir ".webui.pid"
$outLog = Join-Path $webuiDir "webui.out.log"
$errLog = Join-Path $webuiDir "webui.err.log"

function Get-PythonExe {
    $workspaceRoot = Resolve-Path (Join-Path $repoRoot "..\..")
    $candidates = @(
        (Join-Path $workspaceRoot "nanobot\venv311\Scripts\python.exe"),
        (Join-Path $repoRoot ".venv\Scripts\python.exe"),
        (Join-Path $repoRoot ".venv\bin\python.exe"),
        "python"
    )

    foreach ($candidate in $candidates) {
        if ($candidate -eq "python") {
            try {
                & python --version *> $null
                return "python"
            } catch {
                continue
            }
        }
        if (Test-Path $candidate) {
            return $candidate
        }
    }

    throw "Could not find Python. Checked shared venv and local .venv paths."
}

function Test-AlreadyRunning {
    param([string]$PidPath)

    if (-not (Test-Path $PidPath)) {
        return $false
    }

    $existingPid = (Get-Content $PidPath -ErrorAction SilentlyContinue | Select-Object -First 1)
    if (-not $existingPid) {
        Remove-Item $PidPath -Force -ErrorAction SilentlyContinue
        return $false
    }

    try {
        $proc = Get-Process -Id ([int]$existingPid) -ErrorAction Stop
        Write-Host "Web UI already running (PID: $($proc.Id))."
        Write-Host "Open: http://127.0.0.1:8790"
        return $true
    } catch {
        Remove-Item $PidPath -Force -ErrorAction SilentlyContinue
        return $false
    }
}

if (Test-AlreadyRunning -PidPath $pidFile) {
    exit 0
}

$pythonExe = Get-PythonExe
Write-Host "Starting Web UI with: $pythonExe"

if (Test-Path $outLog) { Remove-Item $outLog -Force -ErrorAction SilentlyContinue }
if (Test-Path $errLog) { Remove-Item $errLog -Force -ErrorAction SilentlyContinue }

$proc = Start-Process `
    -FilePath $pythonExe `
    -ArgumentList "`"$runPy`"" `
    -WorkingDirectory $repoRoot `
    -PassThru `
    -WindowStyle Hidden `
    -RedirectStandardOutput $outLog `
    -RedirectStandardError $errLog

$proc.Id | Set-Content $pidFile -Encoding ascii
Start-Sleep -Seconds 3

try {
    if ($PSVersionTable.PSVersion.Major -lt 6) {
        $check = Invoke-WebRequest -Uri "http://127.0.0.1:8790" -UseBasicParsing -TimeoutSec 5
    }
    else {
        $check = Invoke-WebRequest -Uri "http://127.0.0.1:8790" -TimeoutSec 5
    }
    if ($check.StatusCode -eq 200) {
        Write-Host "Web UI started successfully (PID: $($proc.Id))."
        Write-Host "Open: http://127.0.0.1:8790"
        exit 0
    }
} catch {
    # handled below
}

Write-Host "Web UI process started but health check failed."
Write-Host "Check logs:"
Write-Host "  $outLog"
Write-Host "  $errLog"
exit 1
