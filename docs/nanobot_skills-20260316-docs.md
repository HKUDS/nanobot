# Project Documentation

- **Generated at:** 2026-03-16 23:11:21
- **Root Dir:** `nanobot/skills`
- **File Count:** 14
- **Total Size:** 61.68 KB
claude 解读：
*Thinking...*

> The user has shared a large documentation file for what appears to be the "nanobot" project's skills system. They said "详细解释" which means "explain in detail" in Chinese. So I should provide a detailed explanation of this project documentation in Chinese.

# Nanobot Skills 系统详细解释

## 项目概述

Nanobot 是一个 AI 代理（Agent）框架，而 **Skills**（技能）是其核心扩展机制。每个技能本质上是一个模块化的"知识包"，让通用的 AI 代理瞬间具备特定领域的专业能力。可以把它类比为给一个聪明但初来乍到的新员工发一本"岗位操作手册"——手册里包含流程、工具用法、参考资料和现成的脚本。

整个技能系统源自 **OpenClaw** 项目的设计规范，保持了格式兼容性，并通过 **ClawHub** 这个公共注册中心实现技能的搜索、安装和分享。

---

## 技能的结构与原理

### 基本文件结构

每个技能是一个目录，核心是 `SKILL.md` 文件，采用 YAML frontmatter + Markdown 正文的格式。可选地包含三类子目录：

`scripts/` 存放可执行脚本（Python、Bash 等），用于需要确定性结果或反复执行的任务。比如 PDF 旋转脚本——与其让 AI 每次重新写一遍代码，不如直接调用一个经过测试的脚本。

`references/` 存放参考文档，供 AI 在需要时读入上下文。比如数据库 schema、API 文档、公司政策等。这些内容不会默认加载，只在 AI 判断需要时才读取，从而节省宝贵的上下文窗口空间。

`assets/` 存放输出物料，如模板文件、logo、字体等。这些文件不会被读入上下文，而是直接被复制或嵌入到 AI 生成的输出中。

### 三级渐进式加载（Progressive Disclosure）

这是整个系统最精妙的设计之一。AI 的上下文窗口是有限的"公共资源"，需要和系统提示词、对话历史、用户请求共享。因此技能采用三级加载：

第一级是**元数据**（name + description），大约 100 词，始终驻留在上下文中。AI 通过这些信息判断"什么时候该激活这个技能"。这就是为什么文档反复强调 description 字段必须清晰、全面——它是技能的"触发器"。

第二级是 **SKILL.md 正文**，建议控制在 5000 词以内。只有当技能被触发后才加载。

第三级是**捆绑资源**（scripts/references/assets），由 AI 按需加载，理论上没有大小限制，因为脚本可以直接执行而无需读入上下文。

---

## 七个内置技能详解

### 1. GitHub 技能（github）

封装了 `gh` CLI 的常用操作，让 AI 能直接与 GitHub 交互。覆盖了 PR 检查、CI 状态查看、失败日志获取、API 高级查询等场景。关键设计是始终提醒使用 `--repo owner/repo` 参数（因为 AI 可能不在 git 目录中运行），以及善用 `--json` 和 `--jq` 实现结构化输出过滤。

### 2. Weather 技能（weather）

提供两个免费天气数据源：wttr.in 作为主要来源（支持纯文本和 PNG 输出），Open-Meteo 作为备选（返回 JSON，适合程序化处理）。无需 API 密钥是其核心卖点。设计上提供了从极简单行输出到完整预报的多种格式选项。

### 3. Summarize 技能（summarize）

调用 `summarize` CLI 工具，对 URL、本地文件、YouTube 视频进行摘要或文本提取。支持多种 AI 提供商（OpenAI、Anthropic、Google 等），通过环境变量配置 API 密钥。特别值得注意的是 YouTube 处理策略：如果用户要求的转录内容过长，先返回简要摘要，再询问用户想展开哪个部分。

### 4. Tmux 技能（tmux）

这是最复杂的内置技能。它让 AI 能够远程控制 tmux 终端会话——发送按键、抓取输出、等待特定文本出现。核心使用场景是需要交互式 TTY 的情况（比如 Python REPL）。

设计上有几个亮点：使用隔离的 Unix socket（而非默认 tmux socket）避免干扰用户自己的 tmux 环境；配套了 `find-sessions.sh`（查找会话）和 `wait-for-text.sh`（轮询等待特定输出）两个辅助脚本；还特别说明了如何用 tmux 并行编排多个编码代理（如同时运行多个 Codex 实例修复不同 bug）。

### 5. Memory 技能（memory）

实现了双层记忆系统。`MEMORY.md` 是长期记忆，存储用户偏好、项目上下文、人物关系等，始终加载到上下文中。`HISTORY.md` 是追加式事件日志，不自动加载，通过 grep 搜索。系统会自动将旧对话摘要写入 HISTORY.md，并将重要事实提取到 MEMORY.md，实现自动整理。

### 6. Cron 技能（cron）

提供定时任务和提醒功能，支持三种模式：直接提醒（消息发给用户）、动态任务（AI 执行后发送结果）、一次性任务（执行后自动删除）。支持 cron 表达式和 IANA 时区。

### 7. ClawHub 技能（clawhub）

技能的"应用商店"客户端。通过 npx 运行，支持自然语言向量搜索、安装、更新和列出已安装技能。关键细节是必须指定 `--workdir ~/.nanobot/workspace`，否则技能会安装到当前目录而非工作空间。

---

## Skill Creator：技能创建系统

这是整个文档中篇幅最大、也最核心的部分——它是一个"元技能"，指导 AI 如何创建新技能。

### 设计哲学

**精简至上**：上下文窗口是公共资源，每一段文字都必须证明自己的"token 成本"是值得的。默认假设 AI 已经很聪明，只添加它真正不知道的信息。

**自由度匹配**：根据任务的脆弱性选择约束程度。危险的窄桥（如修改生产数据库）需要严格的脚本和步骤；开阔的原野（如写一篇博客）只需高层指导。

### 六步创建流程

第一步**理解需求**：通过与用户对话，收集具体使用场景和触发短语。文档特别强调不要一次问太多问题。

第二步**规划资源**：分析每个场景，识别哪些东西会被反复使用——需要写成脚本的（如 PDF 旋转）、需要作为参考的（如数据库 schema）、需要作为素材的（如前端模板）。

第三步**初始化**：运行 `init_skill.py` 脚本，自动生成符合规范的技能目录骨架。脚本支持指定资源类型和是否生成示例文件。

第四步**编辑实现**：填充 SKILL.md 和各资源文件。文档提供了四种结构模式（工作流型、任务型、参考型、能力型）供选择。强调 frontmatter 的 description 是触发机制的核心，"何时使用"信息必须放在 description 里而非正文中（因为正文在触发后才加载）。

第五步**打包**：运行 `package_skill.py`，自动验证并打包为 `.skill` 文件（实质是 zip）。验证检查包括 frontmatter 格式、命名规范、描述质量、目录结构等。安全上会拒绝包含符号链接的技能。

第六步**迭代**：在实际使用中发现不足，持续改进。

### 三个辅助脚本

`init_skill.py` 处理技能名称的规范化（转为小写连字符格式），创建目录结构，生成带 TODO 占位符的 SKILL.md 模板。

`quick_validate.py` 实现了一个完整的验证器，检查 frontmatter 格式、字段合法性、名称与目录名一致性、描述中不能有 TODO 占位符或尖括号、目录结构中只允许特定子目录等。巧妙地处理了 PyYAML 不可用时的降级解析。

`package_skill.py` 先调用验证器，通过后将技能目录打包为 zip 格式的 `.skill` 文件，排除 `.git`、`__pycache__`、`node_modules` 等目录，拒绝符号链接，防止文件路径逃逸。

---

## 整体架构评价

这个系统的设计体现了几个成熟的工程思想：**关注点分离**（触发逻辑与执行逻辑分开）、**延迟加载**（三级渐进式披露）、**约定优于配置**（统一的目录结构和命名规范）、以及**安全纵深**（符号链接拒绝、路径逃逸检测、域名白名单）。它本质上是在解决一个核心问题：如何在有限的上下文窗口中，让 AI 代理高效地获取和运用专业知识。

