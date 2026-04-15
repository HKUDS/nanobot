# base +record-batch-create

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。

批量创建记录。

## 适用场景（重点）

- 适合大量创建写入场景，例如导入 CSV / Excel、外部系统一次性写入新数据。
- 当输入是长表格或长文本数据时，先按 [lark-base-shortcut-record-value.md](lark-base-shortcut-record-value.md) 做字段映射和类型规范化，再组装 `fields + rows` 调用本命令写入。

## 推荐命令

```bash
lark-cli base +record-batch-create \
  --base-token XXXXXX \
  --table-id tblXXX \
  --json '{"fields":["标题","状态"],"rows":[["任务 A","Open"],["任务 B","Done"]]}'
```

```bash
lark-cli base +record-batch-create \
  --base-token XXXXXX \
  --table-id tblXXX \
  --json @batch-create.json
```

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--base-token <token>` | 是 | Base Token |
| `--table-id <id_or_name>` | 是 | 表 ID 或表名 |
| `--json <body>` | 是 | 批量创建请求体，必须是 JSON 对象。支持直接传 JSON 字符串，或 `@<file_path>` 从文件读取 |

## API 入参详情

**HTTP 方法和路径：**

```http
POST /open-apis/base/v3/bases/:base_token/tables/:table_id/records/batch_create
```

## `--json` 结构

对象形态：`{"fields":[...],"rows":[...]}`。

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `fields` | `string[]` | 是 | 字段 ID 或字段名数组 |
| `rows` | `any[][]` | 是 | 二维数组，每一行按 `fields` 同序给值；单次最多 200 行 |

## 返回重点

`data` 为多行二维数组，与 `+record-list` 返回的多行数据结构一致（按 `fields` 列顺序对齐）。

| 字段 | 类型 | 说明 |
|------|------|------|
| `fields` | `string[]` | 返回的字段名数组 |
| `field_id_list` | `string[]` | 返回的字段 ID 数组 |
| `record_id_list` | `string[]` | 新创建记录 ID 列表 |
| `data` | `any[][]` | 与 `fields` 对齐的多行数据 |
| `ignored_fields` | `array` | 可选，表示被忽略的字段信息 |

## 坑点

- ⚠️ `--json` 必须是对象。
- ⚠️ 写 `rows` 前必须先阅读 [lark-base-shortcut-record-value.md](lark-base-shortcut-record-value.md)，按字段类型填值，禁止按自然语言猜测 value 结构。
- ⚠️ `fields` 与 `rows` 列顺序必须一一对应。
- ⚠️ 空单元格可以显式用 `null` 填充。
- ⚠️ 单次最多 200 行，超出需分批写入。

## 参考

- [lark-base-record.md](lark-base-record.md) — record 索引页
- [lark-base-shortcut-record-value.md](lark-base-shortcut-record-value.md) — 记录值格式规范
