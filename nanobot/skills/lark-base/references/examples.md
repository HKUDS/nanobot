# 飞书多维表格使用场景完整示例（base）

本文档提供基于 `lark-cli base ...` 的完整示例，覆盖 unified Shortcut 与当前 `base/v3` 原生 API 的常见组合方式。

> **返回**: [SKILL.md](../SKILL.md) | **参考**: [shortcut 字段 JSON 规范](lark-base-shortcut-field-properties.md) · [shortcut 记录值规范](lark-base-shortcut-record-value.md)

---

## 场景 1：用 unified Shortcut 快速建表

适合已经明确字段结构、希望一次性完成建表的场景。

```bash
lark-cli base +table-create \
  --base-token bascnXXXXXXXX \
  --name "客户管理表" \
  --fields '[
    {"name":"客户名称","type":"text"},
    {"name":"负责人","type":"user","property":{"multiple":false}},
    {"name":"签约日期","type":"datetime"},
    {"name":"状态","type":"single_select","property":{"options":["进行中","已完成"]}}
  ]'
```

---

## 场景 2：使用原生 API 创建数据表并查看字段

适合需要精确观察 `base/v3` 请求参数和响应结构的场景。原生 API 直接使用 `base` service。

### 步骤 1：在已有 Base 中创建数据表

```bash
lark-cli base tables create \
  --params '{"base_token":"bascnXXXXXXXX"}' \
  --data '{"name":"客户管理表"}'
```

### 步骤 2：列出字段

```bash
lark-cli base table.fields list \
  --params '{"base_token":"bascnXXXXXXXX","table_id":"tblXXXXXXXX","limit":100}'
```

> 提示：当前 `base/v3` 不再使用旧的 `app_token` / `app.table.*` 路径，统一改为 `base_token` + `tables` / `table.fields` / `table.records`。

---

## 场景 3：创建、读取、更新单条记录

### 新增记录

```bash
lark-cli base table.records create \
  --params '{"base_token":"bascnXXXXXXXX","table_id":"tblXXXXXXXX"}' \
  --data '{
    "客户名称":"字节跳动",
    "负责人":[{"id":"ou_xxx"}],
    "状态":"进行中"
  }'
```

### 列出记录

```bash
lark-cli base table.records list \
  --params '{"base_token":"bascnXXXXXXXX","table_id":"tblXXXXXXXX","limit":100}'
```

### 更新记录

```bash
lark-cli base table.records patch \
  --params '{"base_token":"bascnXXXXXXXX","table_id":"tblXXXXXXXX","record_id":"recXXXXXXXX"}' \
  --data '{
    "状态":"已完成"
  }'
```

### 删除记录

```bash
lark-cli base table.records delete \
  --params '{"base_token":"bascnXXXXXXXX","table_id":"tblXXXXXXXX","record_id":"recXXXXXXXX"}'
```

---

## 场景 4：配置视图筛选后按视图读取记录

当前 `base/v3` 原生 spec 没有独立 `search` 方法。需要筛选查询时，推荐先写视图筛选，再通过 `view_id` 读取记录。

### 更新视图筛选条件

```bash
lark-cli base view.filter update \
  --params '{"base_token":"bascnXXXXXXXX","table_id":"tblXXXXXXXX","view_id":"vewXXXXXXXX"}' \
  --data '{
    "logic":"and",
    "conditions":[
      {
        "field_name":"状态",
        "operator":"is",
        "value":["进行中"]
      }
    ]
  }'
```

### 按视图读取记录

```bash
lark-cli base table.records list \
  --params '{"base_token":"bascnXXXXXXXX","table_id":"tblXXXXXXXX","view_id":"vewXXXXXXXX","limit":100}'
```

---

## 场景 5：什么时候优先用 Shortcut

- 需要一次性建表并附带字段、视图时，优先 `lark-cli base +table-create`
- 需要按业务字段名做 upsert 时，优先 `lark-cli base +record-upsert`
- 需要配置筛选视图时，优先 `lark-cli base +view-set-filter`
- 需要记录历史时，优先 `lark-cli base +record-history-list`

原生 API 更适合两类场景：

- 需要逐步核对 `schema base.<resource>.<method>` 的请求参数
- 需要精确控制单次表 / 字段 / 记录 / 视图操作
