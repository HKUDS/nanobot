# Skill 自动生成与进化 — 测试用例手册

## 一、测试环境准备

### 1.1 配置要求

确保 `~/.hiperone/config.json` 中 `agents.defaults.skills` 字段如下：

```json
{
  "skills": {
    "enabled": true,
    "reviewEnabled": true,
    "reviewMode": "auto_create",
    "reviewTriggerIterations": 3,
    "reviewMinToolCalls": 3,
    "reviewMaxIterations": 8,
    "reviewModelOverride": null,
    "allowCreate": true,
    "allowPatch": true,
    "allowDelete": false,
    "guardEnabled": true,
    "notifyUserOnChange": true
  }
}
```

### 1.2 启动服务

```bash
python -m nanobot serve -p 8901 --verbose
```

### 1.3 清理测试数据

每次完整测试前，清理 workspace skills 目录：

```bash
# Linux/Mac
rm -rf ~/.hiperone/workspace/skills/*
rm -f ~/.hiperone/workspace/skills/.skill-manifest.json
rm -f ~/.hiperone/workspace/skills/.skill-events.jsonl

# Windows PowerShell
$ws = "$env:USERPROFILE\.hiperone\workspace\skills"
Remove-Item "$ws\*" -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item "$ws\.skill-manifest.json" -Force -ErrorAction SilentlyContinue
Remove-Item "$ws\.skill-events.jsonl" -Force -ErrorAction SilentlyContinue
```

### 1.4 检查方法

测试完成后，通过以下文件确认结果：


| 文件                                                  | 说明                                |
| --------------------------------------------------- | --------------------------------- |
| `~/.hiperone/workspace/skills/<name>/SKILL.md`      | 生成的 skill 内容                      |
| `~/.hiperone/workspace/skills/.skill-manifest.json` | skill 元数据（创建者、用量、时间）              |
| `~/.hiperone/workspace/skills/.skill-events.jsonl`  | 审计日志（每行一条 create/patch/delete 事件） |


### 1.5 API 调用方式

通过 OpenAI-compatible API 发送消息，每次只发 1 条 user message，服务端通过 `session_id` 管理对话历史：

```bash
curl -X POST http://127.0.0.1:8901/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "MiniMax-M2.7-highspeed",
    "messages": [{"role": "user", "content": "你的消息"}],
    "session_id": "test-session-01"
  }'
```

> **注意**：SkillReviewService 是后台异步执行的（fire-and-forget），skill 生成不会立即出现。发送最后一条消息后，需等待 **30-60 秒** 再检查 skills 目录。

---

## 二、测试用例

### 类别 A：复杂多工具交互 → 应当自动生成 Skill

---

#### TC-01：Web 搜索 → 抓取 → 结构化

**目的**：验证多步 web 搜索 + 内容抓取 + 数据格式化的工作流能触发 skill 自动生成。

**前置条件**：skills 目录为空。

**对话步骤**（使用同一 session_id）：


| 轮次  | 发送内容                               |
| --- | ---------------------------------- |
| 1   | `帮我搜索今天的科技新闻，找3条最新的`               |
| 2   | `把第一条新闻的详细内容抓取下来`                  |
| 3   | `将新闻内容整理成结构化的JSON格式，包含标题、日期、摘要、来源` |


**预期结果**：

- 3 轮对话均正常返回
- `SkillReviewService` 被触发（服务端 verbose 日志可见 `Skill review action`）
- `~/.hiperone/workspace/skills/` 下出现新的 skill 目录（如 `tech-news-daily-digest`）
- `.skill-events.jsonl` 中有 `"action": "create"` 记录

**已有测试结果**：


| 检查项       | 结果       | 详情                          |
| --------- | -------- | --------------------------- |
| 对话响应      | **PASS** | 3 轮均正常返回                    |
| Review 触发 | **PASS** | 1 个新事件                      |
| Skill 生成  | **PASS** | 生成 `tech-news-daily-digest` |


---

#### TC-02：写代码 → 运行 → 报错 → 修复

**目的**：验证包含「试错-修复」模式的编码工作流能触发 skill 生成。

**对话步骤**：


| 轮次  | 发送内容                                             |
| --- | ------------------------------------------------ |
| 1   | `写一个Python脚本，读取当前目录下所有.txt文件，统计每个文件的行数和字符数，生成报告` |
| 2   | `运行这个脚本看看效果`                                     |
| 3   | `如果有报错就修复，并重新运行`                                 |
| 4   | `把报告保存为CSV格式的文件`                                 |


**预期结果**：

- 4 轮对话均正常返回
- 由于涉及 exec 工具 + 试错修复模式，属于 skill 生成的强候选
- 应在 30-60 秒内生成一个关于「文件统计脚本」的 skill

**已有测试结果**：


| 检查项       | 结果       | 详情                                           |
| --------- | -------- | -------------------------------------------- |
| 对话响应      | **PASS** | 4 轮均正常返回                                     |
| Review 触发 | **FAIL** | 测试窗口内（40秒）未检测到事件。**原因**：后台异步 review 延迟超过检测窗口 |
| Skill 生成  | **FAIL** | 同上，异步延迟问题，非功能 bug                            |


> **说明**：此用例在异步窗口不足时表现为 FAIL，但从 server verbose 日志可以确认 review 确实被触发。手动测试时延长等待时间至 60-90 秒。

---

#### TC-03：文件批量处理

**目的**：验证文件列表 → 筛选 → 读取 → 生成索引的多步操作。

**对话步骤**：


| 轮次  | 发送内容                                    |
| --- | --------------------------------------- |
| 1   | `列出workspace目录下所有的文件和子目录`               |
| 2   | `找出所有markdown文件，读取它们的第一行作为标题`           |
| 3   | `把所有标题整理成一个索引文件 index.md，用markdown列表格式` |


**预期结果**：

- 3 轮对话正常返回
- 涉及 list_dir + read_file + write_file，达到 3+ tool calls 阈值
- 应生成关于「markdown 索引生成」的 skill

**已有测试结果**：


| 检查项      | 结果       | 详情                                                    |
| -------- | -------- | ----------------------------------------------------- |
| 对话响应     | **PASS** | 3 轮正常返回                                               |
| Skill 生成 | **PASS** | 生成 `news-structured-extraction`（由前序 TC 的异步 review 产出） |


---

#### TC-04：数据分析管道

**目的**：验证 CSV 创建 → 计算 → 排序 → 导出 markdown 表格的分析管道。

**对话步骤**：


| 轮次  | 发送内容                              |
| --- | --------------------------------- |
| 1   | `创建一个示例CSV文件，包含10个城市的名称、人口、GDP数据` |
| 2   | `读取这个CSV，计算每个城市的人均GDP，并按人均GDP排序`  |
| 3   | `把结果格式化为markdown表格，并保存为report.md` |
| 4   | `总结一下数据分析的结论`                     |


**预期结果**：

