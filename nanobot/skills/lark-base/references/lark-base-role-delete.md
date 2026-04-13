# base +role-delete

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。
>
> **前置条件：** 需要base开启了高级权限，如果调用这个接口返回没有开启高级权限，可以参考 [`lark-base-advperm-enable.md`](lark-base-advperm-enable.md) 了解高级权限启用规则。

删除指定的自定义角色。系统角色（editor / reader）不可删除。

## 推荐命令

```bash
lark-cli base +role-delete \
  --base-token VwGhb**************fMnod \
  --role-id rolxxxxxx4
```

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--base-token <token>` | 是 | Base Token，27 位字母数字字符串 |
| `--role-id <id>` | 是 | 角色 ID，格式 `rol` + 8 位字母数字 |

## API 入参详情

**HTTP 方法和路径：**

```
DELETE /open-apis/base/v3/bases/:base_token/roles/:role_id
```

**Path 参数：**

| 参数 | 必填 | 说明 |
|------|------|------|
| `base_token` | 是 | Base 的唯一标识 |
| `role_id` | 是 | 角色 ID |

无 Query 参数，无 Request Body。

## API 出参详情

**Response：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `code` | int32 | 错误码，0 表示成功 |
| `message` | string | 错误信息 |
| `data` | string | 删除成功时为空 |

## 返回值

命令成功后输出 JSON：

```json
{
  "ok": true,
  "data": {
    "success": true
  }
}
```

## 工作流

> [!CAUTION]
> 这是**高风险不可逆操作** — 删除后无法恢复，执行前必须向用户二次确认。

1. 建议先用 `+role-list` 确认角色存在
2. 向用户确认 `--base-token` 和 `--role-id`
3. 执行命令
4. 确认返回 `code: 0`

## 坑点

- ⚠️ **仅支持删除自定义角色**：系统角色（editor / reader）不可删除，会报业务错误
- ⚠️ **不可逆操作**：删除后角色及其关联的成员配置无法恢复
- ⚠️ **role_id 来源**：可通过 `+role-list` 获取，格式为 `rol` + 8 位字母数字

## 参考

- [lark-base](../SKILL.md) — 多维表格全部命令
- [lark-shared](../../lark-shared/SKILL.md) — 认证和全局参数
