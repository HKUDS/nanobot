# base +role-update

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。
>
> **前置条件：** 需要base开启了高级权限，如果调用这个接口返回没有开启高级权限，可以参考 [`lark-base-advperm-enable.md`](lark-base-advperm-enable.md) 了解高级权限启用规则。

更新指定角色的权限配置。

## 推荐命令

```bash
# 仅修改角色名称
lark-cli base +role-update \
  --base-token VwGhb**************fMnod \
  --role-id rolxxxxxx4 \
  --json '{"role_name":"高级审核员","role_type":"custom_role"}'

# 修改某个表的权限（其他表不受影响）
lark-cli base +role-update \
  --base-token VwGhb**************fMnod \
  --role-id rolxxxxxx4 \
  --json '{"role_name":"财务审核员","role_type":"custom_role","table_rule_map":{"订单表":{"perm":"read_only"}}}'
```

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--base-token <token>` | 是 | Base Token，27 位字母数字字符串 |
| `--role-id <id>` | 是 | 角色 ID，格式 `rol` + 8 位字母数字 |
| `--json <body>` | 是 | 增量 AdvPermBaseRoleConfig JSON，仅含需变更的字段 |

## API 入参详情

**HTTP 方法和路径：**

```
PUT /open-apis/base/v3/bases/:base_token/roles/:role_id
```

**Path 参数：**

| 参数 | 必填 | 说明 |
|------|------|------|
| `base_token` | 是 | Base 的唯一标识 |
| `role_id` | 是 | 角色 ID |

**Request Body（JSON — 增量 AdvPermBaseRoleConfig）：**

> 完整的权限配置结构详见 [role-config.md](role-config.md)，**更新时需要在原始配置上修改，传入的role配置信息尽量完整**。

## API 出参详情

**Response：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `code` | int32 | 错误码，0 表示成功 |
| `message` | string | 错误信息 |
| `data` | string | 更新成功时为空 |

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
> 这是**高危写入操作** — 执行前必须向用户确认，需要 `--yes` 标志。

1. 建议先用 `+role-get` 获取当前配置，确认变更范围
2. 向用户确认 `--base-token`、`--role-id` 和变更 JSON，对于变化的部分可以高亮提示用户
3. 执行命令
4. 确认返回 `code: 0`

## 坑点

- ⚠️ **Delta Merge 语义**：仅传入需变更的字段即可，未传入的保持不变。例如只传 `table_rule_map` 中某个表的 perm，其他表不受影响
- ⚠️ **role_name 和 role_type 必填**：即使不修改也必须传入当前值
- ⚠️ **body 不能为 nil**：PUT 请求必须传 body，否则服务端返回错误

## 参考

- [lark-base](../SKILL.md) — 多维表格全部命令
- [lark-shared](../../lark-shared/SKILL.md) — 认证和全局参数