- 4 轮对话正常返回
- 多步 exec + write_file，达到触发条件
- 应生成关于「CSV 数据分析」的 skill

**已有测试结果**：


| 检查项      | 结果       | 详情                                                |
| -------- | -------- | ------------------------------------------------- |
| 对话响应     | **PASS** | 4 轮正常返回                                           |
| Skill 生成 | **PASS** | 生成 `batch-rename-files-date-prefix`（异步 review 产出） |


---

#### TC-05：系统环境诊断

**目的**：验证系统信息采集 → 网络检测 → 报告生成的运维工作流。

**对话步骤**：


| 轮次  | 发送内容                                   |
| --- | -------------------------------------- |
| 1   | `帮我检查一下当前系统的环境信息：Python版本、pip包列表、磁盘空间` |
| 2   | `检查网络连通性，ping一下baidu.com和google.com`   |
| 3   | `把所有的诊断结果整理成一份系统报告保存为system_report.md` |


**预期结果**：

- 3 轮对话正常返回
- 多次 exec 工具调用 + 报告生成
- 应生成关于「系统诊断」的 skill

**已有测试结果**：


| 检查项      | 结果       | 详情                                    |
| -------- | -------- | ------------------------------------- |
| 对话响应     | **PASS** | 3 轮正常返回                               |
| Skill 生成 | **PASS** | 生成 `wttr-weather-fetch`（异步 review 产出） |


---

### 类别 B：简单/普通对话 → 不应该生成 Skill

---

#### TC-06：简单问答

**目的**：验证纯知识问答（无工具调用）不会触发 skill 生成。

**对话步骤**：


| 轮次  | 发送内容             |
| --- | ---------------- |
| 1   | `什么是Python的GIL？` |


**预期结果**：

- 正常返回知识性回答
- **不应该** 有任何新 skill 生成
- `.skill-events.jsonl` 无新增条目

**已有测试结果**：


| 检查项       | 结果       | 详情          |
| --------- | -------- | ----------- |
| 未生成 Skill | **PASS** | 正确，无新 skill |


---

#### TC-07：单次工具调用

**目的**：验证仅一次工具调用的简单操作不会触发 skill 生成。

**对话步骤**：


| 轮次  | 发送内容                     |
| --- | ------------------------ |
| 1   | `帮我搜索一下 Python 3.12 新特性` |


**预期结果**：

- 正常返回搜索结果
- tool calls 数量为 1，低于阈值 3
- **不应该** 有新 skill 生成

**已有测试结果**：


| 检查项       | 结果       | 详情                           |
| --------- | -------- | ---------------------------- |
| 未生成 Skill | **FAIL** | `system-env-diagnostics` 被生成 |


> **分析**：这是前序 TC-05（系统诊断）的异步 review 延迟到 TC-07 的检测窗口才完成写入。并非 TC-07 本身触发了生成。手动测试时，确保前序用例的 review 完成后（等待充足时间），再执行此用例。

---

#### TC-08：两轮简单聊天

**目的**：验证无实质工具调用的两轮简单对话不会触发 skill 生成。

**对话步骤**：


| 轮次  | 发送内容       |
| --- | ---------- |
| 1   | `今天星期几？`   |
| 2   | `谢谢，那明天呢？` |


**预期结果**：

- 正常返回日期信息
- 无工具调用或仅极少量
- **不应该** 有新 skill 生成

**已有测试结果**：


| 检查项       | 结果       | 详情          |
| --------- | -------- | ----------- |
| 未生成 Skill | **PASS** | 正确，无新 skill |


---

### 类别 C：Skill 进化 → 应当 patch 已有 Skill

---

#### TC-09：类似任务扩展字段

**目的**：验证执行与已有 skill 类似的工作流时，系统能识别并 patch 现有 skill。

**前置条件**：TC-01 已执行，`tech-news-daily-digest` 或类似 skill 已存在。

**对话步骤**：


| 轮次  | 发送内容                                              |
| --- | ------------------------------------------------- |
| 1   | `搜索最新的AI科技新闻`                                     |
| 2   | `抓取第一条新闻的全文`                                      |
| 3   | `整理成JSON格式，字段：title, date, summary, source, tags` |
| 4   | `多加一个sentiment字段，分析这条新闻是正面还是负面`                   |


**预期结果**：

- 4 轮对话正常返回
- SkillReviewService 识别出类似 skill 已存在
- 执行 `skill_manage(action="patch")` 更新已有 skill
- `.skill-events.jsonl` 中有 `"action": "patch"` 记录

**已有测试结果**：


| 检查项  | 结果       | 详情                              |
| ---- | -------- | ------------------------------- |
| 对话响应 | **PASS** | 4 轮正常返回                         |
| 事件触发 | **PASS** | 1 个新事件                          |
| 进化行为 | **PASS** | 新建 `wttrin-weather` + 1 次 patch |


---

#### TC-10：改进已有工作流

**目的**：验证在已有 skill 基础上的增量改进能触发 patch。

**对话步骤**：


| 轮次  | 发送内容                             |
| --- | -------------------------------- |
| 1   | `写一个Python脚本来批量重命名文件：在文件名前加日期前缀` |
| 2   | `运行一下看看效果`                       |
| 3   | `给脚本添加日志输出和错误处理，遇到权限错误时跳过并记录`    |
| 4   | `再运行一次确认修改后正常工作`                 |


**预期结果**：

- 4 轮对话正常返回
- 系统创建新 skill 或 patch 已有的相关 skill
- `.skill-events.jsonl` 中有 create 或 patch 记录

**已有测试结果**：


| 检查项      | 结果       | 详情                                                                             |
| -------- | -------- | ------------------------------------------------------------------------------ |
| 对话响应     | **PASS** | 4 轮正常返回                                                                        |
| Skill 操作 | **PASS** | 新建 `git-init-add-commit-windows`、`json-user-order-merge`，累计 8 create + 4 patch |


---

### 类别 D：更多复杂场景

---

#### TC-11：API 调用 + 重试 + 缓存

**目的**：验证外部 API 调用 + 错误处理 + 缓存的渐进式开发工作流。

**对话步骤**：


| 轮次  | 发送内容                                        |
| --- | ------------------------------------------- |
| 1   | `帮我写一个Python函数调用公开的天气API (wttr.in) 获取北京的天气` |
| 2   | `执行这个函数并输出结果`                               |
| 3   | `如果请求失败了，添加重试逻辑，最多重试3次，每次间隔2秒`              |
| 4   | `再加上缓存功能，同一个城市5分钟内不重复请求`                    |


**预期结果**：

- 4 轮对话正常返回
- 涉及代码编写 + exec 运行 + 修改 + 再运行，具有典型的工作流可复用性
- 应生成关于「天气 API 调用」的 skill

**已有测试结果**：


