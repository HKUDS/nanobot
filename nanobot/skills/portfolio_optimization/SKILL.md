---
name: portfolio-optimization
description: Use when discussing投资组合优化, 均值方差, 风险平价, 因子暴露控制, or 组合构建. Also use when user asks about Markowitz, portfolio construction, or asset allocation.
---

# 组合优化方法论

## 概述

组合优化是将多个投资标的或策略组合起来，在风险和收益之间寻求最优平衡的过程。现代投资组合理论为组合优化提供了数学框架，但在实际应用中需要考虑诸多现实约束。

## 均值-方差优化

### Markowitz模型

给定预期收益向量μ和协方差矩阵Σ，求解最小方差组合：

$$\min_w w^T Σ w$$
$$s.t. w^T μ = R_{target}$$
$$\sum w_i = 1$$

### 实现方法

```python
import numpy as np
from scipy.optimize import minimize

def mean_variance_optimize(expected_returns, cov_matrix, target_return):
    n = len(expected_returns)

    def portfolio_volatility(weights):
        return np.sqrt(weights @ cov_matrix @ weights)

    constraints = [
        {'type': 'eq', 'fun': lambda w: np.sum(w) - 1},
        {'type': 'eq', 'fun': lambda w: w @ expected_returns - target_return}
    ]
    bounds = tuple((0, 1) for _ in range(n))

    result = minimize(portfolio_volatility,
                     np.ones(n) / n,
                     method='SLSQP',
                     bounds=bounds,
                     constraints=constraints)
    return result.x
```

### 有效前沿

- 不同目标收益对应不同最优权重
- 有效前沿上的组合在给定风险下收益最高
- 投资者根据风险偏好选择有效前沿上的点

### 局限性

- 需要准确估计预期收益
- 对输入敏感
- 忽略交易成本

## 风险平价策略

### 核心思想

各资产对组合风险的贡献相等

### 实现

```python
def risk_parity_weights(cov_matrix):
    """风险平价权重"""
    n = cov_matrix.shape[0]

    def risk_contribution(weights):
        vol = np.sqrt(weights @ cov_matrix @ weights)
        marginal_contrib = cov_matrix @ weights
        risk_contrib = weights * marginal_contrib / vol
        return risk_contrib

    def objective(weights):
        rc = risk_contribution(weights)
        target_rc = rc.sum() / n
        return ((rc - target_rc) ** 2).sum()

    constraints = {'type': 'eq', 'fun': lambda w: np.sum(w) - 1}
    bounds = tuple((0.01, 1) for _ in range(n))

    result = minimize(objective,
                     np.ones(n) / n,
                     method='SLSQP',
                     bounds=bounds,
                     constraints=constraints)
    return result.x
```

### 优缺点

**优点**：
- 不需要预期收益
- 分散化效果好
- 稳健性强

**缺点**：
- 可能过度分散
- 忽略预期收益差异

## 因子暴露控制

### 概念

控制组合相对于基准的因子暴露

### 常见约束

| 约束类型 | 描述 |
|----------|------|
| 市值中性 | 组合市值β=0 |
| 行业中性 | 各行业权重=基准权重 |
| 风格中性 | 价值/成长β=0 |

### 实现示例

```python
def factor_neutral_optimize(expected_returns, cov_matrix,
                            factor_exposures, target_factor_exposure):
    n = len(expected_returns)
    k = factor_exposures.shape[1]

    def objective(weights):
        vol = np.sqrt(weights @ cov_matrix @ weights)
        return vol

    constraints = [
        {'type': 'eq', 'fun': lambda w: np.sum(w) - 1},
        {'type': 'eq', 'fun': lambda w: factor_exposures.T @ w - target_factor_exposure}
    ]
    bounds = tuple((0, 1) for _ in range(n))

    result = minimize(objective,
                     np.ones(n) / n,
                     method='SLSQP',
                     bounds=bounds,
                     constraints=constraints)
    return result.x
```

## 换手率约束

### 重要性

高换手率意味着高交易成本，可能侵蚀收益

### 约束方法

```python
def optimize_with_turnover(current_weights,
                          expected_returns, cov_matrix,
                          max_turnover=0.5):
    n = len(expected_returns)

    def objective(weights):
        vol = np.sqrt(weights @ cov_matrix @ weights)
        return vol

    turnover = np.abs(weights - current_weights).sum() / 2

    constraints = [
        {'type': 'eq', 'fun': lambda w: np.sum(w) - 1},
        {'type': 'ineq', 'fun': lambda w: max_turnover - turnover}
    ]
    bounds = tuple((0, 1) for _ in range(n))

    result = minimize(objective,
                     current_weights,
                     method='SLSQP',
                     bounds=bounds,
                     constraints=constraints)
    return result.x
```

### 实践建议

- 日线策略：换手率<100%/月
- 周线策略：换手率<50%/月
- 月线策略：换手率<20%/月

## 流动性考虑

### 流动性指标

| 指标 | 计算 | 阈值建议 |
|------|------|----------|
| 日均成交额 | AVG(成交额,20d) | >1000万 |
| 流动性比率 | 成交量/总股本 | >0.5% |
| 冲击成本 | 0.1%×成交量占比 | <0.5% |

### 流动性约束

```python
def optimize_with_liquidity(expected_returns, cov_matrix,
                           min_liquidity, max_position):
    n = len(expected_returns)

    def objective(weights):
        vol = np.sqrt(weights @ cov_matrix @ weights)
        return vol

    constraints = [
        {'type': 'eq', 'fun': lambda w: np.sum(w) - 1},
    ]
    bounds = []
    for liq in min_liquidity:
        max_w = min(1.0, max_position, liq * 5)  # 流动性约束
        bounds.append((0, max_w))

    result = minimize(objective,
                     np.ones(n) / n,
                     method='SLSQP',
                     bounds=bounds,
                     constraints=constraints)
    return result.x
```

## 实战组合构建流程

### Step 1: 明确投资目标

- 收益目标
- 风险容忍度
- 投资期限
- 流动性要求

### Step 2: 资产/策略选择

- 候选标的池
- 预期收益估计
- 协方差估计

### Step 3: 约束设定

- 权重上下限
- 换手率限制
- 因子暴露约束

### Step 4: 优化求解

- 选择优化方法
- 运行优化器

### Step 5: 结果分析

- 收益/风险特征
- 归因分析
- 敏感性测试

### Step 6: 实施与监控

- 建仓执行
- 定期再平衡
- 持续监控

## 组合优化常见问题

1. **估计误差放大**：预期收益估计误差导致组合表现差
2. **集中度风险**：优化结果可能过度集中
3. **忽略尾部风险**：只关注方差
4. **再平衡成本**：频繁再平衡增加成本

## 建议实践

- 使用稳健的估计方法（收缩估计）
- 设置合理的约束
- 定期回顾和调整
- 结合主观判断
- 关注交易成本

## 配套工具

### 组合管理

使用以下工具管理投资组合：

1. **qlib_backtest** - 组合回测验证
2. **paper_trading** - 模拟组合运行
3. **quant_data** - 获取持仓相关数据

### 优化脚本

参考 `portfolio_optimization` skill 中的 Python 示例：
- 均值-方差优化
- 风险平价权重计算
- 因子暴露控制
