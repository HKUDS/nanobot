#!/bin/bash

# nanobot 启动脚本
# 用法: ./start_nanobot.sh

cd "$(dirname "$0")"

echo "🐈 启动 nanobot..."
echo "配置文件: ~/.nanobot/config.json"
echo "模型: Claude Sonnet 4.6"
echo ""

# 激活虚拟环境
source venv/bin/activate

# 启动网关
nanobot gateway
