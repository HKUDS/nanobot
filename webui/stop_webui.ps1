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
    } catch {
        Remove-Item $PidPath -Force -ErrorAction SilentlyContinue
        return $false
    }

    $proc = $null
    try {
        $proc = Get-CimInstance Win32_Process -Filter "ProcessId = $id" -ErrorAction Stop
    } catch {
        $proc = $null
    }

    if (-not $proc) {
        Write-Host "PID file found, but no process is running with PID $id."
        Remove-Item $PidPath -Force -ErrorAction SilentlyContinue
        return $false
    }

    $runScriptPath = [System.IO.Path]::GetFullPath((Join-Path $webuiDir "run.py"))
    $cmdLine = $proc.CommandLine
    if (-not ($cmdLine -and ($cmdLine -like "*$runScriptPath*"))) {
        Write-Host "PID file refers to a process that does not match this Web UI instance (PID: $id). Skipping."
        Remove-Item $PidPath -Force -ErrorAction SilentlyContinue
        return $false
    }

    $stopped = $false
    try {
        Stop-Process -Id $id -ErrorAction Stop
        Write-Host "Stopped Web UI process (PID: $id)."
        $stopped = $true
    } catch {
        try {
            Stop-Process -Id $id -Force -ErrorAction Stop
            Write-Host "Force-stopped Web UI process (PID: $id)."
            $stopped = $true
        } catch {
            Write-Host "PID file found, but process could not be stopped: $pidText"
        }
    }

    Remove-Item $PidPath -Force -ErrorAction SilentlyContinue
    return $stopped
}

function Stop-ByCommandLine {
    $stoppedAny = $false
    $runScriptPath = [System.IO.Path]::GetFullPath((Join-Path $webuiDir "run.py"))
    $procs = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'"

    foreach ($p in $procs) {
        if ($p.CommandLine -and $p.CommandLine -like "*$runScriptPath*") {
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
