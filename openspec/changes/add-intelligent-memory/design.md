## Context（背景）

### 当前状态

nanobot 目前具有以下记忆相关组件：

- **会话历史**：`~/.nanobot/sessions/` 目录下的 JSONL 文件完整记录所有对话
- **长期记忆**：`~/.nanobot/workspace/memory/MEMORY.md` 文件，可被读取但无自动写入机制
- **每日笔记**：`~/.nanobot/workspace/memory/YYYY-MM-DD.md` 文件，存在但不会被自动创建或写入
- **MemoryStore 类**：提供了 `append_today()` 和 `get_memory_context()` 等方法，但这些方法从未被调用

### 约束

1. **架构约束**：必须与现有的 `AgentLoop`、`SessionManager` 和 `ContextBuilder` 集成
2. **性能约束**：总结操作不能阻塞主对话流程，应在后台或对话间隙执行
3. **存储约束**：继续使用现有的文件系统存储方式（JSONL 和 Markdown），不引入数据库
4. **依赖约束**：无新的外部依赖，仅使用现有的 LLM 提供商（LiteLLM）

### 利益相关者

- **最终用户**：希望无需手动干预即可获得智能记忆
- **开发者**：需要清晰的扩展点和最小化侵入性
- **系统**：保持代码简洁和可维护性

---

## Goals / Non-Goals（目标与非目标）

### Goals（目标）

1. ✅ 实现自动对话总结：在对话结束后自动生成每日概要
2. ✅ 智能信息提取：从对话中提取话题、用户偏好、重要决定、任务、技术问题
3. ✅ 结构化每日笔记：创建符合模板的 Markdown 格式概要文件
4. ✅ 智能长期记忆更新：基于重要性评分和去重机制更新 `MEMORY.md`
5. ✅ 可配置触发机制：支持基于消息数量的自动触发策略
6. ✅ 非阻塞式处理：总结操作不应影响主对话响应速度

### Non-Goals（非目标）

- ❌ 实现向量数据库或复杂检索系统（保持在文件系统存储）
- ❌ 实时总结对话中的每条消息（仅在对话间隙或结束后进行）
- ❌ 修改现有的会话存储格式（保持 JSONL 格式不变）
- ❌ 跨会话的连续对话状态跟踪（每条对话独立总结）

---

## Decisions（技术决策）

### 决策 1：模块化架构

**决策**：创建两个独立模块 - `ConversationSummarizer` 和 `MemoryUpdater`

**理由**：
- **关注点分离**：总结逻辑与记忆更新逻辑分开，符合单一职责原则
- **可测试性**：每个模块可独立单元测试
- **可复用性**：`MemoryUpdater` 也可用于其他场景（如手动更新记忆）

**替代方案**：
- 在 `AgentLoop` 中内联实现所有逻辑
  - ❌ 优点：代码集中，减少文件数量
  - ❌ 缺点：代码臃肿，难以测试和复用

### 决策 2：使用子代理进行总结

**决策**：创建总结任务时，使用现有的 `SubagentManager` 在独立的子代理上下文中执行

**理由**：
- **非阻塞**：主对话循环可以快速响应用户，不等待总结完成
- **成本优化**：总结任务可以使用更便宜的模型（如 deepseek/deepseek-chat），主对话使用高质量模型
- **灵活配置**：用户可通过配置或环境变量自定义总结使用的模型
- **错误隔离**：总结失败不影响主对话流程

**实现方式**：
```python
# 在 AgentLoop 中
# 1. 从环境变量读取总结模型（优先级：环境变量 > 配置文件 > 默认值）
SUMMARY_MODEL_ENV = "NANOBOT_SUMMARY_MODEL"
DEFAULT_SUMMARY_MODEL = "deepseek/deepseek-chat"

summary_model = os.getenv(SUMMARY_MODEL_ENV) or config.agents.summary_model or DEFAULT_SUMMARY_MODEL

async def _trigger_summary(self, session_key: str):
    summary_prompt = self._build_summary_prompt(today_messages)
    summary = await self.subagents.summarize(
        prompt=summary_prompt,
        model=summary_model  # 使用配置的便宜模型
    )
```

**配置方式**：

用户可通过以下方式配置总结使用的模型：

**方式 1：环境变量（推荐）**
```bash
export NANOBOT_SUMMARY_MODEL="deepseek/deepseek-chat"
```

**方式 2：配置文件**
```json
// ~/.nanobot/config.json
{
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5",
      "summaryModel": "deepseek/deepseek-chat"  // 新增配置项
    }
  }
}
```