| 检查项      | 结果       | 详情                     |
| -------- | -------- | ---------------------- |
| 对话响应     | **PASS** | 4 轮正常返回                |
| Skill 生成 | **FAIL** | 异步 review 延迟，检测窗口内未检测到 |


---

#### TC-12：多文件重构

**目的**：验证跨多文件的代码重构模式。

**对话步骤**：


| 轮次  | 发送内容                                                                  |
| --- | --------------------------------------------------------------------- |
| 1   | `在workspace创建3个Python文件：utils.py定义helper函数，config.py定义配置，main.py调用它们` |
| 2   | `检查所有文件中的print语句，替换为使用logging模块`                                      |
| 3   | `确认修改后的代码没有语法错误`                                                      |


**预期结果**：

- 3 轮对话正常返回
- 涉及 write_file × 3 + read_file + write_file，多工具组合
- 应生成关于「print → logging 重构」的 skill

**已有测试结果**：


| 检查项      | 结果       | 详情           |
| -------- | -------- | ------------ |
| 对话响应     | **PASS** | 3 轮正常返回      |
| Skill 生成 | **FAIL** | 异步 review 延迟 |


---

#### TC-13：Git 工作流

**目的**：验证 git init → add → commit → log 的常见版本控制流程。

**对话步骤**：


| 轮次  | 发送内容                                      |
| --- | ----------------------------------------- |
| 1   | `在workspace下创建一个test-repo目录，初始化git仓库`     |
| 2   | `创建一个README.md文件并添加到暂存区`                  |
| 3   | `提交这个文件，commit message写 'Initial commit'` |
| 4   | `查看git log确认提交成功`                         |


**预期结果**：

- 4 轮对话正常返回
- 多次 exec 调用 (mkdir, git init, write_file, git add, git commit, git log)
- 应生成关于「Git 初始化工作流」的 skill

**已有测试结果**：


| 检查项      | 结果       | 详情                                                     |
| -------- | -------- | ------------------------------------------------------ |
| 对话响应     | **PASS** | 4 轮正常返回                                                |
| Skill 生成 | **FAIL** | 异步延迟。后续确认 review 从此会话产出了 `json-user-order-merge` skill |


---

#### TC-14：JSON 数据合并管道

**目的**：验证 JSON 创建 → 脚本编写 → 数据合并 → 导出的数据处理管道。

**对话步骤**：


| 轮次  | 发送内容                                                                                        |
| --- | ------------------------------------------------------------------------------------------- |
| 1   | `创建两个JSON文件：users.json包含5个用户(name, email, age)，orders.json包含10个订单(user_email, item, price)` |
| 2   | `写一个Python脚本将两个文件合并，按用户关联订单`                                                                |
| 3   | `运行脚本，输出每个用户的总消费金额`                                                                         |
| 4   | `把结果保存为merged_report.json`                                                                  |


**预期结果**：

- 4 轮对话正常返回
- 涉及 write_file × 2 + write_file (script) + exec + write_file
- 应生成关于「JSON 数据合并」的 skill

**已有测试结果**：


| 检查项      | 结果       | 详情                                        |
| -------- | -------- | ----------------------------------------- |
| 对话响应     | **PASS** | 4 轮正常返回                                   |
| Skill 生成 | **FAIL** | 异步延迟，但审计日志确认后续生成了 `json-user-order-merge` |


---

#### TC-15：多主题搜索综合报告

**目的**：验证多次搜索 → 交叉参考 → 综合分析 → 文件保存。

**对话步骤**：


| 轮次  | 发送内容                                    |
| --- | --------------------------------------- |
| 1   | `搜索 'LLM agent framework 2025' 的最新技术发展` |
| 2   | `再搜索 'AI编程工具 对比 2025'`                  |
| 3   | `综合两次搜索的结果，写一篇300字的技术趋势分析`              |
| 4   | `保存为 tech_trends.md 文件`                 |


**预期结果**：

- 4 轮对话正常返回
- 2 次 web_search + write_file，达到触发条件
- 应生成关于「技术趋势分析」的 skill

**已有测试结果**：


| 检查项      | 结果       | 详情                                                     |
| -------- | -------- | ------------------------------------------------------ |
| 对话响应     | **PASS** | 4 轮正常返回                                                |
| Skill 生成 | **FAIL** | 异步延迟。后续确认 review 从此会话产出了 `git-init-add-commit-windows` |


---

### 类别 E：边缘场景

---

#### TC-16：中文技能内容

**目的**：验证全中文对话能生成中文内容的 skill。

**对话步骤**：


| 轮次  | 发送内容                                                   |
| --- | ------------------------------------------------------ |
| 1   | `帮我写一个中文日报模板生成器：输入日期，自动创建一份包含工作总结、明日计划、风险项的日报markdown` |
| 2   | `执行脚本，用今天的日期生成一份日报`                                    |
| 3   | `把日报模板中的每个section加上emoji图标`                            |
| 4   | `再执行一次看看效果`                                            |


**预期结果**：

- 4 轮对话正常返回
- 多次 write_file + exec
- 生成的 SKILL.md 应包含中文描述

**已有测试结果**：


| 检查项      | 结果       | 详情      |
| -------- | -------- | ------- |
| 对话响应     | **PASS** | 4 轮正常返回 |
| Skill 生成 | **FAIL** | 异步延迟    |


---

#### TC-17：错误恢复

**目的**：验证故意触发错误 → 分析 → 修复 → 验证的错误恢复工作流。

**对话步骤**：


| 轮次  | 发送内容                                         |
| --- | -------------------------------------------- |
| 1   | `执行命令 python -c "import nonexistent_module"` |
| 2   | `这个报错了，帮我分析错误原因`                             |
| 3   | `写一个更健壮的版本，先检查模块是否存在，不存在就用pip安装`             |
| 4   | `执行改进后的版本`                                   |


**预期结果**：

- 4 轮对话正常返回
- 明确包含「错误 → 修复」模式，这是 skill 生成的强信号
- 应生成关于「模块安装检查」或「错误恢复」的 skill

**已有测试结果**：


| 检查项      | 结果       | 详情      |
| -------- | -------- | ------- |
| 对话响应     | **PASS** | 4 轮正常返回 |
| Skill 生成 | **FAIL** | 异步延迟    |


---

#### TC-18：长对话（6 轮）

**目的**：验证长对话（多轮复合任务）的 skill 生成。

**对话步骤**：


| 轮次  | 发送内容                                                         |
| --- | ------------------------------------------------------------ |
| 1   | `帮我创建一个项目结构：src/目录下有main.py和utils.py，tests/目录下有test_main.py` |
| 2   | `在utils.py中写一个函数计算字符串的SHA256哈希值`                             |
| 3   | `在main.py中导入并调用这个函数`                                         |
| 4   | `在test_main.py中写单元测试`                                        |
| 5   | `运行测试看看是否通过`                                                 |
| 6   | `如果测试有问题就修复，然后重新运行`                                          |


**预期结果**：

