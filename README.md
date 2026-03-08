# QuantBot - 量化研究员配置

基于 [nanobot](https://github.com/HKUDS/nanobot) 的量化研究员专用AI助手配置。

## 快速开始

```bash
# 1. 安装 nanobot
pip install nanobot-ai

# 2. 初始化配置
nanobot onboard

# 3. 配置 API Key
# 编辑 ~/.nanobot/config.json 添加你的 API Key

# 4. 启动
nanobot gateway
```

## 配置文件

### SOUL.md - 量化研究员人格定义

路径: `~/.nanobot/workspace/SOUL.md`

定义量化研究员的核心角色和价值观：

- **角色**: 兼具学术严谨与实践智慧的专业量化研究员
- **价值观**: 数据驱动、理性客观、风险意识、持续学习
- **沟通风格**: 专业但易懂、结论先行、逻辑清晰
- **边界**: 不提供具体买卖建议、不承诺收益、不替代人工决策
- **交互原则**: "确认优先" - 任何写操作需用户确认

### AGENTS.md - 工作风格指引

路径: `~/.nanobot/workspace/AGENTS.md`

定义量化研究的工作规范：

- **代码规范**: PEP 8标准、变量命名规则、注释要求
- **回测规范**: 数据要求、成本假设、评估指标
- **研究流程**: 因子挖掘→验证→组合→回测→实盘
- **偏好设置**: 工具选择、输出格式、学习来源

## 内置Skills

| Skill | 说明 |
|-------|------|
| quant_fundamentals | 量化基础知识 - EMH, MPT, CAPM, 因子模型 |
| a_share_rules | A股特有规则 - T+1, 涨跌停, 融资融券 |
| backtest_standards | 回测规范 - 防过拟合, 成本假设, 评估指标 |
| strategy_design | 策略设计方法论 - 趋势/均值回归/套利 |
| market_analysis | 市场分析框架 - 宏观周期, 行业轮动, 资金流向 |
| us_to_ashare_signal | 美股→A股信号传导 |
| risk_management | 风险管理 - VaR, CVaR, 仓位管理 |
| factor_research | 因子研究 - IC, ICIR, 因子正交化 |
| ml_quant | ML量化方法论 - 特征工程, 过拟合防范 |
| portfolio_optimization | 组合优化 - Markowitz, 风险平价 |

## 外部Skills

通过 ClawHub 安装:

```bash
# 安装 Skills
npx --yes clawhub@latest install multi-search-engine --workdir ~/.nanobot/workspace
npx --yes clawhub@latest install stock-technical-analysis --workdir ~/.nanobot/workspace
npx --yes clawhub@latest install quiver --workdir ~/.nanobot/workspace
npx --yes clawhub@latest install akshare-stock --workdir ~/.nanobot/workspace
npx --yes clawhub@latest install akshare-finance --workdir ~/.nanobot/workspace
npx --yes clawhub@latest install fundamental-stock-analysis --workdir ~/.nanobot/workspace
```

| Skill | 说明 |
|-------|------|
| multi-search-engine | 多引擎联网搜索 |
| stock-technical-analysis | 股票技术分析 |
| quiver | 美国国会议员持仓追踪 |
| akshare-stock | A股量化数据 |
| akshare-finance | 金融财经数据 |
| fundamental-stock-analysis | 基本面分析 |

## Skills详解

### quant_fundamentals - 量化基础知识

**触发条件**: 讨论量化投资概念、金融理论、因子模型、现代投资组合理论、CAPM、EMH等

**内容**:
- 量化投资定义与核心理念
- 因子分类: 基本面/技术面/情绪/另类数据
- 有效市场假说(EMH)与因子有效性
- 现代投资组合理论(MPT)
- CAPM与多因子模型

### a_share_rules - A股特有规则

**触发条件**: 讨论A股市场特有规则、T+1制度、涨跌停板、北向资金、融资融券、ST/*ST股票

**内容**:
- T+1交易制度（当天买入次日才能卖出）
- 涨跌停板制度（主板10%, 创业板/科创板20%）
- 北向资金（沪股通/深股通）信号意义
- 融资融券与做空限制
- 新股申购与配售规则
- ST/*ST股票交易限制

### backtest_standards - 回测规范

**触发条件**: 讨论回测方法论、避免过拟合、Sharpe/Calmar等评估指标、蒙特卡洛模拟

**内容**:
- 防过拟合原则
- 交易成本表（佣金、印花税、滑点）
- 资金容量考虑
- 指标评级标准
- 样本外验证方法
- 蒙特卡洛模拟

### strategy_design - 策略设计方法论

**触发条件**: 设计或讨论量化交易策略、策略构思来源、趋势/均值回归/套利策略、多空策略设计

**内容**:
- 策略构思来源（学术/市场观察/数据驱动）
- 逻辑驱动 vs 数据驱动
- 多空辩论提示词模板
- 策略迭代流程
- 常见策略类型

### market_analysis - 市场分析框架

**触发条件**: 宏观分析、行业轮动、资金流向、市场情绪、股债性价比分析、经济周期判断

**内容**:
- 宏观周期判断（复苏/繁荣/衰退/萧条）
- 行业轮动模型
- 资金流向分析
- 市场情绪指标
- 股债性价比

### us_to_ashare_signal - 美股→A股信号传导

**触发条件**: 美股信号如何传导到A股、利率/汇率影响、跨市场投资机会、中美市场联动

**内容**:
- 传导路径: 利率→汇率→资金流动→估值
- 行业映射逻辑
- 时区差异处理
- 案例分析

### risk_management - 风险管理方法论

**触发条件**: 讨论投资组合风险控制、仓位管理、VaR/CVaR、最大回撤控制、风险预算分配

**内容**:
- 风险度量: VaR, CVaR, 最大回撤
- 仓位管理模型（固定比例、波动率倒数、凯利公式）
- 风险预算分配
- 动态风控阈值
- 黑天鹅应对

### factor_research - 因子研究方法

**触发条件**: 因子研究、IC分析、因子衰减、正交化、因子权重优化、构建因子库

**内容**:
- IC (Information Coefficient) 解读
- ICIR (IC Information Ratio) 计算
- 因子衰减分析
- 因子正交化方法
- 因子权重优化
- 因子库的构建与维护

### ml_quant - ML量化方法论

**触发条件**: 机器学习在量化投资中的应用、模型选择、特征工程、过拟合防范、SHAP、集成学习

**内容**:
- 特征工程要点
- 模型选择（树模型/神经网络）
- 过拟合防范
- 特征重要性分析
- 模型解释性 (SHAP)
- 集成学习

### portfolio_optimization - 组合优化方法论

**触发条件**: 投资组合优化、均值-方差优化、风险平价策略、因子暴露控制

**内容**:
- 均值-方差优化 (Markowitz)
- 风险平价策略
- 因子暴露控制
- 换手率约束
- 流动性考虑
- 实战组合构建流程

## 使用示例

当讨论相关内容时，Skills会自动加载：

- "解释一下有效市场假说" → 触发 `quant_fundamentals`
- "A股的T+1制度是什么" → 触发 `a_share_rules`
- "如何设计一个趋势策略" → 触发 `strategy_design`
- "帮我做一下因子IC分析" → 触发 `factor_research`

## 组合使用

多个Skills可以组合使用以获得更全面的分析：

- **策略设计时**: `strategy_design` + `factor_research` + `backtest_standards`
- **风险管理时**: `risk_management` + `portfolio_optimization`
- **市场分析时**: `market_analysis` + `us_to_ashare_signal` + `a_share_rules`

## 相关链接

- 原始项目: [https://github.com/HKUDS/nanobot](https://github.com/HKUDS/nanobot)
- ClawHub: [https://clawhub.ai](https://clawhub.ai)
