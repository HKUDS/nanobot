# base +dashboard-block-delete

> **前置条件：** 先阅读 [lark-base-dashboard.md](lark-base-dashboard.md) 了解整体工作流。

删除仪表盘中的一个组件（Block），不可恢复。

## 推荐命令

```bash
lark-cli base +dashboard-block-delete \
  --base-token bascn***************CtadY \
  --dashboard-id blkxxx \
  --block-id chtxxxxxxxx
```

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--base-token <token>` | 是 | Base Token |
| `--dashboard-id <id>` | 是 | 仪表盘 ID |
| `--block-id <id>` | 是 | Block ID |
| `--dry-run` | 否 | 预览 API 调用，不执行 |

## 返回示例

```json
{
  "block_id": "chtxxxxxxxx",
  "deleted": true
}
```

## 返回重点

| 字段 | 说明 |
|------|------|
| `block_id` | 被删除的组件 ID |
| `deleted` | 是否删除成功 |

> [!CAUTION]
> 这是**写入操作**且**不可逆** — 执行前必须向用户确认。

## 参考

- [lark-base-dashboard.md](lark-base-dashboard.md) — dashboard 模块指引
