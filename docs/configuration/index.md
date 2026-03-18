# 設定總覽

Nanobot 使用單一 JSON 設定檔管理所有行為，包括 AI 模型、聊天頻道、工具以及閘道伺服器。

---

## 設定檔位置

預設設定檔路徑為：

```
~/.nanobot/config.json
```

執行 `nanobot onboard` 互動式精靈會自動在此路徑建立設定檔。

### 使用自訂路徑

透過 `-c` / `--config` 旗標可指定任意路徑的設定檔：

```bash
# 啟動閘道時指定設定檔
nanobot gateway --config ~/.nanobot-work/config.json

# 執行 CLI Agent 時指定設定檔
nanobot agent -c ~/.nanobot-personal/config.json -m "你好！"
```

> [!TIP]
> 多執行個體部署時，每個執行個體使用獨立的設定檔路徑。詳見[多執行個體指南](./multi-instance.md)。

---

## 設定檔格式

設定檔為標準 JSON，支援 **camelCase**（駝峰式）與 **snake_case**（底線式）兩種鍵名，兩者可混用：

```json
{
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5",
      "maxTokens": 8192,
      "max_tool_iterations": 40
    }
  }
}
```

> [!NOTE]
> 標準 JSON 不支援註解（`//`）。本文件的範例中有時使用 `// 說明` 僅供閱讀，實際設定檔請勿包含註解。

---

## Pydantic 驗證

Nanobot 使用 [Pydantic](https://docs.pydantic.dev/) 解析並驗證設定。啟動時若設定格式有誤，程式會立即報錯並指出問題所在，不會靜默忽略無效值。

---

## 環境變數支援

所有設定選項均可透過環境變數覆蓋，前綴為 `NANOBOT_`，巢狀鍵以雙底線 `__` 分隔：

| 環境變數 | 對應設定 |
|----------|----------|
| `NANOBOT_AGENTS__DEFAULTS__MODEL` | `agents.defaults.model` |
| `NANOBOT_PROVIDERS__ANTHROPIC__API_KEY` | `providers.anthropic.api_key` |
| `NANOBOT_GATEWAY__PORT` | `gateway.port` |
| `NANOBOT_TOOLS__EXEC__TIMEOUT` | `tools.exec.timeout` |

環境變數的優先順序高於設定檔中的值，適合在 Docker 或 CI/CD 環境中注入機密資訊。

```bash
# 範例：用環境變數設定 API 金鑰
export NANOBOT_PROVIDERS__ANTHROPIC__API_KEY="sk-ant-..."
nanobot gateway
```

---

## 頂層鍵速查表

| 鍵 | 型別 | 說明 |
|----|------|------|
| [`agents`](./reference.md#agents) | 物件 | Agent 預設行為（模型、工作區、Token 限制等） |
| [`channels`](./reference.md#channels) | 物件 | 聊天頻道設定（Slack、Discord、Telegram 等） |
| [`providers`](./reference.md#providers) | 物件 | LLM 供應商 API 金鑰與端點 |
| [`gateway`](./reference.md#gateway) | 物件 | HTTP 閘道伺服器（主機、埠號、心跳） |
| [`tools`](./reference.md#tools) | 物件 | 工具設定（網路搜尋、Shell 執行、MCP 伺服器等） |

---

## 最小可用設定範例

以下為僅需 Telegram 頻道與 Anthropic 模型的最小設定：

```json
{
  "providers": {
    "anthropic": {
      "apiKey": "sk-ant-..."
    }
  },
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "allowFrom": ["YOUR_USER_ID"]
    }
  }
}
```

未列出的選項均使用預設值，無須明確設定。

---

## 延伸閱讀

- [完整設定參考](./reference.md) — 每個選項的詳細說明與預設值
- [多執行個體指南](./multi-instance.md) — 同時執行多個 Nanobot 執行個體
- [CLI 參考](../cli-reference.md) — 所有命令列旗標
