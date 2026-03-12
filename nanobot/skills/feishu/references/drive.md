# 云空间 (Drive)

使用 `@larksuiteoapi/node-sdk` 在 NestJS 中管理飞书云空间文件和文件夹。

## 所需权限

| 权限标识 | 说明 |
|----------|------|
| `drive:drive` | 读写云空间（创建、移动、删除） |
| `drive:drive:readonly` | 只读云空间（列出、查看） |

## 从 URL 提取 Token

文件夹 URL 格式：`https://xxx.feishu.cn/drive/folder/{folder_token}`

```typescript
const url = 'https://xxx.feishu.cn/drive/folder/ABC123';
const folderToken = new URL(url).pathname.split('/drive/folder/')[1]; // 'ABC123'
```

## 列出文件夹内容

```typescript
// 列出指定文件夹
const res = await client.drive.file.list({
  params: { folder_token: 'fldcnXXX' },
});
const files = res.data?.files ?? [];
// files: [{token, name, type, url, created_time, modified_time, owner_id}, ...]

// 列出根目录（不传 folder_token）
const rootRes = await client.drive.file.list({
  params: {},
});
```

## 创建文件夹

```typescript
const res = await client.drive.file.createFolder({
  data: {
    name: '新文件夹',
    folder_token: 'fldcnXXX', // 父文件夹 token
  },
});
const folderToken = res.data?.token;
const folderUrl = res.data?.url;
```

## 移动文件

```typescript
const res = await client.drive.file.move({
  path: { file_token: 'ABC123' },
  data: {
    type: 'docx', // 文件类型
    folder_token: 'fldcnXXX', // 目标文件夹
  },
});
```

## 删除文件

```typescript
const res = await client.drive.file.delete({
  path: { file_token: 'ABC123' },
  params: {
    type: 'docx', // 文件类型
  },
});
```

## 文件类型参考

| 类型 | 说明 |
|------|------|
| `doc` | 旧版文档 |
| `docx` | 新版文档 |
| `sheet` | 电子表格 |
| `bitable` | 多维表格 |
| `folder` | 文件夹 |
| `file` | 上传的文件 |
| `mindnote` | 思维导图 |
| `shortcut` | 快捷方式 |

## 机器人根文件夹限制

飞书机器人使用 `tenant_access_token`，没有自己的「我的空间」根文件夹。这意味着：

- 不指定 `folder_token` 创建文件夹会失败（400 错误）
- 机器人只能访问**已共享给它**的文件和文件夹
- **解决方案**：用户先手动创建一个文件夹并共享给机器人，机器人就可以在其中创建子文件夹和文件

## Common Mistakes

| 错误 | 正确做法 |
|------|----------|
| 机器人不指定 folder_token 创建文件夹 | 必须指定一个已共享给机器人的 folder_token |
| move/delete 时 type 参数搞错 | type 必须与文件实际类型一致 |
| 用 folder_token 当 file_token | `folder_token` 用于列出目录，`file_token` 用于移动/删除 |
| 文件不在机器人可访问范围内 | 需先将文件/文件夹共享给机器人应用 |
