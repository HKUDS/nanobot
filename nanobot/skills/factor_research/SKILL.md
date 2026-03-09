---
name: factor-research
description: Use when discussing因子研究, IC analysis, ICIR, 因子衰减, 因子正交化, or因子权重优化. Also use when user asks about factor investing, factor research methodology, or building因子库.
---

# 因子研究方法

## 概述

因子投资是量化投资的核心方法论。有效的因子研究需要严谨的统计方法和深入的经济逻辑支撑。本技能涵盖从因子发现到因子应用的完整流程。

## IC (Information Coefficient)

### 定义

IC = 因子值与下期收益的相关系数

$$IC = \rho(F_{rank}, R_{t+1})$$

### 解读

| IC值 | 评级 | 含义 |
|------|------|------|
| >0.05 | 优秀 | 因子预测能力强 |
| 0.03-0.05 | 良好 | 因子有一定预测能力 |
| 0.01-0.03 | 一般 | 因子预测能力较弱 |
| <0.01 | 较差 | 因子几乎无预测能力 |

### IC计算

```python
import pandas as pd
import numpy as np
from scipy.stats import spearmanr

def calculate_ic(returns, factor):
    """计算IC（Spearman相关系数）"""
    # 去除NaN
    valid_data = returns.dropna()
    factor_aligned = factor.loc[valid_data.index]

    # Spearman相关
    ic, p_value = spearmanr(factor_aligned, valid_data)
    return ic
```

### IC时序图

- 观察IC的时序稳定性
- 识别IC失效的时期
- 分析失效原因

## ICIR (IC Information Ratio)

### 定义

$$ICIR = \frac{Mean(IC)}{Std(IC)}$$

### 解读

| ICIR值 | 评级 |
|--------|------|
| >1.0 | 优秀 |
| 0.5-1.0 | 良好 |
| <0.5 | 一般 |

### 含义

- ICIR衡量因子预测能力的稳定性
- 高IC但不稳定 ≠ 好因子
- ICIR高表示因子持续有效

## 因子衰减分析

### 持有期衰减

因子预测能力随持有期的变化：

```python
def factor_decay_analysis(factor, returns, max_horizon=20):
    """分析因子在不同持有期的IC"""
    ic_by_horizon = {}
    for h in range(1, max_horizon + 1):
        shifted_returns = returns.shift(-h)
        ic = calculate_ic(shifted_returns, factor)
        ic_by_horizon[h] = ic
    return ic_by_horizon
```

### 衰减模式

| 模式 | 描述 | 策略建议 |
|------|------|----------|
| 持续型 | IC随时间缓慢衰减 | 适合长周期策略 |
| 短期型 | IC快速衰减 | 适合日内/短线 |
| 周期型 | IC周期性变化 | 需动态调整 |

### 最佳持有期

- 选择IC最高的持有期
- 考虑换手率和 权衡收益交易成本
-和执行难度

## 因子正交化方法

### 为什么要正交化

- 去除因子间的共线性
- 分离因子独立贡献
- 提高因子组合稳定性

### 方法1：残差法

```python
from sklearn.linear_model import LinearRegression

def orthogonalize(target_factor, base_factors):
    """残差法正交化"""
    X = base_factors.values
    y = target_factor.values

    model = LinearRegression()
    model.fit(X, y)

    residual = y - model.predict(X)
    return pd.Series(residual, index=target_factor.index)
```

### 方法2：施密特正交化

```python
def gram_Schmidt(factors):
    """施密特正交化"""
    import numpy as np
    Q, R = np.linalg.qr(factors.values)
    return pd.DataFrame(Q, index=factors.index)
```

### 方法3：因子正交

- 对因子进行行业、市值中性化
- 常用回归方法

## 因子权重优化

### 因子权重方法

