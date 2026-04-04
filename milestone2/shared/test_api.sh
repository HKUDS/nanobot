#!/bin/bash
# 在 WSL 中测试 API (curl)

set -e

BFF_URL="${BFF_URL:-http://localhost:8000}"

echo "=== Nanobot BFF API 测试 ==="

echo -e "\n--- 1. 健康检查 ---"
curl -s "${BFF_URL}/health" | python3 -m json.tool

echo -e "\n--- 2. 创建对话 ---"
RESPONSE=$(curl -s -X POST "${BFF_URL}/conversations" \
  -H "Content-Type: application/json" \
  -d '{"title": "测试任务", "model": "deepseek-chat"}')
echo "$RESPONSE" | python3 -m json.tool
CONV_ID=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['conversation_id'])")
echo "Conversation ID: $CONV_ID"

echo -e "\n--- 3. 发送消息 ---"
curl -s -X POST "${BFF_URL}/conversations/${CONV_ID}/messages" \
  -H "Content-Type: application/json" \
  -d '{"content": "你好，你能做什么？"}' | python3 -m json.tool

echo -e "\n--- 4. 获取轨迹 ---"
curl -s "${BFF_URL}/conversations/${CONV_ID}/trajectory" | python3 -m json.tool

echo -e "\n--- 5. 获取历史 ---"
curl -s "${BFF_URL}/conversations/${CONV_ID}/history" | python3 -m json.tool

echo -e "\n=== 测试完成 ==="
