# 项目规划总档案

## 0. 基线信息
- 唯一计划文件：`plan/mobile-testing-roadmap.md`
- 写入范围：本仓库内全部“计划 / 改进 / 更新”内容
- 更新策略：追加日志式（仅新增，不覆盖历史；除非明确要求“重写全档”）
- 时间标准：`Asia/Shanghai`
- 文档语言：中文
- 维护规则：
  - 所有后续计划类输出仅写入本文件的“## 2. 规划与改进记录（追加区）”
  - 严禁创建第二个计划文件
  - 若发生误写到其他 `plan/*.md`，在本文件追加纠偏记录并回归本文件维护

## 1. 当前架构梳理（初始）
### 1.1 启动装配链路（CLI / Gateway / Agent / Channel / Cron / Heartbeat）
- CLI 入口由 `nanobot/cli/commands.py` 负责，`gateway` 命令完成主服务装配。
- `gateway` 组装 `Config`、`MessageBus`、`AgentLoop`、`ChannelManager`、`CronService`、`HeartbeatService`。
- `agent` 命令支持单次会话和交互式会话；底层统一复用 `AgentLoop`。

### 1.2 MessageBus 与事件模型
- `InboundMessage` / `OutboundMessage` 定义了渠道消息的统一数据结构。
- `MessageBus` 使用异步队列解耦“渠道收发”和“Agent处理”，降低渠道实现耦合度。
- `session_key` 由 `channel:chat_id`（或 override）驱动，成为会话隔离核心键。

### 1.3 AgentLoop 与 ToolRegistry 执行闭环
- `AgentLoop` 是核心调度器：构建上下文 -> 调用模型 -> 执行工具 -> 汇总响应。
- `ToolRegistry` 管理工具注册、参数校验和执行；默认工具包括文件、命令、Web、消息、子代理、定时任务。
- 工具调用走迭代循环（直到无工具调用或达到上限），形成可组合任务执行能力。
- MCP 工具通过动态注册接入到同一工具平面，与内置工具并行可用。

### 1.4 Session / Memory / Skills 上下文组织
- `SessionManager` 负责 JSONL 会话落盘与缓存，历史按会话键隔离。
- `MemoryStore` 管理 `MEMORY.md`（长期）与 `HISTORY.md`（可检索日志），并提供会话压缩归档。
- `ContextBuilder` 组装系统提示（身份、模板文件、记忆、技能摘要）和用户消息。
- `SkillsLoader` 支持 builtin + workspace 技能并做按需加载，减少上下文膨胀。

### 1.5 Provider Registry 与 MCP 扩展位
- Provider 采用注册表模型（`ProviderSpec`），统一维护模型关键词匹配、环境变量、网关识别、前缀策略。
- `LiteLLMProvider` 负责多供应商统一调用；`OpenAICodexProvider` 走 OAuth Responses 路径。
- MCP 扩展由 `tools.mcpServers` 配置驱动，支持 stdio/HTTP 两种传输并自动发现远端工具。

### 1.6 当前瓶颈与风险点
- 全局处理锁：`AgentLoop` 在消息处理路径使用全局锁，限制高并发会话/多设备吞吐。
- 配置重复定义：`MatrixConfig` 在 `nanobot/config/schema.py` 中存在重复定义，后续演进易引发维护风险。
- 工具输出主要为文本形态，复杂测试产物（截图/视频/结构化报告）仍缺统一约定。

## 2. 规划与改进记录（追加区）
### 追加模板（后续每次新增一段）
`### [YYYY-MM-DD HH:mm Asia/Shanghai] <类型>：<标题>`

`背景`

`变更点`

`影响范围`

`后续动作`

### [2026-02-28 22:37 Asia/Shanghai] PLAN：统一规划文档机制建立
背景
- 需要将当前架构梳理先落盘，并建立后续计划内容单文件持续维护机制，避免分散在多个文档。

