# base +dashboard-get

> **前置条件：** 先阅读 [lark-base-dashboard.md](lark-base-dashboard.md) 了解整体工作流。

获取仪表盘详情（名称、主题配置、包含的所有组件列表）。常用于：1) 查看仪表盘有哪些组件；2) 获取组件 ID 用于后续编辑/删除。

## 推荐命令

```bash
lark-cli base +dashboard-get \
  --base-token VwGhb**************fMnod \
  --dashboard-id blkxxxxxxx
```

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--base-token <token>` | 是 | Base Token |
| `--dashboard-id <id>` | 是 | 仪表盘 ID |
| `--format <fmt>` | 否 | 输出格式 |
| `--dry-run` | 否 | 预览 API 调用，不执行 |

## 返回示例

```json
{
  "dashboard_id": "blkxxxxxxxxxxxx",
  "name": "数据分析仪表盘",
  "theme": {
    "theme_style": "default"
  },
  "blocks": [
    {
      "block_id": "chtxxxxxxxx",
      "block_name": "总净利润",
      "block_type": "statistics"
    },
    {
      "block_id": "chtxxxxxxxx",
      "block_name": "品类占比",
      "block_type": "pie"
    }
  ]
}
```

## 返回重点

| 字段 | 类型 | 说明 |
|------|------|------|
| `dashboard_id` | string | 仪表盘 ID（如 `blkxxxxxxxxxxxx`）|
| `name` | string | 仪表盘名称 |
| `theme.theme_style` | string | 主题风格：`default` / `SimpleBlue` / `DarkGreen` / `summerBreeze` / `simplistic` / `energetic` / `deepDark` / `futuristic` |
| `blocks` | []object | 组件列表，每项包含 `block_id`（组件ID）、`block_name`（名称）、`block_type`（类型，如 `column`/`line`/`pie`）|

## 参考

- [lark-base-dashboard.md](lark-base-dashboard.md) — dashboard 模块指引
