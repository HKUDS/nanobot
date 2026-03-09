---
name: ml-quant
description: Use when discussing machine learning in quantitative投资, ML模型选择, 特征工程, 过拟合防范, SHAP, or 集成学习. Also use when user asks about 树模型, 神经网络, or ML量化策略.
---

# ML量化方法论

## 概述

机器学习在量化投资中的应用日益广泛。本技能涵盖ML在量化领域应用的核心方法和最佳实践，包括特征工程、模型选择、过拟合防范和模型解释性。

## 特征工程要点

### 特征类型

| 类型 | 示例 | 处理要点 |
|------|------|----------|
| 原始特征 | 价格、成交量 | 清洗缺失值 |
| 衍生特征 | 收益率、变化率 | 选择合适窗口 |
| 交叉特征 | PE×ROE | 防止维度灾难 |
| 滞后特征 | lag(returns, 1) | 避免前视偏差 |

### 特征处理

```python
# 标准化
from sklearn.preprocessing import StandardScaler
scaler = StandardScaler()
features_scaled = scaler.fit_transform(features)

# 去极值
def winsorize(data, lower=0.01, upper=0.99):
    q_low = data.quantile(lower)
    q_high = data.quantile(upper)
    return data.clip(q_low, q_high)
```

### 特征选择

- **过滤法**：相关性分析、卡方检验
- **包装法**：递归特征消除
- **嵌入法**：L1正则化、树模型特征重要性

## 模型选择

### 树模型

**优点**：
- 可解释性强
- 对异常值不敏感
- 可以处理非线性关系

**常用算法**：
- XGBoost
- LightGBM
- CatBoost

### 神经网络

**优点**：
- 可以学习复杂模式
- 适合大规模数据

**缺点**：
- 可解释性差
- 容易过拟合
- 训练时间长

### 模型选择建议

| 数据量 | 推荐模型 |
|--------|----------|
| <1万 | 线性模型、简单树模型 |
| 1万-10万 | LightGBM、XGBoost |
| >10万 | 深度学习、集成模型 |

### 量化常用模型

```python
# LightGBM示例
import lightgbm as lgb

model = lgb.LGBMClassifier(
    n_estimators=100,
    learning_rate=0.05,
    max_depth=5,
    num_leaves=31,
    random_state=42
)
```

## 过拟合防范

### 核心原则

- **数据量**：样本数 >> 特征数 × 参数数
- **验证**：始终使用样本外数据
- **正则化**：使用L1/L2、Dropout等
- **简化**：参数越少越好

### 防止过拟合技巧

1. **Early Stopping**
```python
from sklearn.model_selection import train_test_split

X_train, X_test = train_test_split(X, test_size=0.2)
model.fit(X_train, y_train,
          eval_set=[(X_test, y_test)],
          early_stopping_rounds=50)
```

2. **交叉验证**
```python
from sklearn.model_selection import TimeSeriesSplit

tscv = TimeSeriesSplit(n_splits=5)
for train_idx, test_idx in tscv.split(X):
    # 时序交叉验证
    pass
```

3. **正则化**
```python
# L1+L2正则化
model = Ridge(alpha=1.0, lasso_alpha=0.1)
```

4. **Dropout（神经网络）**
```python
model.add(Dropout(0.3))
```

### 过拟合信号

- 训练集表现远好于测试集
- 测试集指标波动大
- 复杂模型简单数据

## 特征重要性分析

### 树模型重要性

```python
# 特征重要性
feature_importance = pd.Series(
    model.feature_importances_,
    index=features.columns
).sort_values(ascending=False)
```

### 排列重要性

```python
from sklearn.inspection import permutation_importance

perm_importance = permutation_importance(
    model, X_test, y_test, n_repeats=10
)
```

### 重要性解读

- 高重要性特征贡献大
- 但可能是过拟合导致的
- 需要结合业务逻辑判断

## 模型解释性 (SHAP)

### SHAP值

SHAP (SHapley Additive exPlanations) 解释每个特征对预测的贡献：

```python
import shap

explainer = shap.TreeExplainer(model)
shap_values = explainer.shap_values(X)

# 特征重要性
shap.summary_plot(shap_values, X)
```

### SHAP解读

- **正值**：特征推动预测向上
- **负值**：特征推动预测向下
- **颜色**：特征值高低

### 可解释性实践

- 关键决策需要可解释性
- SHAP可以帮助发现模型问题
- 但不要过度依赖解释

## 集成学习

### Bagging

- 随机森林
- 样本有放回抽样
- 降低方差

### Boosting

- XGBoost、LightGBM
- 串行学习
- 降低偏差

### Stacking

- 多模型组合
- 元学习器融合
- 适合异构模型

### 集成实践

```python
# 简单集成
predictions = (
    model1.predict_proba(X) * 0.3 +
    model2.predict_proba(X) * 0.3 +
    model3.predict_proba(X) * 0.4
)
```

## ML量化策略流程

### 完整流程

1. **数据准备**
   - 原始数据获取
   - 特征构建
   - 数据清洗

2. **特征选择**
   - 相关性分析
   - 重要性筛选
   - 共线性检测

3. **模型训练**
   - 样本内训练
   - 超参数调优
   - Early stopping

4. **验证测试**
   - 样本外测试
   - 时序验证
   - 蒙特卡洛模拟

5. **上线监控**
   - 实时预测
   - 漂移检测
   - 定期重训

### 时序注意事项

- **不能用未来数据**：严格避免前视偏差
- **滑动窗口**：使用滚动窗口训练
- **时序切分**：不能用随机切分

```python
# 正确做法：时序切分
train_data = data[:'2020-12-31']
test_data = data['2021-01-01':]

# 滚动训练
for date in test_dates:
    train_window = data[date-window:date]
    model.fit(train_window)
    predictions.append(model.predict(current))
```

## ML在量化中的注意事项

1. **数据质量 > 模型复杂度**
2. **简单模型往往更稳健**
3. **不要迷信模型预测**
4. **持续监控模型表现**
5. **考虑交易成本**

## 常见陷阱

1. **前视偏差**：使用了未来数据
2. **幸存者偏差**：只使用当前存在的股票
3. **过度拟合**：复杂模型在小数据上
4. **数据挖掘**：偶然发现但无经济逻辑
5. **忽视交易成本**：回测成本过低

## 配套工具

### 数据获取

使用以下工具获取 ML 所需数据：

1. **quant_data** - 实时/历史行情数据
2. **db_reader** - 本地数据库查询

### 回测验证

使用 **qlib_backtest** Tool：
- 时序交叉验证
- 样本外测试
- 因子 IC 分析

### 特征工程脚本

本项目提供参考脚本：
- 数据清洗标准化
- 特征构建示例
- 模型训练流程
