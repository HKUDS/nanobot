#!/bin/bash
# Nanobot BFF + KM容器 完整启动脚本 (WSL)
# 确保环境变量配置正确

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=========================================="
echo "Nanobot BFF + KM 系统启动"
echo "=========================================="
echo ""

# 确保PublicMemory目录存在
echo "📁 确保PublicMemory目录存在..."
PM_DIR="$SCRIPT_DIR/data/public_memory"
mkdir -p "$PM_DIR"
touch "$PM_DIR/public_memory.jsonl" 2>/dev/null || true
echo "   PublicMemory目录: $PM_DIR"
echo "   PublicMemory文件: $PM_DIR/public_memory.jsonl"

# 激活虚拟环境
echo ""
echo "🐍 激活虚拟环境..."
source "$SCRIPT_DIR/shared/venv/bin/activate"

# 设置环境变量
echo ""
echo "🔧 设置环境变量..."
export PYTHONPATH="$SCRIPT_DIR"

export HTTP_PROXY="${HTTP_PROXY:-http://172.27.160.1:7890}"
export HTTPS_PROXY="${HTTPS_PROXY:-http://172.27.160.1:7890}"
export http_proxy="$HTTP_PROXY"
export https_proxy="$HTTPS_PROXY"

export DEEPSEEK_API_KEY="${DEEPSEEK_API_KEY:-sk-b192d1bf26f740adace7d5f628656921}"
export DASHSCOPE_API_KEY="${DASHSCOPE_API_KEY:-sk-91fe1c9c529b46bb88dc200a2e97b2b6}"

echo "   PYTHONPATH: $PYTHONPATH"
echo "   HTTP_PROXY: $HTTP_PROXY"
echo "   DEEPSEEK_API_KEY: ${#DEEPSEEK_API_KEY} chars"
echo "   PUBLIC_MEMORY_HOST_PATH: $PM_DIR"
export PUBLIC_MEMORY_HOST_PATH="$PM_DIR"

# 检查Docker
echo ""
echo "🐳 检查Docker..."
if docker ps >/dev/null 2>&1; then
    echo "   ✅ Docker正常"
else
    echo "   ⚠️  Docker未运行，容器管理将受限"
fi

# 停止可能冲突的Docker容器
echo ""
echo "🛑 停止可能冲突的Docker容器..."
docker compose -f "$SCRIPT_DIR/shared/docker-compose.yml" down 2>/dev/null || true

# 启动BFF
echo ""
echo "🚀 启动BFF服务..."
echo "   BFF将在 http://localhost:8000 运行"
echo "   KM容器将由BFF自动创建"
echo "=========================================="
python -m bff.bff_service
