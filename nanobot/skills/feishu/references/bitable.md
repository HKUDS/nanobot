# 多维表格 (Bitable)

使用 `@larksuiteoapi/node-sdk` 在 NestJS 中操作飞书多维表格。

## 所需权限

| 权限标识 | 说明 |
|----------|------|
| `bitable:app` | 读写多维表格 |
| `drive:drive` | 访问云空间（创建/列出多维表格时需要） |

> 对于已有的多维表格，需确保应用已被添加为协作者：云文档右上角「...」→「更多」→「添加文档应用」。

## 获取 app_token

多维表格的 `app_token` 有三种获取方式：
1. **通过 API 创建** → 响应中包含 `app_token`
2. **通过 API 列出** → 从文件列表中获取
3. **从 URL 提取** → 见下方 URL 解析

### URL 解析

多维表格有两种 URL 格式：

| 格式 | URL 示例 | 说明 |
|------|----------|------|
| `/base/` | `https://xxx.feishu.cn/base/{app_token}?table=tblXXX` | 直接提取 `app_token` |
| `/wiki/` | `https://xxx.feishu.cn/wiki/{node_token}?table=tblXXX` | 需先通过 Wiki API 获取 `obj_token` |

```typescript
// /base/ 格式：直接提取
const baseUrl = 'https://xxx.feishu.cn/base/ABC123?table=tblXXX';
const u = new URL(baseUrl);
const appToken = u.pathname.match(/\/base\/([A-Za-z0-9]+)/)?.[1]; // 'ABC123'
const tableId = u.searchParams.get('table'); // 'tblXXX'

// /wiki/ 格式：需先获取 obj_token
const wikiUrl = 'https://xxx.feishu.cn/wiki/XYZ789?table=tblXXX';
const nodeToken = new URL(wikiUrl).pathname.match(/\/wiki\/([A-Za-z0-9]+)/)?.[1];
const nodeRes = await client.wiki.space.getNode({ params: { token: nodeToken } });
const appTokenFromWiki = nodeRes.data?.node?.obj_token; // 这才是真正的 app_token
```

## 创建多维表格

```typescript
const res = await client.bitable.app.create({
  data: {
    name: '项目跟踪表',
    // folder_token: 'fldcnxxxxxx', // 可选：目标文件夹
  },
});
const appToken = res.data?.app?.app_token;
const defaultTableId = res.data?.app?.table_id;
```

## 获取多维表格信息

```typescript
const info = await client.bitable.app.get({
  path: { app_token: appToken },
});
```

## 列出数据表

```typescript
const tables = await client.bitable.appTable.list({
  path: { app_token: appToken },
  params: { page_size: 20 },
});
// tables.data?.items — [{table_id, name, revision}, ...]
```

## 创建数据表

```typescript
const newTable = await client.bitable.appTable.create({
  path: { app_token: appToken },
  data: {
    table: {
      name: '新数据表',
      default_view_name: '默认视图',
      fields: [
        { field_name: '任务名称', type: 1 }, // 1 = 多行文本
        { field_name: '状态', type: 3 },      // 3 = 单选
        { field_name: '截止日期', type: 5 },  // 5 = 日期
      ],
    },
  },
});
```

## 列出字段

```typescript
const fields = await client.bitable.appTableField.list({
  path: { app_token: appToken, table_id: tableId },
  params: { page_size: 100 },
});
// fields.data?.items — [{field_id, field_name, type, is_primary, property}, ...]
```

## 查询记录

```typescript
// 使用 search 方法支持 filter 和 sort
const records = await client.bitable.appTableRecord.search({
  path: { app_token: appToken, table_id: tableId },
  data: {
    field_names: ['任务名称', '负责人', '状态'],
    filter: {
      conjunction: 'and',
      conditions: [
        { field_name: '状态', operator: 'is', value: ['进行中'] },
      ],
    },
    sort: [
      { field_name: '截止日期', desc: false },
    ],
    page_size: 20,
  },
});
// records.data?.items — [{record_id, fields: {...}}, ...]
```

### filter 语法

```typescript
// conjunction: 'and' | 'or'
// operator: 'is' | 'isNot' | 'contains' | 'doesNotContain' | 'isEmpty' | 'isNotEmpty' | 'isGreater' | 'isLess'
{
  conjunction: 'and',
  conditions: [
    { field_name: '状态', operator: 'is', value: ['进行中'] },
    { field_name: '优先级', operator: 'is', value: ['高'] },
  ],
}
```

## 获取单条记录

```typescript
const record = await client.bitable.appTableRecord.get({
  path: { app_token: appToken, table_id: tableId, record_id: 'recXXX' },
});
```

## 列出记录（简单查询）

```typescript
const list = await client.bitable.appTableRecord.list({
  path: { app_token: appToken, table_id: tableId },
  params: {
    page_size: 100,
    // filter: '...', // URL filter 表达式
    // sort: '...', // URL sort 表达式
  },
});
```

## 新增记录

