# nanobot 中的 AI Agent Memory

本页介绍 nanobot 如何实现长期 AI Agent Memory：session 历史记录、压缩归档、持久知识文件、Dream 整合，以及由 Git 支持的 memory 变更。

nanobot 的 memory 建立在一个简单的理念之上：memory 应该让人感觉鲜活，但不应让人感觉混乱。

良好的 memory 不是一堆笔记。它是一套安静的注意力系统。它会注意哪些内容值得保留，放下那些不再需要聚光灯关注的内容，并将经历转化为平静、持久且有用的东西。

这就是 nanobot 中 memory 的形态。

## 设计

nanobot 不会将 memory 视为一个巨大的文件。

它将 memory 分成多个层次，因为不同类型的记忆需要不同的工具：

- `session.messages` 保存正在进行的短期对话。
- `memory/history.jsonl` 是压缩后的历史对话轮次的持续归档。
- `SOUL.md`、`USER.md` 和 `memory/MEMORY.md` 是持久知识文件。
- `GitStore` 记录这些持久文件随时间发生的变化。

这让系统在当下保持轻量，同时能够随时间进行反思。

## 流程

Memory 分两个阶段在 nanobot 中流转。

### 阶段 1：Consolidator

当对话变得足够大、开始给上下文窗口带来压力时，nanobot 不会试图永远携带每一条旧消息。

相反，`Consolidator` 会总结对话中最早且安全的一部分，并将该总结追加到 `memory/history.jsonl`。

该文件具有以下特点：

- 仅追加
- 基于游标
- 优先针对机器消费进行优化，其次才是供人检查

每一行都是一个 JSON 对象：

```json
{"cursor": 42, "timestamp": "2026-04-03 00:02", "content": "- User prefers dark mode\n- Decided to use PostgreSQL"}
```

它不是最终的 memory，而是塑造最终 memory 的原材料。

### 阶段 2：Dream

`Dream` 是更缓慢、更具思考性的层。默认情况下，它按 cron 计划运行，也可以手动触发。

Dream 会读取：

- `memory/history.jsonl` 中的新条目
- 当前的 `SOUL.md`
- 当前的 `USER.md`
- 当前的 `memory/MEMORY.md`

然后，它会在一次操作中精确地编辑长期文件：不是重写所有内容，而是进行能保持 memory 连贯性的最小诚实变更。

这就是为什么 nanobot 的 memory 不只是归档。它还具有解释性。

## 文件

在本页中，`workspace` 表示已配置的**代理工作区**（默认为
`~/.nanobot/workspace/`，或通过 `--workspace` 传入的路径）。在 WebUI 中选择不同的项目会更改该聊天的项目上下文和工具工作目录；不会重新定位下面的文件。

```text
workspace/
├── SOUL.md              # The bot's long-term voice and communication style
├── USER.md              # Stable knowledge about the user
├── prompts/
│   ├── README.md        # Notes for memory guidance files
│   └── dream.md         # Optional instructions for how Dream organizes memory
└── memory/
    ├── MEMORY.md        # Project facts, decisions, and durable context
    ├── history.jsonl    # Append-only history summaries
    ├── .cursor          # Consolidator write cursor
    ├── .dream_cursor    # Dream consumption cursor
    └── .git/            # Version history for long-term memory files
```

所选项目可以提供自己的 `AGENTS.md`，但项目本地的 `SOUL.md`、`USER.md` 和 `memory/` 不会替代上述由 Agent 所拥有的文件。这样可以让一个 Agent 在不同项目间工作时，始终保持其配置文件和 memory 的连续性。当必须隔离身份或 memory 时，请使用单独配置的 Agent 工作区。

这些文件承担不同的职责：

- `SOUL.md` 记住 nanobot 应该如何表达。
- `USER.md` 记住用户是谁以及用户的偏好。
- `MEMORY.md` 记住关于工作本身仍然成立的内容。
- `history.jsonl` 记住一路上发生的事情。

## 为什么使用 `history.jsonl`

旧的 `HISTORY.md` 格式便于随意阅读，但作为操作基础时过于脆弱。