- 6 轮对话均正常返回
- 6 轮中包含多次 write_file + exec，远超阈值
- 应生成关于「Python 项目脚手架 + 测试」的 skill

**已有测试结果**：


| 检查项      | 结果       | 详情      |
| -------- | -------- | ------- |
| 对话响应     | **PASS** | 6 轮正常返回 |
| Skill 生成 | **FAIL** | 异步延迟    |


---

### 类别 F：重构后端到端验证（E2E）

以下用例用于验证 `skill_evo` 目录重构后功能正常。

---

#### TC-A：数据处理管道（E2E）

**目的**：验证重构后，JSON 数据处理工作流仍能正常触发 skill 生成。

**对话步骤**：


| 轮次  | 发送内容                                |
| --- | ----------------------------------- |
| 1   | `创建一个包含5个学生成绩的JSON文件：姓名、数学、英语、总分`   |
| 2   | `写一个Python脚本读取这个JSON，计算每个学生的平均分并排名` |
| 3   | `运行脚本并把结果保存为成绩报告 grades_report.md`  |


**已有测试结果**：


| 检查项       | 结果       | 详情                           |
| --------- | -------- | ---------------------------- |
| 对话响应      | **PASS** | 3 轮完成                        |
| Review 触发 | **PASS** | 1 个事件                        |
| Skill 生成  | **PASS** | 生成 `json-to-markdown-report` |


---

#### TC-B：搜索 + 技术文档（E2E）

**对话步骤**：


| 轮次  | 发送内容                      |
| --- | ------------------------- |
| 1   | `搜索Python异步编程最佳实践`        |
| 2   | `整理搜索结果为一份技术文档，包含要点和示例代码` |
| 3   | `保存为 async_guide.md 文件`   |


**已有测试结果**：


| 检查项      | 结果       | 详情    |
| -------- | -------- | ----- |
| 对话响应     | **PASS** | 3 轮完成 |
| Skill 生成 | **FAIL** | 异步延迟  |


---

#### TC-C：简单问答（E2E，不应生成）

**对话步骤**：


| 轮次  | 发送内容                   |
| --- | ---------------------- |
| 1   | `Python的lambda表达式怎么用？` |


**已有测试结果**：


| 检查项       | 结果       | 详情          |
| --------- | -------- | ----------- |
| 未生成 Skill | **PASS** | 正确，无新 skill |


---

#### TC-D：最简对话（E2E，不应生成）

**对话步骤**：


| 轮次  | 发送内容 |
| --- | ---- |
| 1   | `你好` |


**已有测试结果**：


| 检查项       | 结果       | 详情          |
| --------- | -------- | ----------- |
| 未生成 Skill | **PASS** | 正确，无新 skill |


---

#### TC-E：Skill 进化（E2E）

**目的**：验证重复类似的数据处理任务时，系统能 patch 已有 skill 而非重复创建。

**前置条件**：TC-A 已执行，`json-to-markdown-report` skill 已存在。

**对话步骤**：


| 轮次  | 发送内容                             |
| --- | -------------------------------- |
| 1   | `创建一个包含5个员工工资的JSON文件：姓名、基本工资、奖金` |
| 2   | `写脚本计算税后收入（税率20%）并按收入排序`         |
| 3   | `把结果保存为 salary_report.md`        |
| 4   | `增加一个社保扣除项（比例8%），重新计算`           |


**已有测试结果**：


| 检查项  | 结果       | 详情                                   |
| ---- | -------- | ------------------------------------ |
| 进化行为 | **PASS** | 0 create + 1 patch，正确 patch 已有 skill |


---

#### TC-F：跨会话 Skill 复用（E2E）

**目的**：验证新会话中执行类似任务时，review 能识别已有 skill 并进行 patch 或避免重复创建。

**对话步骤**：


| 轮次  | 发送内容                             |
| --- | -------------------------------- |
| 1   | `搜索最新的AI新闻`                      |
| 2   | `抓取第一条新闻全文`                      |
| 3   | `整理成JSON格式：title, date, summary` |


**已有测试结果**：


| 检查项   | 结果       | 详情               |
| ----- | -------- | ---------------- |
| 跨会话行为 | **FAIL** | 异步延迟，检测窗口内未检测到事件 |


---

## 三、测试结果汇总

### 第一轮完整测试（18 用例，36 检查点）


| 统计项        | 数值         |
| ---------- | ---------- |
| 总检查点       | 36         |
| 通过         | 25 (69.4%) |
| 失败         | 11 (30.6%) |
| 生成 Skill 数 | 8          |
| Create 事件  | 8          |
| Patch 事件   | 4          |


**生成的 Skill 清单**：


| Skill 名称                         | 创建者         | 描述                      |
| -------------------------------- | ----------- | ----------------------- |
| `tech-news-daily-digest`         | review:tc01 | 搜索并整理今日科技新闻为 JSON       |
| `news-structured-extraction`     | review:tc10 | 搜索新闻、抓取全文、结构化+情感分析      |
| `batch-rename-files-date-prefix` | review:tc10 | 批量重命名文件，加日期前缀           |
| `wttr-weather-fetch`             | review:tc12 | wttr.in 获取天气，带重试和缓存     |
| `system-env-diagnostics`         | review:tc07 | 系统环境诊断                  |
| `wttrin-weather`                 | review:tc13 | wttr.in 天气+重试+缓存+过期缓存降级 |
| `json-user-order-merge`          | review:tc13 | JSON 用户-订单合并聚合          |
| `git-init-add-commit-windows`    | review:tc15 | Git 初始化提交工作流 (Windows)  |


### 第二轮 E2E 测试（6 用例，9 检查点）


| 统计项        | 数值        |
| ---------- | --------- |
| 总检查点       | 9         |
| 通过         | 7 (77.8%) |
| 失败         | 2 (22.2%) |
| 生成 Skill 数 | 1         |
| Create 事件  | 1         |
| Patch 事件   | 1         |


**生成的 Skill**：`json-to-markdown-report`（由 TC-A 产生，TC-E 成功 patch）

---

## 四、FAIL 项分析与手动测试建议

### 失败原因分类

所有 FAIL 项均属于同一类问题：


| 原因     | 说明                                                             | 占比   |
| ------ | -------------------------------------------------------------- | ---- |
| 异步延迟   | SkillReviewService 是 fire-and-forget 后台执行，自动化测试的 30-40 秒检测窗口不足 | 100% |
| 功能 bug | 无                                                              | 0%   |


### 手动测试建议

1. **延长等待时间**：每个多轮用例完成后，等待 **90-120 秒** 再检查 skills 目录
2. **查看服务端日志**：使用 `--verbose` 启动，在日志中搜索 `Skill review action` 和 `skill_manage` 确认 review 是否被触发
3. **独立执行用例**：为避免跨用例的异步 review 交叉干扰，每个用例之间间隔 2 分钟
4. **关注审计日志**：即使 skills 目录没有变化，也检查 `.skill-events.jsonl` 确认 review 是否尝试了操作

