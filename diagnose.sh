#!/bin/bash

echo "🔍 nanobot 飞书连接诊断"
echo "================================"
echo ""

# 检查进程
echo "1. 检查 nanobot 进程状态："
if ps aux | grep -E "nanobot gateway" | grep -v grep > /dev/null; then
    echo "   ✅ nanobot gateway 正在运行"
    ps aux | grep -E "nanobot gateway" | grep -v grep | awk '{print "   进程 ID:", $2, "运行时间:", $10}'
else
    echo "   ❌ nanobot gateway 未运行"
fi
echo ""

# 检查配置
echo "2. 检查飞书配置："
if grep -q '"enabled": true' ~/.nanobot/config.json | grep -A 5 feishu; then
    echo "   ✅ 飞书频道已启用"
else
    echo "   ❌ 飞书频道未启用"
fi

APP_ID=$(grep -A 5 '"feishu"' ~/.nanobot/config.json | grep appId | cut -d'"' -f4)
if [ ! -z "$APP_ID" ]; then
    echo "   ✅ App ID: $APP_ID"
else
    echo "   ❌ App ID 未配置"
fi
echo ""

# 检查端口
echo "3. 检查网关端口："
if lsof -i :18790 > /dev/null 2>&1; then
    echo "   ✅ 端口 18790 正在监听"
else
    echo "   ⚠️  端口 18790 未监听（WebSocket 模式不需要）"
fi
echo ""

# 检查网络连接
echo "4. 检查飞书 WebSocket 连接："
if lsof -i -n | grep -i python | grep -i established | grep -q feishu; then
    echo "   ✅ 已建立到飞书服务器的连接"
else
    echo "   ⚠️  未检测到活跃的飞书连接"
fi
echo ""

# 检查最近的日志
echo "5. 最近的活动（最后 10 行进程输出）："
echo "   提示：如果看不到日志，请在终端中直接运行 'nanobot gateway' 查看实时输出"
echo ""

echo "================================"
echo "💡 故障排查建议："
echo ""
echo "1. 如果 nanobot 未运行，执行："
echo "   cd /Users/samsonchoi/AI_Workspace2/nanobot"
echo "   source venv/bin/activate"
echo "   nanobot gateway"
echo ""
echo "2. 在飞书中测试："
echo "   - 搜索你的机器人名称"
echo "   - 发送一条消息"
echo "   - 查看终端输出是否有收到消息的日志"
echo ""
echo "3. 检查飞书应用配置："
echo "   - 确认应用已发布"
echo "   - 确认添加了权限：im:message, im:message.p2p_msg:readonly"
echo "   - 确认事件订阅：im.message.receive_v1（长连接模式）"
echo ""
echo "4. 查看实时日志："
echo "   在新终端窗口运行 'nanobot gateway' 可以看到详细的调试信息"
