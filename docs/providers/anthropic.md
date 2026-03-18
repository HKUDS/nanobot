# Anthropic（Claude 模型）

Anthropic 是 Claude 模型系列的開發商，提供直接 API 存取。相比透過 OpenRouter，直連 Anthropic 可獲得更低延遲、更穩定的 Prompt Caching，以及 Thinking（推理努力度）等進階功能。

---

## 取得 API 金鑰

1. 前往 Anthropic Console（console.anthropic.com）
2. 以 Google 帳號或 Email 完成註冊
3. 進入 **API Keys** 頁面
4. 點選「Create Key」，輸入名稱後建立
5. 複製金鑰，格式為 `sk-ant-api03-xxxxxxxx...`

> Anthropic 採用信用額度制。新帳號通常有免費試用額度，正式使用需加值或訂閱。

---

## 可用模型

Anthropic 提供三個等級的模型，分別針對不同的效能/成本需求：

### Claude Opus — 最強推理

| 模型 ID | 特點 |
|--------|------|
| `claude-opus-4-5` | 最新 Opus，最高推理能力，支援 Thinking |

適用場景：複雜分析、程式碼架構設計、長文寫作

### Claude Sonnet — 平衡之選

| 模型 ID | 特點 |
|--------|------|
| `claude-sonnet-4-5` | 最新 Sonnet，高性能同時保持合理成本 |
| `claude-sonnet-3-7` | 支援強化版 Extended Thinking |
| `claude-sonnet-3-5` | 穩定成熟，廣泛採用 |

適用場景：一般任務、程式碼生成、問答

### Claude Haiku — 速度優先

| 模型 ID | 特點 |
|--------|------|
| `claude-haiku-3-5` | 最新 Haiku，速度最快、成本最低 |

適用場景：即時回應、批量處理、輕量任務

---

## 設定範例

### 基本設定

```json
{
  "agents": {
    "defaults": {
      "model": "claude-opus-4-5"
    }
  },
  "providers": {
    "anthropic": {
      "api_key": "sk-ant-api03-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    }
  }
}
```

### 啟用 Prompt Caching

nanobot 對 Anthropic 直連啟用了 `cache_control` 支援。Prompt Caching 會自動應用於系統提示詞和工具定義，無需額外設定。若希望明確確認，可在 `agents.defaults` 中設定：

```json
{
  "agents": {
    "defaults": {
      "model": "claude-opus-4-5",
      "prompt_caching": true
    }
  },
  "providers": {
    "anthropic": {
      "api_key": "sk-ant-api03-..."
    }
  }
}
```

Prompt Caching 對長系統提示（超過 1024 tokens）效果顯著，可節省 50-90% 的快取命中輸入費用。

> **注意：** Prompt Caching 僅在 Anthropic 直連和 OpenRouter 路由下有效，其他閘道可能不支援 `cache_control` 標頭。

### 設定推理努力度（Thinking）

Claude Opus 和部分 Sonnet 版本支援 Extended Thinking，可提升複雜推理任務的品質：

```json
{
  "agents": {
    "defaults": {
      "model": "claude-opus-4-5",
      "thinking": {
        "type": "enabled",
        "budget_tokens": 10000
      }
    }
  },
  "providers": {
    "anthropic": {
      "api_key": "sk-ant-api03-..."
    }
  }
}
```

| 參數 | 說明 |
|------|------|
| `type` | `"enabled"` 啟用思考；`"disabled"` 停用 |
| `budget_tokens` | 思考過程最多可用的 tokens 數（建議範圍：1000–32000） |

> **注意：** Thinking 模式下 `temperature` 必須設為 1（Anthropic 強制要求）。nanobot 在後端自動處理此限制。

### 完整設定範例

```json
{
  "agents": {
    "defaults": {
      "model": "claude-sonnet-4-5",
      "max_tokens": 8192,
      "temperature": 0.7
    }
  },
  "providers": {
    "anthropic": {
      "api_key": "sk-ant-api03-..."
    }
  }
}
```

---

## 模型偵測

nanobot 透過以下關鍵字自動識別 Anthropic 模型（無需明確指定 `provider`）：

- 模型名稱包含 `anthropic` 或 `claude`

例如，`model: "claude-haiku-3-5"` 會自動選用 `anthropic` 提供商設定。

---

## Prompt Caching 節費原理

Anthropic 的 Prompt Caching 對重複傳送的相同內容（系統提示、工具定義、長文件）提供快取讀取折扣，通常比標準輸入 Token 費率低約 90%（快取命中時）。

nanobot 在以下情況自動觸發快取：
- 每次對話都使用的固定系統提示
- MCP 工具定義清單（通常很長）
- 長記憶體摘要（memory consolidation 輸出）

對於高頻使用的 bot 或長對話，Prompt Caching 可大幅降低總費用。

---

## 常見問題

**Q：我可以同時設定 Anthropic 和 OpenRouter 嗎？**
可以。nanobot 根據模型名稱選擇，若兩個都設定了且沒有明確指定 `provider`，系統以關鍵字比對 `anthropic`/`claude` 自動路由到 Anthropic 直連。

**Q：Anthropic API 在中國大陸是否可用？**
Anthropic 的 API 端點（`api.anthropic.com`）在中國大陸需要 VPN。如果網路受限，建議使用 OpenRouter 或 SiliconFlow 作為替代。

**Q：如何查看我的 API 用量？**
前往 Anthropic Console 的 **Usage** 頁面，可查看 Token 用量、費用細目及按模型的統計。

---

## 延伸閱讀

- 提供商總覽：[providers/index.md](./index.md)
- OpenRouter（替代方案）：[providers/openrouter.md](./openrouter.md)
- 官方文件：Anthropic 官方網站的 API Reference 和 Models 頁面
