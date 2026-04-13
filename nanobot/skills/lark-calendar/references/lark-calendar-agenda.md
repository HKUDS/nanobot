
# calendar +agenda

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。

查看近期日程安排。只读操作，不修改任何日程。

需要的scopes: ["calendar:calendar.event:read"]

## 命令

```bash
# 查看今天日程（默认）
lark-cli calendar +agenda

# 自定义时间范围（ISO 8601）
lark-cli calendar +agenda --start "2026-03-10T00:00+08:00" --end "2026-03-17T00:00+08:00"

# 自定义时间范围（仅日期）
lark-cli calendar +agenda --start 2026-03-10 --end 2026-03-17

# 人类可读格式输出
lark-cli calendar +agenda --format pretty

# 指定日历
lark-cli calendar +agenda --calendar-id cal_xxx
```

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--start <time>` | 否 | 开始时间（ISO 8601 或仅日期，默认当天） |
| `--end <time>` | 否 | 结束时间（默认与 `--start` 属于同一天，自动取当天结束时间） |
| `--calendar-id <id>` | 否 | 日历 ID（省略则使用主日历） |
| `--format` | 否 | 输出格式：json（默认） \| pretty |
| `--dry-run` | 否 | 预览 API 调用，不执行 |

## 时间格式

`--start` 和 `--end` 支持以下格式：

| 格式 | 示例 | 说明 |
|------|------|------|
| ISO 8601 | `2026-03-10T14:00:00+08:00` | 完整格式 |
| 日期+时间 | `2026-03-10 14:00:00` | 自动补全时区 |
| 仅日期 | `2026-03-10` | start 取 00:00:00，end 取 23:59:59 |
| Unix 时间戳 | `1741564800` | 秒级时间戳 |

## 输出格式

**将结果整理为易读的日程表：**

```
## 2026-03-10 周一

09:00 - 09:30  站会
10:00 - 11:00  产品评审
14:00 - 15:00  与 Alice 1:1

## 2026-03-11 周二

（无日程）
```

**注意：按日期分组，并严格按照开始时间升序（从早到晚的时间线）排序输出。** 显示标题、时长

## 提示

- 已取消的日程会自动过滤，无需额外处理。
- 如无日程，告知用户"日程清空"。
- 大于 40 天的时间范围会自动拆分查询并合并结果。
- 查看多个日历：先用 `lark-cli calendar calendars list --page-all` 列出日历列表，再逐个查询。

## 参考

- [lark-calendar](../SKILL.md) -- 日历全部命令
- [lark-shared](../../lark-shared/SKILL.md) -- 认证和全局参数
