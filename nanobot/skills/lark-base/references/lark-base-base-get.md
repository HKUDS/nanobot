# base +base-get

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。

读取一个 Base 的详情。

## 推荐命令

```bash
lark-cli base +base-get \
  --base-token app_xxx
```

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--base-token <token>` | 是 | Base Token |

## API 入参详情

**HTTP 方法和路径：**

```
GET /open-apis/base/v3/bases/:base_token
```

## 返回重点

- 返回 `base`，通常包含 `base_token / name / url` 等信息。

## 坑点

- ⚠️ 先确认传入的是 `base_token`，不是 `workspace_token`。
- ⚠️ 如果最初输入来自 `/wiki/...`，不要直接把 `wiki_token` 当 `--base-token`；若报 `param baseToken is invalid` / `base_token invalid`，先用 `lark-cli wiki spaces get_node` 取 `node.obj_token`，再重试 `+base-get`。

## 参考

- [lark-base-workspace.md](lark-base-workspace.md) — base 索引页
