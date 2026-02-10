#!/bin/bash
# 发送蚂蚁钉消息
# 使用方法: ./send_ding.sh <联系人/群名> <消息内容>
# 示例: ./send_ding.sh 221711 "你好，我喜欢你"

TARGET="${1:-}"
MESSAGE="${2:-}"

if [ -z "$TARGET" ] || [ -z "$MESSAGE" ]; then
    echo "使用方法: $0 <联系人/群名> <消息内容>"
    echo "示例: $0 221711 \"你好，我喜欢你\""
    exit 1
fi

osascript <<EOF
-- 激活 Antding 并等待确认前台
tell application "Antding" to activate
delay 1

-- 循环等待直到 Antding 成为前台应用
tell application "System Events"
    repeat 10 times
        if frontmost of process "DingTalk" then exit repeat
        delay 0.2
    end repeat
end tell

-- Antding 已在前台，关闭可能的弹窗
tell application "System Events"
    tell process "DingTalk"
        key code 53
    end tell
end tell
delay 0.3

-- 设置剪贴板并搜索
set the clipboard to "$TARGET"

tell application "System Events"
    tell process "DingTalk"
        keystroke "f" using command down
        delay 0.8
        keystroke "v" using command down
        delay 1.5
        keystroke return
        delay 1
    end tell
end tell

-- 发送消息
set the clipboard to "$MESSAGE"
tell application "System Events"
    keystroke "v" using command down
    delay 0.3
    keystroke return
end tell
EOF

echo "消息已发送给 $TARGET"
