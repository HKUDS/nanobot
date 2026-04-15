---
name: lark-vc
version: 1.0.0
description: "飞书视频会议：查询会议记录、获取会议纪要产物（总结、待办、章节、逐字稿）。1. 查询已经结束的会议数量或详情时使用本技能(如昨天 | 上周 | 今天已经开过的会议等场景)，查询未开始的会议日程使用 lark-calendar 技能。2. 支持通过关键词、时间范围、组织者、参与者、会议室等筛选条件搜索会议记录。3. 获取或整理会议纪要时使用本技能。"
metadata:
  requires:
    bins: ["lark-cli"]
  cliHelp: "lark-cli vc --help"
---

# vc (v1)

**CRITICAL — 开始前 MUST 先用 Read 工具读取 [`../lark-shared/SKILL.md`](../lark-shared/SKILL.md)，其中包含认证、权限处理**

## 核心概念

- **视频会议（Meeting）**：飞书视频会议实例，通过 meeting\_id 标识。
- **会议记录（Meeting Record）**：视频会议结束后生成的记录，支持通过关键词、时间段、参会人、组织者、会议室等筛选条件搜索会议室。
- **会议纪要（Note）**：视频会议结束后生成的结构化文档，包含纪要文档（包含总结、待办、章节）和逐字稿文档。
- **妙记（Minutes）**：来源于飞书视频会议的录制产物或用户上传的音视频文件，支持视频/音频的转写和会议纪要，通过 minute\_token 标识。
- **纪要文档（MainDoc）**：AI 智能纪要的主文档，包含 AI 生成的总结和待办，对应 `note_doc_token`。
- **用户会议纪要（MeetingNotes）**：用户主动绑定到会议的纪要文档，对应 `meeting_notes`。仅通过 `--calendar-event-ids` 路径返回。
- **逐字稿（VerbatimDoc）**：会议的逐句文字记录，包含说话人和时间戳。

## 核心场景

### 1. 搜索会议记录
1. 仅支持搜索已结束的会议，对于还未开始的未来会议，需要使用 lark-calendar 技能。
2. 仅支持使用关键词、时间段、参会人、组织者、会议室等筛选条件搜索会议记录，对于不支持的筛选条件，需要提示用户。
3. 搜索结果存在多条数据时，务必注意分页数据获取，不要遗漏任何会议记录。

### 2. 整理会议纪要
1. 整理纪要文档时默认给出纪要文档和逐字稿链接即可，无需读取纪要文档或逐字稿内容。
2. 用户明确需要获取纪要文档中的总结、待办、章节产物时，再读取文档获取具体内容。
3. 读取智能纪要（`note_doc_token`）内容时，纪要文档的**第一个 `<whiteboard>`** 标签是封面图（AI 生成的总结可视化），应同时下载展示给用户：
```bash
# 1. 读取纪要内容
lark-cli docs +fetch --doc <note_doc_token>
# 2. 从返回的 markdown 中提取第一个 <whiteboard token="xxx"/> 的 token
# 3. 下载封面图到 artifact 目录（和逐字稿同目录，保持产物归拢）
#    并非所有纪要都有封面画板，没有 <whiteboard> 标签时跳过即可
lark-cli docs +media-download --type whiteboard --token <whiteboard_token> --output ./artifact-<title>/cover
```
> **产物目录规范**：同一会议的所有下载产物（封面图、逐字稿等）统一放到 `artifact-<title>/` 目录下，不要散落在当前工作目录。

> **纪要相关文档 — 根据用户意图选择：**
> - `note_doc_token` → **AI 智能纪要**（AI 总结 + 待办 + 章节）
> - `meeting_notes` → **用户绑定的会议纪要**（用户主动关联到会议的文档，仅 `--calendar-event-ids` 路径返回）
> - `verbatim_doc_token` → **逐字稿**（完整的逐句文字记录，含说话人和时间戳）— 用户说"逐字稿""完整记录""谁说了什么"时用这个
> - 用户说"纪要""总结""纪要内容"时，应同时返回 `note_doc_token` 和 `meeting_notes`（如有）
> - 用户意图不明确时，应展示所有文档链接让用户选择，而不是替用户决定

