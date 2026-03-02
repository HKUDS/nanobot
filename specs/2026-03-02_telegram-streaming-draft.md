# Telegram Streaming Response via sendMessageDraft

## 背景

- Telegram Bot API 9.3 引入了 `sendMessageDraft` 方法，允许 bot 在生成消息时流式推送部分文本给用户
- Bot API 9.5（2026-03-01）已对所有 bot 开放此功能
- 当前 nanobot 的 LLM 调用是非流式的（一次性返回完整响应），Telegram channel 收到完整文本后才发送
- `python-telegram-bot` 22.6 已支持 `Bot.send_message_draft()` 方法

## 目标

在 Telegram channel 中实现流式响应：LLM 生成 token 时，通过 `sendMessageDraft` 实时推送部分文本给用户，生成完毕后调用 `sendMessage` 发送最终消息。

## 技术约束

### sendMessageDraft API 签名
```python
Bot.send_message_draft(
    chat_id: int,        # 目标私聊 ID
    draft_id: int,       # 草稿唯一 ID（非零），相同 ID 的变更会有动画效果
    text: str,           # 部分消息文本（1-4096 字符）
    parse_mode: str,     # 可选，Markdown/HTML
    entities: list,      # 可选
)
```

### 限制
- **仅支持私聊**，不支持群组
- text 长度 1-4096 字符
- 返回 True on success

### 当前架构
- LLM provider (`litellm_provider.py`) 当前使用 `acompletion()` 非流式调用
- `AgentLoop` 在 `loop.py` 中调用 provider，获取完整响应后通过 `MessageBus` 发送 `OutboundMessage`
- `TelegramChannel.send()` 接收 `OutboundMessage` 并发送到 Telegram

## 需要改动的模块

1. **LLM Provider** — 支持 streaming 模式（`stream=True`），返回 async iterator
2. **AgentLoop** — 在 streaming 模式下，将 token chunks 通过某种机制（callback/bus event）推送给 channel
3. **TelegramChannel** — 接收 streaming chunks，调用 `sendMessageDraft` 推送，最后 `sendMessage` 发送最终消息
4. **OutboundMessage / MessageBus** — 可能需要新增 streaming event 类型

## 验收标准

- [ ] Telegram 私聊中，bot 回复时用户能看到实时打字效果（sendMessageDraft）
- [ ] 群组中行为不变（无 streaming，直接发送完整消息）
- [ ] 最终消息通过 sendMessage 发送，格式正确（HTML）
- [ ] streaming 过程中的 draft 不需要完整 HTML 格式化（可以是纯文本）
- [ ] 如果 sendMessageDraft 调用失败，graceful fallback 到非流式模式
- [ ] 不影响现有的 tool call 流程（tool call 期间不需要 streaming）
- [ ] lint / tsc 通过
- [ ] 代码有适当的日志记录
