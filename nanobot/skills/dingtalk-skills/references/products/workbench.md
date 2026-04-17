# 工作台 (workbench) 命令参考

## 用户可见输出约束

- 本文中的 `dws` 命令示例仅供 agent 在后台执行参考，不要原样发给用户。
- 需要用户打开工作台应用页面、授权页面或其他入口时，只返回链接、页面入口或简短说明。
- 如果处理工作台请求时遇到 `AUTH_TOKEN_EXPIRED` / `USER_TOKEN_ILLEGAL` / "Token验证失败"，先由 agent 在后台发起 `dws auth login --device` 获取授权链接；用户可见回复只返回授权链接和“完成授权后我继续处理工作台请求”的提示，不要让用户执行命令。

## 命令总览

### 查看所有工作台应用
```
Usage:
  dws workbench app list [flags]
Example:
  dws workbench app list
```
### 批量获取应用详情
```
Usage:
  dws workbench app get [flags]
Example:
  dws workbench app get --ids <APP_ID_1>,<APP_ID_2>
Flags:
      --ids string   应用 ID 列表 (必填)
```

## 意图判断

用户说"工作台有什么应用/看看应用" → `app list`
用户说"应用详情" → `app get` (需 appId)

## 核心工作流

```bash
# 查看所有应用 — 提取 appId
dws workbench app list --format json

# 获取应用详情
dws workbench app get --ids app1,app2 --format json
```
## 上下文传递表
| 操作 | 提取 | 用于 |
|------|------|------|
| `app list` | `appId` | app get 的 --ids |