| 方法 | 描述 | 优点 | 缺点 |
|------|------|------|------|
| 等权 | 各因子权重相等 | 简单 | 未考虑因子质量 |
| IC加权 | 按IC均值加权 | 反映预测能力 | 可能过度集中 |
| ICIR加权 | 按ICIR加权 | 考虑稳定性 | 计算复杂 |
| 风险平价 | 风险贡献相等 | 分散风险 | 权重可能极端 |

### IC加权示例

```python
def ic_weighted_portfolio(factors_ic, target_vol=0.15):
    """IC加权组合"""
    # 标准化IC
    ic_mean = factors_ic.mean()
    ic_std = factors_ic.std()
    ic_score = (ic_mean - ic_std) / ic_mean.std()

    # 权重
    weights = ic_score / ic_score.sum()

    # 调整到目标波动率
    portfolio_vol = factors_vol.dot(weights)
    weights = weights * (target_vol / portfolio_vol)

    return weights
```

## 因子库的构建与维护

### 因子分类框架

```
因子库
├── 基本面因子
│   ├── 价值因子（PE, PB, 股息率）
│   ├── 成长因子（营收增速、利润增速）
│   └── 质量因子（ROE、资产负债率）
├── 技术面因子
│   ├── 动量因子（20日、60日收益）
│   ├── 波动率因子
│   └── 流动性因子
└── 另类因子
    ├── 分析师预期
    └── 资金流向
```

### 因子入库标准

| 指标 | 入库阈值 |
|------|----------|
| IC均值 | >0.02 |
| ICIR | >0.3 |
| 覆盖率 | >80% |
| 样本外IC | >0.01 |

### 因子维护

- **定期监控**：每月评估因子有效性
- **动态调整**：根据市场环境调整权重
- **淘汰机制**：IC持续低于阈值则剔除

## 分组回测

### 方法

- 按因子值分为N组
- 第一组vs第N组构成多空组合
- 观察各组收益 monotonic

```python
def group_backtest(factor, returns, n_groups=5):
    """分组回测"""
    # 分组
    factor_rank = factor.rank()
    group_labels = pd.qcut(factor_rank, n_groups, labels=False)

    # 各组收益
    group_returns = returns.groupby(group_labels).mean()

    # 多空收益
    long_short = group_returns.iloc[-1] - group_returns.iloc[0]

    return group_returns, long_short
```

### 分组单调性

- 理想情况下各组收益呈单调关系
- 单调性好说明因子稳定

## 因子研究流程

### 标准流程

1. **因子构思**：基于经济逻辑或数据挖掘
2. **数据处理**：清洗、标准化、去极值
3. **IC分析**：计算IC序列和ICIR
4. **分组回测**：验证因子预测能力
5. **衰减分析**：确定最佳持有期
6. **正交化处理**：去除冗余
7. **样本外验证**：留出数据测试
8. **因子入库**：加入因子库

### 注意事项

- 先有逻辑再有数据
- 避免过度拟合
- 样本外验证必须通过
- 持续跟踪因子表现

## 常见问题

1. **IC高但分组回测不单调**：数据处理问题或因子非线性
2. **IC不稳定**：可能因子周期性强或失效
3. **因子相关性高**：需要正交化
4. **样本外IC下降**：可能过拟合

## 配套工具

### Scripts

本 skill 提供以下脚本，位于 `{baseDir}/scripts/`：

#### calculate_ic.py
计算因子 IC 和 ICIR。

```bash
python {baseDir}/scripts/calculate_ic.py \
  --factor factor.csv \
  --returns returns.csv \
  --output ic_report.json
```

#### group_backtest.py
因子分组回测。

```bash
python {baseDir}/scripts/group_backtest.py \
  --factor factor.csv \
  --returns returns.csv \
  --n-groups 5
```

### References

因子入库标准参考：

| 指标 | 入库阈值 |
|------|----------|
| IC均值 | >0.02 |
| ICIR | >0.3 |
| 覆盖率 | >80% |
| 样本外IC | >0.01 |

### 数据获取

使用 `quant_data` Tool 获取实时市场数据：
- 北向资金流向
- 行业板块涨跌
- 个股行情
