# 企业微信应用图片发送功能补丁

## 背景
企业微信应用（wechat_bridge）收到消息后，当 agent 调用 `message` 工具发送图片时，由于 `wechat` 不是已注册的渠道，图片发送失败。本补丁解决了这个问题。

## 修改的文件

| 文件 | 位置 | 修改量 |
|------|------|--------|
| `commands.py` | `.venv/lib/.../site-packages/nanobot/cli/` | +50 行 |
| `wechat_bridge.py` | `scripts/bridge/` | +28 行, -12 行 |

---

## 1. commands.py 修改详情

### 新增变量
```python
pending_outbound: dict[str, list[dict]] = {}
```
跟踪待发送的出站消息，key 为 `channel:chat_id`。

### 新增函数 `capture_unknown_channel_outbound()`
```python
async def capture_unknown_channel_outbound():
    """捕获发送到未知渠道的出站消息"""
    while True:
        try:
            msg = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
            # 只捕获未注册渠道的消息
            if msg.channel not in channels.enabled_channels:
                session_key = f"{msg.channel}:{msg.chat_id}"
                if session_key in pending_outbound:
                    pending_outbound[session_key].append({
                        "content": msg.content,
                        "media": msg.media,
                    })
        except asyncio.TimeoutError:
            continue
        ...
```

### 修改 `handle_message()` 返回值
```python
# 修改前
return web.json_response({"response": response or ""})

# 修改后
return web.json_response({
    "response": response or "",
    "media": media_paths  # 新增：媒体文件路径列表
})
```

### 启动捕获任务
```python
# 在 run() 的 asyncio.gather() 中添加
await asyncio.gather(
    agent.run(),
    channels.start_all(),
    capture_unknown_channel_outbound(),  # 新增
)
```

---

## 2. wechat_bridge.py 修改详情

### 修改 `chat()` 方法返回类型
```python
# 修改前
async def chat(self, message: str, user_id: str, channel: str = "wechat") -> str:
    ...
    return response if response else "（无回复）"

# 修改后
async def chat(self, message: str, user_id: str, channel: str = "wechat") -> tuple[str, list[str]]:
    """返回 (response_text, media_paths)"""
    ...
    response = data.get("response", "")
    media = data.get("media", [])
    return (response if response else "（无回复）", media)
```

### 修改 `process()` 方法处理媒体
```python
# 修改前
response = await self.nanobot.chat(content, user_id)
await self.wechat.send_text(response, user_id)
# 从文本提取文件路径发送

# 修改后
response, media_paths = await self.nanobot.chat(content, user_id)
await self.wechat.send_text(response, user_id)

# 优先发送 API 返回的媒体文件
for file_path in media_paths:
    if os.path.exists(file_path):
        success = await self.wechat.send_file(file_path, user_id)
        ...

# 兼容旧模式：从回复文本提取文件路径
files = FileHandler.extract_file_paths(response)
for file_path, ext in files:
    if file_path not in media_paths:  # 避免重复发送
        ...
```

---

## 工作流程

```
用户消息: "发张图片"
       ↓
wechat_bridge → HTTP API → gateway
       ↓
agent 调用 message 工具 (channel="wechat", media=["/path/image.jpg"])
       ↓
capture_unknown_channel_outbound() 捕获消息
       ↓
HTTP API 返回 {"response": "...", "media": ["/path/image.jpg"]}
       ↓
wechat_bridge 提取 media 路径
       ↓
上传图片到企业微信 → 发送给用户
```

---

## 应用方法

### commands.py
```bash
cp archive/site-packages-patch/commands.py.patched \
   .venv/lib/python3.12/site-packages/nanobot/cli/commands.py
```

### wechat_bridge.py
已在 git 中，无需手动应用。

---

## 注意事项

1. **commands.py** 在 site-packages 中，nanobot 包更新后需重新应用补丁
2. 修改后需重启 gateway 服务：`pkill -f "nanobot gateway" && .venv/bin/nanobot gateway &`
3. 修改后需重启 wechat_bridge：`pkill -f "wechat_bridge" && .venv/bin/python scripts/bridge/wechat_bridge.py &`

## 日期
2026-03-15
