# QuantBot 补充设计文档 v2.1
## 策略生命周期 · 持续学习机制 · 用户交互流程

> 本文档是《QuantBot 设计文档 v1.2》的补充，专门解决三个核心问题：
> 1. 策略修改/并行/主动进化的细节决策机制
> 2. 收盘后复盘、量化社区学习、研报阅读的实现方式
> 3. 用户需求引导流程与系统整体工作节奏
>
> **v2.1 更新**：统一搜索入口改为 `multi-search-engine` Skill；Cron 任务修正为"触发自然语言任务"而非"执行固定代码逻辑"；"确认优先"原则与通用智能设计对齐。

---

## 目录

- [一、策略生命周期管理（核心设计决策）](#一策略生命周期管理核心设计决策)
- [二、"确认优先"交互原则](#二确认优先交互原则)
- [三、持续学习机制](#三持续学习机制)
- [四、用户引导入门流程（Onboarding）](#四用户引导入门流程onboarding)
- [五、系统工作节奏总览](#五系统工作节奏总览)

---

## 一、策略生命周期管理（核心设计决策）

这是 QuantBot 最需要想清楚的设计问题。以下逐一给出明确答案。

---

### 1.1 策略修改后：替代 还是 并行？

**答：始终并行，永不覆盖，由用户决定是否"升代"。**

**设计理由：**
- 回测好不等于实盘好；修改后的策略 v2 可能在特定市场环境下退化
- 保留原版策略是比较和追溯的唯一依据
- 用户需要看到"改进了多少"才有置信度

**实现方式——Git 管理的策略仓库：**

所有量化策略统一存放在一个 Git 仓库中，用 **Git 分支和 commit 记录**替代手动的版本号目录，天然支持版本回退、修改对比、并行测试。

```
~/.nanobot/strategies/          ← Git 仓库根目录（git init）
│
├── active/                     ← 当前主力策略（main 分支）
│   ├── north_momentum.py       ← 无版本号，git log 查历史
│   ├── earnings_surprise.py
│   └── README.md               ← 策略总览索引（含当前绩效快照）
│
├── experimental/               ← 实验中策略（单独 feature 分支）
│   └── north_momentum_v4_candidate.py
│
├── backtest_results/           ← 回测结果归档（不纳入 git，.gitignore）
│   └── 2026-03/
│       └── north_momentum_20260307.json
│
└── .gitignore                  ← 忽略大数据文件和回测缓存
```

**Git 工作流约定：**

```
策略修改流程（QuantBot 操作 Git）：

1. 学习/优化阶段（静默执行）
   git checkout -b candidate/north-momentum-v4
   # ... 修改策略代码 ...
   git commit -m "feat: 加入震荡市过滤条件（来源：聚宽xxx策略）"
   # 执行回测，对比结果

2a. 回测有提升 → 告知用户，等待确认
    用户确认后：
    git checkout main
    git merge candidate/north-momentum-v4
    git commit -m "strategy: north_momentum 更新至 v4，夏普 1.2→1.5"
    git branch -d candidate/north-momentum-v4

2b. 回测无提升 → 静默归档学习，不合并
    git checkout main
    git branch -m candidate/north-momentum-v4 archive/north-momentum-v4-rejected
    # 保留分支以备日后参考，不合并进 main

3. 用户想查看历史
   git log --oneline active/north_momentum.py   # 查看该策略所有变更
   git diff HEAD~2 HEAD active/north_momentum.py # 对比两个版本的代码差异
   git checkout <commit-hash> active/north_momentum.py  # 回退到某个版本
```

**每次 commit 的消息规范：**

```
类型前缀：
  feat:     新增策略逻辑或因子
  fix:      修正策略 bug 或参数错误
  optimize: 参数优化（需附上回测指标变化）
  learn:    从外部学习吸收的改进（需注明来源）
  revert:   回退到历史版本

示例：
  feat: 加入北向资金连续流入过滤条件
  optimize: 均线周期 20→15，夏普 1.1→1.3（样本外验证）
  learn: 借鉴聚宽「月末效应」策略，加入节前日历过滤（来源：joinquant.com/xxx）
  revert: 回退震荡过滤条件，近30日实盘表现弱于原版
```

**Git 辅助工具封装：**

```python
# 文件：nanobot/agent/tools/strategy_git.py

class StrategyGitTool(Tool):
    """
    量化策略 Git 版本管理工具
    QuantBot 通过此工具完成策略的提交、分支、合并、回退
    """
    name = "strategy_git"
    REPO_PATH = "~/.nanobot/strategies"

    def execute(self, action: str, **kwargs):
        """
        action 支持：
          commit     提交当前策略变更（需提供 message）
          branch     创建候选分支（需提供 branch_name）
          merge      合并候选分支到 main（需用户确认后才调用）
          log        查看某策略文件的修改历史
          diff       对比两个版本的代码差异
          checkout   回退到指定 commit（需用户确认后才调用）
        """
        pass
```

**关键原则：`candidate/` 分支同类策略最多保留 2 个并行测试**，`archive/` 分支长期保留供学习参考。

---

### 1.2 每次修改都需要回测验证吗？

**答：是的，但区分"快速验证"和"完整回测"两档。**

```
修改类型                快速验证（1-3分钟）    完整回测（10-30分钟）
─────────────────────────────────────────────────────────────────
参数微调（均线周期）     ✅ 优先                 仅在快速验证通过后
新增一个过滤条件         ✅ 优先                 通过后执行
更换核心逻辑/因子        ❌ 跳过               ✅ 直接完整回测
跨市场适用性验证         ❌ 跳过               ✅ 直接完整回测
```

**快速验证定义：**
- 数据范围：最近 1 年（而非完整 5 年）
- 省略 Qlib ML 模型训练，直接用规则信号
- 仅报告：夏普比率、最大回撤、交易次数
- 目的：快速排除明显无效的修改方向

**快速验证通过标准（可由用户在 onboarding 时设定）：**
- 夏普 > 用户设定阈值（默认 0.8）
- 最大回撤不比原版策略扩大超过 5%
- 交易次数在合理范围（避免频繁交易磨损）

---

### 1.3 QuantBot 何时主动提出修改策略？

**答：有 4 类触发条件，但所有主动修改提案都需用户确认后才执行。**

```
触发条件一：策略绩效衰减检测（每周 Cron 检查）
─────────────────────────────────────────────
检测逻辑：
  滚动计算最近 20 个交易日 vs 最近 60 个交易日的夏普比率
  若 近20日夏普 / 近60日夏普 < 0.6（即衰减超过40%）
  → 触发衰减预警

QuantBot 主动发送：
  "⚠️ 策略衰减预警
   北向动量策略（v3）近 20 日表现明显弱化：
   · 近20日夏普：0.4   近60日夏普：1.2（衰减67%）
   · 近20日最大回撤：-18%（历史均值 -11%）
   
   可能原因分析：
   1. 北向资金近期受宏观影响波动加剧，信号质量下降
   2. 市场由趋势转为震荡，趋势跟随策略普遍失效
   
   我有两个改进方向，是否要探讨？
   A) 加入震荡市场识别过滤条件
   B) 降低仓位，观察一段时间
   
   [探讨改进A] [探讨改进B] [暂不处理，继续观察]"
```

```
触发条件二：学习到社区新策略/研报后（QuantBot 先自主验证，有提升才告知）
─────────────────────────────────────────────
当 QuantBot 从聚宽/QuantConnect/研报学习到有价值的策略或因子思路后：

【阶段一：QuantBot 自主研究（静默执行，不打扰用户）】
  1. 提炼该策略/研报的核心逻辑和关键参数
  2. 判断与当前已有策略的关系：
     · 完全独立的新策略类型 → 独立回测验证
     · 可借鉴某个条件/因子 → 尝试融入现有策略生成候选改进版
  3. 用 Qlib 执行回测，与当前 active 策略对比核心指标：
     · 夏普比率、年化收益、最大回撤、IC
  4. 将学习要点记入 MEMORY.md（无论结果如何都记录）

【阶段二-A：有提升 → 告知用户，等待确认】
  当新策略/改进版回测结果优于当前策略时（至少一项关键指标提升且无明显退化），
  QuantBot 推送：

  "📚 学习成果：我从[来源]发现了一个有价值的思路并已完成验证

   核心思路：[一句话描述学到的逻辑]
   
   我基于此对 north_momentum_v3 做了改进尝试（v4-candidate），
   回测对比结果如下：

   | 指标       | 当前 v3 | 候选 v4 | 变化    |
   |-----------|--------|--------|--------|
   | 夏普比率   | 1.2    | 1.5    | ↑ +25% |
   | 年化收益   | 18%    | 21%    | ↑ +3%  |
   | 最大回撤   | -14%   | -12%   | ↑ 改善  |
   
   是否将 v4-candidate 加入并行模拟测试？
   [✅ 开始并行测试] [📄 查看详细回测报告] [❌ 暂不采用，仅记录]"

【阶段二-B：无提升 → 静默学习，仅更新知识库】
  当改进尝试回测结果未能超越当前策略时，QuantBot 不打扰用户，
  而是：
  · 将该策略/研报的有效思路提炼后写入 MEMORY.md「量化知识积累」章节
  · 记录失效原因（如"该因子在 A 股 T+1 限制下有效性弱于美股"）
  · 在下次周报中以一句话带过："本周学习了 N 个策略思路，
    经验证暂无超越现有策略的改进，知识要点已归档。"
```

```
触发条件三：市场制度/环境重大变化
─────────────────────────────────────────────
（通过每日新闻监控触发）
当检测到如：交易规则变化、行业政策重大调整、
牛熊市切换信号时：

  "🔔 市场环境信号
   检测到可能影响当前策略的重大事件：[描述]
   
   初步影响评估：
   · north_momentum_v3 受影响程度：[高/中/低]
   · 建议：[暂停运行/降仓观察/不影响]
   
   是否需要我做详细分析？"
```

```
触发条件四：用户主动要求
─────────────────────────────────────────────
用户说"优化一下策略"、"策略感觉最近不对"等
→ 进入策略诊断对话流程（见第二章）
```

---

### 1.4 模拟运行的具体机制

**模拟运行 ≠ 实盘交易，是基于每日收盘数据的"虚拟持仓"跟踪。**

```python
# 文件：nanobot/agent/tools/paper_trading.py

class PaperTradingTracker:
    """
    模拟交易跟踪器
    每个工作日收盘后，根据策略信号更新虚拟持仓，
    记录每日盈亏，定期生成绩效报告
    """
    
    def __init__(self, strategy_id: str, initial_capital: float = 1_000_000):
        self.strategy_id = strategy_id
        self.capital = initial_capital       # 虚拟资金（默认100万）
        self.positions = {}                  # 当前持仓 {股票代码: 持仓量}
        self.trade_log = []                  # 交易记录
        self.daily_nav = []                  # 每日净值
    
    def run_daily(self, date: str):
        """
        每日收盘后执行：
        1. 获取今日行情（AkShare）
        2. 运行策略信号计算
        3. 生成交易指令（含涨跌停过滤）
        4. 更新虚拟持仓和净值
        5. 记录到 paper_trading/{strategy_id}/YYYY-MM-DD.json
        """
        pass
    
    def get_performance_summary(self, days: int = 20) -> dict:
        """返回最近 N 日模拟绩效摘要"""
        pass
```

**模拟运行数据存储结构：**
```
~/.nanobot/paper_trading/
├── north_momentum_v3/
│   ├── positions.json          ← 当前持仓
│   ├── trade_log.csv           ← 完整交易记录
│   ├── daily_nav.csv           ← 每日净值曲线
│   └── performance.json        ← 最新绩效指标
└── competing/
    └── north_momentum_v3_vs_v4/
        ├── v3_nav.csv
        ├── v4_nav.csv
        └── comparison_report.md
```

---

## 二、"确认优先"交互原则

**核心设计决策：QuantBot 的所有"写操作"（修改策略、存档、开始/停止模拟）都需要用户确认。"读操作"（分析、学习、报告）可自主执行。**

### 2.1 操作分级表

```
操作类型           自动执行    需要确认    说明
─────────────────────────────────────────────────────────────────
学习量化社区文章    ✅ 自动     —          Cron 定时执行，结果汇报
每日市场复盘        ✅ 自动     —          收盘后自动生成，推送摘要
因子有效性验证      ✅ 自动     —          后台执行，结果记入因子库
快速回测（1年）     ✅ 自动     —          在分析类对话中可直接执行
─────────────────────────────────────────────────────────────────
创建新策略          —          ✅ 确认    展示策略设计，确认后才编写
完整回测（5年+）    —          ✅ 确认    告知耗时，请用户确认
开始模拟运行        —          ✅ 确认    明确资金、周期、风险
修改正在运行的策略  —          ✅ 确认    展示改动内容后等待确认
停止/废弃策略       —          ✅ 确认    告知影响后确认
策略升代（替换主力）—          ✅ 确认    展示 A/B 对比后确认
```

### 2.2 确认消息设计规范

每条需要确认的消息必须包含以下结构：

```
[标题] 操作类型 + 策略名
[内容] 本次操作的具体内容（做什么、改什么）
[预期] 预计结果或耗时
[风险] 可能的负面影响（如有）
[选项] 明确的行动按钮（不只是"是/否"）
```

**示例——创建新策略确认消息：**

```
📋 新策略创建确认

基于你的需求，我设计了以下策略方案：

策略名称：北向资金 + 业绩超预期复合策略
核心逻辑：当北向资金连续净流入 ≥ 3 日，同时
         该股近期业绩超预期幅度 > 10%，触发买入信号
选股范围：沪深300成分股
持仓周期：约 10-20 个交易日
预计回测耗时：约 15 分钟（Qlib 完整回测，2019-2024）

在开始之前，请确认：
· 初始模拟资金：100万元（可修改）
· 回测区间：2019-01-01 至 2024-12-31

[✅ 确认，开始回测] [✏️ 我要修改方案] [❌ 取消]
```

**示例——策略衰减修改确认消息：**

```
⚠️ 策略修改方案确认

当前策略：north_momentum_v3（运行中 · 已运行42天）

检测到近20日绩效衰减，我建议以下修改：
─────────────────────────────────
修改内容：加入"市场震荡过滤"条件
         当沪深300 20日波动率 > 历史80分位时，
         暂停开新仓，仅持有现有仓位直至平仓

预期效果（基于历史回测）：
· 震荡市最大回撤：-18% → -12%（估计）
· 年化收益可能略有下降（约1-2%）
· 整体夏普比率预计提升

操作方式：创建 north_momentum_v4，与 v3 并行运行
         观察周期：20个交易日后对比结果

[✅ 创建v4并行测试] [💬 我有其他想法] [⏸️ 暂不修改，继续观察]
```

---

## 三、持续学习机制

### 3.1 每日收盘后复盘（16:00–17:00 自动执行）

#### 数据架构原则：两类数据，两条路径，严格分工

QuantBot 继承了 nanobot 原生的 **WebSearch**（搜索引擎）和 **WebFetch**（页面抓取）工具——这两个工具本质上就是 QuantBot 的"浏览器"，可以搜索和访问任意公开网页，无需为每个平台单独开发 SDK。数值型结构化数据则全部走 AkShare 接口。

```
┌─────────────────────────────────────────────────────────────────────┐
│                         数据来源架构                                  │
├─────────────────────────────┬───────────────────────────────────────┤
│   数值型数据                 │   文本型数据（新闻/分析/研报/观点）       │
│   → AkShare（唯一来源）      │   → WebSearch + WebFetch（浏览器搜索）   │
├─────────────────────────────┼───────────────────────────────────────┤
│ · 大盘指数精确涨跌幅          │ · 财经平台今日复盘文章（雪球/同花顺等）   │
│ · 北向资金净流入金额          │ · 用户指定博主/大V的最新观点             │
│ · 融资融券余额精确数值         │ · 券商研报摘要                         │
│ · 行业板块精确涨跌排行         │ · 国内外财经新闻、政策解读              │
│ · 个股 K 线 / 财务报表数据    │ · 美股动态 / 宏观信号                  │
└─────────────────────────────┴───────────────────────────────────────┘
```

> **为什么文本数据统一用浏览器搜索而不用专门 SDK？**  
> nanobot 原生的 WebSearch/WebFetch 加上 `multi-search-engine` Skill（覆盖 Google/Bing/DuckDuckGo 多引擎），
> 可以访问任意公开网页，比维护多个平台 API 更灵活、更稳定，
> 也不受平台接口变更影响。只要平台页面公开可访问，QuantBot 就能读到。
> **所有文本搜索统一走 multi-search-engine，LLM 自行构造搜索词和判断是否需要搜索。**

---

**文本来源优先级（复盘执行顺序）：**

```
优先级 1：用户指定来源（每次复盘必抓，最高优先级）
─────────────────────────────────────────────────────
  用户可通过对话随时添加，或在 config.json 中预配置：
  · 指定博主主页（雪球大V / 微信公众号 / 个人博客 / 任意 URL）
  · 固定复盘页面（如某券商每日点评固定页）
  · 临时粘贴的文章链接（即时阅读分析，一次性）

优先级 2：核心财经平台（WebSearch 驱动，每日定时搜索）
─────────────────────────────────────────────────────
  ┌──────────────────────┬─────────────────────────────────┬──────┐
  │  平台                 │  抓取内容                        │ 频率 │
  ├──────────────────────┼─────────────────────────────────┼──────┤
  │  雪球（xueqiu.com）   │  今日 A 股复盘 / 大V观点          │ 每日 │
  │  同花顺（10jqka）     │  个股新闻 / 今日行情分析          │ 每日 │
  │  新浪财经             │  市场综述 / 今日热点新闻          │ 每日 │
  │  东方财富（eastmoney）│  研报摘要 / 分析师评级变化        │ 每日 │
  │  华尔街见闻           │  美股 / 全球宏观信号              │ 每日 │
  │  华尔街日报（WSJ）    │  美联储政策 / 国际宏观深度报道    │ 每日 │
  │  路透社 / 彭博中文    │  中国经济 / 大宗商品              │ 每日 │
  └──────────────────────┴─────────────────────────────────┴──────┘

  搜索词示例（**multi-search-engine** 自动多引擎并发，含日期避免抓到旧文章）：
  · "A股今日收盘复盘 {date} 雪球"
  · "今日 A 股热点 {date} 同花顺"
  · "Fed Powell China market impact {date} WSJ"
  · "纳斯达克 A股影响 {date} 华尔街见闻"

优先级 3：量化社区（WebFetch 深度阅读，每周一次）
─────────────────────────────────────────────────────
  · 聚宽（joinquant.com）— 策略思路 / 因子讨论 / 量化课堂
  · QuantConnect         — 国际策略思路 / 因子研究文章
  · 雪球量化专区          — 散户量化实践 / 市场规律讨论

优先级 4：主动专项搜索（动态触发，AkShare 数值异动时自动触发，使用 multi-search-engine）
─────────────────────────────────────────────────────
  当 AkShare 数值数据检测到异动时，自动用 WebSearch 搜索解读文章：
  · 某板块单日涨跌 > 3%  → "[板块名] 今日异动原因 {date}"
  · 北向资金单日 > 50亿  → "北向资金大幅流入原因 {date}"
  · 个股换手率异常        → "[股票名] 异常成交 {date}"
  · AkShare 公告监控触发  → "[政策关键词] 对A股影响 分析"
```

**收盘复盘 Cron 任务（每个工作日 16:15 触发）：**

```python
async def post_market_review(date: str):

    # ── 路径A：数值型数据（AkShare）──────────────────────────
    # Step 1：大盘行情数据
    market_data = await AShareRealtimeTool.execute(index=True)
    # Step 2：资金流向数据
    north_flow  = await NorthFundFlowTool.execute(days=1)
    margin_data = await MarginTradingTool.execute()
    # Step 3：板块涨跌排行
    sector_rank = await IndustryRankTool.execute()

    # ── 路径B：文本型数据（WebSearch + WebFetch）─────────────
    # Step 4：用户指定来源（最高优先级，逐一 WebFetch）
    user_content = await UserSourceFetchTool.execute(
        source_config=load_user_sources()
    )
    # Step 5：核心财经平台聚合（WebSearch 并发搜索）
    platform_news = await MarketReviewWebTool.execute(date=date)

    # Step 6：板块异动专项搜索（仅当 AkShare 检测到异动时触发）
    anomaly_news = []
    for sector in sector_rank.top_movers(threshold=3.0):
        anomaly_news += await web_search(f"{sector} 今日异动原因")

    # Step 7：美股信号（22:00 补充追加，不阻塞当前复盘）
    # → 由单独的 us_market_monitor Cron 任务处理

    # ── 综合分析与输出 ──────────────────────────────────────
    # Step 8：LLM 综合所有数据，生成复盘报告
    all_inputs = merge(market_data, north_flow, margin_data,
                       user_content, platform_news, anomaly_news)
    review = await llm_synthesize(all_inputs)

    # Step 9：检查对当前运行策略的影响
    strategy_impact = await assess_strategy_impact(review)

    # Step 10：写入研究日记 + 推送 Telegram 简报摘要
    write_daily_note(date, review, strategy_impact)
    push_telegram_brief(review)  # 控制在 200 字以内
```

### 3.2 用户自定义学习来源

所有用户自定义来源均通过 WebSearch/WebFetch 获取，在 `config.json` 中配置：

```json
{
  "learning_sources": {
    "daily_review": [
      {
        "name": "某券商每日复盘",
        "url": "https://xxx.com/daily-review",
        "type": "webpage",
        "fetch_mode": "webfetch"
      },
      {
        "name": "XX公众号RSS",
        "url": "https://rss.xxx.com/feed",
        "type": "rss",
        "fetch_mode": "webfetch"
      }
    ],
    "bloggers": [
      {
        "name": "雪球大V-量化小散",
        "url": "https://xueqiu.com/u/xxxxxxx",
        "platform": "xueqiu",
        "fetch_mode": "webfetch",
        "note": "擅长均线+量化因子，每日收盘后更新"
      },
      {
        "name": "东方财富博主-xxx",
        "url": "https://guba.eastmoney.com/list,xxx.html",
        "platform": "eastmoney",
        "fetch_mode": "webfetch"
      }
    ],
    "research_reports": [
      {
        "name": "海通证券研报",
        "url": "https://research.haitong.com/",
        "fetch_mode": "webfetch",
        "frequency": "weekly"
      }
    ]
  }
}
```

**用户随时通过对话更新来源：**
```
用户："帮我关注雪球上 xxx 的每日分析，他的主页是 https://xueqiu.com/u/xxx"
QuantBot："好的，已将该博主加入每日复盘来源。从明天收盘后开始自动抓取。
          目前你的每日来源共有 N 个，如需管理请说'查看学习来源'。"

用户："帮我读一下这篇研报 https://xxx.com/report.pdf"
QuantBot："[WebFetch 读取 PDF 内容]
          已读取该研报，以下是量化相关要点摘要：..."
```

### 3.3 量化社区学习机制

所有社区内容均通过 **WebFetch 直接读取页面 + WebSearch 搜索话题** 获取：

| 社区 | 学习内容 | 获取方式 | 频率 |
|------|---------|---------|------|
| **聚宽（joinquant.com）** | 量化课堂、精选策略思路、社区讨论 | WebFetch 页面 | 每周一次 |
| **QuantConnect** | 国际策略思路、因子研究文章 | WebFetch + WebSearch | 每两周一次 |
| **雪球量化专区** | 量化实践帖子、大V观点 | WebSearch "雪球 量化策略 本周" | 每周两次 |
| **GitHub 量化项目** | 新开源策略、工具更新动态 | WebSearch "quantitative trading github 2026" | 每月一次 |

**聚宽学习工具（`QuantCommunityLearnerTool`）搜索词设计：**

```python
JOINQUANT_SEARCH_QUERIES = {
    "community":  "聚宽 量化策略 本周 site:joinquant.com",
    "factor":     "聚宽 Alpha因子 IC 本月 site:joinquant.com",
    "courses":    "聚宽量化课堂 最新 site:joinquant.com",
}

QUANTCONNECT_SEARCH_QUERIES = {
    "strategies": "QuantConnect A-share China strategy 2026",
    "factors":    "QuantConnect alpha factor research 2026",
}
```

**每周学习报告格式：**

```
📚 QuantBot 量化学习周报 | 第N周

【本周学习来源】
· 聚宽社区 3 篇文章
· QuantConnect 1 个策略思路
· 用户指定来源：xxx博主 2 篇

【本周值得关注的策略思路】
1. 聚宽-用户xxx分享了一个"资金流向+换手率"复合因子，
   在中证500上近3年IC=0.041，值得验证
   → 建议：是否要我本地用 Qlib 验证这个因子？[是] [暂不]

2. QuantConnect 上有人分享了"月末效应+消费板块"策略，
   国际市场验证有效，A股可能也有类似规律
   → 建议：是否要我探索 A 股的月末效应？[是] [暂不]

【知识积累摘要】
· 学习了高频因子衰减的概念：日频换手率因子通常在1-2年内衰减
· 了解了聚宽 CNE6 风险模型的应用方式

【已加入验证队列】（上周你确认的学习建议）
· 正在验证：资金流向+换手率因子（预计本周完成）
```

### 3.4 研报阅读机制

**研报来源：**
- 券商公开研报（通过 WebFetch 抓取 PDF 链接）
- AkShare 提供的宏观研报接口
- 用户手动提供的研报 URL 或上传 PDF

**研报处理流程：**

```
研报 URL/PDF
     ↓
WebFetch 或 文件读取
     ↓
LLM 提炼（量化相关部分）：
  ·  报告中有哪些因子/策略思路？
  ·  有哪些数据支持当前市场判断？
  ·  对当前持仓策略有何影响？
     ↓
提炼结果写入：
  ·  当日研究日记（即时参考）
  ·  MEMORY.md 知识积累章节（长期保留）
     ↓
若发现对策略有显著影响 → 向用户汇报
```

---

## 四、用户引导入门流程（Onboarding）

**目标：用户输入基础投资需求 → QuantBot 通过提问获得足够信息 → 才开始编写策略并运行模拟。**

### 4.1 需求收集对话（6 个核心问题）

QuantBot 会依次提出以下问题（不会一次全问，保持对话节奏）：

```
第 1 轮：了解基础诉求
─────────────────────────────────────────────
QuantBot：
"你好！我是 QuantBot，专注 A 股量化策略研究。
在开始之前，我想先了解你的一些想法：

你对量化策略最主要的期望是什么？
· A) 追求高收益，能承受较大回撤
· B) 稳健增值，控制回撤在 15% 以内
· C) 探索学习为主，收益是次要目标
· D) 我想先自己描述一下想法"
```

```
第 2 轮：了解市场偏好（用户回答后）
─────────────────────────────────────────────
QuantBot：
"明白了。你更感兴趣哪类 A 股市场？

· 大盘蓝筹（沪深300成分股，流动性好）
· 中小盘成长（中证500/1000，波动大）
· 特定行业/主题（如科技、消费、医药）
· 都可以，由数据说话"
```

```
第 3 轮：了解交易风格偏好
─────────────────────────────────────────────
QuantBot：
"你对持仓周期有偏好吗？这会影响策略类型的选择：

· 短线（持股 1-5 天）：需要更频繁关注，交易成本高
· 中线（持股 1-4 周）：较均衡，推荐新手
· 长线（持股 1-3 个月）：持仓稳定，需要耐心"
```

```
第 4 轮：了解风控底线
─────────────────────────────────────────────
QuantBot：
"你能接受的最大单次策略回撤是多少？
（这是一个非常重要的参数，会直接影响策略设计）

· -10% 以内（非常保守）
· -15% 以内（稳健）
· -20% 以内（中等风险）
· -30% 以内（激进）

注：以上是策略层面的回撤，不代表个别股票涨跌。"
```

```
第 5 轮：了解策略想法（可选）
─────────────────────────────────────────────
QuantBot：
"你有没有对某种策略逻辑特别感兴趣，或者已经有一些想法？
例如：'我觉得北向资金持续流入的股票之后会涨'
或者 '我想做业绩超预期的事件驱动策略'

如果没有，直接告诉我'没有想法，由你推荐'也完全可以。"
```

```
第 6 轮：了解参与程度偏好
─────────────────────────────────────────────
QuantBot：
"最后，你希望参与的深度是？

· 轻量模式：只看每周报告，重要变化时通知我
· 标准模式：每日收盘后简报 + 重要变化通知
· 深度模式：我想深度参与每个研究决策"
```

### 4.2 方案确认与策略启动

收集完信息后，QuantBot 生成一份确认方案：

```
📋 QuantBot 策略研究方案确认

基于你的需求，我为你设计了以下方案：

【策略定位】
目标：稳健增值，夏普比率 > 1.2
标的：沪深300 成分股（流动性好，规则清晰）
周期：中线（10-20个交易日换仓）
风控：最大回撤目标控制在 -15% 以内

【初始策略】
策略名：north_earnings_v1（北向动量+业绩超预期）
核心逻辑：结合北向资金流入信号和业绩超预期事件
初始资金：100万元（虚拟）

【工作模式】
学习：每周从聚宽社区学习量化知识
复盘：每个工作日收盘后自动生成简报
汇报：每周五发送本周策略表现周报
参与：重要决策（修改策略/停止运行）前都会先问你

【接下来的步骤】
1. 进行 5 年历史回测（约15分钟）
2. 回测通过后，开始模拟运行
3. 每周向你汇报进展

[✅ 确认，开始执行] [✏️ 我要调整] [💬 先聊聊策略逻辑]
```

---

### 4.3 工作模式说明（不是每日都更新策略）

**这一点非常重要，需要在 SOUL.md 中明确写入：**

```markdown
## 工作节奏原则

QuantBot 的工作遵循以下节奏，而非每日都做策略修改：

### 日常模式（每个工作日）
- 自动获取行情和资金流向数据
- 运行模拟持仓的每日盈亏更新
- 抓取用户指定来源的市场分析
- 生成简洁的每日简报推送

### 每周模式（周五/周六）
- 汇报本周策略模拟绩效
- 量化社区学习摘要
- 若发现策略衰减信号，提出改进建议（需用户确认）

### 按需模式（用户主动触发）
- 用户提出策略想法 → 即时研究和回测
- 用户提问量化知识 → 即时解答
- 用户要求验证某个因子 → 立即执行

### 不做的事
- ❌ 不每日主动提议修改策略（除非检测到衰减）
- ❌ 不在没有充分回测数据的情况下建议策略变更
- ❌ 不以"今天市场不好"为理由修改策略逻辑
- ❌ 不向用户推送过多通知，避免信息过载
```

---

## 五、系统工作节奏总览

### 5.1 时间维度全景图

```
每个工作日（Cron 触发自然语言任务，LLM 自行决定具体步骤）
────────────────────────────────────────────────────────
> ⚠️ 重要：Cron 触发的是一段**任务描述文字**，交给 LLM 去判断用哪些工具、
> 以什么顺序、分析什么维度。不是执行预编排的代码逻辑。

09:00  【LLM 任务】检查今日是否有重大宏观或政策新闻，
       评估对当前运行中的量化策略是否有影响，若影响显著请告知用户。
       搜索时使用 multi-search-engine skill。

16:15  【LLM 任务】A 股刚收盘，从本地数据库读取今日行情数据做市场复盘，
       同时用 multi-search-engine 搜索今日市场分析文章和用户指定来源，
       生成约 200 字简报推送。

20:00  【脚本任务，不走 LLM】直接执行 db_daily_update.py，
       通过 AkShare 拉取当日完整 A 股数据并写入本地 SQLite 数据库。
       · 选择 20:00 而非 16:30 的原因：
         北向资金结算数据约 17:30 后才完整发布；
         融资融券余额数据约 18:00 后发布；
         20:00 可确保所有当日数据均已落地，入库完整准确。
       · 这是唯一不走 LLM 的 Cron——数据入库是确定性操作，
         Python 脚本直接执行，更快、更稳、零 token 消耗。
       · 详细设计见「六、本地数据库设计」

21:00  【LLM 任务】读取本地数据库中今日收盘数据，
       更新所有模拟持仓净值，记录每日净值变化。

每周五  Cron 触发任务："生成本周策略模拟绩效周报：
        本周净值变化 vs 沪深300、近期绩效是否有衰减迹象、
        本周量化社区有哪些值得关注的学习内容（multi-search-engine 搜索聚宽/雪球）。
        如有改进建议请附在报告末尾，等待用户确认后再行动。"

每月初  Cron 触发任务："对所有活跃策略做月度健康检查：
        当月绩效 vs 历史均值，是否有系统性偏差，
        更新 MEMORY.md 知识库，若有策略长期跑输基准请告知用户。"

用户主动触发（随时）
────────────────────────────────────────────────────────
"研究一个动量策略"   → LLM 自行决定获取什么数据、用什么工具验证
"我看到一篇文章..."  → 读取并分析，提炼量化价值
"策略最近怎么样"     → 生成即时绩效报告
"学习一下这个因子"   → 执行因子验证（LLM 自行决定方式）
"读一下这份研报"     → WebFetch 读取并提炼量化相关内容
```

### 5.2 信息推送分级

为避免信息过载，推送消息按重要性分级：

```
🔴 Level 1（立即推送，等待确认）
   · 策略衰减超过 50%
   · 重大政策变化影响当前策略
   · 模拟持仓单日亏损超过设定阈值

🟡 Level 2（每日简报，合并推送）
   · 今日市场概况
   · 资金流向摘要
   · 美股信号提示

🟢 Level 3（周报，汇总推送）
   · 量化社区学习成果
   · 因子验证结果
   · 改进建议（非紧急）

⚪ Level 4（用户查询时才显示）
   · 完整策略代码
   · 详细回测报告
   · 历史交易记录
```

### 5.3 对话场景示例

**场景 A：用户漫无目的地探索**
```
用户："我对量化挺好奇的，想试试"
QuantBot：进入 Onboarding 流程（见第四章）
```

**场景 B：用户带着具体想法来**
```
用户："我觉得业绩超预期的股票会涨，能帮我研究一下吗？"
QuantBot："这是个有价值的假设！业绩超预期效应在 A 股确实有
          历史研究支持。我来帮你验证：

          首先几个问题：
          1. 你希望在哪个范围的股票里验证？（沪深300/全A）
          2. '超预期'怎么定义比较合理？（实际EPS/预期EPS-1 > 10%？）
          3. 买入时机：公告当日、次日、还是等3日观察？

          有想法就说，没想法我给你推荐默认参数也可以。"
```

**场景 C：用户只想学习，不想运行策略**
```
用户："我想学习一下量化因子是怎么回事"
QuantBot："好！我们从最基础的概念开始，结合 A 股实际案例讲解。
          不需要现在就运行任何策略，纯学习也完全可以。
          
          你想从哪个角度开始？
          · 技术类因子（均线、动量、波动率）
          · 基本面因子（估值、成长、盈利质量）
          · 另类因子（资金流向、情绪、北向资金）
          · 给我推荐一个合适的入门路径"
```

**场景 D：策略运行一段时间后，用户来查询**
```
用户："策略最近跑得怎么样？"
QuantBot：[调用 paper_trading 报告工具]

"📊 north_earnings_v1 近期表现（已运行 42 天）

本月收益：+3.2%   基准(沪深300)：+1.8%   超额：+1.4%
近20日夏普：1.4   近60日夏普：1.2   状态：✅ 稳定

最近交易（本周）：
· 2026-03-05 买入 贵州茅台(600519) 
· 2026-03-07 卖出 宁德时代(300750) +2.1%

当前持仓：5 只股票，分散良好

总体来看策略运行正常，目前无需调整。
如需查看完整持仓明细，回复'持仓详情'。"
```

---


---

## 六、本地数据库设计

### 6.1 设计决策：为什么需要本地数据库

> **核心矛盾**：AkShare 每次调用都需要联网请求，回测和模拟交易需要反复读取历史数据，
> 实时调用既慢（每次 1-5 秒）又受限（频繁请求可能被封）。
> 本地数据库将 AkShare 数据落地存储，后续所有读取操作从本地完成，
> AkShare 只承担"每日增量更新"的角色。

```
数据流向：

AkShare（每日 20:00 一次）
    ↓  db_daily_update.py（脚本，不走 LLM）
本地 SQLite 数据库（~/.nanobot/market_data.db）
    ↓  DatabaseReadTool（Tool）
LLM / Qlib 回测 / 模拟持仓净值计算
```

**技术选型：SQLite**

| 方案 | 优点 | 缺点 | 结论 |
|------|------|------|------|
| SQLite | 零依赖、单文件、A 股数据量完全够用 | 并发写入有限制 | ✅ 首选 |
| PostgreSQL | 并发强、功能全 | 需单独部署维护 | 个人项目杀鸡用牛刀 |
| Qlib PIT DB | 专为回测设计，防未来数据泄露 | 只读，不适合灵活查询 | 回测专用，与 SQLite 并存 |

> **两库并存原则**：
> - SQLite：日常查询、复盘、模拟持仓——灵活读写
> - Qlib PIT DB：策略回测——防数据泄露，由 Qlib 独立维护

---

### 6.2 数据库表结构

```sql
-- 文件：~/.nanobot/market_data.db

-- 表一：个股每日行情（核心表）
CREATE TABLE daily_quotes (
    date        TEXT NOT NULL,          -- 交易日期 YYYY-MM-DD
    symbol      TEXT NOT NULL,          -- 股票代码 000001.SZ
    name        TEXT,                   -- 股票名称
    open        REAL,                   -- 开盘价
    high        REAL,                   -- 最高价
    low         REAL,                   -- 最低价
    close       REAL,                   -- 收盘价
    volume      REAL,                   -- 成交量（手）
    amount      REAL,                   -- 成交额（元）
    pct_chg     REAL,                   -- 涨跌幅 %
    turnover    REAL,                   -- 换手率 %
    PRIMARY KEY (date, symbol)
);

-- 表二：指数行情（沪深300/中证500/上证指数等）
CREATE TABLE index_quotes (
    date        TEXT NOT NULL,
    symbol      TEXT NOT NULL,          -- 000300.SH / 000905.SH 等
    name        TEXT,
    close       REAL,
    pct_chg     REAL,
    volume      REAL,
    amount      REAL,
    PRIMARY KEY (date, symbol)
);

-- 表三：北向资金（陆股通净流入）
CREATE TABLE north_fund_flow (
    date            TEXT PRIMARY KEY,
    sh_net_buy      REAL,               -- 沪股通净买入（亿元）
    sz_net_buy      REAL,               -- 深股通净买入（亿元）
    total_net_buy   REAL,               -- 合计净买入（亿元）
    sh_buy          REAL,               -- 沪股通买入
    sh_sell         REAL,               -- 沪股通卖出
    sz_buy          REAL,               -- 深股通买入
    sz_sell         REAL               -- 深股通卖出
);

-- 表四：融资融券
CREATE TABLE margin_trading (
    date            TEXT PRIMARY KEY,
    rz_balance      REAL,               -- 融资余额（亿元）
    rq_balance      REAL,               -- 融券余额（亿元）
    rz_buy          REAL,               -- 融资买入额
    rq_sell         REAL                -- 融券卖出额
);

-- 表五：行业板块日行情
CREATE TABLE industry_quotes (
    date        TEXT NOT NULL,
    industry    TEXT NOT NULL,          -- 行业名称（申万一级）
    pct_chg     REAL,                   -- 涨跌幅 %
    net_inflow  REAL,                   -- 主力净流入（亿元）
    PRIMARY KEY (date, industry)
);

-- 表六：数据更新日志（每次入库记录）
CREATE TABLE update_log (
    date        TEXT NOT NULL,
    table_name  TEXT NOT NULL,
    rows_upserted INTEGER,
    duration_sec  REAL,
    status      TEXT,                   -- success / failed
    error_msg   TEXT,
    updated_at  TEXT,                   -- 实际执行时间戳
    PRIMARY KEY (date, table_name)
);
```

---

### 6.3 每日更新脚本（db_daily_update.py）

```python
# 文件：scripts/db_daily_update.py
# Cron：0 20 * * 1-5  python3 ~/.nanobot/scripts/db_daily_update.py

import akshare as ak
import sqlite3
import pandas as pd
from datetime import datetime, date
import logging

DB_PATH = "~/.nanobot/market_data.db"
TODAY   = date.today().strftime("%Y-%m-%d")
log     = logging.getLogger("db_update")


def update_daily_quotes(conn: sqlite3.Connection):
    """更新全市场个股日行情（AkShare: stock_zh_a_hist）"""
    # 实际生产中按需拉取，或用增量接口 stock_zh_a_daily
    df = ak.stock_zh_a_hist(symbol="all", period="daily",
                             start_date=TODAY, end_date=TODAY)
    df["date"] = TODAY
    df.to_sql("daily_quotes", conn, if_exists="append",
              index=False, method="upsert_or_ignore")
    return len(df)


def update_index_quotes(conn: sqlite3.Connection):
    """更新主要指数日行情"""
    INDICES = {
        "000300": "沪深300",
        "000905": "中证500",
        "000001": "上证指数",
        "399001": "深证成指",
    }
    rows = 0
    for code, name in INDICES.items():
        df = ak.stock_zh_index_daily(symbol=f"sh{code}" if code.startswith("0") else f"sz{code}")
        latest = df[df["date"] == TODAY].copy()
        latest["symbol"] = f"{code}.{'SH' if code.startswith('0') else 'SZ'}"
        latest["name"]   = name
        latest.to_sql("index_quotes", conn, if_exists="append", index=False)
        rows += len(latest)
    return rows


def update_north_fund(conn: sqlite3.Connection):
    """更新北向资金数据"""
    df = ak.stock_hsgt_fund_flow_summary_em()
    today_row = df[df["日期"] == TODAY]
    if today_row.empty:
        log.warning("北向资金数据今日暂未发布")
        return 0
    today_row.to_sql("north_fund_flow", conn, if_exists="append", index=False)
    return len(today_row)


def update_margin(conn: sqlite3.Connection):
    """更新融资融券数据"""
    df = ak.stock_margin_sse_szse()
    today_row = df[df["date"] == TODAY]
    today_row.to_sql("margin_trading", conn, if_exists="append", index=False)
    return len(today_row)


def update_industry(conn: sqlite3.Connection):
    """更新申万一级行业涨跌幅"""
    df = ak.stock_board_industry_summary_ths()
    df["date"] = TODAY
    df.to_sql("industry_quotes", conn, if_exists="append", index=False)
    return len(df)


def main():
    conn = sqlite3.connect(DB_PATH)
    tasks = [
        ("daily_quotes",   update_daily_quotes),
        ("index_quotes",   update_index_quotes),
        ("north_fund_flow",update_north_fund),
        ("margin_trading", update_margin),
        ("industry_quotes",update_industry),
    ]

    for table, func in tasks:
        t0 = datetime.now()
        try:
            rows = func(conn)
            elapsed = (datetime.now() - t0).total_seconds()
            conn.execute(
                "INSERT OR REPLACE INTO update_log VALUES (?,?,?,?,?,?,?)",
                (TODAY, table, rows, elapsed, "success", None,
                 datetime.now().isoformat())
            )
            log.info(f"✅ {table}: {rows} 行，耗时 {elapsed:.1f}s")
        except Exception as e:
            conn.execute(
                "INSERT OR REPLACE INTO update_log VALUES (?,?,?,?,?,?,?)",
                (TODAY, table, 0, 0, "failed", str(e),
                 datetime.now().isoformat())
            )
            log.error(f"❌ {table} 更新失败: {e}")

    conn.commit()
    conn.close()
    log.info(f"📦 {TODAY} 数据入库完成")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
```

---

### 6.4 数据库读取 Tool（供 LLM 调用）

```python
# 文件：nanobot/agent/tools/db_reader.py

class DatabaseReadTool(Tool):
    """
    从本地 SQLite 数据库读取 A 股历史数据
    LLM 调用此工具替代直接调用 AkShare——更快、无网络依赖
    """
    name = "db_read"
    description = (
        "从本地数据库读取 A 股行情、北向资金、融资融券、行业涨跌等数据。"
        "数据每日 20:00 自动更新，适合查询近期历史数据。"
        "查询实时当日数据仍需调用 AkShare。"
    )
    DB_PATH = "~/.nanobot/market_data.db"

    QUERY_TEMPLATES = {
        # 查询某股票近 N 日行情
        "stock_history": """
            SELECT date, close, pct_chg, volume, turnover
            FROM daily_quotes
            WHERE symbol = ? AND date >= ?
            ORDER BY date ASC
        """,
        # 查询北向资金近 N 日
        "north_fund": """
            SELECT date, total_net_buy, sh_net_buy, sz_net_buy
            FROM north_fund_flow
            WHERE date >= ?
            ORDER BY date ASC
        """,
        # 查询指数近 N 日
        "index_history": """
            SELECT date, close, pct_chg
            FROM index_quotes
            WHERE symbol = ? AND date >= ?
            ORDER BY date ASC
        """,
        # 查询行业涨跌
        "industry_rank": """
            SELECT industry, pct_chg, net_inflow
            FROM industry_quotes
            WHERE date = ?
            ORDER BY pct_chg DESC
        """,
        # 查询数据库最新日期（用于判断数据是否已更新）
        "latest_date": """
            SELECT MAX(date) as latest FROM daily_quotes
        """,
    }

    def execute(self, query_type: str, **params) -> str:
        """
        query_type: stock_history / north_fund / index_history /
                    industry_rank / latest_date
        params: symbol, days, date 等（按 query_type 需要传入）
        """
        import sqlite3, os
        conn = sqlite3.connect(os.path.expanduser(self.DB_PATH))
        sql = self.QUERY_TEMPLATES[query_type]
        # 根据 query_type 组装参数...
        conn.close()
```

---

### 6.5 数据库初始化（首次运行）

```bash
# scripts/db_init.sh
# 首次运行时执行，初始化数据库并拉取历史数据

python3 -c "
import sqlite3, os
conn = sqlite3.connect(os.path.expanduser('~/.nanobot/market_data.db'))
# 执行建表 SQL（见 6.2 节）
conn.executescript(open('scripts/create_tables.sql').read())
conn.commit()
conn.close()
print('数据库初始化完成')
"

# 补拉近 2 年历史数据（首次需要，约 10-30 分钟）
python3 scripts/db_backfill.py --start 2023-01-01 --end $(date +%Y-%m-%d)
```

**数据量估算：**

| 数据表 | 日增量 | 2 年存量 | 磁盘占用 |
|-------|-------|---------|---------|
| daily_quotes（全 A 5000 股）| ~5000 行 | ~250 万行 | ~400 MB |
| index_quotes（10 个指数）| ~10 行 | ~5000 行 | < 1 MB |
| north_fund_flow | 1 行 | ~500 行 | < 1 MB |
| margin_trading | 1 行 | ~500 行 | < 1 MB |
| industry_quotes（31 个行业）| ~31 行 | ~1.5 万行 | ~3 MB |
| **合计** | | | **~405 MB** |

> 2 年全 A 股历史数据约 400 MB，普通笔记本完全可以承载，SSD 读写速度下查询毫秒级响应。

> 本文档与《QuantBot 设计文档 v1.2》配合使用，共同构成完整的定制化设计规范。
