---
name: feishu-doc-perm
description: 飞书文档权限管理最佳实践 - 创建、配置、批量管理文档权限...
---

# feishu-doc-perm - 飞书文档权限管理

飞书文档权限管理最佳实践 - 创建、配置、批量管理文档权限

---

## 功能

- 文档权限查询与配置
- 批量添加协作者
- 权限模板管理
- 安全最佳实践

---

## 安装

无需安装，直接使用OpenClaw内置的 `feishu_perm` 工具

---

## 使用指南

### 1. 查询文档当前权限

```json
{
  "action": "list",
  "token": "文档Token（从URL中获取）",
  "type": "docx"
}
```

**示例**：
```
feishu_perm action=list token=S96CdbmrHogje9xJjZNcmUjSnGb type=docx
```

**返回示例**：
```json
{
  "members": [
    {
      "member_type": "openid",
      "member_id": "ou_xxx",
      "perm": "full_access"
    },
    {
      "member_type": "openchat",
      "member_id": "oc_xxx",
      "perm": "view"
    }
  ]
}
```

---

### 2. 添加单个用户权限

```json
{
  "action": "add",
  "token": "文档Token",
  "type": "docx",
  "member_id": "用户OpenID",
  "member_type": "openid",
  "perm": "edit"  // 可选: view/edit/full_access
}
```

**权限级别说明**：
| 权限 | 说明 |
|------|------|
| `view` | 仅查看，不可编辑 |
| `edit` | 可编辑内容，不可管理权限 |
| `full_access` | 完全权限，包括删除 |

**示例**：
```
feishu_perm action=add token=xxx type=docx member_id=ou_d72a33db769620cc975476103efbbebf member_type=openid perm=edit
```

---

### 3. 添加群聊权限

```json
{
  "action": "add",
  "token": "文档Token",
  "type": "docx",
  "member_id": "群聊ID",
  "member_type": "openchat",
  "perm": "view"
}
```

**获取群聊ID**：
- 从OpenClaw的inbound metadata中获取 `chat_id`
- 格式：`oc_60c795e2e04eefc3d09eb49da4df15a5`

---

### 4. 移除权限

```json
{
  "action": "remove",
  "token": "文档Token",
  "type": "docx",
  "member_id": "要移除的用户ID",
  "member_type": "openid"
}
```

---

## 完整工作流

### 场景1：创建文档并授权给群成员

```
1. 创建文档
   feishu_doc action=create title="xxx"

2. 获取文档Token（从返回值或URL中）

3. 添加群聊查看权限
   feishu_perm action=add token=xxx type=docx member_id=oc_xxx member_type=openchat perm=view

4. 添加特定用户编辑权限
   feishu_perm action=add token=xxx type=docx member_id=ou_xxx member_type=openid perm=edit
```

### 场景2：处理"无法转发"问题

**问题**：用户反馈飞书文档无法转发

**原因**：默认权限不允许转发

**解决方案**：
```
1. 给用户添加编辑权限
   feishu_perm action=add ... perm=edit

2. 或指导用户手动开启：
   文档 → 右上角"..." → 权限设置 → "获得链接的人可查看" → 勾选"允许转发"
```

---

## 安全最佳实践

### ✅ 推荐做法

1. **最小权限原则**
   - 默认给 `view` 权限
   - 需要编辑才给 `edit`
   - 仅管理员给 `full_access`

2. **群聊权限 vs 个人权限**
   - 群聊给 `view`（只读）
   - 特定协作者给 `edit`（可编辑）
   - 创建者保留 `full_access`

3. **敏感文档保护**
   - 核心配置文件（SOUL.md等）仅限创建者可编辑
   - 群聊中不展示敏感配置
   - 定期审查文档权限

### ❌ 避免做法

1. 给群聊 `full_access`（所有人可删除）
2. 给陌生人编辑权限而不审核
3. 在群聊中分享包含敏感信息的文档

---

## 常见问题

**Q: 如何获取文档Token？**
A: 从飞书文档URL中提取，格式：`https://feishu.cn/docx/TOKEN`

**Q: 如何获取用户OpenID？**
A: 从OpenClaw的inbound metadata中获取 `sender_id`，格式：`ou_xxx`

**Q: 为什么添加了权限还是无法转发？**
A: 除了权限，还需确保文档设置中勾选了"允许转发"选项

**Q: 可以批量添加权限吗？**
A: 目前需要逐个添加，可通过循环脚本批量处理

---

## 快速参考

```
查询权限:
feishu_perm action=list token=xxx type=docx

添加用户编辑权限:
feishu_perm action=add token=xxx type=docx member_id=ou_xxx member_type=openid perm=edit

添加群聊查看权限:
feishu_perm action=add token=xxx type=docx member_id=oc_xxx member_type=openchat perm=view

移除权限:
feishu_perm action=remove token=xxx type=docx member_id=ou_xxx member_type=openid
```

---

## 版本

- v1.0.0 - 基础权限管理功能
- 创建日期：2026-02-25
- 基于实践整理

---

## 相关资源

- [feishu_doc](../feishu-doc/) - 飞书文档操作
- [飞书开放平台权限文档](https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/reference/drive-v1/permission/overview)
