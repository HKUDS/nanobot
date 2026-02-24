# AI500 Skill

NOFX Data API 技能，提供 AI 驱动的加密货币评分、机构资金流向、持仓量变化、多空比、资金费率等专业数据。

## 目录结构

```
ai500/
├── run.sh          # 主入口脚本
├── secret.env      # API 密钥（不提交 Git）
├── config.yaml     # 配置文件
└── memory/         # 运行日志和结果（自动创建）
```

## 配置

编辑 `secret.env`：

```
NOFX_API_KEY=你的API密钥
```

> 注意：直接写值，不加引号，不加空格。

在 [nofxos.ai](https://nofxos.ai) 获取 API Key。

## 用法

```bash
bash run.sh <command> [args...]
```

### AI500 指数

```bash
bash run.sh ai500-list                    # AI评分>70的高潜力币种
bash run.sh ai500 BTCUSDT                 # 特定交易对的AI分析
bash run.sh ai500-stats                   # AI500整体统计
```

### AI300 量化模型

```bash
bash run.sh ai300-list                    # 资金流量排名
bash run.sh ai300-stats                   # 信号统计
```

### 持仓量 (OI)

```bash
bash run.sh oi-top [duration]             # OI增幅最大排名
bash run.sh oi-low [duration]             # OI降幅最大排名
```

### 资金流向

```bash
bash run.sh netflow-top [type] [duration] # 净流入排名
bash run.sh netflow-low [type] [duration] # 净流出排名
# type: Institutional（机构）| Personal（散户），默认 Institutional
```

### 行情数据

```bash
bash run.sh price-ranking [duration] [order]  # 涨跌幅排名
bash run.sh coin BTCUSDT                       # 单币种综合数据
```

### 多空比

```bash
bash run.sh long-short-list               # 异常信号列表
bash run.sh long-short BTCUSDT            # 特定币种历史
```

### 资金费率

```bash
bash run.sh funding-top                   # 最高正费率（多头拥挤）
bash run.sh funding-low                   # 最低负费率（空头拥挤）
bash run.sh funding BTCUSDT               # 特定币种费率
```

### 其他

```bash
bash run.sh oi-cap                        # OI市值排名
bash run.sh upbit-hot                     # Upbit热门币种
bash run.sh upbit-netflow-top             # Upbit净流入排名
bash run.sh upbit-netflow-low             # Upbit净流出排名
bash run.sh heatmap-future BTCUSDT        # 合约订单簿热力图
bash run.sh heatmap-spot BTCUSDT          # 现货订单簿热力图
bash run.sh heatmap-list                  # 所有币种热力图概览
bash run.sh query-rank                    # 今日查询热度排名
```

## duration 可选值

`1m` `5m` `15m` `30m` `1h` `4h` `8h` `12h` `24h` `2d` `3d` `5d` `7d`（默认 `1h`）

## 输出

每次结果保存在 `memory/`：
- `<command>.json` — API 响应
- `error.log` — 失败记录
- `run.log` — 运行日志
