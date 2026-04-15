# base +advperm-enable

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。

启用指定 Base 的高级权限。启用后可使用自定义角色等高级权限功能。

## 推荐命令

```bash
# 启用高级权限
lark-cli base +advperm-enable \
  --base-token VwGh**************Mnod
```

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--base-token <token>` | 是 | Base Token，27 位字母数字字符串 |

## API 入参详情

**HTTP 方法和路径：**

```
PUT /open-apis/base/v3/bases/:base_token/advperm/enable?enable=true
```

**Path 参数：**

| 参数 | 必填 | 说明 |
|------|------|------|
| `base_token` | 是 | Base 的唯一标识，27 位字母数字字符串 |

**Query 参数：**

| 参数 | 必填 | 类型 | 说明 |
|------|------|------|------|
| `enable` | 是 | bool | 固定为 `true`，表示启用高级权限 |

## API 出参详情

**Response：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `code` | int32 | 错误码，0 表示成功 |
| `message` | string | 错误信息 |
| `data` | string | 成功时为空 |

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

1. 向用户确认 `--base-token`
2. 执行命令
3. 确认返回 `code: 0` 表示启用成功

## 坑点

- ⚠️ **操作用户必须为 Base 管理员**：非管理员调用会返回权限错误
- ⚠️ **API 路径版本**：本接口使用 `base/v3`，路径必须从原始文档提取，不要用 WebSearch 补全
- ⚠️ **data 字段是 JSON 字符串**：响应中 `data` 是 string 类型（非 object），需要双重解析
- ⚠️ **启用后才能管理角色**：`+role-create / +role-update / +role-delete` 等角色操作需要先启用高级权限

## 参考

- [lark-base](../SKILL.md) — 多维表格全部命令
- [lark-shared](../../lark-shared/SKILL.md) — 认证和全局参数
