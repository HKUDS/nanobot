$ErrorActionPreference = "Stop"

$webuiDir = $PSScriptRoot
$pidFile = Join-Path $webuiDir ".webui.pid"

function Stop-ByPidFile {
    param([string]$PidPath)

    if (-not (Test-Path $PidPath)) {
        return $false
    }

    $pidText = Get-Content $PidPath -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $pidText) {
        Remove-Item $PidPath -Force -ErrorAction SilentlyContinue
        return $false
    }

    try {
        $id = [int]$pidText
        Stop-Process -Id $id -Force -ErrorAction Stop
        Write-Host "Stopped Web UI process (PID: $id)."
    } catch {
        Write-Host "PID file found, but process is not running: $pidText"
    }

    Remove-Item $PidPath -Force -ErrorAction SilentlyContinue
    return $true
}

function Stop-ByCommandLine {
    $stoppedAny = $false
    $procs = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'"

    foreach ($p in $procs) {
        if ($p.CommandLine -and $p.CommandLine -like "*nano1\\nanobot\\webui\\run.py*") {
            try {
                Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop
                Write-Host "Stopped orphan Web UI process (PID: $($p.ProcessId))."
                $stoppedAny = $true
            } catch {
                # ignore
            }
        }
    }

    return $stoppedAny
}

$stopped = Stop-ByPidFile -PidPath $pidFile
if (-not $stopped) {
    $stopped = Stop-ByCommandLine
}

if ($stopped) {
    Write-Host "Web UI stopped."
    exit 0
}

Write-Host "No running Web UI process found."
exit 0
