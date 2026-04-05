#!/bin/bash
# Nanobot BFF 启动脚本 (WSL)

cd /mnt/d/collections2026/phd_application/nanobot1/milestone2

# 激活虚拟环境
source shared/venv/bin/activate

# 设置 PYTHONPATH
export PYTHONPATH=/mnt/d/collections2026/phd_application/nanobot1/milestone2

# 取消代理
unset http_proxy https_proxy

echo "🐈 启动 Nanobot BFF 服务..."
echo "📁 项目根目录：$PWD"
echo ""

# 启动 BFF 服务
python -m bff.bff_service
