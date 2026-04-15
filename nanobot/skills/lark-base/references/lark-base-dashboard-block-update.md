# base +dashboard-block-update

> **前置条件：** 先阅读 [lark-base-dashboard.md](lark-base-dashboard.md) 了解整体工作流
> **关键：** 更新前必须阅读 [dashboard-block-data-config.md](dashboard-block-data-config.md) 了解 data_config 结构和更新规则

更新仪表盘中组件的名称或数据配置。

## 关键约束

- **不可修改 `type` 和 `layout`** — 只能更新 `name` 和 `data_config`。
- **`data_config` 顶层按 key merge** — 只需传入要修改的顶层字段，未传的字段保留原值；但每个字段内部是全量替换（如传新 `filter` 会完整覆盖旧 `filter`）。
- **`series` 与 `count_all` 二选一** — 且至少提供其一。
- **表名用 name，不是 ID** — `table_name` 对应的是表名称（如「订单表」），不是 `table_id`。
- **`user_id_type`** 仅在 filter 涉及人员字段时有意义。

> [!TIP]
> CLI 默认会对 `data_config` 做轻量校验与规范化；如需兼容特殊场景，可加 `--no-validate` 跳过。

## 推荐命令

```bash
# 示例 1：更新组件名称
lark-cli base +dashboard-block-update \
  --base-token xxx \
  --dashboard-id blk_xxx \
  --block-id chtxxxxxxxx \
  --name "新名称"

# 示例 2：更新数据配置（只传要改的字段，未传字段保留原值）
lark-cli base +dashboard-block-update \
  --base-token xxx \
  --dashboard-id blk_xxx \
  --block-id chtxxxxxxxx \
  --data-config '{"filter":{"conjunction":"and","conditions":[{"field_name":"状态","operator":"is","value":"已完成"}]}}'
```

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--base-token <token>` | 是 | Base Token |
| `--dashboard-id <id>` | 是 | 仪表盘 ID |
| `--block-id <id>` | 是 | Block ID |
| `--name <name>` | 否 | 新名称 |
| `--data-config <json>` | 否 | 数据配置 JSON。**结构随 block 的 `type` 变化**。**⚠️ 必须阅读 [dashboard-block-data-config.md](dashboard-block-data-config.md) 了解如何构造** |
| `--user-id-type <type>` | 否 | 用户 ID 类型，filter 涉及人员字段时使用 |
| `--no-validate` | 否 | 跳过 data_config 本地校验（用于兼容特殊场景） |
| `--dry-run` | 否 | 预览 API 调用，不执行 |

## 返回示例

```json
{
  "block": {
    "block_id": "chtxxxxxxxx",
    "name": "新名称",
    "type": "column",
    "data_config": {
      "table_name": "订单表",
      "series": [{"field_name": "金额", "rollup": "SUM"}],
      "group_by": [{"field_name": "类别", "mode": "integrated"}]
    }
  },
  "updated": true
}
```

## 返回重点

| 字段 | 说明 |
|------|------|
| `block.block_id` | 组件 ID |
| `block.name` | 更新后的名称 |
| `block.type` | 组件类型（不可修改）|
| `block.data_config` | 更新后的数据配置 |
| `updated` | 是否更新成功 |

> [!CAUTION]
> 这是**写入操作** — 执行前必须向用户确认。

## 参考

- [lark-base-dashboard.md](lark-base-dashboard.md) — dashboard 模块指引
- [dashboard-block-data-config.md](dashboard-block-data-config.md) — data_config 结构、图表类型、filter 规则