**方式 3：配置对象扩展（推荐）**
```json
{
  "agents": {
    "summary": {
      "enabled": true,
      "model": "deepseek/deepseek-chat",        // 总结使用的模型
      "interval": 10,                        // 触发间隔（消息数）
      "maxTokens": 4000                       // 总结最大 token 数
    }
  }
}
```

**模型选择建议**：

| 用途 | 推荐模型 | 理由 |
|------|-----------|------|
| **总结任务** | `deepseek/deepseek-chat` | 便宜（¥0.001/M tokens），中文优秀 |
| **总结任务** | `google/gemini-1.5-flash` | 超快且便宜 |
| **总结任务** | `openai/gpt-4o-mini` | 平衡性能和成本 |
| **高质量总结** | `anthropic/claude-3.5-haiku` | 优秀的推理能力，相对便宜 |

**优先级顺序**：
```
1. 环境变量 NANOBOT_SUMMARY_MODEL（最高优先级）
2. 配置文件中的 agents.summary.model（专门用于总结）
3. 配置文件中的 agents.defaults.model（回退到主对话模型）
   - 这样可以确保总结使用的模型与用户在主对话中使用的模型一致
   - 例如：用户使用 anthropic/claude-opus-4-5，总结也使用同一模型
4. 默认值：deepseek/deepseek-chat
   - 仅当以上三个配置项都未设置时，才使用此默认值
```

### 决策 3：基于消息计数的触发机制

**决策**：实现基于消息数量的触发策略，而非时间或状态检测

**理由**：
- **简单可靠**：消息计数器容易维护和测试
- **可配置**：通过环境变量 `NANOBOT_SUMMARY_INTERVAL` 调整触发频率
- **避免误触发**：不会因长时间静默或网络问题意外触发

**触发规则**：
```python
# 默认：每 10 条用户消息后触发
DEFAULT_SUMMARY_INTERVAL = 10

# 可通过环境变量覆盖
interval = int(os.getenv("NANOBOT_SUMMARY_INTERVAL", DEFAULT_SUMMARY_INTERVAL))

# 在 session 中跟踪消息计数
if session.message_count % interval == 0:
    await self._trigger_summary(session.key)
```

### 决策 4：去重策略

**决策**：使用简单的字符串相似度（编辑距离）和关键词匹配进行去重

**理由**：
- **轻量级**：无需引入额外依赖（如 fuzzywuzzy）
- **足够准确**：对于文本记忆场景，简单的字符串匹配已够用
- **易于理解**：开发者可快速理解去重逻辑

**实现方式**：
```python
def deduplicate_with_memory(self, new_items: list[str]) -> list[str]:
    unique_items = []
    existing_content = self.memory.read_long_term()

    for item in new_items:
        # 如果相似度 > 0.8 或完全匹配，跳过
        if self._is_similar_to_existing(item, existing_content):
            continue
        unique_items.append(item)
    
    return unique_items
```

### 决策 5：重要性评分机制

**决策**：基于关键词和信号词进行简单的二元分类（重要 / 不重要）

**理由**：
- **避免复杂性**：不实现复杂的 NLP 模型或机器学习
- **可解释性**：用户可轻松理解为什么某条信息被记录
- **可调整性**：通过配置关键词列表让用户自定义

**评分规则**：
```python
def calculate_importance(self, info: str) -> int:
    score = 0

    # 用户明确要求记录
    if any(keyword in info.lower() for keyword in ["记住", "记录", "记住"]):
        score += 3

    # 配置信息
    if any(keyword in info.lower() for keyword in ["api", "配置", "密钥", "设置"]):
        score += 2

    # 用户偏好
    if any(keyword in info.lower() for keyword in ["喜欢", "偏好", "风格", "模型"]):
        score += 1

    # 技术问题解决方案
    if any(keyword in info.lower() for keyword in ["问题", "解决", "修复", "bug"]):
        score += 2

    # 阈值：>= 2 分为重要
    return score >= 2
```

---

## Risks / Trade-offs（风险和权衡）

### 风险 1：频繁总结导致的成本增加

**风险描述**：自动触发总结会增加 LLM 调用次数，提高 API 成本

**缓解措施**：
- [ ] 使用便宜的模型（如 deepseek/deepseek-chat）进行总结
- [ ] 设置合理的默认触发间隔（如 10 条消息）
- [ ] 避免重复总结同一天的内容（基于日期检查）
- [ ] 在环境变量中提供总成本预估（可选）

### 风险 2：信息提取准确性

**风险描述**：简单的关键词匹配可能误判或遗漏重要信息

