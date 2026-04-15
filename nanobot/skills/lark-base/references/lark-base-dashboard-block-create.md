# base +dashboard-block-create

> **前置条件：** 先阅读 [lark-base-dashboard.md](lark-base-dashboard.md) 了解整体工作流
> **关键：** 创建前必须阅读 [dashboard-block-data-config.md](dashboard-block-data-config.md) 了解组件类型和 data_config 结构

在仪表盘中创建一个组件（Block）。

## 关键约束

- **`type` 创建后不可修改**，创建时务必选对
- **`data_config` 结构随 `type` 变化**，不同组件类型字段不同，**⚠️ 必须阅读 [dashboard-block-data-config.md](dashboard-block-data-config.md) 了解如何构造**
- **组件创建必须串行执行**，不能并发

## 推荐命令

```bash
# 简单示例：创建一个指标卡（统计记录数）
lark-cli base +dashboard-block-create \
  --base-token xxx \
  --dashboard-id blk_xxx \
  --name "总记录数" \
  --type statistics \
  --data-config '{"table_name":"订单表","count_all":true}'

# 文本组件示例（Markdown 富文本）
lark-cli base +dashboard-block-create \
  --base-token xxx \
  --dashboard-id blk_xxx \
  --name "说明文字" \
  --type text \
  --data-config '{"text":"# 标题\n## 副标题\n**加粗** *斜体* ~~删除~~\n1. 列表1\n2. 列表2"}'

# 复杂配置用文件传入
lark-cli base +dashboard-block-create \
  --base-token xxx \
  --dashboard-id blk_xxx \
  --name "销售额趋势" \
  --type line \
  --data-config @config.json
```

完整流程参考 [lark-base-dashboard.md](lark-base-dashboard.md) 的「场景 1：从 0 到 1 创建仪表盘」

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--base-token <token>` | 是 | Base Token |
| `--dashboard-id <id>` | 是 | 仪表盘 ID（从 `+dashboard-list/get` 获取） |
| `--name <name>` | **是** | 组件名称（允许重名） |
| `--type <type>` | **是** | 组件类型，见下方枚举值。**不同 type 对应不同的 data_config 结构**，常用：`column`(柱状图)、`line`(折线图)、`pie`(饼图)、`statistics`(指标卡)、`text`(文本) |
| `--data-config <json>` | 否 | 数据配置 JSON，**结构随 type 变化**。**⚠️ 必须阅读 [dashboard-block-data-config.md](dashboard-block-data-config.md) 了解如何构造**。创建时会做本地校验，更新时由后端校验 |
| `--user-id-type <type>` | 否 | 用户 ID 类型，filter 涉及人员字段时使用 |
| `--dry-run` | 否 | 预览 API 调用，不执行 |

### type 枚举值

| 值 | 说明 |
|----|------|
| `column` | 柱状图 |
| `bar` | 条形图 |
| `line` | 折线图 |
| `pie` | 饼图 |
| `ring` | 环形图 |
| `area` | 面积图 |
| `combo` | 组合图 |
| `scatter` | 散点图 |
| `funnel` | 漏斗图 |
| `wordCloud` | 词云 |
| `radar` | 雷达图 |
| `statistics` | 指标卡 |
| `text` | 文本（支持 Markdown） |

## 返回示例

```json
{
  "block": {
    "block_id": "chtxxxxxxxx",
    "name": "总记录数",
    "type": "statistics",
    "data_config": {
      "table_name": "电商交易明细",
      "count_all": true
    }
  },
  "created": true
}
```

## 返回重点

| 字段 | 说明 |
|------|------|
| `block.block_id` | 组件 ID，后续编辑/删除需要用到，务必记录 |
| `block.name` | 组件名称 |
| `block.type` | 组件类型 |
| `block.data_config` | 实际创建的数据配置（可能包含后端自动添加的默认值）|
| `created` | 是否创建成功 |

> [!CAUTION]
> 这是**写入操作** — 执行前必须向用户确认。


## 参考

- [lark-base-dashboard.md](lark-base-dashboard.md) — dashboard 模块指引
- [dashboard-block-data-config.md](dashboard-block-data-config.md) — data_config 结构、图表类型、filter 规则
