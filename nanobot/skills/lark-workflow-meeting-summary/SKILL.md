---
name: lark-workflow-meeting-summary
version: 1.0.0
description: "会议纪要整理工作流：汇总指定时间范围内的会议纪要并生成结构化报告。当用户需要整理会议纪要、生成会议周报、回顾一段时间内的会议内容时使用。"
metadata:
  requires:
    bins: ["lark-cli"]
---

# 会议纪要汇总工作流

**CRITICAL — 开始前 MUST 先用 Read 工具读取 [`../lark-shared/SKILL.md`](../lark-shared/SKILL.md)，其中包含认证、权限处理**。然后阅读 [`../lark-vc/SKILL.md`](../lark-vc/SKILL.md)，了解会议纪要相关操作。

## 适用场景

- "帮我整理这周的会议纪要" / "总结最近的会议" / "生成会议周报"
- "看看今天开了哪些会" / "回顾过去一周开了哪些会"

## 前置条件

仅支持 **user 身份**。执行前确保已授权：

```bash
lark-cli auth login --domain vc        # 基础（查询+纪要）
lark-cli auth login --domain vc,drive   # 含读取纪要文档正文、生成文档
```

## 工作流

```
{时间范围} ─► vc +search ──► 会议列表 (meeting_ids)
                   │
                   ▼
               vc +notes ──► 纪要文档 tokens
                   │
                   ▼
               drive metas batch_query 纪要元数据
                   │
                   ▼
               结构化报告
```

### Step 1: 确定时间范围

默认**过去 7 天**。推断规则："今天"→当天，"这周"→本周一~now，"上周"→上周一~上周日，"这个月"→1日~now。

> **注意**：日期转换必须调用系统命令（如 `date`），不要心算。时间范围参数需根据 CLI 实际要求格式化（通常为 `YYYY-MM-DD` 或 ISO 8601）。

### Step 2: 查询会议记录

```bash
# page-size 最大为 30
lark-cli vc +search --start "<YYYY-MM-DD>" --end "<YYYY-MM-DD>" --format json --page-size 30
```

- 时间范围拆分：搜索的时间范围最大为 1 个月。搜索更长时间范围的会议，需要拆分为多次时间范围为一个月查询。
- `--end` 为**包含当天**的日期（即查"今天"时 start 和 end 都填今天）
- `--format json` 输出 JSON 格式，你更佳擅长解析 JSON 数据。
- `--page-size 30` 每页最多 30 条。
- 有 `page_token` 时必须继续翻页，收集所有 `id` 字段（meeting-id）

### Step 3: 获取纪要元数据

1. 查询会议关联的纪要信息
```bash
lark-cli vc +notes --meeting-ids "id1,id2,...,idN"   
```
- 根据上一步搜集到的 `meeting-id` 查询会议纪要。
- 单次最多查询 50 个纪要信息，超过 50 个需分批调用。
- 部分会议返回 `no notes available`，在最终输出中标注"无纪要"
- 记录每个会议的 `note_doc_token`（纪要文档 Token）和 `verbatim_doc_token`（逐字稿文档 Token）


2. 获取纪要文档和逐字稿文档链接
```bash
# 学习命令使用方式
lark-cli schema drive.metas.batch_query

# 批量获取纪要文档与逐字稿链接: 一次最多查询 10 个文档
lark-cli drive metas batch_query --data '{"request_docs": [{"doc_type": "docx", "doc_token": "<doc_token>"}], "with_url": true}'
```

### Step 4: 整理纪要报告

根据时间跨度选择输出格式：

- **单日汇总**（"今天"/"昨天"）：用"今日会议概览"标题，逐会议列出会议时间、主题、纪要链接、逐字稿链接。
- **多日/周报**（"这周"/"过去 7 天"等）：用"会议纪要周报"标题，含概览统计、逐会议详情。

### Step 5: 生成文档（可选，用户要求时）

阅读 [`../lark-doc/SKILL.md`](../lark-doc/SKILL.md) 学习云文档技能。

```bash
lark-cli docs +create --title "会议纪要汇总 (<start> - <end>)" --markdown "<内容>"
# 或追加到已有文档
lark-cli docs +update --doc "<url_or_token>" --mode append --markdown "<内容>"
```

## 参考

- [lark-shared](../lark-shared/SKILL.md) — 认证、权限（必读）
- [lark-vc](../lark-vc/SKILL.md) — `+search`、`+notes` 详细用法
- [lark-doc](../lark-doc/SKILL.md) — `+fetch`、`+create`、`+update` 详细用法