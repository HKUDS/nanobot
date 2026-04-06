# Nanobot 容器化智能体管理系统 - Windows 部署脚本

Write-Host "🚀 开始部署 Nanobot 容器化智能体管理系统..." -ForegroundColor Green

# 检查环境
Write-Host "📋 检查部署环境..." -ForegroundColor Yellow

# 检查 Docker
if (-not (Get-Command "docker" -ErrorAction SilentlyContinue)) {
    Write-Host "❌ Docker 未安装，请先安装 Docker" -ForegroundColor Red
    exit 1
}

# 检查 Python
if (-not (Get-Command "python" -ErrorAction SilentlyContinue)) {
    Write-Host "❌ Python 未安装，请先安装 Python" -ForegroundColor Red
    exit 1
}

# 检查 Node.js
if (-not (Get-Command "node" -ErrorAction SilentlyContinue)) {
    Write-Host "❌ Node.js 未安装，请先安装 Node.js" -ForegroundColor Red
    exit 1
}

Write-Host "✅ 环境检查通过" -ForegroundColor Green

# 进入项目目录
Set-Location "D:\collections2026\phd_application\nanobot1\milestone2"

# 清理现有容器
Write-Host "🧹 清理现有容器..." -ForegroundColor Yellow

docker stop $(docker ps -aq) 2>$null
docker rm $(docker ps -aq) 2>$null

# 构建 Docker 镜像
Write-Host "🔨 构建 nanobot-agent 镜像..." -ForegroundColor Yellow
docker build --no-cache -f shared/Dockerfile.agent -t nanobot-agent:latest .

# 验证镜像构建
Write-Host "✅ 镜像构建完成" -ForegroundColor Green
docker images | Select-String "nanobot-agent"

# 创建虚拟环境（如果不存在）
if (-not (Test-Path "shared\venv_win")) {
    Write-Host "🐍 创建 Python 虚拟环境..." -ForegroundColor Yellow
    python -m venv shared\venv_win
}

# 激活虚拟环境
Write-Host "🔧 激活虚拟环境..." -ForegroundColor Yellow
.\shared\venv_win\Scripts\Activate.ps1

# 安装 Python 依赖
Write-Host "📦 安装 Python 依赖..." -ForegroundColor Yellow
pip install -r shared\requirements.txt

# 安装前端依赖
Write-Host "🌐 安装前端依赖..." -ForegroundColor Yellow
Set-Location "frontend"
npm install
Set-Location ".."

Write-Host "🎉 部署完成！" -ForegroundColor Green
Write-Host ""
Write-Host "📋 启动说明：" -ForegroundColor Cyan
Write-Host "1. 启动 BFF 服务：.\shared\venv_win\Scripts\Activate.ps1 && python -m bff.bff_service"
Write-Host "2. 启动前端服务：cd frontend && npm run dev"
Write-Host "3. 访问系统：http://localhost:3000"
Write-Host ""
Write-Host "🔧 常用命令：" -ForegroundColor Cyan
Write-Host "- 查看容器：docker ps"
Write-Host "- 查看日志：docker logs nanobot_conv_xxx"
Write-Host "- 清理系统：docker system prune -a --volumes"
Write-Host ""
Write-Host "📞 技术支持：查看 deployment\README.md 获取详细文档" -ForegroundColor Cyan