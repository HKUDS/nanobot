# SAYG-Mem 工程验证 - 一键启动（PowerShell）
# 双击此文件运行，或: .\quick_run.ps1

param(
    [switch]$BFFOnly
)

$ErrorActionPreference = "Stop"
$ProjectRoot = "D:\collections2026\phd_application\nanobot1\milestone2"
$VenvActivate = "$ProjectRoot\shared\venv\Scripts\Activate.ps1"
$ScriptDir = "$ProjectRoot\sayg_integration"

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "SAYG-Mem 工程验证" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

if (-not (Test-Path $VenvActivate)) {
    Write-Host "[错误] venv不存在: $VenvActivate" -ForegroundColor Red
    Write-Host "请先运行: bash run_bff.sh (启动BFF)" -ForegroundColor Yellow
    Write-Host "         bash run_validation.sh (运行验证)" -ForegroundColor Yellow
    Read-Host "按回车退出"
    exit 1
}

# 激活虚拟环境
Write-Host "[激活] 虚拟环境..." -ForegroundColor Yellow
. $VenvActivate
Write-Host "[ OK ] Python: $(which python)" -ForegroundColor Green

if ($BFFOnly) {
    Write-Host ""
    Write-Host "[启动] BFF服务 (http://localhost:8000)..." -ForegroundColor Yellow
    Write-Host "[提示] 按 Ctrl+C 停止服务" -ForegroundColor Gray
    Write-Host ""
    python -m bff.bff_service
} else {
    Write-Host ""
    Write-Host "[运行] 验证脚本..." -ForegroundColor Yellow
    Write-Host ""

    Set-Location $ScriptDir
    python validate_engineering_v3.py

    Write-Host ""
    Write-Host "============================================" -ForegroundColor Cyan
    Write-Host "完成! 日志文件在: $ScriptDir\logs\" -ForegroundColor Green
    Write-Host "============================================" -ForegroundColor Cyan
}
