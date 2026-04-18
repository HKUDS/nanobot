#!/bin/bash
# SAYG-Mem 工程验证 - 启动BFF服务
# 使用方法: bash run_bff.sh

set -e

MILESTONE2_DIR="/mnt/d/collections2026/phd_application/nanobot1/milestone2"
VENV_DIR="$MILESTONE2_DIR/shared/venv"

echo "============================================"
echo "SAYG-Mem: 启动BFF服务"
echo "============================================"

cd "$MILESTONE2_DIR"

if [ ! -d "$VENV_DIR" ]; then
    echo "错误: venv目录不存在: $VENV_DIR"
    exit 1
fi

echo "激活虚拟环境..."
source "$VENV_DIR/bin/activate"

echo "当前Python: $(which python)"
echo "BFF服务将在 http://localhost:8000 启动"
echo ""
echo "按 Ctrl+C 停止服务"
echo "============================================"

python -m bff.bff_service
