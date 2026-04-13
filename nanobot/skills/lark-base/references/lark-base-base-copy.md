# base +base-copy

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。

复制一个已有 Base；可选只复制结构，不复制内容。

## 推荐命令

```bash
lark-cli base +base-copy \
  --base-token app_xxx \
  --name "Copied Base"

lark-cli base +base-copy \
  --base-token app_xxx \
  --name "Copied Base" \
  --folder-token fld_xxx \
  --time-zone Asia/Shanghai \
  --without-content
```

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--base-token <token>` | 是 | 源 Base Token |
| `--name <name>` | 否 | 新 Base 名称 |
| `--folder-token <token>` | 否 | 目标文件夹 token |
| `--time-zone <tz>` | 否 | 时区，如 `Asia/Shanghai` |
| `--without-content` | 否 | 只复制结构，不复制内容 |

## API 入参详情

**HTTP 方法和路径：**

```
POST /open-apis/base/v3/bases/:base_token/copy
```

## 返回重点

- 返回 `base`。
- CLI 会额外标记 `copied: true`。
- 回复结果时，必须主动返回新 Base 的可访问链接：
  - 优先使用返回结果中的 `base.url`
  - 同时返回新 Base 的 token；字段名以实际返回为准，常见为 `base_token` 或 `app_token`
  - 如果本次返回没有 `url`，至少返回新 Base 的名称和 token

> [!IMPORTANT]
> 如果 Base 是**以应用身份（bot）复制**出来的，agent 在复制成功后应**默认继续使用 bot 身份**，为当前可用的 user 身份添加该 Base 的 `full_access`（管理员）权限。
> 推荐流程：
> 1. 先用 `lark-cli contact +get-user` 获取当前用户信息，并从返回结果中读取该用户的 `open_id`
> 2. 再切回 bot 身份，使用这个 `open_id` 给该用户授权该 Base 的 `full_access`（管理员）权限
>
> 如果 `lark-cli contact +get-user` 无法执行，或者本地没有可用的 user 身份、拿不到当前用户的 `open_id`，则应视为“本地没有可用的 user 身份”，明确说明因此未完成授权。
>
> 回复复制结果时，除 `base token` 和可访问链接外，还必须明确告知用户授权结果：
> - 如果授权成功：直接说明当前 user 已获得该 Base 的管理员权限
> - 如果本地没有可用的 user 身份：明确说明因此未完成授权
> - 如果授权失败：明确说明 Base 已复制成功，但授权失败，并透出失败原因；同时提示用户可以稍后重试授权，或继续使用应用身份（bot）处理该 Base
>
> 如果授权未完成，应继续给出后续引导：用户可以稍后重试授权，也可以继续使用应用身份（bot）处理该 Base；如果希望后续改由自己管理，也可将 Base owner 转移给该用户。
>
> **仍然不要擅自执行 owner 转移。** 如果用户需要把 owner 转给自己，必须单独确认。

## 工作流

> [!CAUTION]
> 这是**写入操作** — 执行前必须向用户确认。

1. 先确认源 Base Token。
2. `--name`、`--folder-token`、`--time-zone` 都是可选项；用户没要求时不要为这些可选参数额外追问。
3. 只要结构时，显式传 `--without-content`。
4. 复制成功后，整理并返回：新 Base 名称、token，以及响应中已有的可访问链接。

## 参考

- [lark-base-workspace.md](lark-base-workspace.md) — base / workspace 索引页
- [lark-base-base-create.md](lark-base-base-create.md) — 创建全新 Base