变更点
- 固定唯一文件路径：`plan/mobile-testing-roadmap.md`。
- 固定更新策略：追加日志式，仅在本文件追加，不覆盖既有历史。
- 固定写入范围：本仓库内全部计划/改进/更新内容统一写入本文件。
- 固定结构契约：本文件保持 4 个主区块并长期稳定。

影响范围
- 影响本仓库后续所有规划类文档产出流程。
- 约束协作方式：后续规划更新必须落在“## 2. 规划与改进记录（追加区）”。

后续动作
- 每次新计划先追加 `PLAN` 区块；若同任务有实施结果，再追加 `UPDATE` 区块记录偏差与结论。
- 若出现误写到其他 `plan/*.md`，在本文件追加纠偏记录，并停止使用其他计划文件。

### [2026-02-28 22:44 Asia/Shanghai] PLAN：手机 App 自动化测试（Maestro + MCP）首期落地
背景
- 目标是将 nanobot 从通用 Agent 演进到可执行移动端自动化测试，且优先复用官方生态工具，降低维护成本。

变更点
- 采用 Maestro 官方 MCP 能力作为首期执行引擎，不新增自研设备控制协议。
- 在 CLI 增加 `nanobot mobile setup/status`，降低初始化与排障门槛。
- 增加内置 `mobile-testing` skill，固化测试流程、产物规范与 MCP 工具使用方式。
- 在 README 增加移动自动化章节与命令入口，形成可复制的 onboarding 路径。

影响范围
- 影响 CLI 能力面（新增 `mobile` 命令组）。
- 影响技能体系（新增移动测试技能）。
- 影响文档与协作流程（移动测试从“方案”进入“可执行”状态）。

后续动作
- 补充端到端样例 flow（登录、核心路径 smoke）。
- 在后续迭代追加失败重试策略与结构化报告聚合逻辑。

### [2026-02-28 22:44 Asia/Shanghai] UPDATE：手机 App 自动化测试首期能力已实现
背景
- 需要把“Maestro + MCP”从建议变为仓库可直接使用的功能入口，并记录标准产物路径。

变更点
- 已新增 CLI：
  - `nanobot mobile setup`：创建 `mobile/*` 与 `reports/mobile/*` 目录、样例 flow、summary 文件，并注入 `tools.mcpServers.maestro` (`maestro mcp`)。
  - `nanobot mobile status`：查看移动测试目录和 maestro MCP 配置状态。
- 已新增技能：`nanobot/skills/mobile-testing/SKILL.md`。
- 已更新文档：
  - README 新增 “Mobile App Automation (Maestro)” 小节。
  - CLI Reference 新增 `nanobot mobile setup/status`。
  - `nanobot/skills/README.md` 新增 `mobile-testing` 条目。
- 已新增测试：`tests/test_mobile_commands.py`，覆盖 setup 初始化、保留已有配置、force 覆盖三类场景。

影响范围
- 本仓库已具备“移动自动化脚手架 + MCP配置 + 技能引导 + 基础测试”四件套。
- 仍需用户本机安装 Maestro CLI 并准备模拟器/真机环境。

后续动作
- 下一步可补 `mobile run` 批量执行与结果聚合命令，减少手工脚本粘合。
- 根据真实项目补全 flow 目录下的业务测试样例与失败归档策略。

### [2026-02-28 22:52 Asia/Shanghai] PLAN：补齐 mobile run 批量执行与结构化归档
背景
- 已完成移动自动化初始化与技能接入，但仍缺少统一执行入口，无法稳定产出 run 级别结构化报告。

变更点
- 新增 `nanobot mobile run` 命令用于批量执行 flow（默认 `mobile/flows/*.ya?ml`）。
- 每次执行生成唯一 `runId`，并把日志与 summary 写入 `reports/mobile/runs/<runId>/`。
- 同步刷新 `reports/mobile/summary-latest.json`，作为最近一次执行快照。
- 支持 `--flow`、`--suite`、`--platform`、`--continue-on-fail/--fail-fast` 参数。

影响范围
- 影响 CLI 移动自动化工作流，形成“setup -> run -> status”闭环。
- 影响后续 agent 报告与 CI 消费方式（可直接读取 summary json）。

