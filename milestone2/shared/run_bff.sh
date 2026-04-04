#!/bin/bash
# 启动 BFF 服务 (WSL/Linux) - 自动激活虚拟环境

set -e

echo "=== 启动 Nanobot BFF 服务 ==="

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_DIR="$PROJECT_ROOT/venv"

if [ -d "$VENV_DIR" ]; then
    source "$VENV_DIR/bin/activate"
    echo "[虚拟环境] 已激活: $VENV_DIR"
else
    echo "[警告] 未找到虚拟环境: $VENV_DIR"
    echo "[提示] 运行: python3 -m venv venv"
fi

export PYTHONPATH="${PROJECT_ROOT}:${PYTHONPATH}"
export DEEPSEEK_API_KEY="${DEEPSEEK_API_KEY:-sk-b192d1bf26f740adace7d5f628656921}"
export DASHSCOPE_API_KEY="${DASHSCOPE_API_KEY:-sk-91fe1c9c529b46bb88dc200a2e97b2b6}"

cd "$PROJECT_ROOT"

echo "PYTHONPATH: ${PYTHONPATH}"
echo "DEEPSEEK_API_KEY: ${DEEPSEEK_API_KEY:0:10}..."

python3 -m bff.bff_service
