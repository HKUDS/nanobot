---
name: send-ding
description: 通过 AppleScript 自动发送蚂蚁钉/钉钉消息。支持向个人（工号）或群组发送消息。
allowed-tools: Bash
---

# Send Ding

通过 UI 自动化向蚂蚁钉（Antding）发送消息。当用户请求发送钉钉消息、发钉、通知某人时，使用此 skill。

## Instructions

当用户请求发送钉钉消息时：

1. **解析消息目标和内容**
   - 从用户请求中提取收件人（工号、花名或群名）
   - 提取要发送的消息内容
   - 如果信息不完整，询问用户补充

2. **执行发送脚本**
   ```bash
   ~/.claude/skills/send-ding/scripts/send_ding.sh <联系人/群名> <消息内容>
   ```

3. **确认发送结果**
   - 脚本执行成功后，告知用户消息已发送
   - 如果失败，说明可能的原因（权限、应用未启动等）

## Parameters

| 参数 | 说明 | 示例 |
|------|------|------|
| 联系人/群名 | 工号（精确匹配）或花名/群名（模糊匹配） | `221711`、`不狸`、`AI摸鱼社区` |
| 消息内容 | 要发送的文本消息 | `你好，这是测试消息` |

## Examples

### Example 1: 用工号发送消息

**User asks**: "帮我给 221711 发一条钉钉消息：明天的会议改到下午3点"

**What the skill does**:
```bash
~/.claude/skills/send-ding/scripts/send_ding.sh 221711 "明天的会议改到下午3点"
```

### Example 2: 用花名发送消息

**User asks**: "发钉给不狸，内容是：代码已经提交了，麻烦帮忙 review"

**What the skill does**:
```bash
~/.claude/skills/send-ding/scripts/send_ding.sh 不狸 "代码已经提交了，麻烦帮忙 review"
```

### Example 3: 向群组发送消息

**User asks**: "在 AI摸鱼社区 群里发一条消息：今天分享会取消"

**What the skill does**:
```bash
~/.claude/skills/send-ding/scripts/send_ding.sh "AI摸鱼社区" "今天分享会取消"
```

## Prerequisites

- macOS 系统
- 已安装蚂蚁钉（Antding.app）
- 已授予终端/Claude Code「辅助功能」权限（系统设置 → 隐私与安全性 → 辅助功能）

## Best Practices

- 使用工号搜索可精确匹配，避免选错联系人
- 消息内容中如有特殊字符，会自动通过剪贴板处理
- 发送前确认收件人信息正确

## Limitations

- 仅支持 macOS 系统
- 脚本执行期间会切换到蚂蚁钉窗口，请勿操作键盘鼠标
- 如果搜索结果有多个，默认选择第一个
- 需要蚂蚁钉应用保持登录状态
