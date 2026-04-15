# base +role-create

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。
> 
> **前置条件：** 需要base开启了高级权限，如果调用这个接口返回没有开启高级权限，可以参考 [`lark-base-advperm-enable.md`](lark-base-advperm-enable.md) 了解高级权限启用规则。

在指定 Base 中创建一个自定义角色，需传入完整的 AdvPermBaseRoleConfig 作为角色配置。

## 推荐命令

```bash
# 创建简单角色（仅设置名称和类型）
lark-cli base +role-create \
  --base-token VwGhb**************fMnod \
  --json '{"role_name":"财务审核员","role_type":"custom_role"}'

# 创建角色并配置表权限、字段权限、记录筛选
lark-cli base +role-create \
  --base-token VwGhb**************fMnod \
  --json '{"role_name":"财务审核员","role_type":"custom_role","base_rule_map":{"copy":false,"download":false},"table_rule_map":{"订单表":{"perm":"edit","record_rule":{"record_operations":["add"],"edit_filter_rule_group":{"conjunction":"and","filter_rules":[{"conjunction":"and","filters":[{"field_name":"部门","operator":"is","filter_values":["财务部"]}]}]},"other_record_all_read":true},"field_rule":{"field_perm_mode":"specify","field_perms":{"金额":"edit","备注":"read","密码":"no_perm"}}},"用户表":{"perm":"read_only"}},"dashboard_rule_map":{"销售看板":{"perm":"read_only"}}}'
```

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--base-token <token>` | 是 | Base Token，27 位字母数字字符串 |
| `--json <body>` | 是 | AdvPermBaseRoleConfig JSON，包含角色名称、类型、权限配置 |

## API 入参详情

**HTTP 方法和路径：**

```
POST /open-apis/base/v3/bases/:base_token/roles
```

**Path 参数：**

| 参数 | 必填 | 说明 |
|------|------|------|
| `base_token` | 是 | Base 的唯一标识，27 位字母数字字符串 |

**Request Body（JSON — AdvPermBaseRoleConfig）：**

> 完整的权限配置结构详见 [role-config.md](role-config.md)

## API 出参详情

**Response：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `code` | int32 | 错误码，0 表示成功 |
| `message` | string | 错误信息 |
| `data` | string | 创建成功时为空 |

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


1. 向用户确认 `--base-token` 和角色配置 JSON
2. 执行命令
3. 确认返回 `code: 0` 表示创建成功

## 坑点

- ⚠️ **role_type 必须为 custom_role**：创建接口仅支持 `custom_role`，传其他值会报业务错误
- ⚠️ **API 路径版本**：本接口使用 `base/v3`，路径必须从原始文档提取，不要用 WebSearch 补全
- ⚠️ **data 字段是 JSON 字符串**：响应中 `data` 是 string 类型（非 object），需要双重解析
- ⚠️ **Filter 字段**：`field_name`、`operator`、`filter_values` 由客户端传入，`field_type`、`field_ui_type`、`reference_type` 由服务端 filterFiller 自动补全
- ⚠️ **前置条件**：Base 必须已开启高级权限，操作用户必须为 Base 管理员

## 参考

- [lark-base](../SKILL.md) — 多维表格全部命令
- [lark-shared](../../lark-shared/SKILL.md) — 认证和全局参数
