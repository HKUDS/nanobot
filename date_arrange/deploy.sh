#!/bin/bash

# Date Arrange 部署脚本
# 用于快速部署完整的Date Arrange系统

set -e

echo "🚀 开始部署 Date Arrange 系统..."

# 检查环境
echo "📋 检查部署环境..."

# 检查Docker
if ! command -v docker &> /dev/null; then
    echo "❌ Docker未安装，请先安装Docker"
    exit 1
fi

# 检查Docker Compose
if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose未安装，请先安装Docker Compose"
    exit 1
fi

# 检查环境变量文件
if [ ! -f .env ]; then
    echo "⚠️  未找到.env文件，创建示例环境变量文件..."
    cat > .env << EOF
# Date Arrange 环境配置

# OpenAI API密钥（用于Nanobot）
OPENAI_API_KEY=your_openai_api_key_here

# 服务端口配置
FRONTEND_PORT=3001
API_PORT=8000
NGINX_PORT=80

# 数据库配置（可选）
# DATABASE_URL=postgresql://user:password@localhost:5432/date_arrange

# 日志级别
LOG_LEVEL=INFO

# 时区配置
TZ=Asia/Shanghai
EOF
    echo "✅ 已创建.env文件，请编辑配置后重新运行部署脚本"
    exit 1
fi

# 加载环境变量
set -a
source .env
set +a

# 创建必要的目录
echo "📁 创建数据目录..."
mkdir -p data/workspace data/logs

# 构建Docker镜像
echo "🔨 构建Docker镜像..."

# 构建API服务镜像
echo "📦 构建Date Arrange API镜像..."
docker build -f Dockerfile.api -t date-arrange-api:latest .

# 构建前端镜像
echo "📦 构建前端镜像..."
cd frontend
docker build -t date-arrange-frontend:latest .
cd ..

# 构建Nanobot Agent镜像（如果存在）
if [ -f "../milestone2/shared/Dockerfile.agent" ]; then
    echo "🤖 构建Nanobot Agent镜像..."
    docker build -f ../milestone2/shared/Dockerfile.agent -t nanobot-agent:latest ../milestone2
else
    echo "⚠️  未找到Nanobot Agent Dockerfile，跳过构建"
fi

# 启动服务
echo "🚀 启动Date Arrange服务..."
docker-compose up -d

# 等待服务启动
echo "⏳ 等待服务启动..."
sleep 30

# 检查服务状态
echo "🔍 检查服务状态..."

# 检查API服务
if curl -f http://localhost:${API_PORT}/health > /dev/null 2>&1; then
    echo "✅ Date Arrange API服务运行正常"
else
    echo "❌ Date Arrange API服务启动失败"
    docker-compose logs date-arrange-api
    exit 1
fi

# 检查前端服务
if curl -f http://localhost:${FRONTEND_PORT} > /dev/null 2>&1; then
    echo "✅ 前端服务运行正常"
else
    echo "❌ 前端服务启动失败"
    docker-compose logs date-arrange-frontend
    exit 1
fi

# 检查Nginx服务
if curl -f http://localhost:${NGINX_PORT} > /dev/null 2>&1; then
    echo "✅ Nginx服务运行正常"
else
    echo "❌ Nginx服务启动失败"
    docker-compose logs nginx
    exit 1
fi

echo ""
echo "🎉 Date Arrange 系统部署完成！"
echo ""
echo "📊 服务访问地址："
echo "   前端界面: http://localhost:${NGINX_PORT}"
echo "   API文档: http://localhost:${API_PORT}/docs"
echo "   健康检查: http://localhost:${API_PORT}/health"
echo ""
echo "🔧 常用命令："
echo "   查看日志: docker-compose logs -f"
echo "   停止服务: docker-compose down"
echo "   重启服务: docker-compose restart"
echo "   更新服务: docker-compose pull && docker-compose up -d"
echo ""
echo "💡 提示："
echo "   1. 请确保.env文件中的OPENAI_API_KEY已正确配置"
echo "   2. 首次使用需要等待Nanobot Agent初始化完成"
echo "   3. 查看详细日志可使用: docker-compose logs -f [服务名]"

# 显示服务状态
echo ""
echo "📈 当前服务状态："
docker-compose ps