后续动作
- 补充 `mobile run` 与 MCP 执行结果融合策略（统一汇总来源）。
- 增加对 screenshot/video 等非日志产物的自动归档策略。

### [2026-02-28 22:52 Asia/Shanghai] UPDATE：mobile run 已落地并完成测试补充
背景
- 需要把“可初始化”升级为“可批量执行 + 可持续归档”的可用状态。

变更点
- 已新增 `nanobot mobile run`：
  - 自动发现 flows（或通过 `--flow` 指定）。
  - 逐个执行 `maestro test <flow>` 并保存每个 flow 日志。
  - 生成 run 级 summary（包含 passed/failed/requested/executed 统计）。
  - 失败时返回非 0 退出码，支持 fail-fast。
- 已补充测试覆盖：
  - 全通过场景 summary 写入校验。
  - fail-fast 停止执行校验。

影响范围
- CLI 已具备移动自动化“初始化、执行、状态查询”基础能力。
- 产物标准路径与结构化 JSON 已可用于后续自动汇总/通知。

后续动作
- 继续迭代 `mobile run`，接入 screenshot/video 采集与失败关键帧索引。
- 按真实业务用例沉淀默认 flow 模板集。

### [2026-02-28 22:53 Asia/Shanghai] UPDATE：mobile run 增强为每 flow 独立 Maestro 产物目录
背景
- 初版 `mobile run` 已有日志与 summary，但需要把 Maestro 原生产物（截图/调试信息）纳入统一归档。

变更点
- `mobile run` 执行时为每个 flow 注入 `--test-output-dir`，路径为：
  - `reports/mobile/artifacts/<run-id>/<flow-id>/`
- `summary-latest.json` 中 `flows[]` 新增 `artifactDir` 字段。
- `summary-latest.json` 中 `artifacts[]` 新增 `maestro-output-dir` 类型条目。
- README 与 `mobile-testing` skill 已同步更新产物路径说明。

影响范围
- 失败排查可直接定位到单 flow 的 Maestro 产物目录。
- 后续接 CI 时可无缝收集 run 级别截图与调试证据。

后续动作
- 下一步可增加失败时的关键截图索引（例如最后一帧截图路径）到 summary。

### [2026-02-28 23:06 Asia/Shanghai] PLAN：mobile run 接入 MCP 执行模式与自动降级
背景
- 当前 `mobile run` 仅本地 subprocess 调用 Maestro CLI，尚未直接复用已配置的 MCP 工具平面。

变更点
- 为 `mobile run` 增加 `--mode auto|local|mcp` 与 `--mcp-server` 参数。
- 新增 MCP 执行分支：连接指定 MCP server，优先调用 `run_flow_files` / `run_flow`。
- `auto` 模式在 MCP 失败时自动降级到本地 `maestro test`，减少执行中断。
- summary 新增执行元数据：`executionMode` 与 `mcpServer`。

影响范围
- 统一 CLI 与 Agent 在 Maestro 能力上的执行路径，降低后续维护分叉。
- 提升可用性：MCP 不稳定时仍可自动回退本地模式。

后续动作
- 对接设备选择（device id）与并行执行策略，补充更细粒度重试。

### [2026-02-28 23:06 Asia/Shanghai] UPDATE：mobile run 已支持 MCP/Local 双执行链
背景
- 需要把移动自动化执行层升级为“优先 MCP，可自动回退”的可运行机制。

变更点
- CLI 已新增：
  - `--mode auto|local|mcp`
  - `--mcp-server <name>`
- 已新增 MCP 执行逻辑：
  - 自动选择 `mcp_<server>_run_flow_files` 或 `mcp_<server>_run_flow`
  - 按工具 schema + 常见字段构造多组 payload 候选并执行
  - 失败时记录 payload 与工具返回内容到 run log
- 已实现 auto 模式回退：
  - MCP 失败时自动切回本地 `maestro test --test-output-dir ...`