**缓解措施**：
- [ ] 设计详细的总结提示词，明确要求提取的字段
- [ ] 在提示词中提供正例和反例
- [ ] 允许用户手动调整总结模板
- [ ] 未来可考虑使用更先进的 NLP 技术（作为可选升级）

### 风险 3：并发冲突

**风险描述**：多个并发会话可能同时触发总结，导致文件写入冲突

**缓解措施**：
- [ ] 使用异步文件操作和适当的锁机制
- [ ] 为每个会话的总结添加时间戳，合并同一天的多次总结
- [ ] 实现追加模式而非覆盖模式，保留多次总结的结果

### 风险 4：长期记忆膨胀

**风险描述**：频繁更新长期记忆可能导致文件过大，影响读取性能

**缓解措施**：
- [ ] 实现定期清理机制（如保留最近 N 条重要记录）
- [ ] 在 `MEMORY.md` 中使用结构化格式（如分类标记），便于清理
- [ ] 添加配置选项控制最大记忆条目数

### 权衡 1：简单性 vs 功能丰富性

**权衡**：
- **选择**：偏向简单实现（基于规则的重要性评分、简单的字符串匹配）
- **代价**：可能无法提取更复杂的语义信息

**说明**：第一阶段采用简单实现，确保稳定性和可理解性。如未来需要，可升级到更高级的 NLP 技术（如向量相似度、意图分类）。

### 权衡 2：自动化 vs 用户控制

**权衡**：
- **选择**：完全自动化（对话结束自动触发）
- **代价**：用户无法精确控制何时总结

**说明**：提供环境变量和配置选项，让高级用户可以：
- 调整触发间隔
- 禁用自动总结
- 手动触发总结（通过专门工具）

---

## Architecture（架构设计）

### 系统组件

```
┌─────────────────────────────────────────────────────────────┐
│                     AgentLoop                          │
│  ┌──────────────────────────────────────────────────┐  │
│  │ 对话循环（run, _process_message）            │  │
│  │                                        │  │
│  │  ┌──────────────────────────────────────┐    │  │
│  │  │ SessionManager                  │    │  │
│  │  │ - 管理会话历史                 │    │  │
│  │  │ - 返回最近 N 条消息             │    │  │
│  │  └──────────────────────────────────────┘    │  │
│  │                                        │  │
│  │  ┌──────────────────────────────────────┐    │  │
│  │  │ ConversationSummarizer  (新增)    │    │  │
│  │  │ - 提取话题、偏好、决定          │    │  │
│  │  │ - 生成结构化每日概要           │    │  │
│  │  └──────────────────────────────────────┘    │  │
│  │                                        │  │
│  │  ┌──────────────────────────────────────┐    │  │
│  │  │ MemoryUpdater  (新增)              │    │  │
│  │  │ - 评估信息重要性                │    │  │
│  │  │ - 去重和更新长期记忆            │    │  │
│  │  └──────────────────────────────────────┘    │  │
│  │                                        │  │
│  │  ┌──────────────────────────────────────┐    │  │
│  │  │ SubagentManager                  │    │  │
│  │  │ - 异步执行总结任务               │    │  │
│  │  └──────────────────────────────────────┘    │  │
│  └──────────────────────────────────────────────────┘  │
│                                              │
└─────────────────────────────────────────────────────┘

        触发条件
        ↓
┌─────────────────────────────────────────────────────┐
│        文件系统（FileSystem）                  │
│  ┌──────────────────┐  ┌──────────────┐   │
│  │ sessions/        │  │ memory/      │   │
│  │ cli_direct.jsonl  │  │ MEMORY.md    │   │
│  │ telegram_123.jsonl│  │ 2026-02-07.md│   │
│  └──────────────────┘  └──────────────┘   │
└─────────────────────────────────────────────────────┘
```

### 数据流

**正常对话流程**：
```
用户消息
   ↓
AgentLoop._process_message()
   ↓
构建上下文（读取历史、记忆、skills）
   ↓
调用 LLM
   ↓
返回响应给用户
   ↓
保存到会话历史
   ↓
检查触发条件（消息计数 % interval == 0?）
   ↓
  否 → 等待下一条消息
  是 → 触发异步总结
        ↓
        ConversationSummarizer.summarize_today()
                ↓
        读取当天会话历史
                ↓
        子代理调用 LLM 提取信息
                ↓
        MemoryUpdater.update_long_term()
                ↓
        评估重要性、去重
                ↓
        写入每日概要（memory/YYYY-MM-DD.md）
        写入长期记忆（memory/MEMORY.md）
```

### 模块接口

