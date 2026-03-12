# 知识库 (Wiki)

使用 `@larksuiteoapi/node-sdk` 在 NestJS 中操作飞书知识库。

## 所需权限

| 权限标识 | 说明 |
|----------|------|
| `wiki:wiki` | 读写知识库 |
| `wiki:wiki:readonly` | 只读知识库 |

> 机器人需被添加为知识空间成员才能访问：知识空间 → 设置 → 成员管理 → 添加机器人。

## 从 URL 提取 Token

URL 格式：`https://xxx.feishu.cn/wiki/{token}`

```typescript
const url = 'https://xxx.feishu.cn/wiki/ABC123def';
const token = new URL(url).pathname.split('/wiki/')[1]; // 'ABC123def'
```

## 列出知识空间

```typescript
const res = await client.wiki.space.list({});
const spaces = res.data?.items ?? [];
// spaces: [{space_id, name, description, visibility}, ...]
```

> 如果返回空列表，说明机器人未被添加到任何知识空间。

## 列出节点

```typescript
// 列出空间根节点
const res = await client.wiki.spaceNode.list({
  path: { space_id: '7xxx' },
});
const nodes = res.data?.items ?? [];
// nodes: [{node_token, obj_token, obj_type, title, has_child}, ...]

// 列出子节点
const childRes = await client.wiki.spaceNode.list({
  path: { space_id: '7xxx' },
  params: { parent_node_token: 'wikcnXXX' },
});
```

## 获取节点详情

```typescript
const res = await client.wiki.space.getNode({
  params: { token: 'ABC123def' }, // 从 URL 提取的 token
});
const node = res.data?.node;
// node: {node_token, space_id, obj_token, obj_type, title, parent_node_token, has_child, creator}
```

> **关键**：返回的 `obj_token` 是实际文档/表格的 token，需用它来调用 docx/bitable 等 API。

## 创建节点

```typescript
const res = await client.wiki.spaceNode.create({
  path: { space_id: '7xxx' },
  data: {
    obj_type: 'docx',              // 节点类型
    node_type: 'origin',            // 固定值
    title: '新页面',
    // parent_node_token: 'wikcnXXX', // 可选：父节点
  },
});
const node = res.data?.node;
// node: {node_token, obj_token, obj_type, title}
```

### obj_type 取值

| 值 | 说明 |
|------|------|
| `docx` | 新版文档（默认） |
| `doc` | 旧版文档 |
| `sheet` | 电子表格 |
| `bitable` | 多维表格 |
| `mindnote` | 思维导图 |
| `file` | 文件 |
| `slides` | 幻灯片 |

## 移动节点

```typescript
await client.wiki.spaceNode.move({
  path: { space_id: '7xxx', node_token: 'wikcnXXX' },
  data: {
    target_space_id: '7yyy',         // 目标空间（不传则同空间内移动）
    target_parent_token: 'wikcnYYY', // 目标父节点
  },
});
```

## 重命名节点

```typescript
await client.wiki.spaceNode.updateTitle({
  path: { space_id: '7xxx', node_token: 'wikcnXXX' },
  data: { title: '新标题' },
});
```

## Wiki-Doc 工作流（关键）

知识库页面的内容读写必须通过 docx API，流程：

```typescript
// 1. 获取节点详情 → 拿到 obj_token
const nodeRes = await client.wiki.space.getNode({
  params: { token: wikiToken },
});
const objToken = nodeRes.data?.node?.obj_token;

// 2. 用 obj_token 作为 doc_token 读取文档
const contentRes = await client.docx.document.rawContent({
  path: { document_id: objToken },
});

// 3. 用 obj_token 作为 doc_token 写入文档
const convertRes = await client.docx.document.convert({
  data: { content_type: 'markdown', content: '# 新内容\n\n正文...' },
});
await client.docx.documentBlockChildren.create({
  path: { document_id: objToken, block_id: objToken },
  data: { children: convertRes.data?.blocks ?? [] },
});
```

> **重要**：不要用 `node_token` 或 URL 中的 `token` 直接调用 docx API，必须用 `getNode()` 返回的 `obj_token`。

## 搜索不可用

Wiki API 不提供搜索功能。获取内容需通过以下方式：

- 通过 `spaceNode.list()` 浏览节点树
- 通过 `space.getNode()` + URL 中的 token 直接查询

## 知识库访问设置

机器人需要被添加为知识空间成员才能访问：

1. 打开知识空间 → 设置 → 成员管理
2. 添加机器人应用
3. 参考：https://open.feishu.cn/document/server-docs/docs/wiki-v2/wiki-qa

## Common Mistakes

| 错误 | 正确做法 |
|------|----------|
| 用 wiki URL 中的 token 直接调用 docx API | 必须先 `getNode()` 获取 `obj_token`，再用 `obj_token` 调用 docx API |
| 列出空间返回空但实际有内容 | 机器人未被添加为空间成员 |
| 尝试搜索知识库内容 | Wiki API 不支持搜索，只能通过 `list` 浏览或 `getNode` 查询 |
| 创建节点忘记传 `node_type: 'origin'` | `node_type` 是必填字段，值固定为 `'origin'` |
| 混淆 `node_token` 和 `obj_token` | `node_token` 是知识库节点标识，`obj_token` 是实际文档标识 |
