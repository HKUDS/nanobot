#!/bin/bash
# Nanobot BFF 启动脚本 (WSL) - 测试用宿主机版本

cd /mnt/d/collections2026/phd_application/nanobot1/milestone2

echo "🔧 启动 Nanobot BFF 服务（宿主机测试版）..."
echo "📁 项目根目录：$PWD"
echo ""

# 检查并停止可能冲突的Docker容器
echo "🛑 检查并停止可能冲突的Docker容器..."
docker compose -f shared/docker-compose.yml down 2>/dev/null || true

# 检查Docker访问权限
echo "🐳 检查Docker访问权限..."
if docker ps >/dev/null 2>&1; then
    echo "✅ Docker访问正常"
else
    echo "⚠️  Docker访问失败，容器管理功能将受限"
    echo "   请确保Docker守护进程正在运行且当前用户有访问权限"
fi

# 激活虚拟环境
echo "🐍 激活虚拟环境..."
source shared/venv/bin/activate

# 设置环境变量
echo "🔧 设置环境变量..."

# 设置 PYTHONPATH
export PYTHONPATH=/mnt/d/collections2026/phd_application/nanobot1/milestone2

# 设置代理（解决DeepSeek API DNS解析问题）
export HTTP_PROXY="${HTTP_PROXY:-http://172.27.160.1:7890}"
export HTTPS_PROXY="${HTTPS_PROXY:-http://172.27.160.1:7890}"
export http_proxy="${HTTP_PROXY}"
export https_proxy="${HTTPS_PROXY}"

# 设置API密钥（使用环境变量或默认值）
export DEEPSEEK_API_KEY="${DEEPSEEK_API_KEY:-sk-b192d1bf26f740adace7d5f628656921}"
export DASHSCOPE_API_KEY="${DASHSCOPE_API_KEY:-sk-91fe1c9c529b46bb88dc200a2e97b2b6}"

# 设置KM合并阈值（降低阈值以观察自动触发）
export KM_MERGE_THRESHOLD=3
export KM_MERGE_INTERVAL=5.0
export CONSOLIDATOR_SIMHASH_THRESHOLD=8

# 打印环境变量状态
echo "� 环境变量状态:"
echo "   PYTHONPATH: $PYTHONPATH"
echo "   HTTP_PROXY: ${HTTP_PROXY:-未设置}"
echo "   HTTPS_PROXY: ${HTTPS_PROXY:-未设置}"
echo "   DEEPSEEK_API_KEY长度: ${#DEEPSEEK_API_KEY}"
echo "   DASHSCOPE_API_KEY长度: ${#DASHSCOPE_API_KEY}"
echo ""

# 启动 BFF 服务
echo "🚀 启动 BFF 服务..."
echo "========================================"
python -m bff.bff_service
