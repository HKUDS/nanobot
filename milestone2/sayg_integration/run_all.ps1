# SAYG-Mem 工程验证 - 便捷启动脚本
# 使用方法: 在PowerShell中运行 .\run_all.ps1

param(
    [switch]$SkipBFF,
    [switch]$ValidationOnly
)

$ErrorActionPreference = "Stop"

$ProjectRoot = "D:\collections2026\phd_application\nanobot1\milestone2"
$VenvActivate = "$ProjectRoot\shared\venv\Scripts\Activate.ps1"
$ScriptDir = "$ProjectRoot\sayg_integration"

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "SAYG-Mem 工程验证" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

if (-not (Test-Path $VenvActivate)) {
    Write-Host "错误: venv不存在: $VenvActivate" -ForegroundColor Red
    exit 1
}

# 激活虚拟环境
Write-Host "[1/3] 激活虚拟环境..." -ForegroundColor Yellow
. $VenvActivate
Write-Host "      Python: $(which python)" -ForegroundColor Green

if (-not $SkipBFF) {
    Write-Host ""
    Write-Host "[2/3] 启动BFF服务..." -ForegroundColor Yellow
    Write-Host "      提示: 按 Ctrl+C 停止" -ForegroundColor Gray
    Write-Host ""

    # 在后台启动BFF
    $bffJob = Start-Job -ScriptBlock {
        param($dir, $venv)
        Set-Location $dir
        . "$venv\Scripts\Activate.ps1"
        python -m bff.bff_service
    } -ArgumentList $ProjectRoot, "$ProjectRoot\shared\venv"

    Write-Host "      BFF正在后台启动 (Job ID: $($bffJob.Id))" -ForegroundColor Green

    # 等待BFF就绪
    Write-Host "      等待BFF就绪..." -ForegroundColor Gray
    Start-Sleep -Seconds 5

    # 检查BFF是否就绪
    $bffReady = $false
    for ($i = 0; $i -lt 30; $i++) {
        try {
            $response = Invoke-WebRequest -Uri "http://localhost:8000/" -TimeoutSec 2 -ErrorAction SilentlyContinue
            if ($response.StatusCode -eq 200 -or $response.StatusCode -eq 307) {
                $bffReady = $true
                Write-Host "      BFF就绪 ✓" -ForegroundColor Green
                break
            }
        } catch {
            Start-Sleep -Seconds 1
        }
    }

    if (-not $bffReady) {
        Write-Host "      警告: BFF可能未就绪，继续执行..." -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "[3/3] 运行验证脚本..." -ForegroundColor Yellow
Write-Host ""

Set-Location $ScriptDir
python validate_engineering_v3.py

if (-not $SkipBFF -and $bffJob) {
    Write-Host ""
    Write-Host "[Cleanup] 停止BFF服务..." -ForegroundColor Yellow
    Stop-Job -Job $bffJob -ErrorAction SilentlyContinue
    Remove-Job -Job $bffJob -ErrorAction SilentlyContinue
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "验证完成!" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Cyan