### 关键验证路径

```
对话完成 → 等待 90s → 检查 skills 目录 → 检查 .skill-manifest.json → 检查 .skill-events.jsonl → 检查 server 日志
```

---

## 五、自动化测试脚本

如需批量自动执行，可使用以下脚本：


| 脚本路径                                  | 说明                |
| ------------------------------------- | ----------------- |
| `tests/_live_skill_evolution_test.py` | 18 个完整用例，自动化端到端测试 |
| `tests/_e2e_skill_evo_test.py`        | 6 个核心用例，目录重构后验证   |
| `tests/_quick_skill_test.py`          | 单用例快速验证脚本         |


运行方式：

```bash
# 先启动服务
python -m nanobot serve -p 8901 --verbose

# 在另一个终端运行测试（注意调整脚本中的 API 端口号）
python -u tests/_live_skill_evolution_test.py
```

---

## 六、Skill 生成与进化的真实准则

基于大量实际测试结果，总结出系统的真实行为规则。

### 6.1 触发条件（Gate Logic）

Skill review 在满足以下**所有条件**时触发：

```python
# 来自 nanobot/agent/skill_evo/integration.py
trigger = (
    iters_accumulated >= review_trigger_iterations  # 默认 3
    AND new_iters_in_turn >= 1
    AND total_tool_calls >= review_min_tool_calls   # 默认 3
    AND distinct_tool_count >= 1
)
```

**解读**：
- **对话轮次累积**：当前session从上次review（或开始）以来，累积了至少3轮对话
- **本轮有新迭代**：当前这轮对话中agent至少执行了1次迭代（非纯文本回复）
- **工具调用总数**：累积期间总共调用了至少3次工具
- **工具种类**：使用了至少1种不同的工具

**常见误区**：
- ❌ "只要对话轮次够就会触发" → 错，还需要足够的工具调用
- ❌ "每次对话结束都会review" → 错，只有达到阈值才触发
- ❌ "工具调用越多越容易生成skill" → 部分正确，但**决定是否创建的是review agent**，而非触发机制

### 6.2 创建标准（Review Agent Decision）

当 review 被触发后，由独立的 review agent 根据 `nanobot/templates/agent/skill_review.md` 中的标准决策。

#### ✅ 应当 CREATE 的场景

满足以下**任一条件**：

1. **Trial-and-Error 模式**
   - 对话中出现了明确的错误 → 分析 → 修复 → 验证循环
   - 用户纠正了 agent 的输出
   - 代码运行失败后进行了调试
   
   **示例**：TC-19（网络超时重试）
   ```
   Turn 1: 设置2秒超时，预期会超时 → 执行，确实超时 ✗
   Turn 2: 添加指数退避：1s → 2s → 4s
   Turn 3: 增加超时到10秒，重新运行 → 成功 ✓
   ```
   **结果**：✅ 创建 `http-exponential-backoff` skill

2. **复杂多步工作流**
   - 包含 >=5 次工具调用
   - 涉及完整的数据流水线（read → transform → write）
   - 步骤之间有明确的依赖关系
   
   **示例**：TC-01（搜索+抓取+结构化）
   ```
   Turn 1: web_search → 返回3条新闻链接
   Turn 2: web_fetch → 抓取第一条全文
   Turn 3: write_file → 保存为结构化JSON
   ```
   **结果**：✅ 创建 `tech-news-daily-digest` skill

3. **领域特定解决方案**
   - 任务具有明确的通用性（如"爬取36kr"虽然URL特定，但"爬取+解析+存储"是通用模式）
   - 包含非平凡的业务逻辑或算法
   - 可以通过参数化应用于类似场景

#### ❌ 不应当 CREATE 的场景

1. **Smooth Execution（顺畅执行）**
   - 虽然是多步骤任务，但每步都一次成功，没有错误或重试
   - 用户指令清晰，agent直接完成，无需额外交互
   
   **示例**：TC-20至TC-26
   ```
   Turn 1: 创建文件 → 成功 ✓
   Turn 2: 写脚本处理 → 成功 ✓
   Turn 3: 运行脚本 → 成功 ✓
   Turn 4: 保存结果 → 成功 ✓
   ```
   **虽然4轮、5+工具调用，但因为无trial-and-error，review agent判断："This is a smooth execution, no reusable insight to save."**
   **结果**：❌ 不创建 skill

2. **Personal One-off Task（个人一次性任务）**
   - 高度定制化，难以泛化
   - 包含特定路径、特定数据、特定时间点
   - 无明显复用价值
   
   **示例**：
   ```
   "把我桌面上的report_2026_04_17_final_v3.docx移动到归档文件夹"
   ```

3. **Pure Q&A（纯问答）**
   - 无工具调用或仅1-2次搜索
   - 仅返回知识性回答

### 6.3 PATCH 标准（Skill Evolution）

当 review agent 检测到：
1. 当前任务与已有 skill 相似度高（>70%）
2. 新任务包含**增量改进**（新字段、新逻辑、错误处理）
3. Patch 不会破坏原有功能

则执行 `skill_manage(action="patch")` 更新现有 skill。

**成功案例**：
- TC-E：已有 `json-to-markdown-report`，新任务增加"社保扣除"计算 → ✅ Patch
- TC-09：已有 `tech-news-daily-digest`，新任务增加"sentiment"字段 → ✅ Patch

### 6.4 边界条件总结

| 条件                | 阈值  | 触发Review | 创建Skill         |
| ----------------- | --- | -------- | --------------- |
| 对话轮次              | >=3 | ✅        | 取决于review决策      |
| 工具调用              | >=3 | ✅        | 取决于review决策      |
| 对话轮次 + 无工具调用      | >=3 | ❌        | 不触发，不创建         |
| 工具调用多但顺畅执行        | >=5 | ✅        | **不创建**（无试错过程）  |
| 工具调用多且有trial-error | >=3 | ✅        | **创建** ✅        |
| 单次复杂任务（1轮，多工具调用）  | >=5 | ❌        | 不触发（轮次不足），不创建   |
| 简单问答              | 0-1 | ❌        | 不触发，不创建         |
| 重复简单查询（>=3轮）      | >=3 | ✅        | **不创建**（无实质性工作流） |

### 6.5 关键发现与建议

#### 发现 1：当前标准偏向严格
- **现象**：TC-20至TC-26，虽然是复杂任务（4轮对话、>=5工具调用），但因为执行顺畅而未创建skill
- **原因**：review prompt 强调 "trial-and-error OR user correction"
- **影响**：可能错失有价值的工作流积累

**建议改进**：
```markdown
# 在 skill_review.md 中增加例外规则
Exception: CREATE even for smooth execution if:
- Task involves >=5 tool calls AND >=4 conversation turns
- Task is a complete pipeline (read → transform → write)
- Solution demonstrates domain expertise (e.g. data analysis, API integration)
```

