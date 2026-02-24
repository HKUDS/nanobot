---
name: ai500
description: NOFX AI500 加密货币分析，提供 AI 评分排名、机构资金流向、持仓量变化、多空比、资金费率、订单簿热力图等专业数据。
metadata: {"nanobot":{"emoji":"🤖","os":["darwin","linux"],"requires":{"bins":["bash","curl","python3"]}}}
---

# AI500 Skill

通过 NOFX Data API 获取专业级加密货币实时分析数据。凭证存放在 `secret.env`。

## 执行方式

```bash
SKILL_DIR="$(find ~/.nanobot /root/.nanobot -path '*/skills/ai500' -type d 2>/dev/null | head -1)"
bash "$SKILL_DIR/run.sh" <command> [args...]
```

## 命令列表

### AI500 指数
```bash
bash run.sh ai500-list                  # AI评分>70的高潜力币种
bash run.sh ai500 BTCUSDT               # 特定交易对的AI分析
bash run.sh ai500-stats                 # AI500整体统计
```

### AI300 量化模型
```bash
bash run.sh ai300-list                  # AI300资金流量排名
bash run.sh ai300-stats                 # AI300信号统计
```

### 持仓量 (OI)
```bash
bash run.sh oi-top [duration]           # OI增幅最大排名
bash run.sh oi-low [duration]           # OI降幅最大排名
# duration: 1m 5m 15m 30m 1h 4h 8h 12h 24h 2d 3d 5d 7d（默认 1h）
```

### 资金流向
```bash
bash run.sh netflow-top [type] [duration]   # 净流入排名
bash run.sh netflow-low [type] [duration]   # 净流出排名
# type: Institutional（机构）| Personal（散户），默认 Institutional
```

### 行情数据
```bash
bash run.sh price-ranking [duration] [order]  # 涨跌幅排名（order: desc|asc）
bash run.sh coin BTCUSDT                       # 单币种综合数据
```

### 多空比
```bash
bash run.sh long-short-list             # 多空比异常信号列表
bash run.sh long-short BTCUSDT          # 特定币种多空比历史
```

### 资金费率
```bash
bash run.sh funding-top                 # 最高正费率（多头拥挤）
bash run.sh funding-low                 # 最低负费率（空头拥挤）
bash run.sh funding BTCUSDT             # 特定币种资金费率
```

### OI市值排名
```bash
bash run.sh oi-cap                      # 按OI价值排名
```

### Upbit 交易所
```bash
bash run.sh upbit-hot                   # Upbit热门币种
bash run.sh upbit-netflow-top           # Upbit净流入排名
bash run.sh upbit-netflow-low           # Upbit净流出排名
```

### 订单簿热力图
```bash
bash run.sh heatmap-future BTCUSDT      # 合约订单簿热力图
bash run.sh heatmap-spot BTCUSDT        # 现货订单簿热力图
bash run.sh heatmap-list                # 所有币种热力图概览
```

### 查询热度
```bash
bash run.sh query-rank                  # 今日查询最多的币种
```

## 配置

`secret.env`（需手动填写）：
```
NOFX_API_KEY=你的API密钥
```

`config.yaml`：
```yaml
base_url: https://nofxos.ai
```

## 结果与日志

- 每次结果写入 `memory/<command>.json`
- 错误追加到 `memory/error.log`
- 运行日志 `memory/run.log`

## 响应字段说明

| 字段 | 说明 |
|------|------|
| `oi_delta_percent` | OI变化百分比（已×100，5.0=5%） |
| `price_delta_percent` | 价格变化百分比（已×100） |
| `price_delta` | 价格变化比例（小数，0.05=5%） |
| `amount` | 资金流向（USDT，正=流入，负=流出） |
| `funding_rate` | 资金费率（已×100，0.01=0.01%） |
| `ai500.score` | AI综合评分（0-100） |
