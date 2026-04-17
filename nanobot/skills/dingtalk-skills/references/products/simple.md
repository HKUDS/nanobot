# 单命令产品合集

## 用户可见输出约束

- 本文中的 `dws` 命令示例仅供 agent 在后台执行参考，不要原样发给用户。
- 需要用户打开开放平台文档、审批页面、授权页面或其他入口时，只返回链接、页面入口或简短说明。
- 如果处理本文覆盖的产品请求时遇到 `AUTH_TOKEN_EXPIRED` / `USER_TOKEN_ILLEGAL` / "Token验证失败"，先由 agent 在后台发起 `dws auth login --device` 获取授权链接；用户可见回复只返回授权链接和“完成授权后我继续处理当前请求”的提示，不要让用户执行命令。

以下产品命令较少，合并参考。

---

## devdoc — 开放平台文档

### 搜索开放平台文档
```
Usage:
  dws devdoc article search [flags]
Example:
  dws devdoc article search --keyword "OAuth2 接入" --page 1 --size 10
Flags:
      --keyword string   搜索关键词 (必填)
      --page string      页码 (默认 1)
      --size string      每页数量 (默认 10)
```

### 搜索错误码
```
Usage:
  dws devdoc article search-error [flags]
Example:
  dws devdoc article search-error --keyword "403" --format json
Flags:
      --keyword string   错误码或关键词 (必填)
```

---

## oa — 审批

### 查询可见审批流程
```
Usage:
  dws oa approval list-forms [flags]
Example:
  dws oa approval list-forms --format json
```

### 查询审批实例详情
```
Usage:
  dws oa approval detail --instance-id <ID> [flags]
Example:
  dws oa approval detail --instance-id <ID> --format json
```

### 查询审批记录
```
Usage:
  dws oa approval records --instance-id <ID> [flags]
Example:
  dws oa approval records --instance-id <ID> --format json
```

### 查询待我审批的任务
```
Usage:
  dws oa approval tasks [flags]
Example:
  dws oa approval tasks --format json
```

### 查询待我处理的审批
```
Usage:
  dws oa approval pending [flags]
Example:
  dws oa approval pending --format json
```

### 查询我发起的审批
```
Usage:
  dws oa approval initiated [flags]
Example:
  dws oa approval initiated --format json
```

### 同意审批
```
Usage:
  dws oa approval approve --instance-id <ID> --task-id <TASK_ID> [flags]
Example:
  dws oa approval approve --instance-id <ID> --task-id <TASK_ID> --format json
```

### 拒绝审批
```
Usage:
  dws oa approval reject --instance-id <ID> --task-id <TASK_ID> [flags]
Example:
  dws oa approval reject --instance-id <ID> --task-id <TASK_ID> --remark "不符合要求" --format json
```

### 撤销审批
```
Usage:
  dws oa approval revoke --instance-id <ID> [flags]
Example:
  dws oa approval revoke --instance-id <ID> --format json
```

---

## 意图判断

- 用户说"开发文档/API 文档/接口文档" → `devdoc article search`
- 用户说"API 报错/错误码" → `devdoc article search-error`
- 用户说"审批/请假/报销/出差" → `oa approval`
- 用户说"同意审批/批准" → `oa approval approve`
- 用户说"拒绝审批/驳回" → `oa approval reject`
- 用户说"撤销审批/撤回" → `oa approval revoke`
- 用户说"待我审批/我要审批的" → `oa approval pending` 或 `oa approval tasks`
- 用户说"我发起的审批" → `oa approval initiated`

## 上下文传递表

| 操作 | 从返回中提取 | 用于 |
|------|-------------|------|
| `devdoc article search` | 文档链接 | 直接展示给用户 |
| `oa approval list-forms` | processCode | detail / records 等 |
| `oa approval tasks` | taskId, instanceId | approve / reject |
| `oa approval pending` | instanceId | detail / approve / reject |
| `oa approval initiated` | instanceId | detail / revoke |
