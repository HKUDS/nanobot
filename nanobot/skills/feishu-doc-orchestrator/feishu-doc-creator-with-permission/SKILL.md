---
name: feishu-doc-creator-with-permission
description: 文档创建+权限管理子技能 - 在飞书创建文档并自动完成权限分配（添加协作者+转移所有权），两步原子操作。
---

# 文档创建+权限管理子技能

## 职责
在飞书创建新文档，并**自动完成完整的权限管理流程**（添加协作者 + 转移所有权），确保用户获得完全控制权。

## 为什么合并？

创建文档和权限管理是**强关联的操作**：
- 应用创建的文档，用户默认没有任何权限
- 必须先添加协作者权限，用户才能编辑
- 必须再转移所有权，用户才能删除

分开执行容易导致遗漏，合并后确保**每次创建都正确分配权限**。

## 输入
- 文档标题（必需）
- Markdown 文件路径（可选，用于确定标题）

## 输出
- `output/doc_with_permission.json` - 包含文档信息和权限状态

## 工作流程

### 第一步：创建文档
使用 `tenant_access_token` 创建新文档，应用成为创建者。

### 第二步：添加协作者权限
使用 `tenant_access_token` 添加协作者，用户获得编辑权限。
- ⚠️ 只有 `tenant_token` 可以添加协作者

### 第三步：转移所有权
使用 `user_access_token` 转移所有权，用户获得完全控制权（可编辑+可删除）。
- ⚠️ 只有 `user_token` 可以转移所有权

### 第四步：保存结果
保存文档信息和权限状态到 `output/doc_with_permission.json`。

## 数据格式

### doc_with_permission.json 格式
```json
{
  "document_id": "U2wNd2rMkot6fzxr67ScN7hJn7c",
  "document_url": "https://feishu.cn/docx/U2wNd2rMkot6fzxr67ScN7hJn7c",
  "title": "文档标题",
  "created_at": "2026-01-22T10:30:00",
  "permission": {
    "collaborator_added": true,
    "owner_transferred": true,
    "user_has_full_control": true,
    "collaborator_id": "ou_xxx"
  }
}
```

## 使用方式

### 命令行
```bash
python scripts/doc_creator_with_permission.py "文档标题" output
```

### 作为子技能被调用
```python
result = call_skill("feishu-doc-creator-with-permission", {
    "title": "文档标题",
    "output_dir": "workflow/step2_create_with_permission"
})
# 返回: {"doc_info_file": "workflow/step2_create_with_permission/doc_with_permission.json"}
```

## 权限管理的必要性

```
只用 tenant_access_token 创建文档：
├─ 应用 = 创建者
├─ 用户 = 无权限 ❌
└─ 结果：用户看不到文档

添加协作者权限后：
├─ 应用 = 创建者
├─ 用户 = 可编辑
└─ 结果：用户可编辑，但无法删除 ⚠️

转移所有权后：
├─ 应用 = 创建者
├─ 用户 = 所有者 ✅
└─ 结果：用户有完全控制权（可编辑 + 可删除）
```

## 与其他技能的协作
- 接收来自主编排技能的标题
- 输出给 `feishu-block-adder`、`feishu-doc-verifier`、`feishu-logger`
- 只传递文件路径，不传递内容