`history.jsonl` 为 nanobot 提供：

- 稳定的增量游标
- 更安全的机器解析
- 更方便的批处理
- 更清晰的迁移和压缩
- 原始历史与整理后知识之间更好的边界

你仍然可以使用熟悉的工具搜索它：

```bash
# grep
grep -i "keyword" memory/history.jsonl

# jq
cat memory/history.jsonl | jq -r 'select(.content | test("keyword"; "i")) | .content' | tail -20

# Python
python -c "import json; [print(json.loads(l).get('content','')) for l in open('memory/history.jsonl','r',encoding='utf-8') if l.strip() and 'keyword' in l.lower()][-20:]"
```

这种差异不仅是技术层面的，也同样是理念层面的：

- `history.jsonl` 用于结构
- `SOUL.md`、`USER.md` 和 `MEMORY.md` 用于意义

## 命令

Memory 并不是藏在幕后。用户可以检查并引导它。

| 命令 | 功能 |
|---------|--------------|
| `/dream` | 立即运行 Dream |
| `/dream-log` | 显示最新的 Dream memory 变更 |
| `/dream-log <sha>` | 显示特定的 Dream 变更 |
| `/dream-restore` | 列出最近的 Dream memory 版本 |
| `/dream-restore <sha>` | 将 memory 恢复到特定变更之前的状态 |
| `/dream-prompt` | 显示 Dream 如何接受 memory 引导 |
| `/dream-prompt init` | 在 `prompts/dream.md` 创建可编辑的 Dream memory 指南 |

这些命令存在是有原因的：自动 memory 功能强大，但用户始终应保有检查、理解和恢复它的权利。

## 版本化 Memory

Dream 更改长期 memory 文件后，nanobot 可以使用 `GitStore` 记录该变更。

这为 memory 提供了自己的历史记录：

- 可以检查发生了哪些变化
- 可以比较不同版本
- 可以恢复到之前的状态

这会将 memory 从无声的变化转变为可审计的过程。

## 引导 Dream

Dream 使用 nanobot 内置的 memory 指令决定保留、更新或遗忘哪些内容。大多数用户可以保持默认设置。

如果某个工作区需要不同的 memory 风格，可以创建一个可编辑的指南：

```text
/dream-prompt init
```

这会创建：

```text
workspace/prompts/dream.md
```

使用普通 Markdown 编辑该文件。当文件中包含内容时，Dream 会在读取最新对话历史之前，按照该文件的内容处理此工作区。你无需将历史记录粘贴到文件中；Dream 会自动添加当前的 `## Conversation History` 块。

要恢复 nanobot 的默认行为，请删除 `prompts/dream.md` 或将其留空。

每个工作区都有自己的指南。更改此文件不会影响其他 nanobot 工作区。

## 配置

Dream 在 `agents.defaults.dream` 下配置：

```json
{
  "agents": {
    "defaults": {
      "dream": {
        "intervalH": 2,
        "modelOverride": null
      }
    }
  }
}
```

| 字段 | 含义 |
|-------|---------|
| `intervalH` | Dream 的运行频率，单位为小时 |
| `cron` | Cron 表达式覆盖项（优先于 `intervalH`） |
| `modelOverride` | Dream 使用的可选 model 预设名称 |

实际来说：

- `intervalH` 是配置 Dream 运行频率的常规方式。内部会将其作为 `every` 计划运行。
- 设置 `cron` 后，它会覆盖 `intervalH`，从而允许使用精确的 cron 表达式（例如 `0 */4 * * *`）。
- `modelOverride` 为 Dream 从 `model_presets` 中选择一个命名条目。它只接受预设名称；不支持原始 model 标识符。如果省略，Dream 会使用主 Agent 所选的运行时。

## 实际使用

在日常使用中，这意味着：

- 对话可以保持快速，而无需携带无限的上下文
- 持久事实可以随着时间变得更加清晰，而不是更加嘈杂
- 用户可以在需要时检查和恢复 memory

Memory 不应让人感觉像一个倾倒区。它应该让人感觉像连续性。

这正是该设计试图保护的东西。
