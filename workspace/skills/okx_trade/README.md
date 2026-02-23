# OKX Trading Skill

OKX 交易系统技能，支持账户查询、下单、撤单等操作。

## 配置

### 自动安装（推荐）

运行安装脚本自动创建配置：

```bash
python3 workspace/skills/okx_trade/setup.py
```

然后编辑配置文件填入你的 API 凭证：

```bash
nano ~/.nanobot/workspace/skills/okx_trade/config.json
```

### 手动安装

1. 在用户工作目录创建配置文件：
   ```bash
   mkdir -p ~/.nanobot/workspace/skills/okx_trade
   cp workspace/skills/okx_trade/config.example.json ~/.nanobot/workspace/skills/okx_trade/config.json
   ```

2. 编辑配置文件，填入你的 OKX API 凭证：
   ```bash
   nano ~/.nanobot/workspace/skills/okx_trade/config.json
   ```

   ```json
   {
     "api_key": "YOUR_OKX_API_KEY",
     "secret_key": "YOUR_OKX_SECRET_KEY",
     "passphrase": "YOUR_OKX_PASSPHRASE",
     "is_demo": true,
     "base_url": "https://www.okx.com"
   }
   ```

**配置文件位置优先级：**
1. `~/.nanobot/workspace/skills/okx_trade/config.json` (推荐，用户配置)
2. `workspace/skills/okx_trade/config.json` (备用，项目目录)

### 获取 API 密钥

1. 登录 OKX 账户
2. 进入 **个人中心** > **API**
3. 创建 API Key，设置权限：
   - 读取：查询账户信息
   - 交易：下单、撤单
4. 保存 API Key、Secret Key 和 Passphrase

### 模拟交易

- `is_demo: true` - 使用模拟交易（推荐测试时使用）
- `is_demo: false` - 使用实盘交易

## 功能

### 1. 查询账户余额

```python
balance = await skill.get_account_balance()
```

### 2. 查询持仓

```python
positions = await skill.get_positions(inst_type="SWAP")
```

### 3. 下单

```python
# 市价买入
result = await skill.place_order(
    inst_id="BTC-USDT-SWAP",
    side="buy",
    order_type="market",
    size="1"
)

# 限价卖出
result = await skill.place_order(
    inst_id="BTC-USDT-SWAP",
    side="sell",
    order_type="limit",
    size="1",
    price="50000"
)
```

### 4. 撤单

```python
result = await skill.cancel_order(
    inst_id="BTC-USDT-SWAP",
    order_id="123456789"
)
```

### 5. 查询订单历史

```python
history = await skill.get_order_history(inst_type="SWAP", limit=50)
```

### 6. 查询行情

```python
ticker = await skill.get_ticker(inst_id="BTC-USDT-SWAP")
```

## 使用示例

```python
import asyncio
from okx_trade import OKXTradeSkill

async def main():
    skill = OKXTradeSkill()

    # 查询余额
    balance = await skill.get_account_balance()
    print("Balance:", balance)

    # 查询 BTC 行情
    ticker = await skill.get_ticker("BTC-USDT-SWAP")
    print("BTC Price:", ticker)

    # 查询持仓
    positions = await skill.get_positions()
    print("Positions:", positions)

if __name__ == "__main__":
    asyncio.run(main())
```

## 安全提示

⚠️ **重要安全建议**：

1. **不要将 API 密钥提交到 Git** - `config.json` 已在 `.gitignore` 中
2. 使用 `config.example.json` 作为模板
3. 限制 API 权限，只开启必要的权限
4. 定期更换 API 密钥
5. 先在模拟环境测试，确认无误后再使用实盘
6. 设置 IP 白名单限制 API 访问

## 依赖

```bash
pip install httpx
```

## 参考文档

- [OKX API 文档](https://www.okx.com/docs-v5/zh/)
