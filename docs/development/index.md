# 開發文件總覽

歡迎來到 nanobot 開發文件。本節提供深入了解 nanobot 架構、貢獻代碼，以及開發自訂插件所需的所有資訊。

## 文件目錄

| 文件 | 說明 |
|------|------|
| [架構說明](./architecture.md) | 系統設計、模組關係、資料流 |
| [貢獻指南](./contributing.md) | 分支策略、代碼風格、提交 PR |
| [頻道插件開發](./channel-plugin.md) | 開發自訂聊天平台插件 |

## 快速入門

### 環境設定

```bash
# 複製儲存庫
git clone https://github.com/HKUDS/nanobot.git
cd nanobot

# 安裝依賴（包含開發依賴）
uv sync

# 執行測試
uv run pytest tests/

# 啟動本地代理進行測試
uv run nanobot agent
```

### 重要原則

nanobot 的核心設計理念是「以最少的代碼實現最核心的功能」：

- **輕量**：~16k Python 代碼行完成完整代理功能
- **非同步優先**：全面使用 `async/await`，避免阻塞呼叫
- **事件驅動**：訊息透過總線路由，各元件鬆散耦合
- **可擴展**：透過插件機制支援自訂頻道和技能

## 專案結構

```
nanobot/
├── agent/          # 核心代理邏輯
│   ├── loop.py     #   代理主循環（LLM ↔ 工具執行）
│   ├── context.py  #   提示詞建構
│   ├── memory.py   #   記憶整合
│   └── tools/      #   工具實作
├── bus/            # 訊息總線
├── channels/       # 聊天平台介面卡（支援插件）
├── providers/      # LLM 提供者
├── session/        # 會話管理
├── config/         # 配置模式（Pydantic）
├── skills/         # 內建技能
├── cron/           # 定時任務服務
└── heartbeat/      # 心跳喚醒服務
```

## 相關資源

- [GitHub 儲存庫](https://github.com/HKUDS/nanobot)
- [問題回報](https://github.com/HKUDS/nanobot/issues)
- [Discord 社群](https://discord.gg/MnCvHqpUGB)
- [頻道插件指南（英文）](../CHANNEL_PLUGIN_GUIDE.md)
