param(
  [string]$SecretPrefix = "local-dev-noaws-18790",
  [string]$C2SecretKey = "LOCAL_DEV_SECRET_18790",
  [string]$Python311Cmd = "",
  [string]$Python312Cmd = ""
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

$ModelRoot = @(
  (Join-Path $BackendDir "models\qwen"),
  (Join-Path $AppRoot "models\qwen"),
  (Join-Path $ScriptRoot "models\qwen")
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $ModelRoot) {
  $ModelRoot = Join-Path $BackendDir "models\qwen"
}

$BitnetModel = Join-Path $ModelRoot "qwen2.5-0.5b-instruct-q4_k_m.gguf"
$PerplexicaChatModel = Join-Path $ModelRoot "qwen2.5-1.5b-instruct-q4_k_m.gguf"
$PerplexicaEmbedModel = $BitnetModel

if (-not (Test-Path $BitnetModel)) {
  Write-Host "[WARN] Missing BitNet model: $BitnetModel"
}
if (-not (Test-Path $PerplexicaChatModel)) {
  Write-Host "[WARN] Missing Perplexica chat model: $PerplexicaChatModel"
}

$LogDir = Join-Path $env:TEMP "LuminaC2_Logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$LanIp = (Get-NetIPAddress -AddressFamily IPv4 |
  Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254*" } |
  Select-Object -First 1 -ExpandProperty IPAddress)
if (-not $LanIp) { $LanIp = "127.0.0.1" }

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

if (-not $Python311Cmd) {
  $Python311Cmd = Resolve-PythonCommand @(
    "py -3.11",
    "python3.11",
    "python"
  )
}
if (-not $Python312Cmd) {
  $Python312Cmd = Resolve-PythonCommand @(
    "py -3.12",
    "python3.12",
    "python"
  )
}
if (-not $Python311Cmd) {
  throw "No usable Python command found for 3.11-compatible services."
}
if (-not $Python312Cmd) {
  throw "No usable Python command found for 3.12-compatible services."
}

function Stop-ByPattern([string]$Pattern) {
  Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -and $_.CommandLine -like "*$Pattern*" } |
    ForEach-Object {
      Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
}

function Start-Managed([string]$Name, [string]$CommandLine, [string]$LogFile) {
  $cmd = "cd /d `"$BackendDir`" && $CommandLine >> `"$LogFile`" 2>&1"
  $p = Start-Process -FilePath "cmd.exe" -ArgumentList "/c", $cmd -WindowStyle Hidden -PassThru
  Write-Host "[STARTED] $Name PID=$($p.Id)"
}

function Wait-Health([string]$Name, [string]$Url, [int]$TimeoutSeconds = 90) {
  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  do {
    try {
      $r = Invoke-RestMethod -Uri $Url -Method Get -TimeoutSec 8
      $status = if ($r.status) { $r.status } else { "ok" }
      Write-Host ("[OK] {0} -> {1}" -f $Name, $status)
      return $true
    } catch {
      Start-Sleep -Seconds 3
    }
  } while ((Get-Date) -lt $deadline)

  Write-Host ("[FAIL] {0} -> Timed out waiting for {1}" -f $Name, $Url)
  return $false
}

Write-Host "[1/4] Stopping old local stack processes..."
Stop-ByPattern "bitnet_server_windows.py"
Stop-ByPattern "perplexica_compat_server.py"
Stop-ByPattern "c2_server.py"

Write-Host "[2/4] Starting local Qwen BitNet adapter (18791)..."
Start-Managed `
  -Name "bitnet" `
  -CommandLine "set `"BITNET_MODEL=$BitnetModel`"&&$Python311Cmd -u bitnet_server_windows.py" `
  -LogFile (Join-Path $LogDir "bitnet.log")

Write-Host "[3/4] Starting local Perplexica-compatible API (3000)..."
Start-Managed `
  -Name "perplexica-compat" `
  -CommandLine "set `"PERPLEXICA_CHAT_MODEL_PATH=$PerplexicaChatModel`"&&set `"PERPLEXICA_EMBED_MODEL_PATH=$PerplexicaEmbedModel`"&&$Python311Cmd -u perplexica_compat_server.py" `
  -LogFile (Join-Path $LogDir "perplexica_compat.log")

Write-Host "[4/4] Starting C2 backend (18790)..."
Start-Managed `
  -Name "c2" `
  -CommandLine "set `"SECRET_PREFIX=$SecretPrefix`"&&set `"C2_SECRET_KEY=$C2SecretKey`"&&set `"BITNET_URL=http://127.0.0.1:18791`"&&set `"PERPLEXICA_URL=http://127.0.0.1:3000`"&&set `"PYTHONIOENCODING=utf-8`"&&$Python312Cmd -u c2_server.py" `
  -LogFile (Join-Path $LogDir "c2.log")

Write-Host "`n[HEALTH CHECK]"
Wait-Health -Name "bitnet" -Url "http://127.0.0.1:18791/health" | Out-Null
Wait-Health -Name "perplexica" -Url "http://127.0.0.1:3000/health" | Out-Null
Wait-Health -Name "c2 (localhost)" -Url "http://127.0.0.1:18790/health" | Out-Null
Wait-Health -Name "c2 (LAN)" -Url "http://$LanIp`:18790/health" -TimeoutSeconds 20 | Out-Null

Write-Host "`nLogs:"
Write-Host (Join-Path $LogDir "bitnet.log")
Write-Host (Join-Path $LogDir "perplexica_compat.log")
Write-Host (Join-Path $LogDir "c2.log")
Write-Host "`nBackendDir: $BackendDir"
Write-Host "ModelRoot: $ModelRoot"
Write-Host "Python311Cmd: $Python311Cmd"
Write-Host "Python312Cmd: $Python312Cmd"
