# SAYG-Mem 多Agent三段内存学习验证 - 启动脚本 (PowerShell)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Milestone2Dir = Split-Path -Parent $ScriptDir
$SharedDir = Join-Path $Milestone2Dir "shared"

Write-Host "=========================================="
Write-Host "SAYG-Mem 多Agent验证启动脚本"
Write-Host "=========================================="

# 1. 检查Docker环境
Write-Host "[1/5] 检查Docker环境..."
try {
    $dockerVersion = docker --version
    Write-Host "  Docker版本: $dockerVersion"
} catch {
    Write-Host "错误: Docker未安装" -ForegroundColor Red
    exit 1
}

# 2. 创建数据目录
Write-Host "[2/5] 创建数据目录..."
$heapsDir = Join-Path $Milestone2Dir "data\heaps"
$pmDir = Join-Path $Milestone2Dir "data\public_memory"
$logsDir = Join-Path $Milestone2Dir "logs"

New-Item -ItemType Directory -Force -Path $heapsDir | Out-Null
New-Item -ItemType Directory -Force -Path $pmDir | Out-Null
New-Item -ItemType Directory -Force -Path $logsDir | Out-Null
Write-Host "  数据目录已创建"

# 3. 构建BFF镜像
Write-Host "[3/5] 构建BFF镜像..."
Set-Location $SharedDir

if (-not (Test-Path "Dockerfile.bff")) {
    Write-Host "错误: Dockerfile.bff不存在" -ForegroundColor Red
    exit 1
}

# 停止旧容器
docker-compose down --remove-orphans 2>$null

# 构建镜像
docker build -t nanobot-bff:latest -f Dockerfile.bff .
if ($LASTEXITCODE -ne 0) {
    Write-Host "错误: BFF镜像构建失败" -ForegroundColor Red
    exit 1
}
Write-Host "  BFF镜像构建完成"

# 4. 启动BFF服务
Write-Host "[4/5] 启动BFF服务..."
docker-compose up -d bff

# 等待BFF服务就绪
Write-Host "  等待BFF服务就绪..."
$maxWait = 60
$counter = 0

while ($counter -lt $maxWait) {
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:8000/health" -TimeoutSec 2 -UseBasicParsing -ErrorAction SilentlyContinue
        if ($response.StatusCode -eq 200) {
            Write-Host "  BFF服务已就绪" -ForegroundColor Green
            break
        }
    } catch {
        # 继续等待
    }
    $counter++
    Write-Host "  等待中... ($counter/$maxWait)"
    Start-Sleep -Seconds 2
}

if ($counter -eq $maxWait) {
    Write-Host "错误: BFF服务启动超时" -ForegroundColor Red
    docker-compose logs bff
    exit 1
}

# 5. 运行验证脚本
Write-Host "[5/5] 运行验证脚本..."
Set-Location $Milestone2Dir

$validationScript = Join-Path $Milestone2Dir "sayg_integration\learn_segments_collab.py"
if (-not (Test-Path $validationScript)) {
    Write-Host "错误: 验证脚本不存在: $validationScript" -ForegroundColor Red
    exit 1
}

# 使用venv中的Python（如果存在）
$pythonExe = "$SharedDir\venv_win\Scripts\python.exe"
if (-not (Test-Path $pythonExe)) {
    $pythonExe = "python"
}

& $pythonExe $validationScript
$exitCode = $LASTEXITCODE

# 显示结果
Write-Host ""
Write-Host "=========================================="
Write-Host "验证完成"
Write-Host "=========================================="
Write-Host "退出码: $exitCode"
Write-Host "报告目录: $logsDir"
Write-Host "数据目录: $Milestone2Dir\data"

# 清理询问
$cleanup = Read-Host "是否停止BFF服务? (y/N)"
if ($cleanup -eq "y" -or $cleanup -eq "Y") {
    Set-Location $SharedDir
    docker-compose down
    Write-Host "BFF服务已停止"
}

exit $exitCode
