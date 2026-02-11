#!/bin/bash
# 在回复编辑器中输入文字并提交
# Usage: bash type_and_submit.sh "回复内容"
# Example: bash type_and_submit.sh "好主意！—— kaguya 回复"

REPLY_TEXT="$1"

if [ -z "$REPLY_TEXT" ]; then
  echo "Error: reply text is required"
  echo "Usage: bash type_and_submit.sh \"回复内容\""
  exit 1
fi

# 输入回复内容
agent-browser type '[contenteditable=true].ne-active' "$REPLY_TEXT"
sleep 1

# 提交回复：找到未 disabled 的回复按钮并点击
agent-browser eval 'var btn = Array.from(document.querySelectorAll("button")).find(function(b) { return b.textContent.trim() === "回复" && !b.disabled; }); if (btn) { btn.click(); "submitted"; } else { "no enabled reply button"; }'

agent-browser wait --load networkidle 2>/dev/null
echo "Reply submitted"