```typescript
const created = await client.bitable.appTableRecord.create({
  path: { app_token: appToken, table_id: tableId },
  data: {
    fields: {
      '任务名称': '设计数据库表结构',
      '状态': '待开始',
      '优先级': '高',
      '截止日期': 1708300800000, // 毫秒时间戳
    },
  },
});
const recordId = created.data?.record?.record_id;
```

## 批量新增记录

```typescript
await client.bitable.appTableRecord.batchCreate({
  path: { app_token: appToken, table_id: tableId },
  data: {
    records: [
      { fields: { '任务名称': '任务1', '状态': '待开始' } },
      { fields: { '任务名称': '任务2', '状态': '待开始' } },
    ],
  },
});
```

## 更新记录

```typescript
await client.bitable.appTableRecord.update({
  path: { app_token: appToken, table_id: tableId, record_id: recordId },
  data: {
    fields: {
      '状态': '已完成',
      '完成日期': Date.now(), // 毫秒时间戳
    },
  },
});
```

## 删除记录

```typescript
// 单条删除
await client.bitable.appTableRecord.delete({
  path: { app_token: appToken, table_id: tableId, record_id: 'recXXX' },
});

// 批量删除
await client.bitable.appTableRecord.batchDelete({
  path: { app_token: appToken, table_id: tableId },
  data: {
    records: ['recXXX', 'recYYY', 'recZZZ'],
  },
});
```

## 字段 CRUD

### 创建字段

```typescript
const res = await client.bitable.appTableField.create({
  path: { app_token: appToken, table_id: tableId },
  data: {
    field_name: '优先级',
    type: 3, // SingleSelect
    // property: { options: [{name: '高'}, {name: '中'}, {name: '低'}] }, // 可选
  },
});
const fieldId = res.data?.field?.field_id;
```

### 更新字段

```typescript
await client.bitable.appTableField.update({
  path: { app_token: appToken, table_id: tableId, field_id: fieldId },
  data: {
    field_name: '新字段名',
    type: 1, // 字段类型
  },
});
```

### 删除字段

```typescript
await client.bitable.appTableField.delete({
  path: { app_token: appToken, table_id: tableId, field_id: fieldId },
});
```

> **注意**：主字段（`is_primary: true`）不能删除，只能重命名。

## 新建多维表格清理建议

新建的多维表格会自动创建默认字段（单选、日期、附件）和空行。建议创建后清理：
1. 删除不需要的默认字段（类型 3/5/17）
2. 重命名主字段为有意义的名称
3. 批量删除空的占位行

## 字段类型与写入格式

| 类型编号 | 字段类型 | 写入格式 | 示例 |
|----------|----------|----------|------|
| 1 | 多行文本 | string 或 text 对象数组 | `"Hello"` 或 `[{"text":"Hello","type":"text"}]` |
| 2 | 数字 | number | `2323.23` |
| 3 | 单选 | string | `"选项1"` |
| 4 | 多选 | string[] | `["选项1", "选项2"]` |
| 5 | 日期 | number（毫秒时间戳） | `1690992000000` |
| 7 | 复选框 | boolean | `true` |
| 11 | 人员 | object[] | `[{"id": "ou_xxx"}]` |
| 13 | 电话号码 | string | `"13800138000"` |
| 15 | 超链接 | object | `{"text": "链接", "link": "https://..."}` |
| 17 | 附件 | object[] | `[{"file_token": "xxx"}]` |
| 18 | 单向关联 | string[] | `["recXXX"]` |
| 19 | 查找引用 | — | 只读，由关联字段自动计算 |
| 20 | 公式 | — | 只读，由公式自动计算 |
| 21 | 双向关联 | string[] | `["recXXX"]` |
| 22 | 地理位置 | object | `{"location": "北京市朝阳区", "pname": "北京市"}` |
| 23 | 群组 | string[] | `["oc_xxx"]` |
| 1001 | 创建时间 | — | 只读，系统自动生成 |
| 1002 | 修改时间 | — | 只读，系统自动生成 |
| 1003 | 创建人 | — | 只读，系统自动生成 |
| 1004 | 修改人 | — | 只读，系统自动生成 |
| 1005 | 自动编号 | — | 只读，系统自动生成 |

## Common Mistakes

| 错误 | 正确做法 |
|------|----------|
| 应用无法访问已有多维表格 | 需先添加应用为协作者 |
| 日期字段传 ISO 字符串 | 必须传毫秒时间戳数字 |
| 人员字段传字符串 | 必须传 `[{id: 'ou_xxx'}]` 数组格式 |
| 单选/多选传不存在的选项 | 选项会自动创建，但注意拼写一致 |
| `app_token` 和 `table_id` 搞混 | `app_token` 是多维表格级别，`table_id` 是数据表级别 |
| 查询用 `list` 不支持复杂筛选 | 使用 `search` 方法支持 filter/sort |
| `/wiki/` URL 直接当 app_token 用 | Wiki URL 的 token 是 node_token，需先 `wiki.space.getNode()` 获取 `obj_token` |
| 删除主字段 | 主字段（`is_primary: true`）不能删除，只能重命名 |
| 写入只读字段（公式/创建时间等） | 类型 19/20/1001-1005 为只读，不能通过 API 写入 |