#### ConversationSummarizer

```python
class ConversationSummarizer:
    """对话总结器 - 提取和总结对话信息"""
    
    def __init__(self, workspace: Path, provider: LLMProvider)
    
    async def summarize_today(self) -> DailySummary:
        """生成今日对话概要"""
    
    def _extract_topics(self, messages: list[Message]) -> list[str]
    
    def _extract_preferences(self, messages: list[Message]) -> dict[str, str]
    
    def _extract_decisions(self, messages: list[Message]) -> list[str]
    
    def _extract_tasks(self, messages: list[Message]) -> list[str]
    
    def _extract_technical(self, messages: list[Message]) -> list[dict]
    
    def _format_daily_summary(self, summary: DailySummary) -> str
```

#### MemoryUpdater

```python
class MemoryUpdater:
    """记忆更新器 - 智能更新长期记忆"""
    
    def __init__(self, workspace: Path)
    
    def update_long_term(self, summary: DailySummary) -> None
        """根据概要更新长期记忆"""
    
    def _calculate_importance(self, info: str) -> int
    
    def _deduplicate_with_memory(self, new_items: list[str]) -> list[str]
    
    def _is_similar_to_existing(self, item: str, existing: str) -> bool
```

#### DailySummary（数据结构）

```python
@dataclass
class DailySummary:
    """每日概要数据结构"""
    date: str  # "2026-02-07"
    topics: list[str]  # 主要话题
    user_preferences: dict[str, str]  # 用户偏好
    decisions: list[str]  # 重要决定
    tasks: list[str]  # 待办事项
    technical_issues: list[dict]  # 技术问题 [{question, solution}]
    key_insights: list[str]  # 关键洞察
```

---

## Migration Plan（迁移计划）

### 部署步骤

1. **创建新模块**
   - [ ] 创建 `nanobot/agent/conversation_summarizer.py`
   - [ ] 创建 `nanobot/agent/memory_updater.py`
   - [ ] 实现数据结构类 `DailySummary`

2. **集成到 AgentLoop**
   - [ ] 修改 `nanobot/agent/loop.py`，导入新模块
   - [ ] 在 `__init__` 中初始化组件
   - [ ] 实现消息计数跟踪
   - [ ] 实现 `_trigger_summary()` 异步方法
   - [ ] 在 `_process_message()` 中添加触发逻辑

3. **配置支持**
   - [ ] 添加环境变量读取（`NANOBOT_SUMMARY_INTERVAL`）
   - [ ] 更新文档说明配置选项

4. **测试**
   - [ ] 编写单元测试（`tests/test_conversation_summarizer.py`）
   - [ ] 编写单元测试（`tests/test_memory_updater.py`）
   - [ ] 集成测试（模拟完整对话流程）
   - [ ] 性能测试（验证不阻塞主对话）

5. **文档更新**
   - [ ] 更新 `README.md` 添加自动记忆功能说明
   - [ ] 更新 `AGENTS.md` 添加相关指令
   - [ ] 添加示例每日概要模板

### 回滚策略

如遇到严重问题：
- [ ] 通过环境变量 `NANOBOT_AUTO_SUMMARY=false` 禁用功能
- [ ] 不删除现有文件（仅追加新内容）
- [ ] 保留手动记忆方式（用户仍可使用 `write_file` 工具）

---

## Configuration（配置）

### 环境变量配置

| 环境变量 | 类型 | 默认值 | 说明 |
|-----------|------|---------|------|
| `NANOBOT_SUMMARY_INTERVAL` | int | `10` | 每多少条用户消息后触发总结 |
| `NANOBOT_SUMMARY_MODEL` | string | `deepseek/deepseek-chat` | 总结任务使用的模型 |
| `NANOBOT_AUTO_SUMMARY` | bool | `true` | 是否启用自动总结功能 |

### 配置文件扩展

需要在现有 `~/.nanobot/config.json` 中添加新的配置对象：

```json
{
  "agents": {
    "summary": {
      "enabled": true,
      "model": "deepseek/deepseek-chat",
      "interval": 10,
      "maxTokens": 4000
    }
  }
}
```

**配置项说明**：

- **enabled**（bool，默认：`true`）：是否启用自动总结功能
  - `false`：禁用，仅可手动触发
  - `true`：启用，自动触发

- **model**（string，默认：`deepseek/deepseek-chat`）：总结使用的 LLM 模型
  - 优先级：环境变量 > 配置文件 > 默认值
  - 推荐模型：
    - `deepseek/deepseek-chat`：便宜，中文优秀（¥0.001/M tokens）
    - `google/gemini-1.5-flash`：超快，性价比高
    - `openai/gpt-4o-mini`：平衡性能和成本
    - `anthropic/claude-3.5-haiku`：优秀的推理，相对便宜