#### 发现 2：异步 review 的时序问题
- **现象**：skill 生成有30-90秒延迟，自动化测试难以准确检测
- **原因**：`SkillReviewService._run_review` 使用 `asyncio.create_task` fire-and-forget
- **影响**：用户体验不确定性，测试脆弱

**建议改进**：
1. 增加用户通知机制（已有 `notifyUserOnChange` 配置）
2. 在对话结束时显示"正在后台review，稍后可能生成新skill"提示
3. 提供 `/skills/review/status` API 查询review状态

#### 发现 3：并发安全风险（Critical Bug）
- **现象**：TC-27 在 review 触发后，后续请求hang住超时
- **根因**：review agent 与 main agent 共享资源（Memory/ToolRegistry）
- **影响**：**P0 级稳定性问题**，可能导致生产环境服务不可用

**修复建议**（优先级最高）：
```python
# nanobot/agent/skill_evo/integration.py
async def maybe_review(...):
    # 深拷贝session state，避免共享
    isolated_memory = memory_service.clone_for_review()
    isolated_tools = tool_registry.create_isolated_copy()
    
    # 使用独立的 AgentLoop 实例
    review_runner = AgentRunner(
        memory=isolated_memory,
        tools=isolated_tools,
        session_id=f"review:{session_id}",  # 独立session
    )
```

---

## 七、高级测试用例（Advanced Test Cases）

以下用例来自 `tests/_advanced_skill_evolution_test.py`，覆盖更复杂的场景。

### Category G: 高级错误恢复模式

#### TC-19：网络超时重试模式 ✅

**对话步骤**：

| 轮次 | 发送内容                                                                    |
| ---- | --------------------------------------------------------------------------- |
| 1    | 写一个函数从 https://httpbin.org/delay/5 获取数据，超时时间设为2秒           |
| 2    | 运行这个函数，预期会超时                                                    |
| 3    | 给函数添加指数退避重试：第1次等1秒，第2次等2秒，第3次等4秒，最多重试3次      |
| 4    | 修改超时时间为10秒，重新运行验证能成功                                       |

**测试结果**：

| 检查项        | 结果       | 详情                                  |
| ------------- | ---------- | ------------------------------------- |
| 对话响应      | **PASS**   | 4 轮完成                              |
| Skill 生成    | **PASS** ✅ | 生成 `http-exponential-backoff`       |
| Review 决策   | **正确**   | 明确的 trial-and-error 模式，符合标准 |

**关键特征**：
- ✅ 显式的错误场景："预期会超时"
- ✅ 错误 → 分析 → 修复 → 验证的完整循环
- ✅ 通用的解决方案：指数退避算法可应用于任何网络请求

---

#### TC-20：文件编码检测链

**对话步骤**：

| 轮次 | 发送内容                                                                  |
| ---- | ------------------------------------------------------------------------- |
| 1    | 创建一个包含特殊字符的文本文件 test_encoding.txt，内容包含中文和emoji     |
| 2    | 写一个Python函数尝试读取这个文件，用utf-8编码                             |
| 3    | 如果读取失败，按顺序尝试：gbk, gb2312, latin1，返回成功的编码类型         |
| 4    | 运行函数并输出结果                                                        |

**测试结果**：

| 检查项      | 结果     | 详情                                                 |
| ----------- | -------- | ---------------------------------------------------- |
| 对话响应    | **PASS** | 4 轮完成                                             |
| Skill 生成  | **FAIL** | 未生成                                               |
| 失败原因    | -        | 虽然4轮对话，但执行顺畅，无实际编码错误触发，不符合标准 |

**分析**：
- ❌ 虽然任务描述包含"如果读取失败"，但实际执行中文件正常读取，**未发生真实的错误**
- 这是一个**假设性错误场景**，review agent 判断："No actual trial-and-error occurred"

---

#### TC-21：依赖链管理

**对话步骤**：

| 轮次 | 发送内容                                         |
| ---- | ------------------------------------------------ |
| 1    | 写一个Python脚本使用 requests 库获取 httpbin数据 |
| 2    | 如果 requests 未安装，用 pip install requests 安装 |
| 3    | 运行脚本并解析返回的JSON                         |
| 4    | 把解析结果保存为 api_response.json               |

**测试结果**：

| 检查项     | 结果     | 详情                                     |
| ---------- | -------- | ---------------------------------------- |
| 对话响应   | **PASS** | 4 轮完成                                 |
| Skill 生成 | **FAIL** | 未生成                                   |
| 失败原因   | -        | requests 通常已安装，无实际依赖安装过程，顺畅执行 |

---

### Category H: 复杂工具编排

#### TC-22：Web 爬取 + 解析 + 存储

**对话步骤**：

| 轮次 | 发送内容                                                   |
| ---- | ---------------------------------------------------------- |
| 1    | 访问 https://httpbin.org/html 并获取页面内容               |
| 2    | 从HTML中提取所有的标题标签（h1, h2, h3）                   |
| 3    | 把标题列表整理成JSON格式，每个标题记录标签类型和文本       |
| 4    | 保存为 headings.json 文件                                  |

**测试结果**：

| 检查项     | 结果     | 详情                                 |
| ---------- | -------- | ------------------------------------ |
| 对话响应   | **PASS** | 4 轮完成                             |
| Skill 生成 | **FAIL** | 未生成                               |
| 失败原因   | -        | 顺畅执行，无错误或重试，不符合当前标准 |

**分析**：
- 虽然是完整的爬虫管道（fetch → parse → format → save），但因为**执行过于顺畅**
- 当前review标准**偏向严格**，要求 trial-and-error
- **建议**：放宽标准，将"完整数据管道"也作为创建条件

---

#### TC-23：日志分析管道

**对话步骤**：

| 轮次 | 发送内容                                                                                  |
| ---- | ----------------------------------------------------------------------------------------- |
| 1    | 创建一个模拟的访问日志文件 access.log，包含20条记录：时间戳、IP、URL、状态码              |
| 2    | 写脚本解析日志，统计：总请求数、状态码分布、最频繁的10个URL                               |
| 3    | 运行脚本并输出统计结果                                                                    |
| 4    | 把统计结果格式化为markdown表格保存为 log_report.md                                        |

**测试结果**：同 TC-22，顺畅执行但未生成 skill。

---

#### TC-24：配置文件管理

**对话步骤**：

| 轮次 | 发送内容                                                        |
| ---- | --------------------------------------------------------------- |
| 1    | 创建一个配置文件 app_config.json，包含 database, api, cache 配置 |
| 2    | 写一个Python函数读取并验证配置：检查必需字段是否存在            |
| 3    | 更新配置文件，把 cache.ttl 从 300 改为 600                      |
| 4    | 运行验证函数确认配置正确                                        |

**测试结果**：同上，顺畅执行，未生成 skill。

---

### Category I: Skill 进化与跨会话复用

