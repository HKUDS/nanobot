#!/bin/bash
# SAYG-Mem 多Agent三段内存学习验证 - 启动脚本

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MILESTONE2_DIR="$(dirname "$SCRIPT_DIR")"
SHARED_DIR="$MILESTONE2_DIR/shared"

echo "=========================================="
echo "SAYG-Mem 多Agent验证启动脚本"
echo "=========================================="

# 1. 检查Docker环境
echo "[1/5] 检查Docker环境..."
if ! command -v docker &> /dev/null; then
    echo "错误: Docker未安装"
    exit 1
fi

if ! docker info &> /dev/null; then
    echo "错误: Docker守护进程未运行"
    exit 1
fi

echo "✅ Docker环境正常"

# 2. 创建数据目录
echo "[2/5] 创建数据目录..."
mkdir -p "$MILESTONE2_DIR/data/heaps"
mkdir -p "$MILESTONE2_DIR/data/public_memory"
mkdir -p "$MILESTONE2_DIR/logs"
echo "✅ 数据目录已创建"

# 3. 构建BFF镜像（包含knowledge_manager.py）
echo "[3/5] 构建BFF镜像..."
cd "$SHARED_DIR"

# 检查Dockerfile.bff是否存在
if [ ! -f "Dockerfile.bff" ]; then
    echo "错误: Dockerfile.bff不存在"
    exit 1
fi

# 清理旧容器（如果有）
docker-compose down --remove-orphans 2>/dev/null || true

# 构建镜像
docker build -t nanobot-bff:latest -f Dockerfile.bff .
echo "✅ BFF镜像构建完成"

# 4. 启动BFF服务
echo "[4/5] 启动BFF服务..."
docker-compose up -d bff

# 等待BFF服务就绪
echo "等待BFF服务就绪..."
MAX_WAIT=60
COUNTER=0
while [ $COUNTER -lt $MAX_WAIT ]; do
    if curl -s http://localhost:8000/health > /dev/null 2>&1; then
        echo "✅ BFF服务已就绪"
        break
    fi
    COUNTER=$((COUNTER+1))
    echo "  等待中... ($COUNTER/$MAX_WAIT)"
    sleep 2
done

if [ $COUNTER -eq $MAX_WAIT ]; then
    echo "错误: BFF服务启动超时"
    docker-compose logs bff
    exit 1
fi

# 5. 运行验证脚本
echo "[5/5] 运行验证脚本..."
cd "$MILESTONE2_DIR"

# 检查验证脚本
if [ ! -f "sayg_integration/learn_segments_collab.py" ]; then
    echo "错误: 验证脚本不存在"
    exit 1
fi

# 设置Python环境
if [ -f "$SHARED_DIR/venv/bin/activate" ]; then
    source "$SHARED_DIR/venv/bin/activate"
elif [ -f "$SHARED_DIR/venv_win/Scripts/python.exe" ]; then
    source "$SHARED_DIR/venv_win/Scripts/activate"
fi

# 运行验证脚本
python sayg_integration/learn_segments_collab.py

# 保存退出码
EXIT_CODE=$?

# 显示日志位置
echo ""
echo "=========================================="
echo "验证完成"
echo "=========================================="
echo "退出码: $EXIT_CODE"
echo "报告目录: $MILESTONE2_DIR/logs/"
echo "数据目录: $MILESTONE2_DIR/data/"

# 清理BFF容器（可选）
read -p "是否停止BFF服务? (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    cd "$SHARED_DIR"
    docker-compose down
    echo "BFF服务已停止"
fi

exit $EXIT_CODE