### 3. 纪要文档与逐字稿链接
1. 纪要文档、逐字稿文档与关联的共享文档默认使用文档 Token 返回。
2. 仅需要获取文档名称和 URL 等基本信息时，使用 `lark-cli drive metas batch_query` 查询
```bash
# 学习命令使用方式
lark-cli schema drive.metas.batch_query

# 批量获取文档基本信息: 一次最多查询 10 个文档
lark-cli drive metas batch_query --data '{"request_docs": [{"doc_type": "docx", "doc_token": "<doc_token>"}], "with_url": true}'
```
3. 需要获取文档内容时，使用 `lark-cli docs +fetch`。
```bash
# 获取文档内容
lark-cli docs +fetch --doc <doc_token>
```

## 资源关系

```
Meeting (视频会议)
├── Note (会议纪要)
│   ├── MainDoc (AI 智能纪要文档, note_doc_token)
│   ├── MeetingNotes (用户绑定的会议纪要文档, meeting_notes)
│   ├── VerbatimDoc (逐字稿, verbatim_doc_token)
│   └── SharedDoc (会中共享文档)
└── Minutes (妙记) ← minute_token 标识，+recording 从 meeting_id 获取
    ├── Transcript (文字记录)
    ├── Summary (总结)
    ├── Todos (待办)
    └── Chapters (章节)
```

> **注意**：`+search` 只能查询已结束的历史会议。查询未来的日程安排请使用 [lark-calendar](../lark-calendar/SKILL.md)。
>
> **优先级**：当用户搜索历史会议时，应优先使用 `vc +search` 而非 `calendar events search`。calendar 的搜索面向日程，vc 的搜索面向已结束的会议记录，支持按参会人、组织者、会议室等维度过滤。
>
> **路由规则**：如果用户在问“开过的会”“今天开了哪些会”“最近参加过什么会”“已结束的会议”“历史会议记录”，优先使用 `vc +search`。只有在查询未来日程、待开的会、agenda 时才优先使用 [lark-calendar](../lark-calendar/SKILL.md)。
> 
> **特殊情况**: 当用户查询“今天有哪些会议”时，通过 `vc +search` 查询今天开过的会议记录，同时使用 lark-calendar 技能查询今天还未开始的会议，统一整理后展示给用户。

## Shortcuts（推荐优先使用）

Shortcut 是对常用操作的高级封装（`lark-cli vc +<verb> [flags]`）。有 Shortcut 的操作优先使用。

| Shortcut | 说明 |
|----------|------|
| [`+search`](references/lark-vc-search.md) | Search meeting records (requires at least one filter) |
| [`+notes`](references/lark-vc-notes.md) | Query meeting notes (via meeting-ids, minute-tokens, or calendar-event-ids) |
| [`+recording`](references/lark-vc-recording.md) | Query minute_token from meeting-ids or calendar-event-ids |

## API Resources

```bash
lark-cli schema vc.<resource>.<method>   # 调用 API 前必须先查看参数结构
lark-cli vc <resource> <method> [flags] # 调用 API
```

> **重要**：使用原生 API 时，必须先运行 `schema` 查看 `--data` / `--params` 参数结构，不要猜测字段格式。

### meeting

  - `get` — 获取会议详情（主题、时间、参会人、note_id）

```bash
# 获取会议基础信息：不包含参会人列表
lark-cli vc meeting get --params '{"meeting_id": "<meeting_id>"}'


# 获取会议基础信息：包含参会人列表
lark-cli vc meeting get --params '{"meeting_id": "<meeting_id>", "with_participants": true}'
```

### minutes（跨域，详见 [lark-minutes](../lark-minutes/SKILL.md)）

  - `get` — 获取妙记基础信息（标题、时长、封面）；查询纪要**内容**请用 `+notes --minute-tokens <minute-token>`

## 权限表

| 方法 | 所需 scope |
|------|-----------|
| `+notes --meeting-ids` | `vc:meeting.meetingevent:read`、`vc:note:read` |
| `+notes --minute-tokens` | `vc:note:read`、`minutes:minutes:readonly`、`minutes:minutes.artifacts:read`、`minutes:minutes.transcript:export` |
| `+notes --calendar-event-ids` | `calendar:calendar:read`、`calendar:calendar.event:read`、`vc:meeting.meetingevent:read`、`vc:note:read` |
| `+recording --meeting-ids` | `vc:record:readonly` |
| `+recording --calendar-event-ids` | `vc:record:readonly`、`calendar:calendar:read`、`calendar:calendar.event:read` |
| `+search` | `vc:meeting.search:read` |
| `meeting.get` | `vc:meeting.meetingevent:read` |