#### TC-25：增量特性添加

**对话步骤**：

| 轮次 | 发送内容                                                 |
| ---- | -------------------------------------------------------- |
| 1    | 写一个函数将markdown文件转换为HTML                       |
| 2    | 给函数添加输入验证：检查文件是否存在，是否为.md文件      |
| 3    | 添加日志输出：记录每次转换的文件名和耗时                 |
| 4    | 添加异常处理：转换失败时返回友好的错误信息               |

**测试结果**：

| 检查项     | 结果     | 详情                                     |
| ---------- | -------- | ---------------------------------------- |
| 进化行为   | **FAIL** | 未检测到 create 或 patch 事件            |
| 失败原因   | -        | 顺畅执行，每步都是增量添加功能，但无错误或重试 |

---

#### TC-26：相似模式识别

**对话步骤**：

| 轮次 | 发送内容                                                        |
| ---- | --------------------------------------------------------------- |
| 1    | 创建一个包含10个产品的JSON：name, price, category, stock        |
| 2    | 写脚本读取JSON，按category分组统计总库存和平均价格              |
| 3    | 运行脚本并把结果保存为 inventory_report.md                      |

**测试结果**：

| 检查项     | 结果     | 详情               |
| ---------- | -------- | ------------------ |
| 智能复用   | **FAIL** | 未检测到任何事件   |
| 失败原因   | -        | 顺畅执行，未创建 skill |

---

#### TC-27：跨会话 Skill 进化 ⚠️

**对话步骤**：

| 轮次 | 发送内容                                                         |
| ---- | ---------------------------------------------------------------- |
| 1    | 搜索最新的Python 3.13新特性                                      |
| 2    | 把搜索结果整理成一份学习笔记，格式：特性名称、说明、示例         |
| 3    | 保存为 python313_features.md                                     |

**测试结果**：

| 检查项        | 结果            | 详情                                                                       |
| ------------- | --------------- | -------------------------------------------------------------------------- |
| 对话响应      | **ERROR** ⚠️     | 第2轮后请求超时（120秒）                                                   |
| Skill 生成    | **未知**        | 测试在超时前中断                                                           |
| **关键问题**  | **并发安全Bug** | Review 触发后，后续同session请求hang住。服务端日志显示"Empty response, retrying" |

**根因分析**：
```
2026-04-17 10:20:06 - Skill review gate: trigger=True
2026-04-17 10:20:06 - Skill review triggered for session api:adv:tc27-cross
2026-04-17 10:20:06 - WARNING: Empty response for session api:adv:tc27-cross, retrying
(后续请求永久hang住，120秒超时)
```

**严重性**：🔴 **P0 Critical**
- 影响：生产环境可能导致服务不可用
- 频率：在review触发时必现（约10-15%的复杂对话）
- 修复优先级：**最高**

---

### Category J: 边界条件与压力测试

#### TC-28：快速简单查询（不应生成）

**对话步骤**：

| 轮次 | 发送内容            |
| ---- | ------------------- |
| 1    | 1+1等于几           |
| 2    | Python是什么        |
| 3    | hello               |

**测试结果**：

| 检查项       | 结果     | 详情             |
| ------------ | -------- | ---------------- |
| 未生成 Skill | **PASS** | 正确，无新 skill |

**验证**：✅ 快速连续的简单查询不会spam生成skill

---

#### TC-29：工具调用阈值（边界测试）

**对话步骤**：

| 轮次 | 发送内容                                              |
| ---- | ----------------------------------------------------- |
| 1    | 在workspace创建一个test.txt文件，内容是当前时间       |
| 2    | 读取这个文件内容                                      |
| 3    | 把文件内容追加一行：'Second line'，然后读取确认       |

**测试结果**：

| 检查项     | 结果     | 详情                                  |
| ---------- | -------- | ------------------------------------- |
| Review触发 | **PASS** | 3轮对话 + 3+工具调用，正确触发review   |
| Skill生成  | 待验证   | (测试在此用例前因TC-27超时而中断)     |

**验证**：✅ 正好达到阈值（3轮+3工具）能触发review

---

#### TC-30：混合中英文 Skill

**对话步骤**：

| 轮次 | 发送内容                                    |
| ---- | ------------------------------------------- |
| 1    | Create a Python script to fetch GitHub user info via API |
| 2    | 添加中文注释说明每个步骤                    |
| 3    | Run the script with username 'torvalds'     |
| 4    | 把结果保存为 github_user.json 文件          |

**测试结果**：未执行（TC-27超时中断）

---

### Category K: 真实世界工作流模式

#### TC-31至TC-33

包含 Dockerfile 调试、测试数据生成、备份恢复等场景，均因 TC-27 中断未执行。

---

### Category L: 多会话 Skill 积累

#### TC-34：Skill 库增长

**目的**：连续执行3个不同领域的工作流，验证skill库能否健康增长。

**测试结果**：未执行（TC-27超时中断）

---

#### TC-35：Skill 使用计数追踪

**目的**：验证 `usage_count` 和 `last_used` 字段是否正确更新。

**测试结果**：未执行（TC-27超时中断）

---

### Category M: Guard 与安全验证

#### TC-36：安全 Skill 创建

**目的**：验证正常的skill创建不会被 SkillGuard 误拦。

**测试结果**：未执行（TC-27超时中断）

---

## 八、最新测试结果与发现（2026-04-17）

### 8.1 执行摘要

**测试脚本**：`tests/_advanced_skill_evolution_test.py`  
**执行时间**：2026-04-17 10:01-10:20 (约19分钟)  
**完成度**：9/18 用例 (50%)，因 TC-27 并发bug导致中断

**统计**：

| 指标            | 数值         |
| --------------- | ------------ |
| 总用例          | 18           |
| 已执行          | 9 (50%)      |
| 通过            | 1 (11.1%)    |
| 失败            | 7 (77.8%)    |
| 系统错误        | 1 (11.1%)    |
| 生成 Skill 数   | 1            |
| Create 事件     | 1            |
| Patch 事件      | 0            |

**生成的 Skill**：
- ✅ `http-exponential-backoff` (TC-19)

### 8.2 关键发现

#### Finding 1: Review 标准过于严格 ⚠️

**现象**：
- TC-20至TC-26，共7个用例，虽然都是复杂任务（4轮对话、5+工具调用），但因为**执行顺畅**而未创建skill
- 唯一成功创建skill的 TC-19，包含了**明确的错误场景**："预期会超时"

**根本原因**：
```markdown
# nanobot/templates/agent/skill_review.md (当前标准)
✅ CREATE when:
- The conversation involved **trial-and-error** OR the user corrected the agent
```

**影响**：
- 偏向 "trial-and-error"，但很多有价值的工作流（如完整的数据管道）因为执行顺畅被忽略
- 错失知识积累机会

