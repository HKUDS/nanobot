# calendar +rsvp

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。

回复指定的日程，更新当前用户的 RSVP 状态（接受、拒绝或待定）。

需要的scopes: ["calendar:calendar.event:reply"]

## 命令

```bash
# 回复日程为接受 (使用主日历)
lark-cli calendar +rsvp --event-id evt_xxx --rsvp-status accept

# 回复日程为拒绝
lark-cli calendar +rsvp --event-id evt_xxx --rsvp-status decline

# 回复日程为待定
lark-cli calendar +rsvp --event-id evt_xxx --rsvp-status tentative

# 指定其他日历下的日程
lark-cli calendar +rsvp --calendar-id cal_xxx --event-id evt_xxx --rsvp-status accept
```

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--event-id <id>` | **是** | 日程 ID |
| `--rsvp-status <status>` | **是** | 回复状态，可选值：`accept` (接受), `decline` (拒绝), `tentative` (待定) |
| `--calendar-id <id>` | 否 | 日历 ID（省略则使用主日历） |
| `--dry-run` | 否 | 预览 API 调用，不执行 |

## 提示

- 只能回复你被邀请的日程。
- 调用前通常需要通过 `+agenda` 等命令获取到具体的 `event-id`。

## 参考

- [lark-calendar](../SKILL.md) -- 日历全部命令
- [lark-shared](../../lark-shared/SKILL.md) -- 认证和全局参数
