# base +role-list

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。
>
> **前置条件：** 需要base开启了高级权限，如果调用这个接口返回没有开启高级权限，可以参考 [`lark-base-advperm-enable.md`](lark-base-advperm-enable.md) 了解高级权限启用规则。。

获取指定 Base 下所有角色的摘要信息列表（包括系统角色和自定义角色），返回 role_id / role_name / role_type。

## 推荐命令

```bash
lark-cli base +role-list --base-token VwGhb**************fMnod
```

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--base-token <token>` | 是 | Base Token，27 位字母数字字符串 |
| `--format <fmt>` | 否 | 输出格式：json / pretty / table / csv / ndjson |

## API 入参详情

**HTTP 方法和路径：**

```
GET /open-apis/base/v3/bases/:base_token/roles
```

**Path 参数：**

| 参数 | 必填 | 说明 |
|------|------|------|
| `base_token` | 是 | Base 的唯一标识 |

无 Query 参数，无 Request Body。

## API 出参详情

**Response `data` 字段（JSON 字符串，需双重解析）：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `base_roles` | []string | AIBaseRoleRef 的 JSON 字符串数组 |
| `total` | int32 | 角色总数 |

**AIBaseRoleRef 结构：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `role_id` | string | 角色 ID，如 `rolxxxxxx1` |
| `role_name` | string | 角色名称 |
| `role_type` | string | 角色类型：`editor` / `reader` / `custom_role` |

## 返回值

命令成功后输出 JSON：

```json
{
  "ok": true,
  "data": {
    "base_roles": [
      "{\"role_id\":\"rolxxxxxx1\",\"role_name\":\"技术管理员\",\"role_type\":\"custom_role\"}",
      "{\"role_id\":\"rolxxxxxx2\",\"role_name\":\"编辑者\",\"role_type\":\"editor\"}"
    ],
    "total": 4
  }
}
```

## 坑点

- ⚠️ **data 是 JSON 字符串**：响应 `data` 是 string 类型，内部 `base_roles` 数组的每个元素也是 JSON 字符串，需要多层解析
- ⚠️ **返回摘要信息**：此接口只返回 role_id / role_name / role_type，不含完整权限配置。要获取完整配置请用 `+role-get`
- ⚠️ **包含系统角色**：返回结果包含  editor / reader 两个系统角色

## 参考

- [lark-base](../SKILL.md) — 多维表格全部命令
- [lark-shared](../../lark-shared/SKILL.md) — 认证和全局参数
