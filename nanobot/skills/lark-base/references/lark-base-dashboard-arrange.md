# base +dashboard-arrange

> **前置条件：** 先阅读 [lark-base-dashboard.md](lark-base-dashboard.md) 了解整体工作流

自动重新排列仪表盘组件布局。服务端根据组件数量和类型进行智能布局优化。

## 使用场景

| 场景 | 说明 |
|------|------|
| **从 0 到 1 搭建后** | 使用 `+dashboard-create` 和 `+dashboard-block-create` 创建仪表盘后，默认布局可能不够工整美观，推荐使用本命令做一次整体重排 |
| **用户明确要求** | 用户主动要求对已有仪表盘进行布局重排或美化时 |

> [!CAUTION]
> - **不建议**在已有仪表盘上自动调用此命令，除非用户明确要求
> - 排列结果是**服务端智能推荐**，不一定完全符合用户预期
> - 无法指定具体位置（如"第一排放 A，第二排放 B"），排列逻辑是**自适应**的

## 推荐命令

```bash
# 基础用法
lark-cli base +dashboard-arrange \
  --base-token xxx \
  --dashboard-id blk_xxx
```

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--base-token <token>` | 是 | Base Token |
| `--dashboard-id <id>` | 是 | 仪表盘 ID |
| `--user-id-type <type>` | 否 | 用户 ID 类型：open_id / union_id / user_id |
| `--dry-run` | 否 | 预览 API 调用，不执行 |

## 返回示例

```json
{
  "dashboard_id": "blk_xxx",
  "name": "数据分析",
  "blocks": [
    {
      "block_id": "chtbxxxx",
      "block_name": "总销售额",
      "block_type": "statistics",
      "layout": {
        "x": 0,
        "y": 0,
        "w": 6,
        "h": 6
      }
    },
    {
      "block_id": "chtbcrxxxx",
      "block_name": "月度趋势",
      "block_type": "column",
      "layout": {
        "x": 6,
        "y": 0,
        "w": 6,
        "h": 6
      }
    }
  ],
  "arranged": true
}
```

## 返回重点

| 字段 | 说明 |
|------|------|
| `blocks[].layout` | 重排后的布局信息，包含 x/y/w/h |
| `arranged` | 是否重排成功 |

> [!CAUTION]
> 这是**写入操作** — 执行前必须向用户确认。

## 参考

- [lark-base-dashboard.md](lark-base-dashboard.md) — dashboard 模块指引
