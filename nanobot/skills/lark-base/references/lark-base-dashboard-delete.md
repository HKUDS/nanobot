# base +dashboard-delete

> **前置条件：** 先阅读 [lark-base-dashboard.md](lark-base-dashboard.md) 了解整体工作流。

删除仪表盘（会同时删除其下所有组件，不可恢复）。

## 推荐命令

```bash
lark-cli base +dashboard-delete \
  --base-token VwGhb**************fMnod \
  --dashboard-id blkxxxxxxx
```

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--base-token <token>` | 是 | Base Token |
| `--dashboard-id <id>` | 是 | 仪表盘 ID |
| `--dry-run` | 否 | 预览 API 调用，不执行 |

## 返回示例

```json
{
  "dashboard_id": "blkxxxxxxxxxxxx",
  "deleted": true
}
```

## 返回重点

| 字段 | 说明 |
|------|------|
| `dashboard_id` | 被删除的仪表盘 ID |
| `deleted` | 是否删除成功 |

> [!CAUTION]
> 这是**写入操作**且**不可逆** — 执行前必须向用户确认。删除仪表盘会同时删除其下所有组件，不可恢复。

## 参考

- [lark-base-dashboard.md](lark-base-dashboard.md) — dashboard 模块指引
