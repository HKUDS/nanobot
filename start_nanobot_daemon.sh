#!/bin/bash

# nanobot 守护进程启动脚本
# 用法: ./start_nanobot_daemon.sh

cd "$(dirname "$0")"

echo "🐈 启动 nanobot (守护进程模式)..."
echo "配置文件: ~/.nanobot/config.json"
echo "模型: Claude Sonnet 4.6"
echo ""

# 检查是否已经在运行
if pgrep -f "nanobot gateway" > /dev/null; then
    echo "⚠️  nanobot 已经在运行中"
    ps aux | grep "nanobot gateway" | grep -v grep
    exit 1
fi

# 激活虚拟环境
source venv/bin/activate

# 使用 nohup 启动网关，输出到日志文件
echo "🐈 Starting nanobot gateway on port 18790..."
nohup nanobot gateway > /tmp/nanobot_startup.log 2>&1 &

# 获取进程 ID
NANOBOT_PID=$!
echo "✓ Nanobot 已启动 (PID: $NANOBOT_PID)"
echo "✓ 日志文件: /tmp/nanobot_startup.log"
echo ""
echo "查看日志: tail -f /tmp/nanobot_startup.log"
echo "停止服务: pkill -f 'nanobot gateway'"
