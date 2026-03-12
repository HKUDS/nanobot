# 云文档 (Document)

使用 `@larksuiteoapi/node-sdk` 在 NestJS 中操作飞书云文档。

## 所需权限

| 权限标识 | 说明 |
|----------|------|
| `docx:document` | 读写新版文档 |
| `docx:document:readonly` | 只读新版文档 |
| `docx:document.block:convert` | Markdown 转 Block（写入/追加需要） |
| `drive:drive` | 访问云空间（创建文档到指定文件夹时需要） |

> 对于已有的文档，需确保应用已被添加为协作者：文档右上角「...」→「更多」→「添加文档应用」。

## 从 URL 提取 Token

URL 格式：`https://xxx.feishu.cn/docx/{doc_token}`

```typescript
const url = 'https://xxx.feishu.cn/docx/ABC123def';
const docToken = new URL(url).pathname.split('/docx/')[1]; // 'ABC123def'
```

## 创建文档

```typescript
const res = await client.docx.document.create({
  data: {
    title: '新文档',
    // folder_token: 'fldcnXXX', // 可选：目标文件夹
  },
});
const docId = res.data?.document?.document_id;
const docUrl = `https://feishu.cn/docx/${docId}`;
```

## 读取文档

### 读取工作流

1. **先获取纯文本** — 快速了解文档内容
2. **检查 hint** — 如果返回中包含 `hint` 字段，说明文档含有表格、图片等结构化内容
3. **获取 Block 列表** — 需要结构化内容时使用 `documentBlock.list()`

### 读取纯文本

```typescript
const [contentRes, infoRes] = await Promise.all([
  client.docx.document.rawContent({ path: { document_id: docToken } }),
  client.docx.document.get({ path: { document_id: docToken } }),
]);
const title = infoRes.data?.document?.title;
const content = contentRes.data?.content;
```

### 读取 Block 列表（结构化内容）

```typescript
const blocksRes = await client.docx.documentBlock.list({
  path: { document_id: docToken },
});
const blocks = blocksRes.data?.items ?? [];
```

## 写入文档（替换全部内容）

工作流：清空现有内容 → 转换 Markdown → 插入新 Block

```typescript
// 1. 清空文档内容（保留 Page block）
const existing = await client.docx.documentBlock.list({
  path: { document_id: docToken },
});
const childIds = existing.data?.items
  ?.filter(b => b.parent_id === docToken && b.block_type !== 1)
  .map(b => b.block_id) ?? [];

if (childIds.length > 0) {
  await client.docx.documentBlockChildren.batchDelete({
    path: { document_id: docToken, block_id: docToken },
    data: { start_index: 0, end_index: childIds.length },
  });
}

// 2. 转换 Markdown 为 Block
const convertRes = await client.docx.document.convert({
  data: { content_type: 'markdown', content: markdownContent },
});
const blocks = convertRes.data?.blocks ?? [];

// 3. 插入 Block
await client.docx.documentBlockChildren.create({
  path: { document_id: docToken, block_id: docToken },
  data: { children: blocks },
});
```

## 追加内容

与写入相同，但跳过清空步骤：

```typescript
// 转换 + 插入（不清空）
const convertRes = await client.docx.document.convert({
  data: { content_type: 'markdown', content: markdownContent },
});
await client.docx.documentBlockChildren.create({
  path: { document_id: docToken, block_id: docToken },
  data: { children: convertRes.data?.blocks ?? [] },
});
```

## Block 操作

### 获取单个 Block

```typescript
const res = await client.docx.documentBlock.get({
  path: { document_id: docToken, block_id: blockId },
});
```

### 更新 Block 文本

```typescript
await client.docx.documentBlock.patch({
  path: { document_id: docToken, block_id: blockId },
  data: {
    update_text_elements: {
      elements: [{ text_run: { content: '新文本内容' } }],
    },
  },
});
```

### 删除 Block

```typescript
// 需要知道 block 在父容器中的 index
const children = await client.docx.documentBlockChildren.get({
  path: { document_id: docToken, block_id: parentId },
});
const index = children.data?.items?.findIndex(item => item.block_id === blockId);

await client.docx.documentBlockChildren.batchDelete({
  path: { document_id: docToken, block_id: parentId },
  data: { start_index: index, end_index: index + 1 },
});
```

## 图片上传

```typescript
import { Readable } from 'stream';

// 1. 上传图片到文档
const uploadRes = await client.drive.media.uploadAll({
  data: {
    file_name: 'image.png',
    parent_type: 'docx_image',
    parent_node: blockId, // 图片 Block 的 block_id
    size: imageBuffer.length,
    file: Readable.from(imageBuffer) as any,
  },
});
if (uploadRes.code !== 0) {
  throw new Error(`Image upload failed [${uploadRes.code}]: ${uploadRes.msg}`);
}
const fileToken = uploadRes.data?.file_token;

