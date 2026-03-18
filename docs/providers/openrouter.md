# OpenRouter（推薦預設提供商）

OpenRouter 是 nanobot 最推薦的入門提供商。只需一個 API 金鑰，即可存取來自 Anthropic、OpenAI、Google、Meta、Mistral 等數十家廠商的 300+ 模型。

---

## 什麼是 OpenRouter？為什麼推薦它？

OpenRouter 是一個 LLM 模型閘道（Gateway），提供統一的 OpenAI 相容 API 介面，後端路由到各家模型提供商。

**推薦原因：**

- **一金鑰通吃** — 不需要分別申請 Anthropic、OpenAI、Google 等各家帳號
- **按量付費** — 每個模型獨立計費，可以低成本嘗試昂貴模型
- **免費模型** — 部分模型（如 Llama、Qwen 系列）提供免費存取額度
- **自動備援** — 可設定同模型的多個提供商備援（Provider Fallback）
- **最佳路由** — 可選擇依據延遲或成本自動選擇最佳提供商
- **支援 Prompt Caching** — nanobot 對 OpenRouter 啟用了 prompt caching 支援

---

## 取得 API 金鑰

1. 前往 OpenRouter 官方網站（openrouter.ai）
2. 點選「Sign In」或「Get Started」，以 Google / GitHub 帳號登入
3. 進入 **Keys** 頁面（Settings → Keys）
4. 點選「Create Key」
5. 複製金鑰，格式為 `sk-or-v1-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`

> **重要：** nanobot 透過金鑰前綴 `sk-or-` 自動偵測 OpenRouter，無需額外設定 `api_base`。

---

## 設定範例

### 最簡設定（使用預設模型）

```json
{
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5"
    }
  },
  "providers": {
    "openrouter": {
      "api_key": "sk-or-v1-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    }
  }
}
```

### 完整設定

```json
{
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5",
      "provider": "openrouter"
    }
  },
  "providers": {
    "openrouter": {
      "api_key": "sk-or-v1-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
      "api_base": "https://openrouter.ai/api/v1"
    }
  }
}
```

> `api_base` 為選填欄位，有設定 `sk-or-` 金鑰時系統會自動使用 `https://openrouter.ai/api/v1`。

---

## 透過 OpenRouter 選用特定模型

OpenRouter 的模型名稱格式為 `{提供商}/{模型名稱}`，例如：

```json
{
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5"
    }
  }
}
```

### 常用模型清單

以下為 OpenRouter 上常用的模型 ID（以 `provider/model` 格式填入 `model` 欄位）：

**Anthropic Claude 系列**

| 模型 ID | 說明 |
|--------|------|
| `anthropic/claude-opus-4-5` | Claude Opus，最強推理 |
| `anthropic/claude-sonnet-4-5` | Claude Sonnet，平衡性能與成本 |
| `anthropic/claude-haiku-3-5` | Claude Haiku，速度最快、成本最低 |

**OpenAI GPT 系列**

| 模型 ID | 說明 |
|--------|------|
| `openai/gpt-4o` | GPT-4o，多模態旗艦 |
| `openai/gpt-4o-mini` | GPT-4o Mini，高性價比 |
| `openai/o3` | o3 推理模型 |

**Google Gemini 系列**

| 模型 ID | 說明 |
|--------|------|
| `google/gemini-2.0-flash-001` | Gemini 2.0 Flash，速度快 |
| `google/gemini-2.5-pro-preview` | Gemini 2.5 Pro，長上下文 |

**開源模型（通常有免費額度）**

| 模型 ID | 說明 |
|--------|------|
| `meta-llama/llama-3.3-70b-instruct` | Meta Llama 3.3 70B |
| `qwen/qwen-2.5-72b-instruct` | 阿里 Qwen 2.5 72B |
| `deepseek/deepseek-chat` | DeepSeek V3 |
| `deepseek/deepseek-r1` | DeepSeek R1 推理模型 |
| `mistralai/mistral-large-2411` | Mistral Large |

> 完整模型清單請前往 OpenRouter 網站的 Models 頁面查看，可按用途、成本、上下文長度篩選。

---

## 成本最佳化建議

### 1. 善用免費模型

OpenRouter 上許多開源模型有免費額度，適合日常輕量任務：
- `meta-llama/llama-3.3-70b-instruct:free`
- `google/gemini-2.0-flash-exp:free`

在模型 ID 末尾加上 `:free` 強制選用免費層（有速率限制）。

### 2. 依任務選擇適合模型

- **快速問答** — 使用 `claude-haiku` 或 `gpt-4o-mini`，成本降低 10-20 倍
- **程式碼生成** — `claude-sonnet` 或 `deepseek-chat` 在成本與品質間取得平衡
- **複雜推理** — 僅在必要時使用 `claude-opus` 或 `o3`

### 3. 利用 Prompt Caching

nanobot 對 OpenRouter 啟用了 prompt caching（快取提示詞）支援，重複的系統提示和工具定義不會重複計費，可節省 50-90% 的輸入 Token 費用（適用於支援快取的模型）。

### 4. 設定消費上限

在 OpenRouter 網站的 Billing 頁面可設定每日/每月消費上限，避免意外超支。

---

## 速率限制

OpenRouter 的速率限制依帳戶等級與模型而異：

| 帳戶狀態 | 限制 |
|---------|------|
| 未儲值 | 每天 50 次請求（免費模型） |
| 已儲值 | 依模型提供商限制，通常較寬鬆 |
| 企業方案 | 聯繫 OpenRouter 銷售 |

若遇到 `429 Too Many Requests` 錯誤，建議：
1. 在 OpenRouter 網站查看各模型的具體速率限制
2. 考慮啟用 OpenRouter 的 Provider Fallback 功能（在網站上設定）
3. 降低 nanobot 並發請求數

---

## 常見問題

**Q：OpenRouter 是否支援串流輸出？**
是的，nanobot 預設使用串流模式，OpenRouter 完整支援。

**Q：我能用 OpenRouter 存取需要商業授權的模型嗎？**
OpenRouter 有部分模型要求通過使用條款驗證，請查看各模型頁面的說明。

**Q：OpenRouter 的定價是否與各家官方一致？**
通常有少量加價（約 0.5-1x 倍率），換取便利性。部分模型可能低於官方定價（因提供商補貼）。

---

## 延伸閱讀

- 提供商總覽：[providers/index.md](./index.md)
- Anthropic 直連：[providers/anthropic.md](./anthropic.md)
- OpenAI 直連：[providers/openai.md](./openai.md)
