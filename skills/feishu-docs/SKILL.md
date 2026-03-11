---
name: feishu-docs
description: "飞书云文档工具 - 读取、搜索、创建飞书云文档内容"
metadata: {"nanobot":{"emoji":"📄","requires":{"env":["FEISHU_APP_ID","FEISHU_APP_SECRET"]}}}
---

# 飞书云文档 (feishu-docs)

读取和管理飞书云文档内容。

## 前提条件

1. **开通飞书应用权限**
   - 进入 https://open.feishu.cn/app
   - 选择你的应用 → 权限管理
   - 开通以下权限：
     - `查看、评论、编辑和管理文档`
     - `查看、编辑和管理知识库`

2. **配置环境变量**
   ```bash
   export FEISHU_APP_ID="你的App ID"
   export FEISHU_APP_SECRET="你的App Secret"
   ```

## 工具函数

### 1. list_docs - 列出云文档

```
列出用户的云文档列表
```

**参数：**
- `parent_node` (可选): 文件夹 token，默认列出根目录
- `page_size` (可选): 每页数量，默认 20

**示例：**
```
列出我的云文档
列出 /文档/项目 文件夹的内容
```

### 2. read_doc - 读取文档内容

```
读取指定飞书云文档的内容
```

**参数：**
- `file_token` (必填): 文档的 file_token

**如何获取 file_token：**
- 打开飞书文档
- 点击右上角「分享」→「复制链接」
- 链接格式：`https://pbichxgoof.feishu.cn/docx/xxxxx`
- `xxxxx` 就是 file_token

**示例：**
```
读取文档 abc123
获取飞书文档内容 token=abc123
```

### 3. search_docs - 搜索云文档

```
搜索飞书云文档中的内容
```

**参数：**
- `keyword` (必填): 搜索关键词
- `page_size` (可选): 返回数量，默认 10

**示例：**
```
搜索包含"项目计划"的文档
搜索云文档 关键词=会议纪要
```

## 使用示例

### 列出所有文档
```
用户：列出我的飞书云文档
助手：(调用 list_docs，返回文档列表)
```

### 读取指定文档
```
用户：读取这个文档的内容 https://pbichxgoof.feishu.cn/docx/abc123
助手：(调用 read_doc，返回文档内容)
```

### 搜索文档
```
用户：帮我搜索关于"Q1财报"的飞书文档
助手：(调用 search_docs，返回搜索结果)
```

## 错误处理

| 错误信息 | 可能原因 | 解决方案 |
|----------|----------|----------|
| 获取 token 失败 | APP_ID 或 APP_SECRET 错误 | 检查环境变量配置 |
| 获取文件列表失败 | 应用没有云文档权限 | 开通应用权限 |
| 获取文档内容失败 | 文档未分享给应用 | 让文档所有者分享给应用 |
| 没有找到文档 | 权限不足或内容为空 | 检查文档权限 |

## 技术细节

- 使用飞书开放平台 API v1
- 认证方式：tenant_access_token
- 支持文档类型：docx, sheet, bitable, mindnote
- 免费 API 额度：100万次/月

## 相关链接

- [飞书开放平台文档](https://open.feishu.cn/document/)
- [云文档 API 参考](https://open.feishu.cn/document/server-docs/drive-v1)
