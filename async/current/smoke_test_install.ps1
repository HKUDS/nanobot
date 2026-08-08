param(
  [string]$InstallDir = "$env:ProgramFiles\LuminaC2",
  [switch]$StartIfNeeded
)

$ErrorActionPreference = "Stop"
$ScriptsDir = Join-Path $InstallDir "scripts"
$StartScript = Join-Path $ScriptsDir "start_local_stack_qwen.ps1"
$CheckScript = Join-Path $ScriptsDir "check_local_stack_qwen.ps1"

if (-not (Test-Path $CheckScript)) {
  throw "Smoke test failed: check script not found at $CheckScript"
}

if ($StartIfNeeded) {
  if (-not (Test-Path $StartScript)) {
    throw "Smoke test failed: start script not found at $StartScript"
  }
  Write-Host "[SMOKE] Starting local stack from installed path..."
  & powershell -NoProfile -ExecutionPolicy Bypass -File $StartScript
}

Write-Host "[SMOKE] Running HTTP checks..."
& powershell -NoProfile -ExecutionPolicy Bypass -File $CheckScript
