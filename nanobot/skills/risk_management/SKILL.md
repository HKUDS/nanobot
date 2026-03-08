---
name: risk-management
description: Use when discussing portfolio risk控制, 仓位管理, VaR, CVaR, or风险管理. Also use when user asks about maximum drawdown, position sizing, or risk budgeting.
---

# 风险管理方法论

## 概述

风险管理是量化投资的核心组成部分。优秀的风险管理可以在保护本金的同时获取合理收益，而忽视风险管理即使有高收益也可能一次性归零。

## 风险度量

### VaR (Value at Risk)

**定义**：在给定置信水平和时间范围内，投资组合可能遭受的最大损失

**计算方法**：

```python
# 历史法VaR
returns = portfolio.history_returns()
var_95 = np.percentile(returns, 5)  # 95%置信度VaR
var_99 = np.percentile(returns, 1)  # 99%置信度VaR
```

**解读**：
- 95% VaR = -5%：有95%概率损失不会超过5%
- 意味着有5%概率损失会超过5%

**局限**：
- 不考虑极端损失
- 假设历史会重演

### CVaR (Conditional VaR)

**定义**：超过VaR部分的平均损失，也称为Expected Shortfall

$$CVaR = E[X | X > VaR]$$

**特点**：
- 考虑尾部风险
- 比VaR更保守

### 最大回撤

**定义**：从历史最高点到最低点的最大跌幅

```python
# 最大回撤计算
cummax = portfolio.value.cummax()
drawdown = (portfolio.value - cummax) / cummax
max_drawdown = drawdown.min()
```

**回撤控制目标**：
- 保守策略：<10%
- 平衡策略：<20%
- 激进策略：<30%

### 波动率

**定义**：收益的标准差

$$σ = \sqrt{\frac{∑(r_i - \bar{r})^2}{n-1}}$$

**年化波动率**：
$$σ_{annual} = σ_{daily} × \sqrt{252}$$

## 仓位管理模型

### 固定比例法

- 每次投入固定比例资金
- 简单易行，但可能错过机会

```python
def fixed_ratio_position(capital, position_value, ratio=0.1):
    target = capital * ratio
    return target - position_value
```

### 波动率倒数法

- 波动率越高，仓位越低

```python
def vol_inverse_position(capital, volatility, target_vol=0.15):
    weight = target_vol / volatility
    return capital * weight
```

### 凯利公式

$$f* = \frac{bp - q}{b} = \frac{p(b+1) - 1}{b}$$

- p：胜率
- b：盈亏比
- q：败率 = 1-p

**注意**：
- 凯利公式仓位较激进
- 建议使用半凯利或更保守

### 风险平价

- 各资产对组合风险贡献相等

```python
# 简化风险平价
def risk_parity_weights(cov_matrix):
    inv_vol = 1 / np.sqrt(np.diag(cov_matrix))
    return inv_vol / inv_vol.sum()
```

## 风险预算分配

### 概念

风险预算 = 总风险 × 风险分配比例

### 实施步骤

1. 确定总风险预算（组合目标波动率）
2. 分配各策略/资产的风险预算
3. 根据风险预算确定仓位
4. 定期再平衡

### 示例

| 策略 | 风险预算 | 目标波动率 | 分配权重 |
|------|----------|------------|----------|
| 股票Alpha | 50% | 12% | 6% |
| CTA趋势 | 30% | 15% | 4.5% |
| 套利 | 20% | 5% | 1% |
| **合计** | **100%** | **9.6%** | **11.5%** |

## 动态风控阈值

### 预警线和平仓线

| 阈值类型 | 常用值 | 动作 |
|----------|--------|------|
| 预警线 | -5% | 关注加强 |
| 警戒线 | -10% | 减仓 |
| 止损线 | -15% | 强制减仓 |
| 平仓线 | -20% | 清仓 |

### 动态调整

- 市场波动加大时收紧阈值
- 策略表现良好时放宽阈值
- 保持一致性，避免随意调整

### 熔断机制

- 单日亏损超过阈值，停止交易
- 设置冷静期
- 复盘后再战

## 黑天鹅应对

### 黑天鹅特征

- 无法预测
- 影响巨大
- 概率极低但存在

### 应对策略

**保险策略**：
- 买入看跌期权对冲
- 持有现金或国债
- 使用尾部风险对冲产品

**组合分散**：
- 多策略组合
- 多资产配置
- 地域分散

**反脆弱设计**：
- 收益非线性（凸性）
- 波动有利于组合
- 极端情况反而受益

### 压力测试

```python
# 历史极端情景测试
stress_scenarios = [
    ("2008金融危机", returns_2008),
    ("2015股灾", returns_2015),
    ("2020疫情", returns_2020),
    ("2022俄乌冲突", returns_2022),
]

for name, scenario in stress_scenarios:
    portfolio_value = backtest_with_returns(scenario)
    drawdown = (portfolio_value - peak) / peak
    print(f"{name}: {drawdown:.1%}")
```

### 存活者偏差

- 每次极端行情后反思
- 记录教训，避免同样错误
- 但不要因噎废食

## 风险管理框架

### 事前风控

- 策略上线前进行风险评估
- 设置风险预算和限制
- 明确最大敞口

### 事中风控

- 实时监控风险指标
- 动态调整仓位
- 触发阈值自动执行

### 事后风控

- 定期复盘风险事件
- 更新风险模型
- 改进风控规则

## 风险管理检查清单

| 检查项 | 建议 |
|--------|------|
| 最大回撤 | <20% |
| 单日最大亏损 | <5% |
| 单策略权重 | <30% |
| 单行业权重 | <40% |
| 流动性覆盖 | 5天可清仓 |
| 杠杆率 | <2倍 |
| 预警/止损线 | 已设置并执行 |

## 常见错误

1. **忽视尾部风险**：只看VaR忽视CVaR
2. **过度自信**：低估极端事件概率
3. **规则不执行**：设了止损不执行
4. **风险收益不匹配**：追求高收益却不愿意承担相应风险
5. **分散不足**：过度集中于单一策略或资产
