# OKX Trade Skill

OKX 交易系统技能，支持账户查询、下单、撤单等操作。

## 目录结构

```
okx_trade/
├── run.sh          # 主入口脚本
├── secret.env      # API 凭证（不提交 Git）
├── config.yaml     # 配置文件
└── memory/         # 运行日志和结果（自动创建）
```

## 配置

### 1. 填写 API 凭证

编辑 `secret.env`：

```bash
OKX_API_KEY=你的API密钥
OKX_SECRET_KEY=你的Secret密钥
OKX_PASSPHRASE=你的Passphrase
```

### 2. 编辑配置

编辑 `config.yaml`：

```yaml
is_demo: true          # true=模拟交易, false=实盘
base_url: https://www.okx.com
```

### 获取 API 密钥

1. 登录 OKX 账户
2. 进入 **个人中心** > **API**
3. 创建 API Key，设置权限（读取 + 交易）
4. 保存 API Key、Secret Key 和 Passphrase

## 用法

```bash
# 查询账户余额
bash run.sh balance

# 查询持仓
bash run.sh positions [SWAP|SPOT|FUTURES]

# 查询行情
bash run.sh ticker BTC-USDT-SWAP

# 下单（市价）
bash run.sh order BTC-USDT-SWAP buy market 1

# 下单（限价）
bash run.sh order BTC-USDT-SWAP sell limit 1 95000

# 撤单
bash run.sh cancel BTC-USDT-SWAP <order_id>

# 查询订单历史
bash run.sh history [SWAP] [100]
```

## 输出

每次运行结果保存在 `memory/`：
- `last_result.json` — 最近一次 API 响应
- `run.log` — 运行日志

## 安全提示

- `secret.env` 已在 `.gitignore` 中，不会提交到 Git
- 先用 `is_demo: true` 测试，确认无误再切换实盘
- 建议在 OKX 后台设置 IP 白名单