- summary 已新增：
  - `executionMode`（mcp/local）
  - `mcpServer`（mcp 模式下记录 server 名称）

影响范围
- `mobile run` 可在无缝模式下接入 Maestro MCP，满足“Agent/MCP 优先”的方向。
- 运行结果与归档格式保持兼容，便于后续 CI 与通知模块消费。

后续动作
- 下一步建议补充 `--device-id` 参数与 MCP payload 设备路由，完成多设备调度闭环。

### [2026-02-28 23:27 Asia/Shanghai] PLAN：补充 Telegram 文本指令直连移动测试快捷链路
背景
- 当前“通过 Telegram 自然语言触发移动测试”仍依赖 LLM 规划与工具调用，在模型不可用或受限环境下无法稳定验证端到端链路。

变更点
- 在 `AgentLoop` 增加移动测试快捷意图识别：命中“打开<appId> + 转账/transfer/send”时不走 LLM。
- 直接生成临时 Maestro flow（启动 App -> 点击转账 -> 断言资产选择弹窗）并执行。
- 将执行日志和产物继续落到 `workspace/reports/mobile/*`，保持已有归档契约。

影响范围
- 影响 `agent/gateway` 消息处理分支：新增 deterministic 快捷路径。
- 对 Telegram、CLI 等同一 Agent 消息面生效（统一入口）。

后续动作
- 扩展更多自然语言模板（如“进入收款页”“打开市场页”）并固化到同一快捷路由。
- 后续结合 MCP 设备路由增强多设备执行策略。

### [2026-02-28 23:33 Asia/Shanghai] UPDATE：Telegram 指令等效链路已落地并在 Android 模拟器验证通过
背景
- 需要验证“用户下发测试语句 -> nanobot 执行模拟器自动化 -> 返回结果与产物路径”是否可运行。

变更点
- 已实现代码：
  - `nanobot/agent/loop.py` 新增移动测试快捷意图识别与执行逻辑。
  - 快捷执行自动生成 flow：`mobile/flows/generated/intent-*.yaml`。
  - 快捷执行自动落盘日志/产物到 `reports/mobile/runs/*` 与 `reports/mobile/artifacts/*`。
- 已新增测试：
  - `tests/test_mobile_shortcut.py` 覆盖意图识别、快捷分支绕过 provider、非快捷消息回落 provider。
- 已完成实机验证（Android Emulator）：
  - 指令：`打开im.token.app，进入转账页面`
  - 关键日志：`Launch app -> Assert FunctionBar.转账 -> Tap -> Assert TokenSelectModal.TokenSymbol.ETH` 全部 `COMPLETED`。
  - 产物示例：
    - `reports/mobile/runs/intent-20260228-233136-im-token-app/transfer.log`
    - `reports/mobile/artifacts/intent-20260228-233136-im-token-app/transfer/2026-02-28_233137/*`
  - `mobile run` 复验通过：`suite=telegram-e2e`，`Passed=1, Failed=0`。

影响范围
- 在 Telegram 频道消息进入 Agent 后，可直接触发移动测试快捷执行，不再强依赖 LLM 可用性。
- 提升了“自然语言到移动自动化执行”的可验证性与稳定性。

后续动作
- 下一步建议补 `intent -> flow` 的可配置映射文件，避免快捷模板硬编码在 `AgentLoop`。
- 结合频道侧指令权限（`allowFrom`）与审计日志，补充生产场景安全约束。

### [2026-02-28 23:38 Asia/Shanghai] UPDATE：按约束优化为“默认模型 + 非 dump 快捷执行 + 懒连接 MCP”
背景
- 需要遵循执行约束：模型走 config 默认配置；明确指令不做页面布局 dump；并优化当前不合理开销（如无必要的 MCP 启动、workspace 可见性不足）。

