#!/bin/bash
# SAYG-Mem 工程验证 - 运行验证脚本 v4
# 使用方法: bash run_validation_v4.sh

set -e

SCRIPT_DIR="/mnt/d/collections2026/phd_application/nanobot1/milestone2/sayg_integration"
MILESTONE2_DIR="/mnt/d/collections2026/phd_application/nanobot1/milestone2"
VENV_DIR="$MILESTONE2_DIR/shared/venv"

echo "============================================"
echo "SAYG-Mem: 运行验证脚本 v4 (真实CWW)"
echo "============================================"

cd "$SCRIPT_DIR"

if [ ! -d "$VENV_DIR" ]; then
    echo "错误: venv目录不存在: $VENV_DIR"
    exit 1
fi

echo "激活虚拟环境..."
source "$VENV_DIR/bin/activate"

echo "当前Python: $(which python)"
echo ""
echo "注意: 请确保BFF服务已在另一个终端运行"
echo "      运行命令: bash run_bff.sh"
echo ""
echo "等待2秒后开始..."
sleep 2

python validate_engineering_v4.py