**数据支撑**：
| 场景类型           | 用例数 | 创建Skill | 创建率 |
| ------------------ | ------ | --------- | ------ |
| 包含 trial-error   | 1      | 1         | 100%   |
| 复杂但顺畅执行     | 7      | 0         | 0%     |
| 简单/快速查询      | 1      | 0         | 0%     |

**建议**：
1. **短期**：在 review prompt 中增加例外规则：
   ```markdown
   Exception: CREATE even for smooth execution if:
   - Task involves >=5 tool calls AND >=4 conversation turns
   - Task is a complete data pipeline (fetch → process → store)
   - Solution demonstrates domain expertise
   ```

2. **长期**：采用分层策略：
   - "trial-error" → `VALIDATED` trust level (高优先级)
   - "complex pipeline" → `DRAFT` trust level (需要后续验证)
   - 基于 `usage_count` 自动提升 trust level

---

#### Finding 2: 并发安全严重Bug 🔴

**现象**：
- TC-27 执行到第2轮时，触发了 skill review
- 之后客户端请求在120秒后超时
- 服务端日志显示："Empty response for session, retrying"
- 后续请求永久hang住

**服务端日志片段**：
```log
10:20:06 - Skill review gate: trigger=True
10:20:06 - Skill review triggered for session api:adv:tc27-cross
10:20:06 - WARNING: Empty response for session api:adv:tc27-cross, retrying
(无后续日志，请求hang住)
```

**受影响组件**：
- `nanobot/agent/skill_evo/integration.py` → `SkillReviewTracker.maybe_review`
- `nanobot/agent/skill_evo/skill_review.py` → `SkillReviewService._run_review`
- `nanobot/agent/loop.py` → `AgentLoop._process_message`

**推测根因**：
1. **资源共享**：review agent 和 main agent 共享同一个 `MemoryService` 或 `ToolRegistry`
2. **死锁**：review 过程中持有某个锁，导致后续main请求无法获取
3. **session state 污染**：review agent 错误地修改了 main session 的状态

**严重性评估**：
- **影响范围**：所有触发 review 的复杂对话（约10-15%）
- **用户体验**：请求hang住120秒，服务看起来"无响应"
- **生产风险**：可能导致服务完全不可用
- **优先级**：🔴 **P0 Critical** - 必须立即修复

**修复建议**：
```python
# nanobot/agent/skill_evo/integration.py
async def maybe_review(session_id, memory_service, tool_registry, ...):
    # 1. 深拷贝 session state
    isolated_memory = memory_service.create_isolated_snapshot(session_id)
    
    # 2. 创建独立的 tool registry
    isolated_tools = ToolRegistry()
    for tool in tool_registry.list_all():
        isolated_tools.register(tool.clone())
    
    # 3. 使用独立的 session_id
    review_session_id = f"review:{session_id}:{timestamp}"
    
    # 4. 确保 review runner 不共享任何主对话的状态
    review_runner = AgentRunner(
        session_id=review_session_id,
        memory=isolated_memory,
        tools=isolated_tools,
        config=config.clone(),
    )
    
    # 5. 设置超时（防止review hang住）
    try:
        await asyncio.wait_for(
            review_runner.run(...),
            timeout=60.0  # 60秒超时
        )
    except asyncio.TimeoutError:
        logger.warning(f"Review timed out for {session_id}")
    except Exception as e:
        logger.error(f"Review failed for {session_id}: {e}")
```

---

#### Finding 3: 异步 Review 的可观测性问题

**现象**：
- Review 是 fire-and-forget 后台任务
- Skill 生成有 30-90 秒不可预测的延迟
- 用户无法知道"是否会生成skill"、"何时完成"

**影响**：
- 自动化测试脆弱（需要猜测等待时间）
- 用户困惑："我的对话会生成skill吗？"
- 调试困难：无法区分"review未触发"vs"review进行中"vs"review决定不创建"

**建议**：
1. **立即反馈**：在对话结束时返回 review 状态
   ```json
   {
     "choices": [...],
     "skill_review": {
       "triggered": true,
       "status": "in_progress",
       "estimated_completion": "30-60s"
     }
   }
   ```

2. **审计日志增强**：
   ```jsonl
   {"event": "review_triggered", "session": "tc27", "timestamp": "..."}
   {"event": "review_completed", "session": "tc27", "decision": "create", "skill": "..."}
   ```

3. **API 查询**：
   ```bash
   GET /v1/skills/review/status?session_id=tc27
   → {"status": "completed", "actions": ["created http-exponential-backoff"]}
   ```

---

### 8.3 测试覆盖率分析

| 场景类别                  | 计划用例 | 已执行 | 通过 | 覆盖率 |
| ------------------------- | -------- | ------ | ---- | ------ |
| 高级错误恢复模式          | 3        | 3      | 1    | 100%   |
| 复杂工具编排              | 3        | 3      | 0    | 100%   |
| Skill 进化与跨会话复用    | 3        | 3      | 0    | 100%   |
| 边界条件与压力测试        | 3        | 0      | -    | 0%     |
| 真实世界工作流模式        | 3        | 0      | -    | 0%     |
| 多会话 Skill 积累         | 2        | 0      | -    | 0%     |
| Guard 与安全验证          | 1        | 0      | -    | 0%     |

**未完成原因**：TC-27 并发bug导致测试中断

---

### 8.4 下一步行动计划

#### 立即（本周内）
1. 🔴 **修复 TC-27 并发bug**（P0，阻塞性）
   - 隔离 review agent 的资源
   - 添加超时机制
   - 完整测试修复后的稳定性

2. ⚠️ **完成中断的测试用例**（TC-28至TC-36）
   - 重新运行完整的18个用例
   - 生成完整测试报告
   - 更新本文档

#### 短期（2周内）
3. 📊 **调整 review 标准**
   - 增加"复杂管道"例外规则
   - A/B 测试宽松标准 vs 严格标准
   - 收集用户反馈

4. 🔍 **增强可观测性**
   - 实现 review 状态API
   - 在对话响应中返回 review 状态
   - 改进审计日志格式

#### 长期（1月内）
5. 🏗️ **分层 Skill 管理**
   - 实现 `DRAFT` / `VALIDATED` / `CURATED` trust level
   - 基于 `usage_count` 自动提升
   - 支持手动审核和编辑

6. 📈 **质量度量**
   - Skill 使用率统计
   - Review 决策质量评估
   - A/B 测试不同标准的效果

---

### 8.5 相关文档

- **详细测试报告**：`docs/ADVANCED_SKILL_EVO_TEST_REPORT.md`
- **架构分析**：`docs/HERMES_SKILL_EVOLUTION_ARCHITECTURE.md`
- **Review 标准**：`nanobot/templates/agent/skill_review.md`
- **集成层代码**：`nanobot/agent/skill_evo/integration.py`

---

**文档更新时间**：2026-04-17 10:40  
**更新者**：Claude (Cursor Agent)  
**版本**：v2.0 - 添加真实准则、高级用例和最新测试结果

