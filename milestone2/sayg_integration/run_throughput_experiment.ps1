# 吞吐量对比实验启动脚本
# 直接在 PowerShell 或 Windows CMD 中运行，不需要 WSL

param(
    [int]$TimeBudget = 300,
    [int]$AgentCount = 3
)

$ErrorActionPreference = "Continue"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  吞吐量对比实验启动脚本" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 检查 Docker 是否运行
Write-Host "[1/4] 检查 Docker 状态..." -ForegroundColor Yellow
$dockerOk = docker ps 2>$null
if (-not $dockerOk) {
    Write-Host "  [ERROR] Docker 未运行，请先启动 Docker Desktop" -ForegroundColor Red
    exit 1
}
Write-Host "  [OK] Docker 运行中" -ForegroundColor Green

# 检查必要的镜像
Write-Host "[2/4] 检查 Docker 镜像..." -ForegroundColor Yellow
$agentImage = docker images nanobot-agent:latest -q
$bffImage = docker images nanobot-bff:latest -q
if (-not $agentImage) {
    Write-Host "  [ERROR] nanobot-agent:latest 镜像不存在" -ForegroundColor Red
    Write-Host "  请先构建: docker build -f shared/Dockerfile.agent -t nanobot-agent:latest ." -ForegroundColor Yellow
    exit 1
}
if (-not $bffImage) {
    Write-Host "  [ERROR] nanobot-bff:latest 镜像不存在" -ForegroundColor Red
    Write-Host "  请先构建: docker build -f shared/Dockerfile.bff -t nanobot-bff:latest ." -ForegroundColor Yellow
    exit 1
}
Write-Host "  [OK] 镜像检查通过" -ForegroundColor Green

# 设置环境变量
Write-Host "[3/4] 设置环境变量..." -ForegroundColor Yellow
$env:BFF_BASE_URL = "http://host.docker.internal:8000"
$env:KM_MERGE_THRESHOLD = "6"
$env:KM_MERGE_INTERVAL = "30.0"
Write-Host "  BFF_BASE_URL=$env:BFF_BASE_URL" -ForegroundColor Cyan
Write-Host "  KM_MERGE_THRESHOLD=$env:KM_MERGE_THRESHOLD" -ForegroundColor Cyan
Write-Host "  KM_MERGE_INTERVAL=$env:KM_MERGE_INTERVAL" -ForegroundColor Cyan

# 检查端口 8000 是否被占用
Write-Host "[4/4] 检查端口 8000..." -ForegroundColor Yellow
$portInUse = netstat -ano | Select-String ":8000 "
if ($portInUse) {
    Write-Host "  [WARNING] 端口 8000 已被占用，BFF 可能无法启动" -ForegroundColor Yellow
    Write-Host "  $portInUse" -ForegroundColor Yellow
} else {
    Write-Host "  [OK] 端口 8000 可用" -ForegroundColor Green
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  实验参数" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  时间预算: $TimeBudget 秒" -ForegroundColor White
Write-Host "  Agent数量: $AgentCount" -ForegroundColor White
Write-Host ""

# 切换到脚本目录
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if ($scriptDir) {
    Set-Location $scriptDir
}

# 启动实验
Write-Host "启动吞吐量对比实验..." -ForegroundColor Green
Write-Host ""

# 使用 Python 运行对比实验
$pythonCmd = "python"
if (Get-Command python3 -ErrorAction SilentlyContinue) {
    $pythonCmd = "python3"
}

& $pythonCmd run_throughput_comparison.py --time-budget $TimeBudget --agent-count $AgentCount

Write-Host ""
Write-Host "实验完成!" -ForegroundColor Green