// 2. 替换图片 Block 的内容
await client.docx.documentBlock.patch({
  path: { document_id: docToken, block_id: blockId },
  data: {
    replace_image: { token: fileToken },
  },
});
```

## Block 类型参考

| block_type | 名称 | 说明 | 可编辑 |
|------------|------|------|--------|
| 1 | Page | 文档根节点（包含标题） | 否 |
| 2 | Text | 纯文本段落 | 是 |
| 3 | Heading1 | 一级标题 | 是 |
| 4 | Heading2 | 二级标题 | 是 |
| 5 | Heading3 | 三级标题 | 是 |
| 6 | Heading4 | 四级标题 | 是 |
| 7 | Heading5 | 五级标题 | 是 |
| 8 | Heading6 | 六级标题 | 是 |
| 9 | Heading7 | 七级标题 | 是 |
| 10 | Heading8 | 八级标题 | 是 |
| 11 | Heading9 | 九级标题 | 是 |
| 12 | Bullet | 无序列表项 | 是 |
| 13 | Ordered | 有序列表项 | 是 |
| 14 | Code | 代码块 | 是 |
| 15 | Quote | 引用块 | 是 |
| 16 | Equation | LaTeX 公式 | 部分 |
| 17 | Todo | 任务/复选框 | 是 |
| 18 | Bitable | 多维表格嵌入 | 否 |
| 19 | Callout | 高亮块 | 是 |
| 20 | ChatCard | 会话卡片嵌入 | 否 |
| 21 | Diagram | 绘图嵌入 | 否 |
| 22 | Divider | 分割线 | 否 |
| 23 | File | 文件附件 | 否 |
| 24 | Grid | 分栏布局容器 | 否 |
| 25 | GridColumn | 分栏列 | 否 |
| 26 | Iframe | 内嵌网页 | 否 |
| 27 | Image | 图片 | 部分（replace_image） |
| 28 | ISV | 第三方小组件 | 否 |
| 29 | MindnoteBlock | 思维导图嵌入 | 否 |
| 30 | Sheet | 电子表格嵌入 | 否 |
| 31 | Table | 表格 | 部分（仅读取，无法通过 API 创建） |
| 32 | TableCell | 表格单元格 | 是 |
| 33 | View | 视图嵌入 | 否 |
| 34 | Undefined | 未知类型 | 否 |
| 35 | QuoteContainer | 引用容器 | 否 |
| 36 | Task | 飞书任务集成 | 否 |
| 37 | OKR | OKR 集成 | 否 |
| 38 | OKRObjective | OKR 目标 | 否 |
| 39 | OKRKeyResult | OKR 关键结果 | 否 |
| 40 | OKRProgress | OKR 进展 | 否 |
| 41 | AddOns | 扩展块 | 否 |
| 42 | JiraIssue | Jira Issue 嵌入 | 否 |
| 43 | WikiCatalog | 知识库目录 | 否 |
| 44 | Board | 画板嵌入 | 否 |
| 45 | Agenda | 议程块 | 否 |
| 46 | AgendaItem | 议程项 | 否 |
| 47 | AgendaItemTitle | 议程项标题 | 否 |
| 48 | SyncedBlock | 同步块引用 | 否 |

> 可编辑的文本类 block（2-17, 19）通过 `documentBlock.patch()` 的 `update_text_elements` 更新；容器类 block（24, 25, 35）需编辑其子 block。

## Markdown 写入限制

- **表格不支持**：Markdown 中的表格无法通过 `document.convert()` → `documentBlockChildren.create()` 创建（error 1770029）
- 支持的 Markdown 元素：标题、列表、代码块、引用、链接、图片（`![](url)` 自动上传）、加粗/斜体/删除线

## Common Mistakes

| 错误 | 正确做法 |
|------|----------|
| 直接用 wiki token 调用 docx API | Wiki 页面需先通过 `wiki.space.getNode()` 获取 `obj_token`，再用 `obj_token` 作为 `doc_token` |
| 写入时未清空旧内容导致重复 | 写入前先调用 `documentBlockChildren.batchDelete()` 清空 |
| 删除 Block 传 block_id 而非 index | `batchDelete` 使用 `start_index` 和 `end_index`，非 block_id |
| 尝试通过 API 创建表格 Block | Table block 无法通过 `documentBlockChildren.create()` 创建 |
| `document.convert()` 缺少权限 | 需要 `docx:document.block:convert` 权限 |
| 图片上传 parent_type 填错 | 文档图片必须用 `docx_image`，不是 `doc_image` |
| 更新文本时覆盖了富文本样式 | `update_text_elements` 会替换整个文本内容，包括样式 |
| 并发写入同一文档 | 飞书文档不支持并发写入，需串行操作 |
| 忘记检查 `res.code !== 0` | 所有 API 调用都需检查返回码 |
| 清空文档时删除了 Page block | `block_type !== 1` 的才能删除，Page block 是根节点 |
