# 通讯录 (Contacts)

使用 `@larksuiteoapi/node-sdk` 在 NestJS 中查询飞书通讯录用户和部门信息。

## 所需权限

| 权限标识 | 说明 |
|----------|------|
| `contact:contact.base:readonly` | 读取通讯录基本信息 |
| `contact:user.base:readonly` | 获取用户基础信息 |
| `contact:department.base:readonly` | 获取部门基础信息 |
| `contact:user.employee_id:readonly` | 获取用户 employee_id（可选） |

> **通讯录权限范围**：必须在安全设置中配置，否则 API 只能查到权限范围内的用户/部门。建议设为「全部成员」。

## 获取用户信息

```typescript
const user = await client.contact.user.get({
  path: { user_id: 'ou_xxx' },
  params: { user_id_type: 'open_id' },
});
// user.data?.user — { name, en_name, email, mobile, department_ids, status, ... }
```

### 用户 ID 类型说明

| user_id_type | 说明 | 示例 |
|--------------|------|------|
| `open_id` | 应用级唯一标识 | `ou_xxx`（默认） |
| `union_id` | 跨应用统一标识 | `on_xxx` |
| `user_id` | 企业内用户 ID | 无固定前缀 |

## 列出部门下的用户

```typescript
const users = await client.contact.user.findByDepartment({
  params: {
    department_id: 'od_xxx',
    page_size: 50,
    department_id_type: 'open_department_id',
    user_id_type: 'open_id',
  },
});
// users.data?.items — [{user_id, name, email, ...}, ...]
// users.data?.has_more, users.data?.page_token — 用于分页
```

### 分页遍历所有成员

```typescript
for await (const items of client.contact.user.listWithIterator({
  params: {
    department_id: 'od_xxx',
    page_size: 50,
    department_id_type: 'open_department_id',
    user_id_type: 'open_id',
  },
})) {
  for (const user of items?.items || []) {
    console.log(user.name, user.open_id);
  }
}
```

## 搜索用户

```typescript
const searchResult = await client.contact.user.search({
  data: { query: '张三' },
  params: {
    user_id_type: 'open_id',
    page_size: 20,
  },
});
// searchResult.data?.items — 匹配的用户列表
```

> 搜索用户需要 `user_access_token`（用户授权），不支持 `tenant_access_token`。如果只有应用凭证，使用 `findByDepartment` 遍历 + 本地过滤替代。

## 获取部门信息

```typescript
const dept = await client.contact.department.get({
  path: { department_id: 'od_xxx' },
  params: { department_id_type: 'open_department_id' },
});
// dept.data?.department — { name, parent_department_id, leader_user_id, member_count, ... }
```

## 列出子部门

```typescript
const children = await client.contact.department.children({
  path: { department_id: 'od_xxx' },
  params: {
    department_id_type: 'open_department_id',
    page_size: 50,
  },
});
// children.data?.items — [{department_id, name, member_count, ...}, ...]
```

## 搜索部门

```typescript
const deptSearch = await client.contact.department.search({
  data: { query: '产品' },
  params: {
    department_id_type: 'open_department_id',
    page_size: 20,
  },
});
```

> 搜索部门同样需要 `user_access_token`。应用凭证可用 `department.children()` 遍历代替。

## 列出所有部门（从根开始）

```typescript
const rootDepts = await client.contact.department.list({
  params: {
    parent_department_id: '0', // 0 表示根部门
    page_size: 50,
    department_id_type: 'open_department_id',
  },
});
```

## 典型工作流

### 查找某部门所有成员

1. **搜索部门** → `client.contact.department.search({ data: { query: '市场部' } })`
   - 或遍历子部门 → `client.contact.department.children()`
2. **获取部门成员** → `client.contact.user.findByDepartment({ params: { department_id } })`

### 查找用户所在部门

1. **获取用户信息** → `client.contact.user.get({ path: { user_id } })`
2. 从返回的 `department_ids` 获取部门 ID
3. **获取部门详情** → `client.contact.department.get({ path: { department_id } })`

### 遍历整个组织架构

1. 从根部门开始 → `client.contact.department.list({ params: { parent_department_id: '0' } })`
2. 递归获取子部门 → `client.contact.department.children()`
3. 获取每个部门成员 → `client.contact.user.findByDepartment()`

## Common Mistakes

| 错误 | 正确做法 |
|------|----------|
| 未配置通讯录权限范围 | 安全设置 → 通讯录权限范围 → 全部成员 |
| 用 `tenant_access_token` 搜索用户 | `user.search()` 需 `user_access_token`，否则用 `findByDepartment` |
| 部门 ID 类型不匹配 | `od_` 开头用 `open_department_id`，纯数字用 `department_id` |
| 忘记传 `user_id_type` 参数 | 不传默认 `open_id`，注意和实际传入的 ID 类型一致 |
| 分页获取不完整 | 检查 `has_more`，使用 `listWithIterator` 自动分页 |
