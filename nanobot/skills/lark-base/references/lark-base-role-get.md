# base +role-get

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。
>
> **前置条件：** 需要base开启了高级权限，如果调用这个接口返回没有开启高级权限，可以参考 [`lark-base-advperm-enable.md`](lark-base-advperm-enable.md) 了解高级权限启用规则。

获取指定角色的完整配置详情（AdvPermBaseRole），包含表权限、字段权限、记录筛选等全量配置。

## 推荐命令

```bash
lark-cli base +role-get \
  --base-token VwGhb**************fMnod \
  --role-id rolxxxxxx4
```

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--base-token <token>` | 是 | Base Token，27 位字母数字字符串 |
| `--role-id <id>` | 是 | 角色 ID，格式 `rol` + 8 位字母数字 |
| `--format <fmt>` | 否 | 输出格式：json / pretty / table / csv / ndjson |

## API 入参详情

**HTTP 方法和路径：**

```
GET /open-apis/base/v3/bases/:base_token/roles/:role_id
```

**Path 参数：**

| 参数 | 必填 | 说明 |
|------|------|------|
| `base_token` | 是 | Base 的唯一标识 |
| `role_id` | 是 | 角色 ID |

无 Query 参数，无 Request Body。

## API 出参详情

**Response `data` 字段（JSON 字符串，需双重解析）：**

完整的 AdvPermBaseRole 对象（结构详见 [role-config.md](role-config.md)）：

| 字段 | 类型 | 说明 |
|------|------|------|
| `role_id` | string | 角色 ID |
| `role_name` | string | 角色名称 |
| `role_type` | string | 角色类型 |
| `base_rule_map` | map\<string, bool\> | Base 级权限（copy/download） |
| `table_rule_map` | map\<string, TableRule\> | 数据表权限配置 |
| `dashboard_rule_map` | map\<string, DashboardRule\> | 仪表盘权限配置 |
| `docx_rule_map` | map\<string, DocxRule\> | 文档权限配置 |

## 返回值

命令成功后输出完整角色配置 JSON：

```json
{
  "ok": true,
  "data": {
    "role_id": "rolxxxxxx4",
    "role_name": "财务审核员",
    "role_type": "custom_role",
    "base_rule_map": {"copy": false, "download": false},
    "table_rule_map": {
      "订单表": {"perm": "edit", "record_rule": {...}, "field_rule": {...}},
      "用户表": {"perm": "read_only"}
    }
  }
}
```

## 坑点

- ⚠️ **与 +role-list 的区别**：`+role-list` 只返回摘要（role_id/name/type），`+role-get` 返回完整的权限配置
- ⚠️ **data 是 JSON 字符串**：响应 `data` 是 string 类型，需要双重解析
- ⚠️ **角色不存在时**：data 为空字符串，不会报错

## 参考

- [lark-base](../SKILL.md) — 多维表格全部命令
- [lark-shared](../../lark-shared/SKILL.md) — 认证和全局参数
