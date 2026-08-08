$ErrorActionPreference = "Stop"
$Secret = "LOCAL_DEV_SECRET_18790"
$LanIp = (Get-NetIPAddress -AddressFamily IPv4 |
  Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254*" } |
  Select-Object -First 1 -ExpandProperty IPAddress)
if (-not $LanIp) { $LanIp = "127.0.0.1" }
$C2Base = "http://$LanIp`:18790"

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

$pythonCmd = Resolve-PythonCommand @(
  "py -3.12",
  "python3.12",
  "python"
)
if (-not $pythonCmd) {
  throw "No usable Python command found to generate JWT token."
}

$token = & cmd.exe /c "$pythonCmd -c ""from jose import jwt; from datetime import datetime,timedelta,timezone; print(jwt.encode({'sub':'local-check','exp': datetime.now(timezone.utc)+timedelta(hours=2)}, '$Secret', algorithm='HS256'))"""
$token = $token.Trim()

Write-Host "[HTTP checks]"
$headers = @{ Authorization = "Bearer $token" }

try {
  $h = Invoke-RestMethod -Uri "$C2Base/health" -Method Get
  Write-Host "[OK] c2 /health -> $($h.status)"
} catch {
  Write-Host "[FAIL] c2 /health -> $($_.Exception.Message)"
}

try {
  $s = Invoke-RestMethod -Uri "$C2Base/status" -Headers $headers -Method Get
  Write-Host "[OK] c2 /status -> reachable (agent_status=$($s.agent_status))"
  if ($s.agent_status -eq "offline") {
    Write-Host "[INFO] agent_status is offline unless a nanobot worker process is running."
  }
} catch {
  Write-Host "[FAIL] c2 /status -> $($_.Exception.Message)"
}

try {
  $b = Invoke-RestMethod -Uri "http://127.0.0.1:18791/health" -Method Get
  Write-Host "[OK] bitnet /health -> $($b.status)"
} catch {
  Write-Host "[FAIL] bitnet /health -> $($_.Exception.Message)"
}

try {
  $p = Invoke-RestMethod -Uri "http://127.0.0.1:3000/api/providers" -Method Get
  Write-Host "[OK] perplexica /api/providers -> providers=$($p.providers.Count)"
} catch {
  Write-Host "[FAIL] perplexica /api/providers -> $($_.Exception.Message)"
}

try {
  $body = @{ command = "status"; priority = "normal" } | ConvertTo-Json
  $r = Invoke-RestMethod -Uri "$C2Base/agent/command" -Headers (@{ Authorization = "Bearer $token"; "Content-Type" = "application/json" }) -Method Post -Body $body
  Write-Host "[OK] /agent/command -> status=$($r.status) plan_id=$($r.plan_id)"
} catch {
  Write-Host "[FAIL] /agent/command -> $($_.Exception.Message)"
}
