# OpenAI（GPT 模型）

nanobot 支援三種使用 OpenAI 模型的方式：直接 API 金鑰、OpenAI Codex OAuth（ChatGPT Plus/Pro）、以及 GitHub Copilot OAuth。

---

## 方式一：OpenAI 直接 API

### 取得 API 金鑰

1. 前往 OpenAI Platform（platform.openai.com）
2. 登入後進入 **API Keys** 頁面
3. 點選「Create new secret key」
4. 複製金鑰，格式為 `sk-proj-xxxxxxxx...`（或舊格式 `sk-xxxxxxxx...`）

> OpenAI 採用預付制。需先儲值至 Billing 頁面，API 才能正常使用。

### 可用模型

**GPT-4o 系列**

| 模型 ID | 特點 |
|--------|------|
| `gpt-4o` | 多模態旗艦，支援圖片輸入 |
| `gpt-4o-mini` | 高性價比，速度快 |
| `gpt-4o-audio-preview` | 支援語音輸入/輸出 |

**o 系列推理模型**

| 模型 ID | 特點 |
|--------|------|
| `o3` | 最新推理旗艦 |
| `o3-mini` | 輕量推理模型 |
| `o4-mini` | 快速推理，高性價比 |
| `o1` | 第一代推理模型 |

**GPT-4 Turbo**

| 模型 ID | 特點 |
|--------|------|
| `gpt-4-turbo` | 128K 上下文，視覺支援 |
| `gpt-4` | 標準 GPT-4 |

> 完整模型清單請參閱 OpenAI Platform 的 Models 頁面。

### 設定範例

```json
{
  "agents": {
    "defaults": {
      "model": "gpt-4o"
    }
  },
  "providers": {
    "openai": {
      "api_key": "sk-proj-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    }
  }
}
```

### 使用自訂 API Base（如代理伺服器）

```json
{
  "providers": {
    "openai": {
      "api_key": "sk-proj-...",
      "api_base": "https://your-proxy.example.com/v1"
    }
  }
}
```

---

## 方式二：OpenAI Codex OAuth（ChatGPT Plus/Pro）

OpenAI Codex 提供商允許持有 **ChatGPT Plus 或 Pro 訂閱**的使用者透過 OAuth 授權使用模型，無需另購 API 額度。

> **重要：** 此方式使用 ChatGPT 網頁後端，行為可能與官方 API 不完全一致，且受 ChatGPT 服務條款約束。

### 前置條件

- 有效的 ChatGPT Plus 或 Pro 訂閱
- 已在瀏覽器中登入 ChatGPT（chatgpt.com）

### 設定步驟

1. 在設定檔中啟用 `openai_codex` 提供商（無需填入 `api_key`）：

```json
{
  "agents": {
    "defaults": {
      "model": "openai-codex/auto",
      "provider": "openai_codex"
    }
  },
  "providers": {
    "openai_codex": {}
  }
}
```

2. 啟動 nanobot 後，系統會引導完成 OAuth 授權流程（開啟瀏覽器登入 ChatGPT）。

3. 授權完成後，OAuth token 會被快取至本地，後續啟動無需重新授權。

### 模型偵測

nanobot 透過 `api_base` 中包含 `codex` 關鍵字，或模型名稱包含 `openai-codex` 來識別此提供商：

```json
{
  "providers": {
    "openai_codex": {
      "api_base": "https://chatgpt.com/backend-api"
    }
  }
}
```

> **限制：** OAuth 提供商不能作為備援候選。必須明確指定 `provider: "openai_codex"` 或使用 `openai-codex/` 模型前綴。

---

## 方式三：GitHub Copilot OAuth

GitHub Copilot 提供商允許持有 **GitHub Copilot 訂閱**的使用者透過 OAuth 授權使用模型。

### 前置條件

- 有效的 GitHub Copilot Individual、Business 或 Enterprise 訂閱
- 已安裝並登入 GitHub CLI（`gh`）或 GitHub Desktop

### 設定範例

```json
{
  "agents": {
    "defaults": {
      "model": "github_copilot/claude-sonnet-4-5",
      "provider": "github_copilot"
    }
  },
  "providers": {
    "github_copilot": {}
  }
}
```

模型名稱格式為 `github_copilot/{model}`，例如：
- `github_copilot/claude-sonnet-4-5`
- `github_copilot/gpt-4o`
- `github_copilot/o3-mini`

### 授權流程

啟動後 nanobot 會自動引導 OAuth 授權，使用 GitHub 帳號登入即可。授權 token 快取後，後續使用無需重複操作。

### 模型偵測

nanobot 透過以下方式識別 GitHub Copilot：
- 模型名稱包含 `github_copilot` 或 `copilot`
- 明確指定 `provider: "github_copilot"`

由於 `skip_prefixes` 設定，`github_copilot/claude-sonnet-4-5` 不會被誤判為 OpenAI Codex。

---

## 三種方式比較

| | 直接 API | Codex OAuth | Copilot OAuth |
|--|---------|-------------|---------------|
| **需要 API 金鑰** | 是 | 否 | 否 |
| **需要訂閱** | 否（按量付費） | ChatGPT Plus/Pro | GitHub Copilot |
| **模型選擇** | 全部 OpenAI 模型 | 限 ChatGPT 可用模型 | Copilot 支援的模型 |
| **成本** | 按 token 計費 | 訂閱費已涵蓋 | 訂閱費已涵蓋 |
| **穩定性** | 最穩定 | 依 ChatGPT 服務 | 依 GitHub 服務 |
| **推薦對象** | 一般開發者 | ChatGPT 訂閱用戶 | Copilot 訂閱用戶 |

---

## 常見問題

**Q：`gpt-4o` 和 `gpt-4o-mini` 有什麼差別？**
`gpt-4o` 為旗艦版，推理能力更強但費用較高；`gpt-4o-mini` 在大多數日常任務中有足夠表現，費用低約 15 倍。

**Q：o 系列推理模型是否支援串流輸出？**
是的，nanobot 支援 o 系列的串流模式。但 o 系列模型不支援 `temperature` 等部分參數，nanobot 會自動跳過不相容的參數。

**Q：如何從 ChatGPT Plus 升級到 OpenAI API 帳號？**
兩者為獨立帳號體系。若需 API 存取，需在 platform.openai.com 另行開立帳號並加值。Codex OAuth 方式可讓你直接使用現有 ChatGPT Plus 訂閱，無需額外費用。

---

## 延伸閱讀

- 提供商總覽：[providers/index.md](./index.md)
- OpenRouter（統一閘道）：[providers/openrouter.md](./openrouter.md)
- 官方文件：OpenAI Platform 的 API Reference 和 Models 頁面
