#!/bin/bash
# 点击第 N 条评论的回复按钮
# Usage: bash click_reply.sh <index>
# Example: bash click_reply.sh 0

INDEX=${1:-0}
MAX_RETRIES=3
RETRY=0

# 1. 滚动到目标评论的可视区域
agent-browser eval "document.querySelectorAll('[class*=rootCommentFloorListItem]')[${INDEX}].scrollIntoView({block: 'center'})"
sleep 0.8

# 2. 获取回复按钮（commentActions-module_actionItem_ 中第一个，即 CommentBubble）的坐标
COORDS=$(agent-browser eval "var item = document.querySelectorAll('[class*=rootCommentFloorListItem]')[${INDEX}]; var btn = item.querySelector('[class*=commentActions-module_actionItem_]'); var r = btn.getBoundingClientRect(); Math.round(r.x + r.width/2) + ',' + Math.round(r.y + r.height/2)")

# 去掉引号
COORDS=$(echo "$COORDS" | tr -d '"')

if [ -z "$COORDS" ] || [ "$COORDS" = "NaN,NaN" ]; then
  echo "Error: could not get reply button coordinates for comment #${INDEX}"
  exit 1
fi

X=$(echo "$COORDS" | cut -d',' -f1)
Y=$(echo "$COORDS" | cut -d',' -f2)
echo "Reply button for comment #${INDEX} at ($X, $Y)"

# 3. 用真实鼠标点击（JS .click() 对语雀无效）
agent-browser mouse move "$X" "$Y"
sleep 0.2
agent-browser mouse down
agent-browser mouse up
sleep 1.5

# 4. 验证回复编辑器已出现，未出现则重试
while [ $RETRY -lt $MAX_RETRIES ]; do
  COUNT=$(agent-browser eval "document.querySelectorAll('[contenteditable=true]').length" 2>/dev/null)
  if echo "$COUNT" | grep -q "2"; then
    echo "Reply editor opened for comment #${INDEX}"
    exit 0
  fi
  RETRY=$((RETRY + 1))
  echo "Retry ${RETRY}/${MAX_RETRIES}: editor not open, re-scrolling and clicking..."

  agent-browser eval "document.querySelectorAll('[class*=rootCommentFloorListItem]')[${INDEX}].scrollIntoView({block: 'center'})"
  sleep 0.8

  COORDS=$(agent-browser eval "var item = document.querySelectorAll('[class*=rootCommentFloorListItem]')[${INDEX}]; var btn = item.querySelector('[class*=commentActions-module_actionItem_]'); var r = btn.getBoundingClientRect(); Math.round(r.x + r.width/2) + ',' + Math.round(r.y + r.height/2)" | tr -d '"')
  X=$(echo "$COORDS" | cut -d',' -f1)
  Y=$(echo "$COORDS" | cut -d',' -f2)

  agent-browser mouse move "$X" "$Y"
  sleep 0.2
  agent-browser mouse down
  agent-browser mouse up
  sleep 1.5
done

echo "Error: failed to open reply editor for comment #${INDEX} after ${MAX_RETRIES} retries"
exit 1
