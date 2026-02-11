---
name: yuque-reply
description: "回复语雀文章评论。打开语雀文章页面，获取评论列表，选择评论进行回复。需要 agent-browser 和已登录的语雀会话。Triggers: 语雀评论, 回复评论, yuque comment, yuque reply, 评论回复, 语雀回复"
metadata: {"nanobot":{"emoji":"💬","requires":{"bins":["agent-browser"]}}}
---

# Yuque Reply - 语雀评论回复

通过 agent-browser 自动化回复语雀（yuque.antfin.com）文章的评论。

> **脚本路径**: 本 skill 的 helper 脚本位于 SKILL.md 同级的 `scripts/` 目录下。将 SKILL.md 路径中的 `SKILL.md` 替换为 `scripts/` 即可。下文用 `SCRIPTS` 代指该目录。

## 前置条件

- `agent-browser` 已安装
- 语雀需要登录，首次使用需用 `--headed` 模式手动登录一次
- Yuque MCP server 已配置（用于获取文档原文和元数据）

## 流程概览

1. **通过 Yuque MCP 获取文章原文和元数据**（评论数、浏览量等）
2. 打开语雀文章页面，滚动到评论区
3. **获取评论列表**
4. **结合原文内容理解评论上下文**，构思回复
5. 对每条要回复的评论：点击回复 → 输入内容 → 提交
6. 关闭浏览器

## Step 0: 通过 Yuque MCP 获取原文和元数据

在打开浏览器之前，先通过 MCP 工具获取文章信息。

语雀文章 URL 格式：`https://yuque.antfin.com/{login}/{book_slug}/{doc_slug}`

```
mcp__yuque__skylark_user_doc_detail(namespace="{login}/{book_slug}", slug="{doc_slug}")
```

返回的关键字段：
- `body_md` — 文章 Markdown 正文（用于理解评论上下文）
- `comments_count` — 评论数
- `title` — 文章标题
- `user.name` — 作者名

**回复时务必参考原文**：阅读 `body_md` 理解文章在讲什么，再结合具体评论内容来构思有针对性的回复。

## Step 1: 打开页面

```bash
# 首次使用需要 headed 模式登录
agent-browser open <语雀文章URL> --headed
```

检查是否被重定向到登录页：

```bash
agent-browser get url
```

如果 URL 包含 `login` 或 `pubbuservice`，说明需要登录。提示用户在 headed 浏览器窗口中手动登录。

## Step 2: 滚动到评论区并获取评论

```bash
agent-browser wait --load networkidle
agent-browser scroll down 2000
agent-browser wait 1000
```

获取页面上的点赞数和浏览量：

```bash
agent-browser snapshot -c -d 3
# 在输出中找到 "XX 人点赞" 和浏览量数字
```

获取评论列表（使用脚本避免引号问题）：

```bash
bash SCRIPTS/get_comments.sh
```

## Step 3: 回复评论

**重要：必须使用脚本来操作，不要直接写 `agent-browser eval "..."` 内联 JS，因为嵌套引号会被 shell 吃掉导致命令截断。**

对每条要回复的评论，依次执行：

### 3a. 点击回复按钮

```bash
# N 是评论索引（0-indexed）
bash SCRIPTS/click_reply.sh N
```

脚本流程：先 scrollIntoView 将评论滚动到可视区域 → 获取 `commentActions-module_actionItem_` 按钮的 getBoundingClientRect 坐标 → 用 `agent-browser mouse move/down/up` 真实鼠标点击 → 验证 contenteditable 编辑器数量变为 2。

> **为什么不用 JS `.click()`**：语雀的评论回复按钮必须在可视区域内且通过真实鼠标事件触发，JS `.click()` 不会打开回复编辑器。

### 3b. 输入回复并提交

```bash
bash SCRIPTS/type_and_submit.sh "你的回复内容 —— kaguya 回复"
```

脚本会在回复编辑器中输入文字，然后自动点击提交按钮。

### 3c. 回复下一条前等待

```bash
agent-browser wait 2000
```

每条回复之间等待 2 秒，确保上一条提交完成、页面状态恢复。

## Step 4: 关闭浏览器

```bash
agent-browser close
```

## 完整示例

假设文章 URL 为 `https://yuque.antfin.com/junyu.junyujiang/wdx498/bhgwk8rb1agl5fd5`

### 1. 获取原文（MCP）

```
mcp__yuque__skylark_user_doc_detail(namespace="junyu.junyujiang/wdx498", slug="bhgwk8rb1agl5fd5")
```

### 2. 打开页面并获取评论

```bash
agent-browser open "https://yuque.antfin.com/junyu.junyujiang/wdx498/bhgwk8rb1agl5fd5" --headed
agent-browser wait --load networkidle
agent-browser scroll down 2000
agent-browser wait 1000
bash SCRIPTS/get_comments.sh
```

### 3. 逐条回复

```bash
# 回复第 0 条评论
bash SCRIPTS/click_reply.sh 0
bash SCRIPTS/type_and_submit.sh "鹊桥机制好主意！—— kaguya 回复"
agent-browser wait 2000

# 回复第 1 条评论
bash SCRIPTS/click_reply.sh 1
bash SCRIPTS/type_and_submit.sh "是的，虽然异地但心连心 —— kaguya 回复"
agent-browser wait 2000
```

### 4. 关闭

```bash
agent-browser close
```

## 注意事项

- 语雀是内网系统，需要蚂蚁内网环境
- 首次使用必须 `--headed` 模式手动登录
- **不要直接写内联 `agent-browser eval "..."` JS 代码**，嵌套引号会被 exec 工具的 shell 截断。务必使用 `scripts/` 目录下的脚本
- **评论必须在可视区域内才能操作**，脚本会自动 scrollIntoView，但如果失败请检查页面是否有弹窗遮挡
- **必须使用真实鼠标点击**（mouse move/down/up），JS `.click()` 无法触发语雀回复编辑器
- 回复编辑器使用 Lake 富文本引擎，只能通过 `agent-browser type` 命令输入，不能直接操作 DOM
- 评论区操作按钮通过 CSS class `commentActions-module_actionItem_` 定位，第一个按钮即回复（CommentBubble 图标）
- 回复按钮在输入内容前是 disabled 状态，输入后自动启用
- 每条回复之间需要等待 2 秒，否则页面状态可能不对
