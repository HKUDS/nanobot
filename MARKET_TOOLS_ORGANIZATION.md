# 市场数据工具 - 文件组织说明

## 📁 文件夹结构

```
nanobot/
├── tests/market_tools/          # 测试脚本文件夹
│   ├── README.md                # 测试脚本使用说明
│   ├── test_stock.py            # A股基础测试
│   ├── test_a_share_simple.py   # A股简化测试（推荐）
│   ├── test_a_share.py          # A股全面测试
│   ├── test_crypto.py           # 加密货币测试
│   ├── test_all_markets.py      # 全市场测试
│   ├── test_quick_markets.py    # 快速市场测试
│   ├── test_akshare_quick.py    # akshare API快速测试
│   ├── test_akshare_apis.py     # akshare API详细测试
│   └── test_agent_model.py      # Agent模型测试
│
└── docs/market_tools/           # 测试文档文件夹
    ├── AGENT_FIX_REPORT.md              # Agent修复报告
    ├── AKSHARE_API_TEST_RESULTS.md      # akshare API测试结果
    ├── A_SHARE_TEST_REPORT.md           # A股测试报告
    ├── FINAL_MARKET_TOOLS_TEST.md       # 市场工具最终测试报告
    ├── MARKET_PY_FIX_REPORT.md          # market.py修复报告
    └── MARKET_TOOLS_TEST_REPORT.md      # 市场工具测试报告
```

---

## 📝 快速开始

### 运行测试

#### 1. A股功能测试（推荐）
```bash
python tests/market_tools/test_a_share_simple.py
```

#### 2. A股全面测试
```bash
python tests/market_tools/test_a_share.py
```

#### 3. 查看akshare API可用性
```bash
python tests/market_tools/test_akshare_quick.py
```

#### 4. 加密货币测试
```bash
python tests/market_tools/test_crypto.py
```

### 查看文档

所有测试报告和文档都在 `docs/market_tools/` 文件夹中：

- **A_SHARE_TEST_REPORT.md** - 最新的A股测试结果和性能分析
- **MARKET_PY_FIX_REPORT.md** - market.py接口修复详情
- **AKSHARE_API_TEST_RESULTS.md** - akshare各API的可用性统计

---

## 🔧 核心文件

### 源代码
- `nanobot/agent/tools/market.py` - 市场数据工具实现

### 配置文件
- `C:\Users\Administrator\.nanobot\config.json` - nanobot配置

---

## ✅ 当前状态

| 功能 | 状态 | 说明 |
|------|------|------|
| A股实时行情 | ✅ 正常 | 支持所有A股代码 |
| A股历史数据 | ✅ 正常 | 支持自定义天数查询 |
| 港股实时行情 | ✅ 正常 | 需要港股代码 |
| 美股实时行情 | ⚠️ 部分可用 | 有备用方案，但可能不稳定 |
| 加密货币 | ⚠️ 部分可用 | 仅支持BTC、LTC等少数币种 |
| ETF基金 | ✅ 正常 | 支持ETF查询 |
| 外汇牌价 | ✅ 正常 | 支持主要货币对 |

---

## 📊 测试覆盖率

- **测试脚本数量**: 9个
- **测试文档数量**: 6个
- **覆盖的功能模块**:
  - ✅ A股实时和历史数据
  - ✅ 错误处理和重试机制
  - ✅ 缓存机制
  - ✅ 数据格式化
  - ✅ 边界情况处理

---

## 🎯 维护建议

1. **定期运行测试**: 每周运行一次 `test_a_share_simple.py` 确保功能正常
2. **更新文档**: 每次修复后更新相应的测试报告
3. **清理旧文件**: 超过3个月的测试报告可以归档或删除
4. **保持简洁**: 新的测试脚本优先添加到 `tests/market_tools/` 文件夹

---

## 📞 联系方式

如有问题或建议，请查看项目主README或提交Issue。

**最后更新时间**: 2026-05-07
