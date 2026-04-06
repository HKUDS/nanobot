#!/bin/bash

# Nanobot 容器化智能体管理系统 - 部署脚本
# 适用于 WSL/Linux 环境

set -e  # 遇到错误立即退出

echo "🚀 开始部署 Nanobot 容器化智能体管理系统..."

# 检查环境
echo "📋 检查部署环境..."

# 检查 Docker
if ! command -v docker &> /dev/null; then
    echo "❌ Docker 未安装，请先安装 Docker"
    exit 1
fi

# 检查 Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 未安装，请先安装 Python3"
    exit 1
fi

# 检查 Node.js
if ! command -v node &> /dev/null; then
    echo "❌ Node.js 未安装，请先安装 Node.js"
    exit 1
fi

echo "✅ 环境检查通过"

# 进入项目目录
cd /mnt/d/collections2026/phd_application/nanobot1/milestone2

# 清理现有容器
echo "🧹 清理现有容器..."
docker stop $(docker ps -aq) 2>/dev/null || true
docker rm $(docker ps -aq) 2>/dev/null || true

# 构建 Docker 镜像
echo "🔨 构建 nanobot-agent 镜像..."
docker build --no-cache -f shared/Dockerfile.agent -t nanobot-agent:latest .

# 验证镜像构建
echo "✅ 镜像构建完成"
docker images | grep nanobot-agent

# 创建虚拟环境（如果不存在）
if [ ! -d "shared/venv" ]; then
    echo "🐍 创建 Python 虚拟环境..."
    python3 -m venv shared/venv
fi

# 激活虚拟环境
echo "🔧 激活虚拟环境..."
source shared/venv/bin/activate

# 安装 Python 依赖
echo "📦 安装 Python 依赖..."
pip install -r shared/requirements.txt

# 安装前端依赖
echo "🌐 安装前端依赖..."
cd frontend
npm install
cd ..

echo "🎉 部署完成！"
echo ""
echo "📋 启动说明："
echo "1. 启动 BFF 服务：source shared/venv/bin/activate && python -m bff.bff_service"
echo "2. 启动前端服务：cd frontend && npm run dev"
echo "3. 访问系统：http://localhost:3000"
echo ""
echo "🔧 常用命令："
echo "- 查看容器：docker ps"
echo "- 查看日志：docker logs nanobot_conv_xxx"
echo "- 清理系统：docker system prune -a --volumes"
echo ""
echo "📞 技术支持：查看 deployment/README.md 获取详细文档"