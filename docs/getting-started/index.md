# 入門指南

歡迎使用 **nanobot** — 一個超輕量的個人 AI 助手框架，支援 16+ 個聊天平台、多個 LLM 提供商，以及 MCP 整合。

本節將引導您從安裝到與您的 AI 助手進行第一次對話，全程只需幾分鐘。

---

## 本節內容

<div class="grid cards" markdown>

-   :material-download-box:{ .lg .middle } **安裝**

    ---

    系統需求、安裝方式（pip / uv / 源碼 / Docker），以及常見問題排解。

    [:octicons-arrow-right-24: 安裝指南](installation.md)

-   :material-rocket-launch:{ .lg .middle } **快速開始**

    ---

    5 分鐘內完成設定，讓 nanobot 在 Telegram 或 CLI 上開始運作。

    [:octicons-arrow-right-24: 快速開始](quick-start.md)

-   :material-wizard-hat:{ .lg .middle } **Onboarding 精靈**

    ---

    深入了解 `nanobot onboard` 精靈的每個步驟，以及如何自訂 workspace 範本。

    [:octicons-arrow-right-24: Onboarding 精靈](onboarding.md)

</div>

---

## 學習路徑

```
安裝 nanobot
    ↓
執行 nanobot onboard（初始化設定與 workspace）
    ↓
編輯 ~/.nanobot/config.json（設定 API 金鑰與模型）
    ↓
nanobot agent（在 CLI 對話）
    ↓
連接聊天頻道（Telegram / Discord / Slack 等）
    ↓
nanobot gateway（啟動 gateway，接收即時訊息）
```

## 前置需求

在開始之前，請確認您已準備好：

| 需求 | 說明 |
|------|------|
| **Python 3.11+** | nanobot 需要 Python 3.11 或更新版本 |
| **uv**（推薦）或 **pip** | Python 套件管理工具 |
| **LLM API 金鑰** | 例如 OpenRouter、Anthropic、OpenAI 等 |
| **（選用）聊天平台 Bot Token** | 例如 Telegram Bot Token，若要連接聊天平台 |

!!! tip "新手推薦"
    如果您不確定從哪裡取得 API 金鑰，推薦使用 [OpenRouter](https://openrouter.ai/keys)，它支援全球主流模型，且提供免費額度。

## 最常見的問題

**Q: nanobot 支援哪些 LLM？**

支援 20+ 個 LLM 提供商，包括 OpenAI、Anthropic Claude、Google Gemini、DeepSeek、Qwen、本地 Ollama 等。詳見 [Providers 文件](../providers/index.md)。

**Q: 需要公開 IP 嗎？**

不需要。大部分聊天頻道（Telegram、Discord、Feishu、DingTalk、Slack）都使用 WebSocket 長連線或 Socket Mode，無需公開 IP。

**Q: nanobot 佔用多少資源？**

極少。nanobot 核心只有約 16,000 行 Python 程式碼，啟動速度快，記憶體佔用極低。