变更点
- 保持模型策略：快捷分支不覆盖模型配置，继续使用 config 默认模型配置。
- 执行策略优化：
  - 快捷分支不再依赖布局 dump，直接基于明确意图（如“转账”）执行固定元素断言（`FunctionBar.转账`、`TokenSelectModal.TokenSymbol.ETH`）。
  - `AgentLoop` 改为懒连接 MCP：仅在真正需要进入 LLM/工具循环时连接，快捷分支直接绕过。
- 可观测性优化：
  - `nanobot mobile status` 新增 `Config` 路径与 `Workspace scope` 提示，便于快速识别 config/workspace 位置关系。

影响范围
- 降低明确测试指令的执行延迟与失败面。
- 避免不必要的 MCP 启动噪声，提升 Telegram/CLI 快捷场景稳定性。
- 改善多工作目录下的配置定位可维护性。

后续动作
- 后续将 `intent -> flow` 规则外置配置化，减少 `AgentLoop` 中硬编码。
- 评估补充 `--workspace` 临时覆盖参数，进一步增强多项目切换体验。

### [2026-02-28 23:44 Asia/Shanghai] UPDATE：远端回执脱敏，禁止向 Telegram 暴露本地目录结构
背景
- 用户要求测试完成后不得向远端 Telegram 返回本机目录结构（绝对路径）。

变更点
- `AgentLoop` 的移动快捷执行接口新增 `expose_paths` 开关。
- 在消息分支中按渠道控制：
  - `telegram` 等远端渠道：`expose_paths=False`，仅返回 `runId`、状态与脱敏说明。
  - `cli/system` 本地渠道：`expose_paths=True`，保留本地 flow/log/artifact 路径便于调试。
- 失败/超时场景同样脱敏：远端不再附带可能包含路径的原始输出 tail。
- 测试补充：
  - `tests/test_commands.py` 新增 `telegram` 与 `cli` 两种渠道参数传递断言。

影响范围
- 远端聊天渠道（重点 Telegram）不再接收到本地文件系统结构信息。
- 本地 CLI 调试能力不受影响，仍可直接定位日志和产物路径。

后续动作
- 可进一步把该策略提升为全局“远端消息路径脱敏”中间层，覆盖更多工具输出场景。

### [2026-02-28 23:55 Asia/Shanghai] UPDATE：修复“选择ETH卡住”，改为按指令动态生成 Maestro 脚本
背景
- 用户反馈指令“打开im.token.app，进入转账页面，选择ETH”在“选择ETH”步骤卡住。
- 根因是快捷链路此前只固定执行到“进入转账弹窗”，未根据指令追加“选择代币”的点击步骤。

变更点
- `AgentLoop` 新增“指令分段解析 -> 动作映射 -> flow 动态生成”逻辑，不再只用固定脚本。
- 支持从文本提取选择动作：
  - 中文：`选择ETH` / `选中ETH` / `切换到ETH`
  - 英文：`select ETH` / `choose ETH` / `pick ETH`
- 当指令包含 `选择<token>` 时，自动写入并执行以下动态步骤：
  - `assertVisible TokenSelectModal.TokenSymbol.<TOKEN>`
  - `tapOn TokenSelectModal.TokenSymbol.<TOKEN>`
- 新增测试覆盖：
  - 动态 flow 内容断言（包含 token 相关步骤）
  - 快捷分支调用参数断言（instruction 直传）

影响范围
- 快捷链路已从“半固定模板”升级为“按用户指令生成脚本”。
- 对“进入转账页面，选择ETH/USDT...”这类明确指令可直接执行对应动作，避免停在弹窗。

后续动作
- 可继续扩展动作词典（如“选择网络”“输入地址”“输入金额”“点击下一步”）并保持同一动态生成框架。

### [2026-03-01 00:41 Asia/Shanghai] UPDATE：语义到 Maestro 命令映射增强（含 `takeScreenshot`）+ 失败检测与超时进度
背景
- 用户要求语义动作必须映射到 Maestro 官方可用命令（参考 docs commands available），并且执行期需可见失败与超时，不可“长时间无反馈”。

