# 权限管理 (Permission)

使用 `@larksuiteoapi/node-sdk` 在 NestJS 中管理飞书云文档的协作者权限。

## 所需权限

| 权限标识 | 说明 |
|----------|------|
| `drive:permission` | 管理文档/文件的协作者权限 |

> **敏感操作警告**：权限管理涉及文档访问控制，添加/移除协作者会直接影响用户的文档可见性。操作前请确认目标对象和权限级别。

## 列出协作者

```typescript
const res = await client.drive.permissionMember.list({
  path: { token: 'ABC123' },
  params: { type: 'docx' },
});
const members = res.data?.items ?? [];
// members: [{member_type, member_id, perm, name}, ...]
```

## 添加协作者

```typescript
const res = await client.drive.permissionMember.create({
  path: { token: 'ABC123' },
  params: { type: 'docx', need_notification: false },
  data: {
    member_type: 'email',
    member_id: 'user@example.com',
    perm: 'edit',
  },
});
```

## 移除协作者

```typescript
await client.drive.permissionMember.delete({
  path: { token: 'ABC123', member_id: 'user@example.com' },
  params: { type: 'docx', member_type: 'email' },
});
```

## Token 类型参考

| 类型 | 说明 |
|------|------|
| `doc` | 旧版文档 |
| `docx` | 新版文档 |
| `sheet` | 电子表格 |
| `bitable` | 多维表格 |
| `folder` | 文件夹 |
| `file` | 上传的文件 |
| `wiki` | 知识库节点 |
| `mindnote` | 思维导图 |

## 成员类型参考

| 类型 | 说明 |
|------|------|
| `email` | 邮箱地址 |
| `openid` | 用户 open_id |
| `userid` | 用户 user_id |
| `unionid` | 用户 union_id |
| `openchat` | 群聊 open_id |
| `opendepartmentid` | 部门 open_id |
| `groupid` | 用户组 ID |
| `wikispaceid` | 知识空间 ID |

## 权限级别参考

| 权限值 | 说明 |
|--------|------|
| `view` | 仅查看 |
| `edit` | 可编辑 |
| `full_access` | 完全访问（可管理权限） |

## Common Mistakes

| 错误 | 正确做法 |
|------|----------|
| token 类型与文件实际类型不匹配 | `type` 参数必须与文件实际类型一致（docx/sheet/bitable 等） |
| 用 wiki URL 的 token 直接操作权限 | Wiki 节点需用 `wiki` 类型，或先获取 `obj_token` 用对应类型 |
| 添加协作者时成员不存在 | 确认 member_id 正确，email 需要是飞书注册邮箱 |
| 移除自身的 full_access 权限 | 文档至少需要一个管理员，避免移除最后一个 full_access 成员 |
