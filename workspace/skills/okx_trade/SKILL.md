---
name: okx_trade
description: OKX 交易系统，支持查询账户余额、持仓、行情，以及下单、撤单、查询历史订单。
metadata: {"nanobot":{"emoji":"📈","os":["darwin","linux"],"requires":{"bins":["bash","curl","openssl","python3"]}}}
---

# OKX Trade Skill

通过 OKX API 执行交易操作。凭证存放在 `secret.env`，配置在 `config.yaml`。

## 执行方式

所有操作通过 `run.sh` 执行：

```bash
SKILL_DIR="$(find ~/.nanobot /root/.nanobot -path '*/skills/okx_trade' -type d 2>/dev/null | head -1)"
bash "$SKILL_DIR/run.sh" <command> [args...]
```

## 命令

### 查询余额
```bash
bash run.sh balance
# 结果 → memory/balance_result.json
```

### 查询持仓
```bash
bash run.sh positions [SWAP|SPOT|FUTURES|MARGIN]
# 结果 → memory/positions_result.json
```

### 查询行情
```bash
bash run.sh ticker BTC-USDT-SWAP
# 结果 → memory/ticker_result.json
```

### 下单
```bash
# 市价买入
bash run.sh order BTC-USDT-SWAP buy market 1

# 限价卖出
bash run.sh order BTC-USDT-SWAP sell limit 1 95000

# 结果 → memory/order_result.json
```

### 撤单
```bash
bash run.sh cancel BTC-USDT-SWAP <order_id>
# 结果 → memory/cancel_result.json
```

### 历史订单
```bash
bash run.sh history [SWAP] [100]
# 结果 → memory/history_result.json
```

## 配置

`secret.env`（需手动填写）：
```
OKX_API_KEY=你的API密钥
OKX_SECRET_KEY=你的Secret密钥
OKX_PASSPHRASE=你的Passphrase
```

`config.yaml`：
```yaml
is_demo: true    # true=模拟交易, false=实盘
base_url: https://www.okx.com
```

## 结果与日志

- 每次结果写入 `memory/<command>_result.json`
- 错误追加到 `memory/trade_error.log`
- 运行日志 `memory/run.log`

## 错误排查

| 错误码 | 原因 | 修复 |
|--------|------|------|
| 50101 | API Key 与环境不匹配 | 检查 `is_demo` 是否与 Key 类型一致 |
| 50102 | 时间戳过期 | 确认服务器时间已同步（NTP） |
| 50111 | 签名错误 | 检查 `secret.env` 中的 key 无多余空格 |
