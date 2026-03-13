param(
  [string]$C2SecretKey = "LOCAL_DEV_SECRET_18790",
  [string]$PythonCmd = ""
)

$ErrorActionPreference = "Stop"
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$AppRoot = Split-Path -Parent $ScriptRoot
$BackendDir = if (Test-Path (Join-Path $AppRoot "backend\c2_server.py")) {
  Join-Path $AppRoot "backend"
} elseif (Test-Path (Join-Path $ScriptRoot "c2_server.py")) {
  $ScriptRoot
} else {
  $PWD.Path
}

$LogDir = Join-Path $env:TEMP "LuminaC2_Logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$LogFile = Join-Path $LogDir "c2_startup.log"

function Resolve-PythonCommand([string[]]$Candidates) {
  foreach ($candidate in $Candidates) {
    if (-not $candidate) { continue }
    $probe = "($candidate --version) >nul 2>&1"
    $p = Start-Process -FilePath "cmd.exe" -ArgumentList "/c", $probe -PassThru -Wait -WindowStyle Hidden
    if ($p.ExitCode -eq 0) {
      return $candidate
    }
  }
  return $null
}

if (-not $PythonCmd) {
  $PythonCmd = Resolve-PythonCommand @(
    "py -3.12",
    "python3.12",
    "python"
  )
}
if (-not $PythonCmd) {
  throw "No usable Python command found for c2_server.py."
}

$cmd = "cd /d `"$BackendDir`" && set `"C2_SECRET_KEY=$C2SecretKey`"&&set `"PYTHONIOENCODING=utf-8`"&&$PythonCmd -u c2_server.py >> `"$LogFile`" 2>&1"
$p = Start-Process -FilePath "cmd.exe" -ArgumentList "/c", $cmd -PassThru -WindowStyle Hidden

Write-Host "[STARTED] C2 PID=$($p.Id)"
Write-Host "BackendDir: $BackendDir"
Write-Host "PythonCmd: $PythonCmd"
Write-Host "LogFile: $LogFile"
