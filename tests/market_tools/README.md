# 市场数据工具测试脚本

本文件夹包含 nanobot 项目中市场数据工具（market.py）的所有测试脚本。

## 📁 文件说明

### 核心测试脚本

#### 1. test_stock.py
**用途**: A股实时行情基础测试
**测试内容**:
- A股实时价格查询
- 多股票测试

**运行方式**:
```bash
python tests/market_tools/test_stock.py
```

---

#### 2. test_a_share_simple.py
**用途**: A股功能简化测试（推荐）
**测试内容**:
- A股实时行情
- A股历史数据
- 多个股票测试

**运行方式**:
```bash
python tests/market_tools/test_a_share_simple.py
```

---

#### 3. test_a_share.py
**用途**: A股功能全面测试
**测试内容**:
- 实时行情测试
- 历史数据测试（不同天数）
- 边界情况测试
- 缓存机制测试

**运行方式**:
```bash
python tests/market_tools/test_a_share.py
```

---

#### 4. test_crypto.py
**用途**: 加密货币价格测试
**测试内容**:
- BTC价格查询
- ETH价格查询

**运行方式**:
```bash
python tests/market_tools/test_crypto.py
```

---

### API可用性测试

#### 5. test_akshare_quick.py
**用途**: akshare API快速可用性测试
**测试内容**:
- 股票市场API（A股、港股、美股）
- 指数、基金、期货、外汇
- 加密货币、债券、宏观数据

**运行方式**:
```bash
python tests/market_tools/test_akshare_quick.py
```

---

#### 6. test_akshare_apis.py
**用途**: akshare API详细测试（完整报告）
**测试内容**:
- 所有主要akshare API接口
- 详细的成功/失败分析
- 生成测试结果文件

**运行方式**:
```bash
python tests/market_tools/test_akshare_apis.py
```

---

### 其他测试脚本

#### 7. test_all_markets.py
**用途**: 全市场测试（A股、港股、美股、加密货币）
**注意**: 美股数据加载较慢，可能需要较长时间

**运行方式**:
```bash
python tests/market_tools/test_all_markets.py
```

---

#### 8. test_quick_markets.py
**用途**: 快速市场测试（优化版）
**特点**: 避免加载全部美股数据，速度更快

**运行方式**:
```bash
python tests/market_tools/test_quick_markets.py
```

---

#### 9. test_agent_model.py
**用途**: nanobot agent模型测试
**测试内容**:
- Provider创建
- Chat功能测试

**运行方式**:
```bash
python tests/market_tools/test_agent_model.py
```

---

## 🎯 推荐使用顺序

### 快速验证（推荐）
```bash
# 1. 测试A股基本功能
python tests/market_tools/test_a_share_simple.py

# 2. 测试API可用性
python tests/market_tools/test_akshare_quick.py
```

### 全面测试
```bash
# 1. 全面测试A股功能
python tests/market_tools/test_a_share.py

# 2. 测试加密货币
python tests/market_tools/test_crypto.py

# 3. 详细API测试
python tests/market_tools/test_akshare_apis.py
```

---

## 📊 测试结果

测试完成后，详细的测试报告会保存在 `docs/market_tools/` 文件夹中。

---

## 🔧 依赖要求

- Python 3.11+
- akshare库
- nanobot项目环境

安装依赖：
```bash
pip install akshare
```

---

## 📝 注意事项

1. **首次运行较慢**: A股数据需要加载全市场5000+股票，首次请求约15-20秒
2. **网络要求**: 部分API可能需要稳定的网络连接
3. **缓存机制**: 60秒内重复请求会使用缓存，速度更快
4. **代理设置**: 测试脚本会自动禁用代理以避免连接问题

---

## 📖 相关文档

详细测试报告请查看 `docs/market_tools/` 文件夹中的文档。
