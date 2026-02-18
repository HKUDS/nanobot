# OpenClaw 生态调研 — 原始项目、创始人动态与复刻全景

> 调研时间：2026-02-17
> 数据来源：GitHub、Reuters、TechCrunch、steipete.me、grigio.org 等

---

## 一、OpenClaw 原始项目

### 基本信息

| 项目             | 详情                                                                                     |
| ---------------- | ---------------------------------------------------------------------------------------- |
| **名称**         | OpenClaw（前身：Clawdbot → Moltbot → OpenClaw）                                          |
| **GitHub**       | [github.com/openclaw/openclaw](https://github.com/openclaw/openclaw)                     |
| **创始人**       | Peter Steinberger ([@steipete](https://github.com/steipete))，奥地利开发者，TU Vienna CS |
| **语言**         | TypeScript 84.2%, Swift 11.7%, Kotlin 1.6%, Shell, Go, Python 等                         |
| **Stars**        | **206,000+** (GitHub 历史增长最快：66 天从 9K → 195K，比 Kubernetes 快 18 倍)            |
| **Forks**        | 37,500+                                                                                  |
| **协议**         | MIT                                                                                      |
| **创建时间**     | 2025-11-24                                                                               |
| **最新版本**     | v2026.2.15                                                                               |
| **Contributors** | 370+                                                                                     |
| **Commits**      | 12,202+                                                                                  |

### 定位与核心能力

OpenClaw 定位是**本地运行的个人 AI 助手**，核心卖点：

- **多通道消息接入**：WhatsApp, Telegram, Slack, Discord, Google Chat, Signal, iMessage (BlueBubbles), Microsoft Teams, Matrix, Zalo, WebChat 等 **15+ 平台**
- **本地优先 (Local-first)**：数据在你自己的设备上，你完全拥有数据
- **Gateway 架构**：WebSocket 控制面 `ws://127.0.0.1:18789`
- **多 Agent 路由**：不同通道/账号可以路由到隔离的 agent
- **语音能力**：Voice Wake + Talk Mode (macOS/iOS/Android + ElevenLabs)
- **Live Canvas**：Agent 驱动的可视化工作区 (A2UI)
- **浏览器控制**：内置 Chrome/Chromium CDP 控制
- **配套 Apps**：macOS 菜单栏 app、iOS node、Android node
- **Skills 平台**：5,700+ 社区技能，ClawHub 分享
- **推荐模型**：Anthropic Claude Pro/Max (Opus 4.6)

安装命令：

```bash
npm install -g openclaw@latest && openclaw onboard --install-daemon
```

---

## 二、名字变迁史

| 时间       | 名字         | 原因                                    |
| ---------- | ------------ | --------------------------------------- |
| 2025-11    | **Clawdbot** | 初始名                                  |
| 2026-01-27 | **Moltbot**  | Anthropic 投诉商标侵权（太像 "Claude"） |
| 2026-01-30 | **OpenClaw** | 社区投票最终命名                        |

> 趣闻：团队放弃 @clawdbot Twitter 账号后，"Handle Snipers" 立刻抢注，骗子用它在 Solana 上发了假 CLAWD 代币。

---

## 三、创始人加入 OpenAI

- **2026-02-14**：Peter Steinberger [在博客宣布](https://steipete.me/posts/2026/openclaw)加入 OpenAI
- **Sam Altman 确认**：_"Peter Steinberger is joining OpenAI to drive the next generation of personal agents"_
- OpenClaw 移交给**开源基金会**，OpenAI 继续支持
- Reuters, TechCrunch, CNBC, Bloomberg, Mashable 等主流媒体均报道
- Reddit 上有人提到他曾在 Lex Fridman 播客说他在 OpenAI 和 Meta 之间纠结（Meta 之前收购了 Manus）
- 他每月在 OpenClaw 上亏损 $10K

---

## 四、复刻/衍生项目全景

### 4.1 核心复刻实现（完整重写/精简重写）

按 Stars 排序：

| #   | 项目                                                      | 语言        | Stars       | 特色                                                     | 状态     |
| --- | --------------------------------------------------------- | ----------- | ----------- | -------------------------------------------------------- | -------- |
| 1   | **[nanobot](https://github.com/HKUDS/nanobot)**           | Python      | **21,000+** | 港大 HKUDS 出品，~4,000 行，99% smaller，教学级          | 最火复刻 |
| 2   | **[PicoClaw](https://github.com/sipeed/picoclaw)**        | Go          | **14,000+** | $10 硬件，10MB RAM，1s 启动，RISC-V，中国 Sipeed 出品    | 活跃     |
| 3   | **[ZeroClaw](https://github.com/zeroclaw-labs/zeroclaw)** | Rust        | **10,400+** | <5MB RAM，<10ms 启动，22+ Provider，Harvard/MIT 学生     | 活跃     |
| 4   | **[NanoClaw](https://github.com/qwibitai/nanoclaw)**      | TypeScript  | **8,750+**  | Apple Containers 安全隔离，Anthropic Agents SDK，~500 行 | 活跃     |
| 5   | **[MimiClaw](https://github.com/memovai/mimiclaw)**       | C           | **2,170**   | ESP32-S3 嵌入式，$5 芯片，纯 C，无 OS，无 Linux          | 活跃     |
| 6   | **[TinyClaw](https://github.com/jlia0/tinyclaw)**         | Shell/TS/Py | **1,928**   | 多 Agent 多团队协作，400 行，Claude Code + tmux，自愈    | 活跃     |
| 7   | **[IronClaw](https://github.com/nearai/ironclaw)**        | Rust        | **1,909**   | NEAR AI 出品，专注隐私安全，Apache 2.0                   | 活跃     |
| 8   | **[Clawlet](https://github.com/mosaxiv/picoclaw)**        | Go          | **625**     | 单二进制，无依赖，内置 SQLite 向量搜索语义记忆           | 活跃     |
| 9   | **[MicroClaw](https://github.com/microclaw/microclaw)**   | Rust        | **168**     | 受 NanoClaw 启发，Telegram/Discord/Slack/飞书            | 活跃     |
| 10  | **[SafeClaw](https://github.com/princezuda/safeclaw)**    | Python      | **19**      | 零成本！无 LLM，纯规则引擎 + ML，无 prompt injection     | 新项目   |
| 11  | **[nano-claw](https://github.com/hustcc/nano-claw)**      | TypeScript  | 6           | nanobot 的 TS 移植版                                     | 小项目   |
| 12  | **[nanoClaw (ysz)](https://github.com/ysz/nanoClaw)**     | —           | —           | ~3,000 行，2 分钟安装                                    | 小项目   |
| 13  | **[aidaemon](https://github.com/davo20019/aidaemon)**     | Rust        | 3           | 后台守护进程，Telegram/Slack/Discord，MCP 集成           | 新项目   |

### 4.2 协调/编排层（多 Agent 系统）

| #   | 项目                                                                  | 语言       | Stars   | 特色                                                     |
| --- | --------------------------------------------------------------------- | ---------- | ------- | -------------------------------------------------------- |
| 1   | **[Clawe](https://github.com/getclawe/clawe)**                        | TypeScript | **205** | 多 Agent 协调系统，类似 Trello 管理多个 OpenClaw agent   |
| 2   | **[Claworc](https://github.com/gluk-w/claworc)**                      | TS/Go      | **35**  | OpenClaw 编排器，单 Web Dashboard 管理多实例，K8s/Docker |
| 3   | **[OpenPaw/OCMT](https://github.com/jomafilms/openclaw-multitenant)** | TypeScript | 12      | 多租户版 OpenClaw，容器隔离 + 加密 vault                 |

### 4.3 增强插件/扩展生态

| #   | 项目                                                                              | 语言       | Stars   | 特色                                                      |
| --- | --------------------------------------------------------------------------------- | ---------- | ------- | --------------------------------------------------------- |
| 1   | **[WebClaw](https://github.com/ibelick/webclaw)**                                 | TypeScript | **487** | 快速 Web 客户端，`npx webclaw` 一键启动                   |
| 2   | **[OpenClaw Supermemory](https://github.com/supermemoryai/clawdbot-supermemory)** | TypeScript | **375** | 长期记忆插件，云端用户画像                                |
| 3   | **[Unbrowse](https://github.com/lekt9/unbrowse-openclaw)**                        | TypeScript | **334** | 自学习 API 技能生成器，从浏览器流量反向工程 API           |
| 4   | **[Foundry](https://github.com/lekt9/openclaw-foundry)**                          | TypeScript | **162** | 自写 meta-extension，观察工作流自动生成新工具             |
| 5   | **[memsearch](https://zilliztech.github.io/memsearch/)** (Zilliz/Milvus)          | Python     | —       | OpenClaw 记忆架构移植为独立库，Markdown + Milvus 向量搜索 |
| 6   | **[PolyClaw](https://github.com/poly-mcp/PolyMCP)**                               | TypeScript | —       | PolyMCP 内的 OpenClaw 风格自主 Agent                      |

### 4.4 中文生态

| 项目                                                                           | 说明                                        |
| ------------------------------------------------------------------------------ | ------------------------------------------- |
| [OpenClaw 中文文档](https://openclaw.cc/)                                      | 官方级中文文档，适配企业微信/飞书/钉钉/微信 |
| [OpenClaw 中文社区](https://clawd.org.cn/)                                     | 社区站，含微信群                            |
| [OpenClaw 汉化版](https://github.com/MaoTouHU/OpenClawChinese)                 | CLI + Dashboard 全中文，每小时自动同步上游  |
| [OpenClaw 汉化版 #2](https://github.com/1186258278/OpenClawChineseTranslation) | 另一个汉化版                                |
| [openclawo.com](https://openclawo.com/)                                        | 中文安装指南站                              |
| [openclawi.com](https://openclawi.com/)                                        | 中文官网镜像                                |
| [阿里云部署教程](https://developer.aliyun.com/article/1711805)                 | 阿里云开发者社区教程                        |

### 4.5 资源汇总 Awesome Lists

| 项目                                                                              | Stars   |
| --------------------------------------------------------------------------------- | ------- |
| **[SamurAIGPT/awesome-openclaw](https://github.com/SamurAIGPT/awesome-openclaw)** | **612** |
| **[rohitg00/awesome-openclaw](https://github.com/rohitg00/awesome-openclaw)**     | 236     |

---

## 五、各实现横向对比

| 项目         | 语言       | 代码量   | RAM     | 启动速度 | 最低硬件      | 亮点                      |
| ------------ | ---------- | -------- | ------- | -------- | ------------- | ------------------------- |
| **OpenClaw** | TypeScript | 430K+ 行 | >1 GB   | >500s    | Mac Mini $599 | 原版，15+ 通道            |
| **nanobot**  | Python     | ~4K 行   | >100 MB | >30s     | ~$50 SBC      | 教学级，港大              |
| **PicoClaw** | Go         | 轻量     | <10 MB  | <1s      | $10 RISC-V    | 皮皮虾，我们走            |
| **ZeroClaw** | Rust       | 极轻     | <5 MB   | <10ms    | $10           | Harvard/MIT，22 providers |
| **NanoClaw** | TypeScript | ~500 行  | 轻量    | 快       | 普通机器      | Apple Containers 安全     |
| **MimiClaw** | C          | ~数千行  | KB 级   | 即时     | **$5 ESP32**  | 无 OS，最便宜             |
| **IronClaw** | Rust       | 中等     | 小      | 快       | 普通机器      | NEAR AI，隐私优先         |
| **SafeClaw** | Python     | 小       | 小      | 快       | 任意          | 无 LLM，零 API 费用       |
| **aidaemon** | Rust       | 小       | 小      | 快       | 任意          | 守护进程模式              |

### 生态分层

```
Original    — OpenClaw (430K 行，全功能)
Lightweight — nanobot / NanoClaw (~500-4K 行)
Tiny        — TinyClaw / Clawlet (几百行)
Micro       — MicroClaw / MimiClaw (嵌入式级)
Pico/Zero   — PicoClaw / ZeroClaw (极致性能)
Alternative — SafeClaw (无 LLM)、IronClaw (隐私)
Meta        — Clawe / Claworc (多 Agent 编排)
```

---

## 六、为什么选 nanobot 作为学习切入点

> 以下来自 session `ses_3913a27dfffe3dpt6SlSezT2bR` 中对"面向毕业设计 + 求职面试"场景的分析

### 核心理由

| 维度         | 为什么适合                                                                        |
| ------------ | --------------------------------------------------------------------------------- |
| **语言**     | Python — 2026 AI 岗面试的通用语言，不需要学新语言                                 |
| **代码量**   | ~3,700 行，一个人一周内可以逐行读完                                               |
| **出身**     | **港大 HKUDS 实验室**出品，天然带教学基因                                         |
| **Stars**    | 21K — 面试说"我深入研究了 GitHub 21K Stars 的项目"比说"我用了 OpenClaw"更有说服力 |
| **架构完整** | 麻雀虽小五脏俱全：Agent Loop → Tool Use → Memory → Channel → Scheduling 全覆盖    |

### 能覆盖的面试高频问题

1. **"Agent loop 是怎么工作的？"** — nanobot 核心循环清晰可见，不到 200 行
2. **"Tool calling 怎么实现？"** — 函数定义、schema 生成、LLM 调用、结果回注，完整链路
3. **"Agent 的 memory/context 怎么管理？"** — Markdown 文件持久化，上下文窗口裁剪
4. **"怎么接多个消息通道？"** — Channel adapter 模式，WhatsApp/Telegram 抽象层
5. **"Prompt injection 怎么防？"** — 对比 OpenClaw 的安全问题 (CVE-2026-25253) 和 nanobot 的设计取舍
6. **"为什么你不直接用 OpenClaw？"** — "430K 行太大，我选了 4K 行的精简实现，逐行读完后自己加了 XX 功能"

### 毕业设计方向建议

| 方向                                 | 难度   | 面试加分                |
| ------------------------------------ | ------ | ----------------------- |
| 加一个新 Channel（如飞书/钉钉）      | ⭐⭐   | 展示你理解 adapter 模式 |
| 实现 multi-agent 协作                | ⭐⭐⭐ | 2026 最火话题           |
| 加向量数据库做 RAG memory            | ⭐⭐⭐ | RAG 是面试必考          |
| 做安全分析 — prompt injection 攻防   | ⭐⭐⭐ | 安全意识加分            |
| 加 MCP (Model Context Protocol) 支持 | ⭐⭐⭐ | 展示你跟进最新标准      |
| 性能 benchmark：nanobot vs OpenClaw  | ⭐⭐   | 展示系统思维            |

### 不推荐的替代选项

| 项目                | 为什么不选                                   |
| ------------------- | -------------------------------------------- |
| PicoClaw / ZeroClaw | Go/Rust — 面试 AI 岗很少用，学新语言浪费时间 |
| NanoClaw            | TypeScript，500 行太少，做不出毕业设计的深度 |
| TinyClaw            | Shell 脚本为主，面试讲不出深度               |
| SafeClaw            | 无 LLM，学不到 agent 核心——和模型交互那部分  |
| MimiClaw            | C + ESP32 嵌入式，太偏门                     |

---

## 七、安全事件备忘

- **CVE-2026-25253**：OpenClaw 关键 RCE 漏洞，17,903 实例公网暴露
- 修复版本：v2026.2.2+
- 这个安全事件加速了轻量复刻的兴起 — 用户开始关注代码可审计性

---

## 八、总结

OpenClaw 是 2025 底到 2026 初最炸裂的开源项目之一：一个周末项目 → GitHub 史上增长最快的仓库 → 创始人被 OpenAI 招走 → 催生庞大的复刻生态。

**nanobot** 作为其中 Python 实现的教学级复刻，是理解 AI Agent 架构的最佳切入点 — 代码量刚好能读完，架构五脏俱全，有名校背书，社区活跃。
