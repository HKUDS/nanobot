# docs/ 文档导航

├── project-structure.md
│   ├── 项目定位
│   ├── 目录结构
│   ├── 启动入口
│   ├── 核心模块及职责
│   ├── 主要调用关系 / 请求流 / 数据流
│   ├── Mermaid 架构图
│   ├── 行为控制层
│   ├── 运行图示
│   └── 建议阅读顺序
│   
├── project-commands.md
│   ├── 安装依赖
│   ├── 启动命令
│   ├── 开发模式命令
│   ├── 测试命令
│   ├── 构建命令
│   ├── lint / format 命令
│   └── 对话中的 Slash 命令
│   
├── code-principle.md
│   ├── 1. Slash 命令实现机制
│   ├── 2. CLI 命令实现机制
│   ├── 3. 核心循环实现机制
│   ├── 4. ExecTool：Shell 命令执行机制
│   └── 5. Heartbeat 心跳巡检机制
│   
├── code-snippets-study.md
│   ├── 使用规则
│   ├── 记录模板
│   ├── 说明
│   ├── 学习记录
│   ├── 记录 1：核心 agent 实现：`AgentLoop` 如何把消息变成回复
│   ├── 记录 2：`openai_codex_provider.py` 入门：文件作用与“类继承 + super()”
│   └── 记录 3：Slash 命令系统：`CommandRouter` 如何路由和分发对话中的命令
│   
└── codex-worklog.md
    ├── 记录模板
    ├── 工作记录
    ├── 记录 1：按用户要求把 `HKUDS/nanobot` 仓库复制到当前文件夹，创建并配置名为 `nanobot` 的 `conda` 环境，安装依赖，完成 Codex 登录，并把默认模型切换为 `gpt-5.4-mini` 后完成基础验证。
    ├── 记录 2：为仓库建立 Codex 工作记录机制，创建标准化任务日志模板，并写入第一条记录。
    ├── 记录 3：为仓库建立面向学习的文档结构，补充默认工作约定、项目结构说明和项目命令说明，并继续维护 Codex 工作记录。
    ├── 记录 4：按新的工作约定更新 `AGENTS.md`，并将 `docs/CHANNEL_PLUGIN_GUIDE.md` 全文改写为中文，继续维护工作记录。
    ├── 记录 5：将已生成的 `nanobot agent` / `nanobot gateway` 图以及 `gateway` 总图写入 `docs/project-structure.md`。
    ├── 记录 6：将对话中刚刚生成的“Channel -> Agent 消息流”图和“单条消息时序图”追加到 `docs/project-structure.md`。
    ├── 记录 7：把“会影响 agent 行为的 md”和“nanobot 的行为控制层”图与说明加入 `docs/project-structure.md`。
    ├── 记录 8：将“仓库自带的运行时文件”、“md 文件如何进入 prompt”以及“主 agent 如何 spawn 子 agent”三张图加入 `docs/project-structure.md` 的合适位置。
    ├── 记录 9：新增 `docs/code-snippets-study.md` 作为代码片段学习文档模板，并建立只在用户明确同意后才写入的工作方式。
    ├── 记录 10：按用户确认的最终版本更新根目录 `AGENTS.md`，把学习入口限定为用户创建的项目文档。
    ├── 记录 11：进一步补充 `AGENTS.md` 的代码学习规则，要求在指定代码内容时加入“代码解释”，以便判断是否写入 `docs/code-snippets-study.md`。
    ├── 记录 12：让 `AGENTS.md` 里的代码学习规则更强制一些，要求回答时默认给出少量源码片段并紧接解释。
    ├── 记录 13：将刚才讲解的核心 agent 代码内容整理进 `docs/code-snippets-study.md`，作为第一条正式学习记录。
    ├── 记录 14：按用户要求把核心代码片段补进 `docs/code-snippets-study.md`，并同步收紧 `AGENTS.md` 的学习规则。
    ├── 记录 15：修复 `docs/code-snippets-study.md` 中核心源码片段的截断问题，确保学习记录可直接阅读。
    ├── 记录 16：将“学习某个 Python 文件时先输出知识点清单”的规则补进 `AGENTS.md`，让后续学习流程更适合按知识点展开。
    ├── 记录 17：将 `openai_codex_provider.py` 的文件作用总结和“类继承与 super()”知识点讲解写入学习文档。
    ├── 记录 18：排查“飞书已配置但收不到消息”的原因，确认问题位于本地环境、网关启动还是飞书侧事件链路。
    ├── 记录 19：将前面对话中生成的 Feishu 群消息进入 session 图示写入 `docs/project-structure.md`，方便后续学习 `groupPolicy=mention/open` 的差异。
    ├── 记录 20：将前面对话中生成的 SkillHub CLI 安装路径和 `skillhub install ontology` 默认落盘位置图示写入 `docs/project-structure.md`。
    ├── 记录 21：在 Windows 环境中安装 SkillHub CLI，但暂不安装 `ontology` 等具体 skill。
    ├── 记录 22：通过 SkillHub CLI 为 `nanobot` 安装 `Self-Improving + Proactive Agent` 技能。
    ├── 记录 23：将本机已安装的 SkillHub CLI 包装成一个 `nanobot` 可识别的 workspace skill，方便后续直接通过 skill 指导 agent 搜索和安装 SkillHub 技能。
    ├── 记录 24：让 `nanobot` 重新切到当前有效的 Codex OAuth 登录态，解决 ChatGPT 工作空间变化后仍沿用旧认证缓存的问题。
    ├── 记录 25：将“普通消息进入 `nanobot` 时 system prompt 的真实组成图”写入 `docs/project-structure.md`，方便后续理解 bootstrap files、memory、always skill 和 skills summary 的装配关系。
    ├── 记录 26：核查本机 Apifox 是否命中过近期供应链风险指标，并结合官方公开信息判断当前版本风险状态。
    ├── 记录 27：按用户提供的 CSDN blog《Apifox 被投毒！你的 SSH 密钥正在被上传》的原始排查口径，重新核查本机 Apifox 风险状态。
    ├── 记录 28：讲解 Heartbeat 心跳巡检机制的设计原理，并将内容写入 `docs/code-principle.md`。
    ├── 记录 29：新增 PostToolUse hook，在每次完成小任务后自动追踪文件变更，经用户确认后写入 `docs/codex-worklog.md`。
    ├── 记录 30：将本机 `nanobot` 默认模型从智谱切换为 `OpenAI Codex OAuth`，并完成本地配置校验。
    ├── 记录 31：将本机 `nanobot` 的 Codex 默认模型切换为 `gpt-5.4-mini`。
    ├── 记录 32：将 `oauth-cli-kit` 的 Codex 缓存从失效 workspace 切回当前 Plus 账号，并验证 `nanobot` 可正常响应。
    └── 记录 33：使用 `skillhub` 安装 `model-deploy` skill 到当前 workspace，并确认可被 `SkillsLoader` 识别。