变更点
- 动态脚本生成升级为“分段语义解析 -> 动作映射 -> YAML 命令输出”：
  - `进入转账页面` -> `assertVisible` + `tapOn`（`FunctionBar.转账`）
  - `选择ETH/USDT...` -> `assertVisible` + `tapOn`（`TokenSelectModal.TokenSymbol.<TOKEN>`）
  - `截图` -> `takeScreenshot`（如 `- takeScreenshot: shot-01`）
  - `返回` -> `back`
- 执行期可观测性增强：
  - 新增进度消息：脚本生成完成、开始执行、失败原因、完成状态。
  - 新增失败原因分类：无设备/应用启动失败/断言失败/超时/通用失败。
  - 新增快捷执行超时控制：默认 `120s`，超时会主动 kill 子进程并回报。
- 远端回执仍保持脱敏策略：Telegram 返回 `runId + reason`，不返回本地路径。

影响范围
- Telegram 指令如“打开im.token.app，进入转账页面，选择ETH，截图”会生成包含 `takeScreenshot` 的脚本，不再停留在固定模板。
- 用户在执行过程中可收到中间状态，定位卡住点不再依赖等待最终超时。

后续动作
- 扩展更多语义动作映射（如输入地址、输入金额、下一步确认）并保持与 Maestro 命令集合对齐。

### [2026-03-01 00:52 Asia/Shanghai] UPDATE：修复“执行完成但 Telegram 无回执”通知可靠性
背景
- 用户反馈某些场景下 app 自动化已执行完成，但 Telegram 未收到“完成通知”。

变更点
- 快捷链路新增“完成通知兜底”：
  - 任务结束后无论成功/失败，先发送一条短 completion 消息（成功/失败 + runId [+ reason]）。
  - 对远端渠道（如 Telegram）完成消息由快捷分支直接入总线发送，避免仅依赖 return 路径。
- Telegram 发送可靠性增强：
  - 文本发送失败时新增三级降级：HTML -> Plain(with reply) -> Plain(without reply)。
  - 如果文本块发送失败会抛错给上层，触发 ChannelManager 重试。
- ChannelManager 新增 outbound 发送重试：
  - 每条消息最多 3 次退避重试（0.5s / 1.0s / 1.5s）。

影响范围
- 用户在 Telegram 端可稳定收到“任务已结束（成功/失败）”通知，不再出现长时间无完成回执。
- 临时网络抖动或 reply 参数异常时，消息投递成功率提升。

后续动作
- 可进一步增加“完成通知 ACK 观测指标”（成功率、重试次数、失败分布）用于生产监控。

### [2026-03-01 01:00 Asia/Shanghai] UPDATE：修复失败误判“应用启动失败”并完善地址/输入语义解析
背景
- 用户反馈指令已进入转账页面，但 Telegram 回执错误标记为“应用启动失败”。
- 复盘 run `intent-20260301-005535-im-token-app` 日志后确认真实失败为：
  - `Assert that id: TokenSelectModal.TokenSymbol.ETHEREUM is visible... FAILED`
  - 即中途断言失败，而非 app launch 失败。

变更点
- 失败分类器从“宽匹配”改为“步骤级匹配”：
  - 仅当 `Launch app ... FAILED` 或 `Unable to launch app` 才判定启动失败。
  - 断言失败/点击失败/输入失败分别给出独立 reason，并附失败步骤详情。
- 语义解析增强，避免误把“选择Ethereum地址”当成代币选择：
  - `选择<token>` 仅在非“地址”语境下映射为 `TokenSelectModal.TokenSymbol.<TOKEN>`。
  - 新增 `选择Ethereum地址` -> `tapOn text: "Ethereum"`。
  - 新增 `输入0x...` -> `inputText: "0x..."`。

影响范围
- Telegram 失败通知 reason 将更准确反映真实失败步骤，避免“已进入页面却报启动失败”的错误提示。
- 复合指令（选择代币 + 选择地址 + 输入 + 截图）的脚本生成语义更贴近用户意图。

后续动作
- 继续扩展地址字段定位策略（text/id 双通道）以提升不同语言和版本 UI 兼容性。
