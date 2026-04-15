# wiki +node-create

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。

在飞书知识库中创建一个新节点，并自动解析目标知识空间。该 shortcut 对原生 `wiki.nodes.create` 做了一层更适合日常使用的封装：可以直接指定 `space_id`，也可以从父节点自动反查所属空间；在 `user` 身份下，如果同时省略 `--space-id` 和 `--parent-node-token`，还会自动回退到个人知识库 `my_library`。

## 命令

```bash
# 在个人知识库根目录下创建一个 docx 节点（user 身份默认回退到 my_library）
lark-cli wiki +node-create \
  --title "项目计划"

# 在指定知识空间中创建一个 docx 节点
lark-cli wiki +node-create \
  --space-id <SPACE_ID> \
  --title "项目计划"

# 在指定父节点下创建一个子节点
lark-cli wiki +node-create \
  --parent-node-token <PARENT_NODE_TOKEN> \
  --title "迭代记录"

# 显式指定创建到个人知识库（仅 user 身份；bot 不支持 `--space-id my_library`）
lark-cli wiki +node-create \
  --space-id my_library \
  --title "学习笔记"

# 创建一个快捷方式节点（shortcut）
lark-cli wiki +node-create \
  --parent-node-token <PARENT_NODE_TOKEN> \
  --node-type shortcut \
  --origin-node-token <ORIGIN_NODE_TOKEN> \
  --title "原文档快捷方式"

# 创建非 docx 类型节点
lark-cli wiki +node-create \
  --space-id <SPACE_ID> \
  --obj-type sheet \
  --title "周报数据"

# 预览底层调用链
lark-cli wiki +node-create \
  --title "Roadmap" \
  --dry-run
```

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--space-id` | 否 | 目标知识空间 ID；`user` 身份可传特殊值 `my_library` 表示个人知识库，`bot` 身份不支持该值 |
| `--parent-node-token` | 否 | 父知识库节点 token；传入后会在该节点下创建新节点 |
| `--title` | 否 | 节点标题 |
| `--node-type` | 否 | 节点类型，默认 `origin`；可选值：`origin`、`shortcut` |
| `--obj-type` | 否 | 节点对应对象类型，默认 `docx`；可选值：`sheet`、`mindnote`、`bitable`、`docx`、`slides` |
| `--origin-node-token` | 否 | 当 `--node-type=shortcut` 时必填，表示快捷方式指向的源节点 token |

## 空间解析规则

- **优先级**：`--space-id` > `--parent-node-token` > `my_library`
- **显式 space**：传了 `--space-id` 时，shortcut 会直接使用该空间；如果该值是 `my_library`，则仅 `user` 身份可用，并会先调用 `GET /open-apis/wiki/v2/spaces/my_library` 解析成真实 `space_id`
- **父节点推断**：未传 `--space-id` 但传了 `--parent-node-token` 时，会先调用 `GET /open-apis/wiki/v2/spaces/get_node` 获取父节点，再读取其 `space_id`
- **个人知识库回退**：`user` 身份下，如果 `--space-id` 和 `--parent-node-token` 都没传，会自动解析 `my_library`
- **bot 身份限制**：`bot` 身份既没有“个人知识库”回退语义，也不支持显式传 `--space-id my_library`；请改用真实 `space_id` 或 `--parent-node-token`

## shortcut 节点规则

- `--node-type=shortcut` 时，必须同时提供 `--origin-node-token`
- `--node-type=origin` 时，不能传 `--origin-node-token`
- `shortcut` 节点只是知识库中的快捷方式入口；真正被引用的节点由 `--origin-node-token` 指定

## 一致性校验

- 如果同时传了 `--space-id` 和 `--parent-node-token`，shortcut 会校验父节点所属空间是否与 `--space-id` 一致
- 如果两者解析出的空间不一致，命令会直接返回验证错误，而不会继续创建
- 对于 `my_library`，`user` 身份下也会先解析出真实 `space_id` 后再做这层校验

## 行为说明

- **默认对象类型**：不传 `--obj-type` 时默认创建 `docx` 节点
- **默认节点类型**：不传 `--node-type` 时默认创建普通节点 `origin`
- **dry-run 编排**：
  - 仅传 `--title`：会展示 `my_library` 解析 + 创建节点 两步调用
  - 仅传 `--parent-node-token`：会展示“查询父节点 -> 创建节点”两步调用
  - 同时需要 `my_library` 和父节点时：会展示三步调用链
- **输出结果**：成功后会返回 `resolved_space_id`、`resolved_by`、`node_token`、`obj_token`、`obj_type`、`node_type`、`title` 等字段，便于后续继续操作

## 推荐场景

- 用户说“在我的知识库里新建一篇页面”时，优先用 `lark-cli wiki +node-create --title "..."`
- 用户已经给出父页面链接或 `parent_node_token` 时，优先传 `--parent-node-token`，让 shortcut 自动推导空间
- 需要创建知识库快捷方式时，使用 `--node-type shortcut --origin-node-token <token>`

> [!CAUTION]
> `wiki +node-create` 是**写入操作**，执行前必须确认用户意图。

## 参考

- [lark-wiki](../SKILL.md) -- 知识库全部命令
- [lark-shared](../../lark-shared/SKILL.md) -- 认证和全局参数
