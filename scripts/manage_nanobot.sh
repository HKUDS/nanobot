#!/bin/bash

# --- 配置区域 ---
SERVICE_NAME="com.nanobot.gateway"
PLIST_PATH="$HOME/Library/LaunchAgents/${SERVICE_NAME}.plist"
# 使用 which nanobot 找到的完整路径
NANOBOT_BIN="$(pyenv root)/versions/$(pyenv version-name)/bin/nanobot"
LOG_FILE="$HOME/Library/Logs/nanobot.log"
ERROR_LOG="$HOME/Library/Logs/nanobot.err.log"
# ----------------

install() {
    echo "正在创建 launchd 配置文件..."
    cat <<EOF > "$PLIST_PATH"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${SERVICE_NAME}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${NANOBOT_BIN}</string>
        <string>gateway</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>${LOG_FILE}</string>
    <key>StandardErrorPath</key>
    <string>${ERROR_LOG}</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>$(dirname $NANOBOT_BIN):/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
</dict>
</plist>
EOF
    echo "安装完成。配置文件位于: $PLIST_PATH"
}

start() {
    echo "启动 Nanobot 服务..."
    launchctl load "$PLIST_PATH"
}

stop() {
    echo "停止 Nanobot 服务..."
    launchctl unload "$PLIST_PATH"
}

restart() {
    echo "正在重启 Nanobot 服务..."
    stop
    sleep 1
    start
    echo "重启操作已完成。"
}

uninstall() {
    stop
    echo "移除配置文件..."
    rm -f "$PLIST_PATH"
    echo "卸载完成。"
}

logs() {
    echo "正在查看实时日志 (Ctrl+C 退出)..."
    tail -f "$LOG_FILE" "$ERROR_LOG"
}

case "$1" in
    install) install ;;
    start) start ;;
    stop) stop ;;
    restart) restart ;;
    uninstall) uninstall ;;
    logs) logs ;;
    *) echo "用法: $0 {install|start|stop|uninstall|logs}" ;;
esac