- **interval**（int，默认：`10`）：触发总结的消息间隔
  - 设置为 `1`：每条消息后总结（频繁，成本高）
  - 设置为 `10`：每 10 条消息后总结（推荐）
  - 设置为 `0`：禁用自动触发

- **maxTokens**（int，默认：`4000`）：总结任务的最大 token 数
  - 根据模型调整：小模型用 2000-4000，大模型用 8000+

### 优先级解析逻辑

```python
# 1. 检查环境变量
if os.getenv("NANOBOT_AUTO_SUMMARY", "true").lower() == "false":
    enabled = False
else:
    enabled = config.agents.summary.enabled or True

# 2. 读取总结模型（环境变量优先）
summary_model = (
    os.getenv("NANOBOT_SUMMARY_MODEL") or
    config.agents.summary.model or
    config.agents.defaults.model or
    "deepseek/deepseek-chat"
)

# 3. 读取触发间隔
summary_interval = int(
    os.getenv("NANOBOT_SUMMARY_INTERVAL") or
    config.agents.summary.interval or
    10
)
```

### 配置示例

#### 示例 1：完全禁用自动总结

**环境变量方式**：
```bash
export NANOBOT_AUTO_SUMMARY=false
```

**配置文件方式**：
```json
{
  "agents": {
    "summary": {
      "enabled": false
    }
  }
}
```

#### 示例 2：使用更便宜的模型

**环境变量方式**：
```bash
export NANOBOT_SUMMARY_MODEL="google/gemini-1.5-flash"
```

**配置文件方式**：
```json
{
  "agents": {
    "summary": {
      "model": "google/gemini-1.5-flash"
    }
  }
}
```

#### 示例 3：调整触发频率

**环境变量方式**：
```bash
export NANOBOT_SUMMARY_INTERVAL=5
```

**配置文件方式**：
```json
{
  "agents": {
    "summary": {
      "interval": 5
    }
  }
}
```

### 成本估算

不同配置下的预估成本（基于中文对话，每条消息约 200 tokens，总结约 1000 tokens）：

| 配置 | 总结频率 | 总结成本/天 | 主对话成本/天 | 总成本/天 |
|------|----------|-------------|-------------|-----------|
| 默认配置 | 每 10 条消息 | ¥0.01 | ¥0.20 | ¥0.21 |
| 频繁模式（interval=5） | 每 5 条消息 | ¥0.02 | ¥0.20 | ¥0.22 |
| 稀少模式（interval=20） | 每 20 条消息 | ¥0.005 | ¥0.20 | ¥0.205 |

**说明**：
- 主对话假设使用 `anthropic/claude-opus-4-5`（约 ¥0.02/M tokens）
- 总结假设使用 `deepseek/deepseek-chat`（约 ¥0.001/M tokens）
- 实际成本根据对话长度和模型价格会有所不同

### 配置验证

在启动时验证配置的有效性：

```python
def validate_summary_config(config: Config) -> list[str]:
    """验证总结配置，返回错误列表"""
    errors = []
    
    if config.agents.summary.enabled:
        # 验证模型名称格式（支持 4 级回退机制）
        summary_model = (
            config.agents.summary.model or
            config.agents.defaults.model or
            "deepseek/deepseek-chat"
        )
        if not summary_model or "/" not in summary_model:
            errors.append("summary.model 必须是有效的模型名称（如 'deepseek/deepseek-chat'）")
        
        # 验证间隔范围
        interval = config.agents.summary.interval or 10
        if interval < 0 or interval > 100:
            errors.append("summary.interval 必须在 0-100 之间")
        
        # 验证 token 范围
        max_tokens = config.agents.summary.max_tokens or 4000
        if max_tokens < 100 or max_tokens > 32000:
            errors.append("summary.maxTokens 必须在 100-32000 之间")
    
    return errors
```

---

## Open Questions（待解决问题）

1. **触发间隔优化**：默认 10 条消息是否合适？是否需要根据对话长度动态调整？

2. **总结提示词优化**：如何设计提示词以最大化提取准确性？是否需要提供示例？

3. **长期记忆清理**：是否需要实现定期清理机制？如何平衡记忆完整性和文件大小？

4. **多会话合并**：同一天有多个会话时，如何合并或标记多次总结？

5. **国际化支持**：总结模板是否需要支持多语言？默认使用中文还是根据对话语言检测？
