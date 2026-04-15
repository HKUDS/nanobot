# base +dashboard-list

> **前置条件：** 先阅读 [lark-base-dashboard.md](lark-base-dashboard.md) 了解整体工作流。

分页列出一个 Base 下的所有仪表盘。常用于：1) 查看当前有哪些仪表盘；2) 获取 dashboard_id 用于后续操作（如添加组件、查看详情）。

## 关键约束

- `+dashboard-list` 禁止并发调用；批量列多个 Base 时必须串行。

## 推荐命令

```bash
lark-cli base +dashboard-list \
  --base-token VwGhb**************fMnod
```

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--base-token <token>` | 是 | Base Token |
| `--page-size <n>` | 否 | 每页数量 |
| `--page-token <token>` | 否 | 分页标记 |
| `--format <fmt>` | 否 | 输出格式：json / pretty / table / csv / ndjson |
| `--dry-run` | 否 | 预览 API 调用，不执行 |

## 返回示例

```json
{
  "items": [
    {"dashboard_id": "blkxxxxxxxxxxxx", "name": "商品总览仪表盘"},
    {"dashboard_id": "blkxxxxxxxxxxxx", "name": "订单总览仪表盘"},
    {"dashboard_id": "blkxxxxxxxxxxxx", "name": "销售数据分析仪表盘"}
  ],
  "total": 3,
  "has_more": false
}
```

## 返回重点

| 字段 | 说明 |
|------|------|
| `items` | 仪表盘列表，每项包含 `dashboard_id`（ID）和 `name`（名称）|
| `total` | 总数 |
| `has_more` | 是否有下一页（为 `true` 时需用 `page_token` 继续获取）|

## 参考

- [lark-base-dashboard.md](lark-base-dashboard.md) — dashboard 模块指引
