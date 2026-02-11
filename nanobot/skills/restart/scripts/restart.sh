#!/bin/bash
# nanobot 自重启脚本
# 使用 setsid 脱离父进程，确保 nanobot 被 kill 后脚本仍能继续执行

LOG_FILE="${HOME}/.nanobot/restart.log"
WAIT_BEFORE_KILL=${1:-2}
WAIT_BEFORE_START=${2:-10}

echo "=== nanobot restart ===" >> "$LOG_FILE"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Restart script started" >> "$LOG_FILE"

# 获取当前 nanobot gateway 进程 PID
OLD_PID=$(pgrep -f "nanobot gateway" | head -1)

if [ -z "$OLD_PID" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: No nanobot gateway process found" >> "$LOG_FILE"
    exit 1
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Found nanobot gateway PID: $OLD_PID" >> "$LOG_FILE"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Waiting ${WAIT_BEFORE_KILL}s before kill..." >> "$LOG_FILE"
sleep "$WAIT_BEFORE_KILL"

# Kill 旧进程
kill "$OLD_PID" 2>/dev/null
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Killed PID $OLD_PID" >> "$LOG_FILE"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Waiting ${WAIT_BEFORE_START}s before restart..." >> "$LOG_FILE"
sleep "$WAIT_BEFORE_START"

# 启动新进程
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting nanobot gateway..." >> "$LOG_FILE"
nohup nanobot gateway >> "$LOG_FILE" 2>&1 &
NEW_PID=$!
echo "[$(date '+%Y-%m-%d %H:%M:%S')] New nanobot gateway started with PID: $NEW_PID" >> "$LOG_FILE"