<a name="toc"></a>
## 📂 扫描目录
- [README.md](#📄-readmemd) (25 lines, 0.84 KB)
- [clawhub/SKILL.md](#📄-clawhubskillmd) (53 lines, 1.35 KB)
- [cron/SKILL.md](#📄-cronskillmd) (57 lines, 1.47 KB)
- [github/SKILL.md](#📄-githubskillmd) (48 lines, 1.34 KB)
- [memory/SKILL.md](#📄-memoryskillmd) (37 lines, 1.43 KB)
- [skill-creator/SKILL.md](#📄-skill-creatorskillmd) (374 lines, 18.43 KB)
- [skill-creator/scripts/init_skill.py](#📄-skill-creatorscriptsinit_skillpy) (378 lines, 13.43 KB)
- [skill-creator/scripts/package_skill.py](#📄-skill-creatorscriptspackage_skillpy) (154 lines, 4.61 KB)
- [skill-creator/scripts/quick_validate.py](#📄-skill-creatorscriptsquick_validatepy) (213 lines, 6.71 KB)
- [summarize/SKILL.md](#📄-summarizeskillmd) (67 lines, 1.99 KB)
- [tmux/SKILL.md](#📄-tmuxskillmd) (121 lines, 3.97 KB)
- [tmux/scripts/find-sessions.sh](#📄-tmuxscriptsfind-sessionssh) (112 lines, 2.87 KB)
- [tmux/scripts/wait-for-text.sh](#📄-tmuxscriptswait-for-textsh) (83 lines, 2.09 KB)
- [weather/SKILL.md](#📄-weatherskillmd) (49 lines, 1.14 KB)

---

## 📄 README.md

````markdown
# nanobot Skills

This directory contains built-in skills that extend nanobot's capabilities.

## Skill Format

Each skill is a directory containing a `SKILL.md` file with:
- YAML frontmatter (name, description, metadata)
- Markdown instructions for the agent

## Attribution

These skills are adapted from [OpenClaw](https://github.com/openclaw/openclaw)'s skill system.
The skill format and metadata structure follow OpenClaw's conventions to maintain compatibility.

## Available Skills

| Skill | Description |
|-------|-------------|
| `github` | Interact with GitHub using the `gh` CLI |
| `weather` | Get weather info using wttr.in and Open-Meteo |
| `summarize` | Summarize URLs, files, and YouTube videos |
| `tmux` | Remote-control tmux sessions |
| `clawhub` | Search and install skills from ClawHub registry |
| `skill-creator` | Create new skills |
````

[⬆ 回到目录](#toc)

## 📄 clawhub/SKILL.md

````markdown
---
name: clawhub
description: Search and install agent skills from ClawHub, the public skill registry.
homepage: https://clawhub.ai
metadata: {"nanobot":{"emoji":"🦞"}}
---

# ClawHub

Public skill registry for AI agents. Search by natural language (vector search).

## When to use

Use this skill when the user asks any of:
- "find a skill for …"
- "search for skills"
- "install a skill"
- "what skills are available?"
- "update my skills"

## Search

```bash
npx --yes clawhub@latest search "web scraping" --limit 5
```

## Install

```bash
npx --yes clawhub@latest install <slug> --workdir ~/.nanobot/workspace
```

Replace `<slug>` with the skill name from search results. This places the skill into `~/.nanobot/workspace/skills/`, where nanobot loads workspace skills from. Always include `--workdir`.

## Update

```bash
npx --yes clawhub@latest update --all --workdir ~/.nanobot/workspace
```

## List installed

```bash
npx --yes clawhub@latest list --workdir ~/.nanobot/workspace
```

## Notes

- Requires Node.js (`npx` comes with it).
- No API key needed for search and install.
- Login (`npx --yes clawhub@latest login`) is only required for publishing.
- `--workdir ~/.nanobot/workspace` is critical — without it, skills install to the current directory instead of the nanobot workspace.
- After install, remind the user to start a new session to load the skill.

````

[⬆ 回到目录](#toc)

## 📄 cron/SKILL.md

````markdown
---
name: cron
description: Schedule reminders and recurring tasks.
---

# Cron

Use the `cron` tool to schedule reminders or recurring tasks.

## Three Modes

1. **Reminder** - message is sent directly to user
2. **Task** - message is a task description, agent executes and sends result
3. **One-time** - runs once at a specific time, then auto-deletes

## Examples

Fixed reminder:
```
cron(action="add", message="Time to take a break!", every_seconds=1200)
```

Dynamic task (agent executes each time):
```
cron(action="add", message="Check HKUDS/nanobot GitHub stars and report", every_seconds=600)
```

One-time scheduled task (compute ISO datetime from current time):
```
cron(action="add", message="Remind me about the meeting", at="<ISO datetime>")
```

Timezone-aware cron:
```
cron(action="add", message="Morning standup", cron_expr="0 9 * * 1-5", tz="America/Vancouver")
```

List/remove:
```
cron(action="list")
cron(action="remove", job_id="abc123")
```

## Time Expressions

| User says | Parameters |
|-----------|------------|
| every 20 minutes | every_seconds: 1200 |
| every hour | every_seconds: 3600 |
| every day at 8am | cron_expr: "0 8 * * *" |
| weekdays at 5pm | cron_expr: "0 17 * * 1-5" |
| 9am Vancouver time daily | cron_expr: "0 9 * * *", tz: "America/Vancouver" |
| at a specific time | at: ISO datetime string (compute from current time) |

## Timezone

Use `tz` with `cron_expr` to schedule in a specific IANA timezone. Without `tz`, the server's local timezone is used.

````

[⬆ 回到目录](#toc)

## 📄 github/SKILL.md

````markdown
---
name: github
description: "Interact with GitHub using the `gh` CLI. Use `gh issue`, `gh pr`, `gh run`, and `gh api` for issues, PRs, CI runs, and advanced queries."
metadata: {"nanobot":{"emoji":"🐙","requires":{"bins":["gh"]},"install":[{"id":"brew","kind":"brew","formula":"gh","bins":["gh"],"label":"Install GitHub CLI (brew)"},{"id":"apt","kind":"apt","package":"gh","bins":["gh"],"label":"Install GitHub CLI (apt)"}]}}
---

# GitHub Skill

Use the `gh` CLI to interact with GitHub. Always specify `--repo owner/repo` when not in a git directory, or use URLs directly.

## Pull Requests

Check CI status on a PR:
```bash
gh pr checks 55 --repo owner/repo
```

List recent workflow runs:
```bash
gh run list --repo owner/repo --limit 10
```

View a run and see which steps failed:
```bash
gh run view <run-id> --repo owner/repo
```

View logs for failed steps only:
```bash
gh run view <run-id> --repo owner/repo --log-failed
```

## API for Advanced Queries

The `gh api` command is useful for accessing data not available through other subcommands.

Get PR with specific fields:
```bash
gh api repos/owner/repo/pulls/55 --jq '.title, .state, .user.login'
```

## JSON Output

Most commands support `--json` for structured output.  You can use `--jq` to filter:

```bash
gh issue list --repo owner/repo --json number,title --jq '.[] | "\(.number): \(.title)"'
```

````

[⬆ 回到目录](#toc)

## 📄 memory/SKILL.md

````markdown
---
name: memory
description: Two-layer memory system with grep-based recall.
always: true
---

# Memory

## Structure

- `memory/MEMORY.md` — Long-term facts (preferences, project context, relationships). Always loaded into your context.
- `memory/HISTORY.md` — Append-only event log. NOT loaded into context. Search it with grep-style tools or in-memory filters. Each entry starts with [YYYY-MM-DD HH:MM].

## Search Past Events

Choose the search method based on file size:

- Small `memory/HISTORY.md`: use `read_file`, then search in-memory
- Large or long-lived `memory/HISTORY.md`: use the `exec` tool for targeted search

Examples:
- **Linux/macOS:** `grep -i "keyword" memory/HISTORY.md`
- **Windows:** `findstr /i "keyword" memory\HISTORY.md`
- **Cross-platform Python:** `python -c "from pathlib import Path; text = Path('memory/HISTORY.md').read_text(encoding='utf-8'); print('\n'.join([l for l in text.splitlines() if 'keyword' in l.lower()][-20:]))"`

Prefer targeted command-line search for large history files.

## When to Update MEMORY.md

Write important facts immediately using `edit_file` or `write_file`:
- User preferences ("I prefer dark mode")
- Project context ("The API uses OAuth2")
- Relationships ("Alice is the project lead")

## Auto-consolidation

Old conversations are automatically summarized and appended to HISTORY.md when the session grows large. Long-term facts are extracted to MEMORY.md. You don't need to manage this.

````

[⬆ 回到目录](#toc)

## 📄 skill-creator/SKILL.md

````markdown
---
name: skill-creator
description: Create or update AgentSkills. Use when designing, structuring, or packaging skills with scripts, references, and assets.
---

# Skill Creator

This skill provides guidance for creating effective skills.

## About Skills

Skills are modular, self-contained packages that extend the agent's capabilities by providing
specialized knowledge, workflows, and tools. Think of them as "onboarding guides" for specific
domains or tasks—they transform the agent from a general-purpose agent into a specialized agent
equipped with procedural knowledge that no model can fully possess.

### What Skills Provide

1. Specialized workflows - Multi-step procedures for specific domains
2. Tool integrations - Instructions for working with specific file formats or APIs
3. Domain expertise - Company-specific knowledge, schemas, business logic
4. Bundled resources - Scripts, references, and assets for complex and repetitive tasks

## Core Principles

### Concise is Key

The context window is a public good. Skills share the context window with everything else the agent needs: system prompt, conversation history, other Skills' metadata, and the actual user request.

**Default assumption: the agent is already very smart.** Only add context the agent doesn't already have. Challenge each piece of information: "Does the agent really need this explanation?" and "Does this paragraph justify its token cost?"

Prefer concise examples over verbose explanations.

### Set Appropriate Degrees of Freedom

Match the level of specificity to the task's fragility and variability:

**High freedom (text-based instructions)**: Use when multiple approaches are valid, decisions depend on context, or heuristics guide the approach.

**Medium freedom (pseudocode or scripts with parameters)**: Use when a preferred pattern exists, some variation is acceptable, or configuration affects behavior.

**Low freedom (specific scripts, few parameters)**: Use when operations are fragile and error-prone, consistency is critical, or a specific sequence must be followed.

Think of the agent as exploring a path: a narrow bridge with cliffs needs specific guardrails (low freedom), while an open field allows many routes (high freedom).

### Anatomy of a Skill

Every skill consists of a required SKILL.md file and optional bundled resources:

```
skill-name/
├── SKILL.md (required)
│   ├── YAML frontmatter metadata (required)
│   │   ├── name: (required)
│   │   └── description: (required)
│   └── Markdown instructions (required)
└── Bundled Resources (optional)
    ├── scripts/          - Executable code (Python/Bash/etc.)
    ├── references/       - Documentation intended to be loaded into context as needed
    └── assets/           - Files used in output (templates, icons, fonts, etc.)
```

#### SKILL.md (required)

Every SKILL.md consists of:

- **Frontmatter** (YAML): Contains `name` and `description` fields. These are the only fields that the agent reads to determine when the skill gets used, thus it is very important to be clear and comprehensive in describing what the skill is, and when it should be used.
- **Body** (Markdown): Instructions and guidance for using the skill. Only loaded AFTER the skill triggers (if at all).

#### Bundled Resources (optional)

##### Scripts (`scripts/`)

Executable code (Python/Bash/etc.) for tasks that require deterministic reliability or are repeatedly rewritten.

- **When to include**: When the same code is being rewritten repeatedly or deterministic reliability is needed
- **Example**: `scripts/rotate_pdf.py` for PDF rotation tasks
- **Benefits**: Token efficient, deterministic, may be executed without loading into context
- **Note**: Scripts may still need to be read by the agent for patching or environment-specific adjustments

##### References (`references/`)

Documentation and reference material intended to be loaded as needed into context to inform the agent's process and thinking.

- **When to include**: For documentation that the agent should reference while working
- **Examples**: `references/finance.md` for financial schemas, `references/mnda.md` for company NDA template, `references/policies.md` for company policies, `references/api_docs.md` for API specifications
- **Use cases**: Database schemas, API documentation, domain knowledge, company policies, detailed workflow guides
- **Benefits**: Keeps SKILL.md lean, loaded only when the agent determines it's needed
- **Best practice**: If files are large (>10k words), include grep search patterns in SKILL.md
- **Avoid duplication**: Information should live in either SKILL.md or references files, not both. Prefer references files for detailed information unless it's truly core to the skill—this keeps SKILL.md lean while making information discoverable without hogging the context window. Keep only essential procedural instructions and workflow guidance in SKILL.md; move detailed reference material, schemas, and examples to references files.

##### Assets (`assets/`)

Files not intended to be loaded into context, but rather used within the output the agent produces.

- **When to include**: When the skill needs files that will be used in the final output
- **Examples**: `assets/logo.png` for brand assets, `assets/slides.pptx` for PowerPoint templates, `assets/frontend-template/` for HTML/React boilerplate, `assets/font.ttf` for typography
- **Use cases**: Templates, images, icons, boilerplate code, fonts, sample documents that get copied or modified
- **Benefits**: Separates output resources from documentation, enables the agent to use files without loading them into context

#### What to Not Include in a Skill

A skill should only contain essential files that directly support its functionality. Do NOT create extraneous documentation or auxiliary files, including:

- README.md
- INSTALLATION_GUIDE.md
- QUICK_REFERENCE.md
- CHANGELOG.md
- etc.

The skill should only contain the information needed for an AI agent to do the job at hand. It should not contain auxiliary context about the process that went into creating it, setup and testing procedures, user-facing documentation, etc. Creating additional documentation files just adds clutter and confusion.

### Progressive Disclosure Design Principle

Skills use a three-level loading system to manage context efficiently:

1. **Metadata (name + description)** - Always in context (~100 words)
2. **SKILL.md body** - When skill triggers (<5k words)
3. **Bundled resources** - As needed by the agent (Unlimited because scripts can be executed without reading into context window)

#### Progressive Disclosure Patterns

Keep SKILL.md body to the essentials and under 500 lines to minimize context bloat. Split content into separate files when approaching this limit. When splitting out content into other files, it is very important to reference them from SKILL.md and describe clearly when to read them, to ensure the reader of the skill knows they exist and when to use them.

**Key principle:** When a skill supports multiple variations, frameworks, or options, keep only the core workflow and selection guidance in SKILL.md. Move variant-specific details (patterns, examples, configuration) into separate reference files.

**Pattern 1: High-level guide with references**

```markdown
# PDF Processing

## Quick start

Extract text with pdfplumber:
[code example]

## Advanced features

- **Form filling**: See [FORMS.md](FORMS.md) for complete guide
- **API reference**: See [REFERENCE.md](REFERENCE.md) for all methods
- **Examples**: See [EXAMPLES.md](EXAMPLES.md) for common patterns
```

the agent loads FORMS.md, REFERENCE.md, or EXAMPLES.md only when needed.

**Pattern 2: Domain-specific organization**

For Skills with multiple domains, organize content by domain to avoid loading irrelevant context:

```
bigquery-skill/
├── SKILL.md (overview and navigation)
└── reference/
    ├── finance.md (revenue, billing metrics)
    ├── sales.md (opportunities, pipeline)
    ├── product.md (API usage, features)
    └── marketing.md (campaigns, attribution)
```

When a user asks about sales metrics, the agent only reads sales.md.

Similarly, for skills supporting multiple frameworks or variants, organize by variant:

```
cloud-deploy/
├── SKILL.md (workflow + provider selection)
└── references/
    ├── aws.md (AWS deployment patterns)
    ├── gcp.md (GCP deployment patterns)
    └── azure.md (Azure deployment patterns)
```

When the user chooses AWS, the agent only reads aws.md.

**Pattern 3: Conditional details**

Show basic content, link to advanced content:

```markdown
# DOCX Processing

## Creating documents

Use docx-js for new documents. See [DOCX-JS.md](DOCX-JS.md).

## Editing documents

For simple edits, modify the XML directly.

**For tracked changes**: See [REDLINING.md](REDLINING.md)
**For OOXML details**: See [OOXML.md](OOXML.md)
```

the agent reads REDLINING.md or OOXML.md only when the user needs those features.

**Important guidelines:**

- **Avoid deeply nested references** - Keep references one level deep from SKILL.md. All reference files should link directly from SKILL.md.
- **Structure longer reference files** - For files longer than 100 lines, include a table of contents at the top so the agent can see the full scope when previewing.

## Skill Creation Process

Skill creation involves these steps:

1. Understand the skill with concrete examples
2. Plan reusable skill contents (scripts, references, assets)
3. Initialize the skill (run init_skill.py)
4. Edit the skill (implement resources and write SKILL.md)
5. Package the skill (run package_skill.py)
6. Iterate based on real usage

Follow these steps in order, skipping only if there is a clear reason why they are not applicable.

### Skill Naming

- Use lowercase letters, digits, and hyphens only; normalize user-provided titles to hyphen-case (e.g., "Plan Mode" -> `plan-mode`).
- When generating names, generate a name under 64 characters (letters, digits, hyphens).
- Prefer short, verb-led phrases that describe the action.
- Namespace by tool when it improves clarity or triggering (e.g., `gh-address-comments`, `linear-address-issue`).
- Name the skill folder exactly after the skill name.

### Step 1: Understanding the Skill with Concrete Examples

Skip this step only when the skill's usage patterns are already clearly understood. It remains valuable even when working with an existing skill.

To create an effective skill, clearly understand concrete examples of how the skill will be used. This understanding can come from either direct user examples or generated examples that are validated with user feedback.

For example, when building an image-editor skill, relevant questions include:

- "What functionality should the image-editor skill support? Editing, rotating, anything else?"
- "Can you give some examples of how this skill would be used?"
- "I can imagine users asking for things like 'Remove the red-eye from this image' or 'Rotate this image'. Are there other ways you imagine this skill being used?"
- "What would a user say that should trigger this skill?"

To avoid overwhelming users, avoid asking too many questions in a single message. Start with the most important questions and follow up as needed for better effectiveness.

Conclude this step when there is a clear sense of the functionality the skill should support.

### Step 2: Planning the Reusable Skill Contents

To turn concrete examples into an effective skill, analyze each example by:

1. Considering how to execute on the example from scratch
2. Identifying what scripts, references, and assets would be helpful when executing these workflows repeatedly

Example: When building a `pdf-editor` skill to handle queries like "Help me rotate this PDF," the analysis shows:

1. Rotating a PDF requires re-writing the same code each time
2. A `scripts/rotate_pdf.py` script would be helpful to store in the skill

Example: When designing a `frontend-webapp-builder` skill for queries like "Build me a todo app" or "Build me a dashboard to track my steps," the analysis shows:

1. Writing a frontend webapp requires the same boilerplate HTML/React each time
2. An `assets/hello-world/` template containing the boilerplate HTML/React project files would be helpful to store in the skill

Example: When building a `big-query` skill to handle queries like "How many users have logged in today?" the analysis shows:

1. Querying BigQuery requires re-discovering the table schemas and relationships each time
2. A `references/schema.md` file documenting the table schemas would be helpful to store in the skill

To establish the skill's contents, analyze each concrete example to create a list of the reusable resources to include: scripts, references, and assets.

### Step 3: Initializing the Skill

At this point, it is time to actually create the skill.

Skip this step only if the skill being developed already exists, and iteration or packaging is needed. In this case, continue to the next step.

When creating a new skill from scratch, always run the `init_skill.py` script. The script conveniently generates a new template skill directory that automatically includes everything a skill requires, making the skill creation process much more efficient and reliable.

For `nanobot`, custom skills should live under the active workspace `skills/` directory so they can be discovered automatically at runtime (for example, `<workspace>/skills/my-skill/SKILL.md`).

Usage:

```bash
scripts/init_skill.py <skill-name> --path <output-directory> [--resources scripts,references,assets] [--examples]
```

Examples:

```bash
scripts/init_skill.py my-skill --path ./workspace/skills
scripts/init_skill.py my-skill --path ./workspace/skills --resources scripts,references
scripts/init_skill.py my-skill --path ./workspace/skills --resources scripts --examples
```

The script:

- Creates the skill directory at the specified path
- Generates a SKILL.md template with proper frontmatter and TODO placeholders
- Optionally creates resource directories based on `--resources`
- Optionally adds example files when `--examples` is set

After initialization, customize the SKILL.md and add resources as needed. If you used `--examples`, replace or delete placeholder files.

### Step 4: Edit the Skill

When editing the (newly-generated or existing) skill, remember that the skill is being created for another instance of the agent to use. Include information that would be beneficial and non-obvious to the agent. Consider what procedural knowledge, domain-specific details, or reusable assets would help another the agent instance execute these tasks more effectively.

#### Learn Proven Design Patterns

Consult these helpful guides based on your skill's needs:

- **Multi-step processes**: See references/workflows.md for sequential workflows and conditional logic
- **Specific output formats or quality standards**: See references/output-patterns.md for template and example patterns

These files contain established best practices for effective skill design.

#### Start with Reusable Skill Contents

To begin implementation, start with the reusable resources identified above: `scripts/`, `references/`, and `assets/` files. Note that this step may require user input. For example, when implementing a `brand-guidelines` skill, the user may need to provide brand assets or templates to store in `assets/`, or documentation to store in `references/`.

Added scripts must be tested by actually running them to ensure there are no bugs and that the output matches what is expected. If there are many similar scripts, only a representative sample needs to be tested to ensure confidence that they all work while balancing time to completion.

If you used `--examples`, delete any placeholder files that are not needed for the skill. Only create resource directories that are actually required.

#### Update SKILL.md

**Writing Guidelines:** Always use imperative/infinitive form.

##### Frontmatter

Write the YAML frontmatter with `name` and `description`:

- `name`: The skill name
- `description`: This is the primary triggering mechanism for your skill, and helps the agent understand when to use the skill.
  - Include both what the Skill does and specific triggers/contexts for when to use it.
  - Include all "when to use" information here - Not in the body. The body is only loaded after triggering, so "When to Use This Skill" sections in the body are not helpful to the agent.
  - Example description for a `docx` skill: "Comprehensive document creation, editing, and analysis with support for tracked changes, comments, formatting preservation, and text extraction. Use when the agent needs to work with professional documents (.docx files) for: (1) Creating new documents, (2) Modifying or editing content, (3) Working with tracked changes, (4) Adding comments, or any other document tasks"

Keep frontmatter minimal. In `nanobot`, `metadata` and `always` are also supported when needed, but avoid adding extra fields unless they are actually required.

##### Body

Write instructions for using the skill and its bundled resources.

### Step 5: Packaging a Skill

Once development of the skill is complete, it must be packaged into a distributable .skill file that gets shared with the user. The packaging process automatically validates the skill first to ensure it meets all requirements:

```bash
scripts/package_skill.py <path/to/skill-folder>
```

Optional output directory specification:

```bash
scripts/package_skill.py <path/to/skill-folder> ./dist
```

The packaging script will:

1. **Validate** the skill automatically, checking:
   - YAML frontmatter format and required fields
   - Skill naming conventions and directory structure
   - Description completeness and quality
   - File organization and resource references

2. **Package** the skill if validation passes, creating a .skill file named after the skill (e.g., `my-skill.skill`) that includes all files and maintains the proper directory structure for distribution. The .skill file is a zip file with a .skill extension.

   Security restriction: symlinks are rejected and packaging fails when any symlink is present.

If validation fails, the script will report the errors and exit without creating a package. Fix any validation errors and run the packaging command again.

### Step 6: Iterate

After testing the skill, users may request improvements. Often this happens right after using the skill, with fresh context of how the skill performed.

**Iteration workflow:**

1. Use the skill on real tasks
2. Notice struggles or inefficiencies
3. Identify how SKILL.md or bundled resources should be updated
4. Implement changes and test again

````

[⬆ 回到目录](#toc)

## 📄 skill-creator/scripts/init_skill.py

````python
#!/usr/bin/env python3
"""
Skill Initializer - Creates a new skill from template

Usage:
    init_skill.py <skill-name> --path <path> [--resources scripts,references,assets] [--examples]

Examples:
    init_skill.py my-new-skill --path skills/public
    init_skill.py my-new-skill --path skills/public --resources scripts,references
    init_skill.py my-api-helper --path skills/private --resources scripts --examples
    init_skill.py custom-skill --path /custom/location
"""

import argparse
import re
import sys
from pathlib import Path

MAX_SKILL_NAME_LENGTH = 64
ALLOWED_RESOURCES = {"scripts", "references", "assets"}

SKILL_TEMPLATE = """---
name: {skill_name}
description: [TODO: Complete and informative explanation of what the skill does and when to use it. Include WHEN to use this skill - specific scenarios, file types, or tasks that trigger it.]
---

# {skill_title}

## Overview

[TODO: 1-2 sentences explaining what this skill enables]

## Structuring This Skill

[TODO: Choose the structure that best fits this skill's purpose. Common patterns:

**1. Workflow-Based** (best for sequential processes)
- Works well when there are clear step-by-step procedures
- Example: DOCX skill with "Workflow Decision Tree" -> "Reading" -> "Creating" -> "Editing"
- Structure: ## Overview -> ## Workflow Decision Tree -> ## Step 1 -> ## Step 2...

**2. Task-Based** (best for tool collections)
- Works well when the skill offers different operations/capabilities
- Example: PDF skill with "Quick Start" -> "Merge PDFs" -> "Split PDFs" -> "Extract Text"
- Structure: ## Overview -> ## Quick Start -> ## Task Category 1 -> ## Task Category 2...

**3. Reference/Guidelines** (best for standards or specifications)
- Works well for brand guidelines, coding standards, or requirements
- Example: Brand styling with "Brand Guidelines" -> "Colors" -> "Typography" -> "Features"
- Structure: ## Overview -> ## Guidelines -> ## Specifications -> ## Usage...

**4. Capabilities-Based** (best for integrated systems)
- Works well when the skill provides multiple interrelated features
- Example: Product Management with "Core Capabilities" -> numbered capability list
- Structure: ## Overview -> ## Core Capabilities -> ### 1. Feature -> ### 2. Feature...

Patterns can be mixed and matched as needed. Most skills combine patterns (e.g., start with task-based, add workflow for complex operations).

Delete this entire "Structuring This Skill" section when done - it's just guidance.]

## [TODO: Replace with the first main section based on chosen structure]

[TODO: Add content here. See examples in existing skills:
- Code samples for technical skills
- Decision trees for complex workflows
- Concrete examples with realistic user requests
- References to scripts/templates/references as needed]

## Resources (optional)

Create only the resource directories this skill actually needs. Delete this section if no resources are required.

### scripts/
Executable code (Python/Bash/etc.) that can be run directly to perform specific operations.

**Examples from other skills:**
- PDF skill: `fill_fillable_fields.py`, `extract_form_field_info.py` - utilities for PDF manipulation
- DOCX skill: `document.py`, `utilities.py` - Python modules for document processing

**Appropriate for:** Python scripts, shell scripts, or any executable code that performs automation, data processing, or specific operations.

**Note:** Scripts may be executed without loading into context, but can still be read by Codex for patching or environment adjustments.

### references/
Documentation and reference material intended to be loaded into context to inform Codex's process and thinking.

**Examples from other skills:**
- Product management: `communication.md`, `context_building.md` - detailed workflow guides
- BigQuery: API reference documentation and query examples
- Finance: Schema documentation, company policies

**Appropriate for:** In-depth documentation, API references, database schemas, comprehensive guides, or any detailed information that Codex should reference while working.

### assets/
Files not intended to be loaded into context, but rather used within the output Codex produces.

**Examples from other skills:**
- Brand styling: PowerPoint template files (.pptx), logo files
- Frontend builder: HTML/React boilerplate project directories
- Typography: Font files (.ttf, .woff2)

**Appropriate for:** Templates, boilerplate code, document templates, images, icons, fonts, or any files meant to be copied or used in the final output.

---

**Not every skill requires all three types of resources.**
"""

EXAMPLE_SCRIPT = '''#!/usr/bin/env python3
"""
Example helper script for {skill_name}

This is a placeholder script that can be executed directly.
Replace with actual implementation or delete if not needed.

Example real scripts from other skills:
- pdf/scripts/fill_fillable_fields.py - Fills PDF form fields
- pdf/scripts/convert_pdf_to_images.py - Converts PDF pages to images
"""

def main():
    print("This is an example script for {skill_name}")
    # TODO: Add actual script logic here
    # This could be data processing, file conversion, API calls, etc.

if __name__ == "__main__":
    main()
'''

EXAMPLE_REFERENCE = """# Reference Documentation for {skill_title}

This is a placeholder for detailed reference documentation.
Replace with actual reference content or delete if not needed.

Example real reference docs from other skills:
- product-management/references/communication.md - Comprehensive guide for status updates
- product-management/references/context_building.md - Deep-dive on gathering context
- bigquery/references/ - API references and query examples

## When Reference Docs Are Useful

Reference docs are ideal for:
- Comprehensive API documentation
- Detailed workflow guides
- Complex multi-step processes
- Information too lengthy for main SKILL.md
- Content that's only needed for specific use cases

## Structure Suggestions

### API Reference Example
- Overview
- Authentication
- Endpoints with examples
- Error codes
- Rate limits

### Workflow Guide Example
- Prerequisites
- Step-by-step instructions
- Common patterns
- Troubleshooting
- Best practices
"""

EXAMPLE_ASSET = """# Example Asset File

This placeholder represents where asset files would be stored.
Replace with actual asset files (templates, images, fonts, etc.) or delete if not needed.

Asset files are NOT intended to be loaded into context, but rather used within
the output Codex produces.

Example asset files from other skills:
- Brand guidelines: logo.png, slides_template.pptx
- Frontend builder: hello-world/ directory with HTML/React boilerplate
- Typography: custom-font.ttf, font-family.woff2
- Data: sample_data.csv, test_dataset.json

## Common Asset Types

- Templates: .pptx, .docx, boilerplate directories
- Images: .png, .jpg, .svg, .gif
- Fonts: .ttf, .otf, .woff, .woff2
- Boilerplate code: Project directories, starter files
- Icons: .ico, .svg
- Data files: .csv, .json, .xml, .yaml

Note: This is a text placeholder. Actual assets can be any file type.
"""


def normalize_skill_name(skill_name):
    """Normalize a skill name to lowercase hyphen-case."""
    normalized = skill_name.strip().lower()
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized)
    normalized = normalized.strip("-")
    normalized = re.sub(r"-{2,}", "-", normalized)
    return normalized


def title_case_skill_name(skill_name):
    """Convert hyphenated skill name to Title Case for display."""
    return " ".join(word.capitalize() for word in skill_name.split("-"))


def parse_resources(raw_resources):
    if not raw_resources:
        return []
    resources = [item.strip() for item in raw_resources.split(",") if item.strip()]
    invalid = sorted({item for item in resources if item not in ALLOWED_RESOURCES})
    if invalid:
        allowed = ", ".join(sorted(ALLOWED_RESOURCES))
        print(f"[ERROR] Unknown resource type(s): {', '.join(invalid)}")
        print(f"   Allowed: {allowed}")
        sys.exit(1)
    deduped = []
    seen = set()
    for resource in resources:
        if resource not in seen:
            deduped.append(resource)
            seen.add(resource)
    return deduped


def create_resource_dirs(skill_dir, skill_name, skill_title, resources, include_examples):
    for resource in resources:
        resource_dir = skill_dir / resource
        resource_dir.mkdir(exist_ok=True)
        if resource == "scripts":
            if include_examples:
                example_script = resource_dir / "example.py"
                example_script.write_text(EXAMPLE_SCRIPT.format(skill_name=skill_name))
                example_script.chmod(0o755)
                print("[OK] Created scripts/example.py")
            else:
                print("[OK] Created scripts/")
        elif resource == "references":
            if include_examples:
                example_reference = resource_dir / "api_reference.md"
                example_reference.write_text(EXAMPLE_REFERENCE.format(skill_title=skill_title))
                print("[OK] Created references/api_reference.md")
            else:
                print("[OK] Created references/")
        elif resource == "assets":
            if include_examples:
                example_asset = resource_dir / "example_asset.txt"
                example_asset.write_text(EXAMPLE_ASSET)
                print("[OK] Created assets/example_asset.txt")
            else:
                print("[OK] Created assets/")


def init_skill(skill_name, path, resources, include_examples):
    """
    Initialize a new skill directory with template SKILL.md.

    Args:
        skill_name: Name of the skill
        path: Path where the skill directory should be created
        resources: Resource directories to create
        include_examples: Whether to create example files in resource directories

    Returns:
        Path to created skill directory, or None if error
    """
    # Determine skill directory path
    skill_dir = Path(path).resolve() / skill_name

    # Check if directory already exists
    if skill_dir.exists():
        print(f"[ERROR] Skill directory already exists: {skill_dir}")
        return None

    # Create skill directory
    try:
        skill_dir.mkdir(parents=True, exist_ok=False)
        print(f"[OK] Created skill directory: {skill_dir}")
    except Exception as e:
        print(f"[ERROR] Error creating directory: {e}")
        return None

    # Create SKILL.md from template
    skill_title = title_case_skill_name(skill_name)
    skill_content = SKILL_TEMPLATE.format(skill_name=skill_name, skill_title=skill_title)

    skill_md_path = skill_dir / "SKILL.md"
    try:
        skill_md_path.write_text(skill_content)
        print("[OK] Created SKILL.md")
    except Exception as e:
        print(f"[ERROR] Error creating SKILL.md: {e}")
        return None

    # Create resource directories if requested
    if resources:
        try:
            create_resource_dirs(skill_dir, skill_name, skill_title, resources, include_examples)
        except Exception as e:
            print(f"[ERROR] Error creating resource directories: {e}")
            return None

    # Print next steps
    print(f"\n[OK] Skill '{skill_name}' initialized successfully at {skill_dir}")
    print("\nNext steps:")
    print("1. Edit SKILL.md to complete the TODO items and update the description")
    if resources:
        if include_examples:
            print("2. Customize or delete the example files in scripts/, references/, and assets/")
        else:
            print("2. Add resources to scripts/, references/, and assets/ as needed")
    else:
        print("2. Create resource directories only if needed (scripts/, references/, assets/)")
    print("3. Run the validator when ready to check the skill structure")

    return skill_dir


def main():
    parser = argparse.ArgumentParser(
        description="Create a new skill directory with a SKILL.md template.",
    )
    parser.add_argument("skill_name", help="Skill name (normalized to hyphen-case)")
    parser.add_argument("--path", required=True, help="Output directory for the skill")
    parser.add_argument(
        "--resources",
        default="",
        help="Comma-separated list: scripts,references,assets",
    )
    parser.add_argument(
        "--examples",
        action="store_true",
        help="Create example files inside the selected resource directories",
    )
    args = parser.parse_args()

    raw_skill_name = args.skill_name
    skill_name = normalize_skill_name(raw_skill_name)
    if not skill_name:
        print("[ERROR] Skill name must include at least one letter or digit.")
        sys.exit(1)
    if len(skill_name) > MAX_SKILL_NAME_LENGTH:
        print(
            f"[ERROR] Skill name '{skill_name}' is too long ({len(skill_name)} characters). "
            f"Maximum is {MAX_SKILL_NAME_LENGTH} characters."
        )
        sys.exit(1)
    if skill_name != raw_skill_name:
        print(f"Note: Normalized skill name from '{raw_skill_name}' to '{skill_name}'.")

    resources = parse_resources(args.resources)
    if args.examples and not resources:
        print("[ERROR] --examples requires --resources to be set.")
        sys.exit(1)

    path = args.path

    print(f"Initializing skill: {skill_name}")
    print(f"   Location: {path}")
    if resources:
        print(f"   Resources: {', '.join(resources)}")
        if args.examples:
            print("   Examples: enabled")
    else:
        print("   Resources: none (create as needed)")
    print()

    result = init_skill(skill_name, path, resources, args.examples)

    if result:
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()

````

[⬆ 回到目录](#toc)

## 📄 skill-creator/scripts/package_skill.py

````python
#!/usr/bin/env python3
"""
Skill Packager - Creates a distributable .skill file of a skill folder

Usage:
    python package_skill.py <path/to/skill-folder> [output-directory]

Example:
    python package_skill.py skills/public/my-skill
    python package_skill.py skills/public/my-skill ./dist
"""

import sys
import zipfile
from pathlib import Path

from quick_validate import validate_skill


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _cleanup_partial_archive(skill_filename: Path) -> None:
    try:
        if skill_filename.exists():
            skill_filename.unlink()
    except OSError:
        pass


def package_skill(skill_path, output_dir=None):
    """
    Package a skill folder into a .skill file.

    Args:
        skill_path: Path to the skill folder
        output_dir: Optional output directory for the .skill file (defaults to current directory)

    Returns:
        Path to the created .skill file, or None if error
    """
    skill_path = Path(skill_path).resolve()

    # Validate skill folder exists
    if not skill_path.exists():
        print(f"[ERROR] Skill folder not found: {skill_path}")
        return None

    if not skill_path.is_dir():
        print(f"[ERROR] Path is not a directory: {skill_path}")
        return None

    # Validate SKILL.md exists
    skill_md = skill_path / "SKILL.md"
    if not skill_md.exists():
        print(f"[ERROR] SKILL.md not found in {skill_path}")
        return None

    # Run validation before packaging
    print("Validating skill...")
    valid, message = validate_skill(skill_path)
    if not valid:
        print(f"[ERROR] Validation failed: {message}")
        print("   Please fix the validation errors before packaging.")
        return None
    print(f"[OK] {message}\n")

    # Determine output location
    skill_name = skill_path.name
    if output_dir:
        output_path = Path(output_dir).resolve()
        output_path.mkdir(parents=True, exist_ok=True)
    else:
        output_path = Path.cwd()

    skill_filename = output_path / f"{skill_name}.skill"

    EXCLUDED_DIRS = {".git", ".svn", ".hg", "__pycache__", "node_modules"}

    files_to_package = []
    resolved_archive = skill_filename.resolve()

    for file_path in skill_path.rglob("*"):
        # Fail closed on symlinks so the packaged contents are explicit and predictable.
        if file_path.is_symlink():
            print(f"[ERROR] Symlink not allowed in packaged skill: {file_path}")
            _cleanup_partial_archive(skill_filename)
            return None

        rel_parts = file_path.relative_to(skill_path).parts
        if any(part in EXCLUDED_DIRS for part in rel_parts):
            continue

        if file_path.is_file():
            resolved_file = file_path.resolve()
            if not _is_within(resolved_file, skill_path):
                print(f"[ERROR] File escapes skill root: {file_path}")
                _cleanup_partial_archive(skill_filename)
                return None
            # If output lives under skill_path, avoid writing archive into itself.
            if resolved_file == resolved_archive:
                print(f"[WARN] Skipping output archive: {file_path}")
                continue
            files_to_package.append(file_path)

    # Create the .skill file (zip format)
    try:
        with zipfile.ZipFile(skill_filename, "w", zipfile.ZIP_DEFLATED) as zipf:
            for file_path in files_to_package:
                # Calculate the relative path within the zip.
                arcname = Path(skill_name) / file_path.relative_to(skill_path)
                zipf.write(file_path, arcname)
                print(f"  Added: {arcname}")

        print(f"\n[OK] Successfully packaged skill to: {skill_filename}")
        return skill_filename

    except Exception as e:
        _cleanup_partial_archive(skill_filename)
        print(f"[ERROR] Error creating .skill file: {e}")
        return None


def main():
    if len(sys.argv) < 2:
        print("Usage: python package_skill.py <path/to/skill-folder> [output-directory]")
        print("\nExample:")
        print("  python package_skill.py skills/public/my-skill")
        print("  python package_skill.py skills/public/my-skill ./dist")
        sys.exit(1)

    skill_path = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else None

    print(f"Packaging skill: {skill_path}")
    if output_dir:
        print(f"   Output directory: {output_dir}")
    print()

    result = package_skill(skill_path, output_dir)

    if result:
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()

````

[⬆ 回到目录](#toc)

## 📄 skill-creator/scripts/quick_validate.py

````python
#!/usr/bin/env python3
"""
Minimal validator for nanobot skill folders.
"""

import re
import sys
from pathlib import Path
from typing import Optional

try:
    import yaml
except ModuleNotFoundError:
    yaml = None

MAX_SKILL_NAME_LENGTH = 64
ALLOWED_FRONTMATTER_KEYS = {
    "name",
    "description",
    "metadata",
    "always",
    "license",
    "allowed-tools",
}
ALLOWED_RESOURCE_DIRS = {"scripts", "references", "assets"}
PLACEHOLDER_MARKERS = ("[todo", "todo:")


def _extract_frontmatter(content: str) -> Optional[str]:
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return "\n".join(lines[1:i])
    return None


def _parse_simple_frontmatter(frontmatter_text: str) -> Optional[dict[str, str]]:
    """Fallback parser for simple frontmatter when PyYAML is unavailable."""
    parsed: dict[str, str] = {}
    current_key: Optional[str] = None
    multiline_key: Optional[str] = None

    for raw_line in frontmatter_text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        is_indented = raw_line[:1].isspace()
        if is_indented:
            if current_key is None:
                return None
            current_value = parsed[current_key]
            parsed[current_key] = f"{current_value}\n{stripped}" if current_value else stripped
            continue

        if ":" not in stripped:
            return None

        key, value = stripped.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            return None

        if value in {"|", ">"}:
            parsed[key] = ""
            current_key = key
            multiline_key = key
            continue

        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        parsed[key] = value
        current_key = key
        multiline_key = None

    if multiline_key is not None and multiline_key not in parsed:
        return None
    return parsed


def _load_frontmatter(frontmatter_text: str) -> tuple[Optional[dict], Optional[str]]:
    if yaml is not None:
        try:
            frontmatter = yaml.safe_load(frontmatter_text)
        except yaml.YAMLError as exc:
            return None, f"Invalid YAML in frontmatter: {exc}"
        if not isinstance(frontmatter, dict):
            return None, "Frontmatter must be a YAML dictionary"
        return frontmatter, None

    frontmatter = _parse_simple_frontmatter(frontmatter_text)
    if frontmatter is None:
        return None, "Invalid YAML in frontmatter: unsupported syntax without PyYAML installed"
    return frontmatter, None


def _validate_skill_name(name: str, folder_name: str) -> Optional[str]:
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
        return (
            f"Name '{name}' should be hyphen-case "
            "(lowercase letters, digits, and single hyphens only)"
        )
    if len(name) > MAX_SKILL_NAME_LENGTH:
        return (
            f"Name is too long ({len(name)} characters). "
            f"Maximum is {MAX_SKILL_NAME_LENGTH} characters."
        )
    if name != folder_name:
        return f"Skill name '{name}' must match directory name '{folder_name}'"
    return None


def _validate_description(description: str) -> Optional[str]:
    trimmed = description.strip()
    if not trimmed:
        return "Description cannot be empty"
    lowered = trimmed.lower()
    if any(marker in lowered for marker in PLACEHOLDER_MARKERS):
        return "Description still contains TODO placeholder text"
    if "<" in trimmed or ">" in trimmed:
        return "Description cannot contain angle brackets (< or >)"
    if len(trimmed) > 1024:
        return f"Description is too long ({len(trimmed)} characters). Maximum is 1024 characters."
    return None


def validate_skill(skill_path):
    """Validate a skill folder structure and required frontmatter."""
    skill_path = Path(skill_path).resolve()

    if not skill_path.exists():
        return False, f"Skill folder not found: {skill_path}"
    if not skill_path.is_dir():
        return False, f"Path is not a directory: {skill_path}"

    skill_md = skill_path / "SKILL.md"
    if not skill_md.exists():
        return False, "SKILL.md not found"

    try:
        content = skill_md.read_text(encoding="utf-8")
    except OSError as exc:
        return False, f"Could not read SKILL.md: {exc}"

    frontmatter_text = _extract_frontmatter(content)
    if frontmatter_text is None:
        return False, "Invalid frontmatter format"

    frontmatter, error = _load_frontmatter(frontmatter_text)
    if error:
        return False, error

    unexpected_keys = sorted(set(frontmatter.keys()) - ALLOWED_FRONTMATTER_KEYS)
    if unexpected_keys:
        allowed = ", ".join(sorted(ALLOWED_FRONTMATTER_KEYS))
        unexpected = ", ".join(unexpected_keys)
        return (
            False,
            f"Unexpected key(s) in SKILL.md frontmatter: {unexpected}. Allowed properties are: {allowed}",
        )

    if "name" not in frontmatter:
        return False, "Missing 'name' in frontmatter"
    if "description" not in frontmatter:
        return False, "Missing 'description' in frontmatter"

    name = frontmatter["name"]
    if not isinstance(name, str):
        return False, f"Name must be a string, got {type(name).__name__}"
    name_error = _validate_skill_name(name.strip(), skill_path.name)
    if name_error:
        return False, name_error

    description = frontmatter["description"]
    if not isinstance(description, str):
        return False, f"Description must be a string, got {type(description).__name__}"
    description_error = _validate_description(description)
    if description_error:
        return False, description_error

    always = frontmatter.get("always")
    if always is not None and not isinstance(always, bool):
        return False, f"'always' must be a boolean, got {type(always).__name__}"

    for child in skill_path.iterdir():
        if child.name == "SKILL.md":
            continue
        if child.is_dir() and child.name in ALLOWED_RESOURCE_DIRS:
            continue
        if child.is_symlink():
            continue
        return (
            False,
            f"Unexpected file or directory in skill root: {child.name}. "
            "Only SKILL.md, scripts/, references/, and assets/ are allowed.",
        )

    return True, "Skill is valid!"


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python quick_validate.py <skill_directory>")
        sys.exit(1)

    valid, message = validate_skill(sys.argv[1])
    print(message)
    sys.exit(0 if valid else 1)

````

[⬆ 回到目录](#toc)

## 📄 summarize/SKILL.md

````markdown
---
name: summarize
description: Summarize or extract text/transcripts from URLs, podcasts, and local files (great fallback for “transcribe this YouTube/video”).
homepage: https://summarize.sh
metadata: {"nanobot":{"emoji":"🧾","requires":{"bins":["summarize"]},"install":[{"id":"brew","kind":"brew","formula":"steipete/tap/summarize","bins":["summarize"],"label":"Install summarize (brew)"}]}}
---

# Summarize

Fast CLI to summarize URLs, local files, and YouTube links.

## When to use (trigger phrases)

Use this skill immediately when the user asks any of:
- “use summarize.sh”
- “what’s this link/video about?”
- “summarize this URL/article”
- “transcribe this YouTube/video” (best-effort transcript extraction; no `yt-dlp` needed)

## Quick start

```bash
summarize "https://example.com" --model google/gemini-3-flash-preview
summarize "/path/to/file.pdf" --model google/gemini-3-flash-preview
summarize "https://youtu.be/dQw4w9WgXcQ" --youtube auto
```

## YouTube: summary vs transcript

Best-effort transcript (URLs only):

```bash
summarize "https://youtu.be/dQw4w9WgXcQ" --youtube auto --extract-only
```

If the user asked for a transcript but it’s huge, return a tight summary first, then ask which section/time range to expand.

## Model + keys

Set the API key for your chosen provider:
- OpenAI: `OPENAI_API_KEY`
- Anthropic: `ANTHROPIC_API_KEY`
- xAI: `XAI_API_KEY`
- Google: `GEMINI_API_KEY` (aliases: `GOOGLE_GENERATIVE_AI_API_KEY`, `GOOGLE_API_KEY`)

Default model is `google/gemini-3-flash-preview` if none is set.

## Useful flags

- `--length short|medium|long|xl|xxl|<chars>`
- `--max-output-tokens <count>`
- `--extract-only` (URLs only)
- `--json` (machine readable)
- `--firecrawl auto|off|always` (fallback extraction)
- `--youtube auto` (Apify fallback if `APIFY_API_TOKEN` set)

## Config

Optional config file: `~/.summarize/config.json`

```json
{ "model": "openai/gpt-5.2" }
```

Optional services:
- `FIRECRAWL_API_KEY` for blocked sites
- `APIFY_API_TOKEN` for YouTube fallback

````

[⬆ 回到目录](#toc)

## 📄 tmux/SKILL.md

````markdown
---
name: tmux
description: Remote-control tmux sessions for interactive CLIs by sending keystrokes and scraping pane output.
metadata: {"nanobot":{"emoji":"🧵","os":["darwin","linux"],"requires":{"bins":["tmux"]}}}
---

# tmux Skill

Use tmux only when you need an interactive TTY. Prefer exec background mode for long-running, non-interactive tasks.

## Quickstart (isolated socket, exec tool)

```bash
SOCKET_DIR="${NANOBOT_TMUX_SOCKET_DIR:-${TMPDIR:-/tmp}/nanobot-tmux-sockets}"
mkdir -p "$SOCKET_DIR"
SOCKET="$SOCKET_DIR/nanobot.sock"
SESSION=nanobot-python

tmux -S "$SOCKET" new -d -s "$SESSION" -n shell
tmux -S "$SOCKET" send-keys -t "$SESSION":0.0 -- 'PYTHON_BASIC_REPL=1 python3 -q' Enter
tmux -S "$SOCKET" capture-pane -p -J -t "$SESSION":0.0 -S -200
```

After starting a session, always print monitor commands:

```
To monitor:
  tmux -S "$SOCKET" attach -t "$SESSION"
  tmux -S "$SOCKET" capture-pane -p -J -t "$SESSION":0.0 -S -200
```

## Socket convention

- Use `NANOBOT_TMUX_SOCKET_DIR` environment variable.
- Default socket path: `"$NANOBOT_TMUX_SOCKET_DIR/nanobot.sock"`.

## Targeting panes and naming

- Target format: `session:window.pane` (defaults to `:0.0`).
- Keep names short; avoid spaces.
- Inspect: `tmux -S "$SOCKET" list-sessions`, `tmux -S "$SOCKET" list-panes -a`.

## Finding sessions

- List sessions on your socket: `{baseDir}/scripts/find-sessions.sh -S "$SOCKET"`.
- Scan all sockets: `{baseDir}/scripts/find-sessions.sh --all` (uses `NANOBOT_TMUX_SOCKET_DIR`).

## Sending input safely

- Prefer literal sends: `tmux -S "$SOCKET" send-keys -t target -l -- "$cmd"`.
- Control keys: `tmux -S "$SOCKET" send-keys -t target C-c`.

## Watching output

- Capture recent history: `tmux -S "$SOCKET" capture-pane -p -J -t target -S -200`.
- Wait for prompts: `{baseDir}/scripts/wait-for-text.sh -t session:0.0 -p 'pattern'`.
- Attaching is OK; detach with `Ctrl+b d`.

## Spawning processes

- For python REPLs, set `PYTHON_BASIC_REPL=1` (non-basic REPL breaks send-keys flows).

## Windows / WSL

- tmux is supported on macOS/Linux. On Windows, use WSL and install tmux inside WSL.
- This skill is gated to `darwin`/`linux` and requires `tmux` on PATH.

## Orchestrating Coding Agents (Codex, Claude Code)

tmux excels at running multiple coding agents in parallel:

```bash
SOCKET="${TMPDIR:-/tmp}/codex-army.sock"

# Create multiple sessions
for i in 1 2 3 4 5; do
  tmux -S "$SOCKET" new-session -d -s "agent-$i"
done

# Launch agents in different workdirs
tmux -S "$SOCKET" send-keys -t agent-1 "cd /tmp/project1 && codex --yolo 'Fix bug X'" Enter
tmux -S "$SOCKET" send-keys -t agent-2 "cd /tmp/project2 && codex --yolo 'Fix bug Y'" Enter

# Poll for completion (check if prompt returned)
for sess in agent-1 agent-2; do
  if tmux -S "$SOCKET" capture-pane -p -t "$sess" -S -3 | grep -q "❯"; then
    echo "$sess: DONE"
  else
    echo "$sess: Running..."
  fi
done

# Get full output from completed session
tmux -S "$SOCKET" capture-pane -p -t agent-1 -S -500
```

**Tips:**
- Use separate git worktrees for parallel fixes (no branch conflicts)
- `pnpm install` first before running codex in fresh clones
- Check for shell prompt (`❯` or `$`) to detect completion
- Codex needs `--yolo` or `--full-auto` for non-interactive fixes

## Cleanup

- Kill a session: `tmux -S "$SOCKET" kill-session -t "$SESSION"`.
- Kill all sessions on a socket: `tmux -S "$SOCKET" list-sessions -F '#{session_name}' | xargs -r -n1 tmux -S "$SOCKET" kill-session -t`.
- Remove everything on the private socket: `tmux -S "$SOCKET" kill-server`.

## Helper: wait-for-text.sh

`{baseDir}/scripts/wait-for-text.sh` polls a pane for a regex (or fixed string) with a timeout.

```bash
{baseDir}/scripts/wait-for-text.sh -t session:0.0 -p 'pattern' [-F] [-T 20] [-i 0.5] [-l 2000]
```

- `-t`/`--target` pane target (required)
- `-p`/`--pattern` regex to match (required); add `-F` for fixed string
- `-T` timeout seconds (integer, default 15)
- `-i` poll interval seconds (default 0.5)
- `-l` history lines to search (integer, default 1000)

````

[⬆ 回到目录](#toc)

## 📄 tmux/scripts/find-sessions.sh

````bash
#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: find-sessions.sh [-L socket-name|-S socket-path|-A] [-q pattern]

List tmux sessions on a socket (default tmux socket if none provided).

Options:
  -L, --socket       tmux socket name (passed to tmux -L)
  -S, --socket-path  tmux socket path (passed to tmux -S)
  -A, --all          scan all sockets under NANOBOT_TMUX_SOCKET_DIR
  -q, --query        case-insensitive substring to filter session names
  -h, --help         show this help
USAGE
}

socket_name=""
socket_path=""
query=""
scan_all=false
socket_dir="${NANOBOT_TMUX_SOCKET_DIR:-${TMPDIR:-/tmp}/nanobot-tmux-sockets}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    -L|--socket)      socket_name="${2-}"; shift 2 ;;
    -S|--socket-path) socket_path="${2-}"; shift 2 ;;
    -A|--all)         scan_all=true; shift ;;
    -q|--query)       query="${2-}"; shift 2 ;;
    -h|--help)        usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
  esac
done

if [[ "$scan_all" == true && ( -n "$socket_name" || -n "$socket_path" ) ]]; then
  echo "Cannot combine --all with -L or -S" >&2
  exit 1
fi

if [[ -n "$socket_name" && -n "$socket_path" ]]; then
  echo "Use either -L or -S, not both" >&2
  exit 1
fi

if ! command -v tmux >/dev/null 2>&1; then
  echo "tmux not found in PATH" >&2
  exit 1
fi

list_sessions() {
  local label="$1"; shift
  local tmux_cmd=(tmux "$@")

  if ! sessions="$("${tmux_cmd[@]}" list-sessions -F '#{session_name}\t#{session_attached}\t#{session_created_string}' 2>/dev/null)"; then
    echo "No tmux server found on $label" >&2
    return 1
  fi

  if [[ -n "$query" ]]; then
    sessions="$(printf '%s\n' "$sessions" | grep -i -- "$query" || true)"
  fi

  if [[ -z "$sessions" ]]; then
    echo "No sessions found on $label"
    return 0
  fi

  echo "Sessions on $label:"
  printf '%s\n' "$sessions" | while IFS=$'\t' read -r name attached created; do
    attached_label=$([[ "$attached" == "1" ]] && echo "attached" || echo "detached")
    printf '  - %s (%s, started %s)\n' "$name" "$attached_label" "$created"
  done
}

if [[ "$scan_all" == true ]]; then
  if [[ ! -d "$socket_dir" ]]; then
    echo "Socket directory not found: $socket_dir" >&2
    exit 1
  fi

  shopt -s nullglob
  sockets=("$socket_dir"/*)
  shopt -u nullglob

  if [[ "${#sockets[@]}" -eq 0 ]]; then
    echo "No sockets found under $socket_dir" >&2
    exit 1
  fi

  exit_code=0
  for sock in "${sockets[@]}"; do
    if [[ ! -S "$sock" ]]; then
      continue
    fi
    list_sessions "socket path '$sock'" -S "$sock" || exit_code=$?
  done
  exit "$exit_code"
fi

tmux_cmd=(tmux)
socket_label="default socket"

if [[ -n "$socket_name" ]]; then
  tmux_cmd+=(-L "$socket_name")
  socket_label="socket name '$socket_name'"
elif [[ -n "$socket_path" ]]; then
  tmux_cmd+=(-S "$socket_path")
  socket_label="socket path '$socket_path'"
fi

list_sessions "$socket_label" "${tmux_cmd[@]:1}"

````

[⬆ 回到目录](#toc)

## 📄 tmux/scripts/wait-for-text.sh

````bash
#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: wait-for-text.sh -t target -p pattern [options]

Poll a tmux pane for text and exit when found.

Options:
  -t, --target    tmux target (session:window.pane), required
  -p, --pattern   regex pattern to look for, required
  -F, --fixed     treat pattern as a fixed string (grep -F)
  -T, --timeout   seconds to wait (integer, default: 15)
  -i, --interval  poll interval in seconds (default: 0.5)
  -l, --lines     number of history lines to inspect (integer, default: 1000)
  -h, --help      show this help
USAGE
}

target=""
pattern=""
grep_flag="-E"
timeout=15
interval=0.5
lines=1000

while [[ $# -gt 0 ]]; do
  case "$1" in
    -t|--target)   target="${2-}"; shift 2 ;;
    -p|--pattern)  pattern="${2-}"; shift 2 ;;
    -F|--fixed)    grep_flag="-F"; shift ;;
    -T|--timeout)  timeout="${2-}"; shift 2 ;;
    -i|--interval) interval="${2-}"; shift 2 ;;
    -l|--lines)    lines="${2-}"; shift 2 ;;
    -h|--help)     usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
  esac
done

if [[ -z "$target" || -z "$pattern" ]]; then
  echo "target and pattern are required" >&2
  usage
  exit 1
fi

if ! [[ "$timeout" =~ ^[0-9]+$ ]]; then
  echo "timeout must be an integer number of seconds" >&2
  exit 1
fi

if ! [[ "$lines" =~ ^[0-9]+$ ]]; then
  echo "lines must be an integer" >&2
  exit 1
fi

if ! command -v tmux >/dev/null 2>&1; then
  echo "tmux not found in PATH" >&2
  exit 1
fi

# End time in epoch seconds (integer, good enough for polling)
start_epoch=$(date +%s)
deadline=$((start_epoch + timeout))

while true; do
  # -J joins wrapped lines, -S uses negative index to read last N lines
  pane_text="$(tmux capture-pane -p -J -t "$target" -S "-${lines}" 2>/dev/null || true)"

  if printf '%s\n' "$pane_text" | grep $grep_flag -- "$pattern" >/dev/null 2>&1; then
    exit 0
  fi

  now=$(date +%s)
  if (( now >= deadline )); then
    echo "Timed out after ${timeout}s waiting for pattern: $pattern" >&2
    echo "Last ${lines} lines from $target:" >&2
    printf '%s\n' "$pane_text" >&2
    exit 1
  fi

  sleep "$interval"
done

````

[⬆ 回到目录](#toc)

## 📄 weather/SKILL.md

````markdown
---
name: weather
description: Get current weather and forecasts (no API key required).
homepage: https://wttr.in/:help
metadata: {"nanobot":{"emoji":"🌤️","requires":{"bins":["curl"]}}}
---

# Weather

Two free services, no API keys needed.

## wttr.in (primary)

Quick one-liner:
```bash
curl -s "wttr.in/London?format=3"
# Output: London: ⛅️ +8°C
```

Compact format:
```bash
curl -s "wttr.in/London?format=%l:+%c+%t+%h+%w"
# Output: London: ⛅️ +8°C 71% ↙5km/h
```

Full forecast:
```bash
curl -s "wttr.in/London?T"
```

Format codes: `%c` condition · `%t` temp · `%h` humidity · `%w` wind · `%l` location · `%m` moon

Tips:
- URL-encode spaces: `wttr.in/New+York`
- Airport codes: `wttr.in/JFK`
- Units: `?m` (metric) `?u` (USCS)
- Today only: `?1` · Current only: `?0`
- PNG: `curl -s "wttr.in/Berlin.png" -o /tmp/weather.png`

## Open-Meteo (fallback, JSON)

Free, no key, good for programmatic use:
```bash
curl -s "https://api.open-meteo.com/v1/forecast?latitude=51.5&longitude=-0.12&current_weather=true"
```

Find coordinates for a city, then query. Returns JSON with temp, windspeed, weathercode.

Docs: https://open-meteo.com/en/docs

````

[⬆ 回到目录](#toc)

---
### 📊 最终统计汇总
- **文件总数:** 14
- **代码总行数:** 1771
- **物理总大小:** 61.68 KB
