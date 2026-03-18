# 多執行個體指南

Nanobot 支援同時執行多個獨立執行個體，每個執行個體擁有各自的設定檔、工作區、排程任務與執行時期資料，互不干擾。

---

## 為何需要多執行個體？

| 使用情境 | 說明 |
|----------|------|
| **不同平台** | 工作用 Slack + 企業微信，個人用 Telegram + Discord |
| **不同模型** | 一個執行個體使用 Claude 處理複雜任務，另一個使用本地 Ollama 模型 |
| **不同工作區** | 每個團隊或專案擁有隔離的工作目錄與記憶體 |
| **不同安全邊界** | 生產執行個體啟用 `restrictToWorkspace`，測試執行個體不限制 |
| **不同排程任務** | 各執行個體維護獨立的 Cron 任務清單 |

---

## 路徑解析規則

每個執行個體的所有執行時期資料均從設定檔路徑派生：

| 元件 | 來源 | 範例 |
|------|------|------|
| **設定檔** | `--config` 旗標 | `~/.nanobot-work/config.json` |
| **工作區** | `--workspace` 旗標，或設定檔中的 `agents.defaults.workspace` | `~/.nanobot-work/workspace/` |
| **排程任務** | 設定檔所在目錄 | `~/.nanobot-work/cron/` |
| **媒體與執行時期狀態** | 設定檔所在目錄 | `~/.nanobot-work/media/` |

> [!NOTE]
> `--config` 選擇要載入的設定檔。工作區預設從該設定檔的 `agents.defaults.workspace` 讀取。傳入 `--workspace` 可臨時覆蓋，不修改設定檔。

---

## 快速開始

### 第一步：建立各執行個體的設定檔與工作區

使用 `nanobot onboard` 精靈同時指定設定檔路徑與工作區：

```bash
# 工作用執行個體
nanobot onboard --config ~/.nanobot-work/config.json \
                --workspace ~/.nanobot-work/workspace

# 個人用執行個體
nanobot onboard --config ~/.nanobot-personal/config.json \
                --workspace ~/.nanobot-personal/workspace
```

精靈會將工作區路徑寫入對應的設定檔，後續無需再手動指定。

### 第二步：編輯各執行個體的設定

分別編輯 `~/.nanobot-work/config.json` 與 `~/.nanobot-personal/config.json`，填入不同的頻道憑證與模型設定。

### 第三步：同時啟動所有執行個體

```bash
# 工作用執行個體，使用預設埠號 18790
nanobot gateway --config ~/.nanobot-work/config.json

# 個人用執行個體，使用不同埠號
nanobot gateway --config ~/.nanobot-personal/config.json --port 18791
```

---

## 範例：工作與個人雙執行個體

### 工作執行個體設定

`~/.nanobot-work/config.json`

```json
{
  "agents": {
    "defaults": {
      "workspace": "~/.nanobot-work/workspace",
      "model": "anthropic/claude-opus-4-5",
      "maxTokens": 8192,
      "maxToolIterations": 40
    }
  },
  "channels": {
    "sendProgress": true,
    "sendToolHints": true,
    "slack": {
      "enabled": true,
      "botToken": "xoxb-WORK-BOT-TOKEN",
      "appToken": "xapp-WORK-APP-TOKEN",
      "allowFrom": ["U01234567", "U07654321"]
    },
    "wecom": {
      "enabled": true,
      "corpId": "YOUR_CORP_ID",
      "corpSecret": "YOUR_CORP_SECRET",
      "agentId": 1000001,
      "allowFrom": ["zhangsan", "lisi"]
    }
  },
  "providers": {
    "anthropic": {
      "apiKey": "sk-ant-work-key"
    }
  },
  "gateway": {
    "host": "0.0.0.0",
    "port": 18790
  },
  "tools": {
    "restrictToWorkspace": true,
    "exec": {
      "timeout": 60
    },
    "web": {
      "search": {
        "provider": "brave",
        "apiKey": "BSA-BRAVE-KEY"
      }
    }
  }
}
```

### 個人執行個體設定

`~/.nanobot-personal/config.json`

```json
{
  "agents": {
    "defaults": {
      "workspace": "~/.nanobot-personal/workspace",
      "model": "anthropic/claude-opus-4-5",
      "maxTokens": 8192
    }
  },
  "channels": {
    "sendProgress": true,
    "sendToolHints": false,
    "telegram": {
      "enabled": true,
      "token": "TELEGRAM-BOT-TOKEN",
      "allowFrom": ["MY_TELEGRAM_USER_ID"]
    },
    "discord": {
      "enabled": true,
      "token": "DISCORD-BOT-TOKEN",
      "allowFrom": ["MY_DISCORD_USER_ID"]
    }
  },
  "providers": {
    "anthropic": {
      "apiKey": "sk-ant-personal-key"
    }
  },
  "gateway": {
    "host": "0.0.0.0",
    "port": 18791
  },
  "tools": {
    "restrictToWorkspace": false,
    "web": {
      "search": {
        "provider": "duckduckgo"
      }
    }
  }
}
```

---

## 使用 CLI Agent 測試各執行個體

```bash
# 測試工作執行個體
nanobot agent -c ~/.nanobot-work/config.json -m "你好，這是工作執行個體"

# 測試個人執行個體
nanobot agent -c ~/.nanobot-personal/config.json -m "你好，這是個人執行個體"

# 使用臨時工作區（不修改設定檔）
nanobot agent -c ~/.nanobot-work/config.json -w /tmp/work-test -m "測試"
```

> [!NOTE]
> `nanobot agent` 啟動本地 CLI Agent，直接使用選定的工作區與設定。它不透過已在執行的 `nanobot gateway` 程序代理。

---

## 以 systemd 服務管理多執行個體

適用於 Linux 伺服器的生產部署。

### 服務範本

建立 `/etc/systemd/system/nanobot@.service`：

```ini
[Unit]
Description=Nanobot AI Assistant - %i instance
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=YOUR_USER
Group=YOUR_GROUP
WorkingDirectory=/home/YOUR_USER
ExecStart=/home/YOUR_USER/.local/bin/nanobot gateway \
    --config /home/YOUR_USER/.nanobot-%i/config.json
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=nanobot-%i

# 安全加固（可選）
NoNewPrivileges=yes
ProtectSystem=strict
ReadWritePaths=/home/YOUR_USER/.nanobot-%i

[Install]
WantedBy=multi-user.target
```

### 啟動各執行個體

```bash
# 載入新的服務定義
sudo systemctl daemon-reload

# 啟用並啟動工作執行個體
sudo systemctl enable nanobot@work
sudo systemctl start nanobot@work

# 啟用並啟動個人執行個體
sudo systemctl enable nanobot@personal
sudo systemctl start nanobot@personal

# 查看狀態
sudo systemctl status nanobot@work
sudo systemctl status nanobot@personal

# 查看日誌
sudo journalctl -u nanobot@work -f
sudo journalctl -u nanobot@personal -f
```

### 個別服務檔（不使用範本）

若偏好為每個執行個體建立獨立服務檔，建立 `/etc/systemd/system/nanobot-work.service`：

```ini
[Unit]
Description=Nanobot AI Assistant - Work Instance
After=network.target

[Service]
Type=simple
User=YOUR_USER
ExecStart=/home/YOUR_USER/.local/bin/nanobot gateway \
    --config /home/YOUR_USER/.nanobot-work/config.json
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

同樣建立 `/etc/systemd/system/nanobot-personal.service`，將設定檔路徑替換為 `~/.nanobot-personal/config.json`。

---

## 最小設定：手動複製

若不使用精靈，可手動建立執行個體目錄：

```bash
# 建立目錄結構
mkdir -p ~/.nanobot-work/workspace
mkdir -p ~/.nanobot-personal/workspace

# 複製基礎設定
cp ~/.nanobot/config.json ~/.nanobot-work/config.json
cp ~/.nanobot/config.json ~/.nanobot-personal/config.json
```

然後編輯每個設定檔，至少修改：

1. `agents.defaults.workspace` — 指向各自的工作區目錄
2. 頻道設定 — 填入對應平台的憑證
3. `gateway.port` — 確保每個執行個體使用不同埠號

---

## 各執行個體資料隔離一覽

| 資料類型 | 隔離方式 | 說明 |
|----------|----------|------|
| 工作區檔案 | 各自的 `workspace` 目錄 | Agent 操作的檔案完全獨立 |
| 記憶體摘要 | 工作區內的 `memory/` 子目錄 | 各執行個體記住不同的對話脈絡 |
| 排程任務 | 設定檔目錄的 `cron/` | 各執行個體維護獨立的排程 |
| 媒體快取 | 設定檔目錄的 `media/` | 圖片等媒體檔案互不影響 |
| API 金鑰 | 各自的設定檔 | 可為不同執行個體使用不同帳號或金鑰 |

---

## 常見問題

**Q：埠號衝突怎麼辦？**

確保每個執行個體在設定檔中設定不同的 `gateway.port`，或在啟動時透過 `--port` 旗標覆蓋。預設埠號為 `18790`。

**Q：可以讓多個執行個體共用同一個工作區嗎？**

技術上可行，但不建議。共用工作區會導致記憶體、排程任務與工作檔案混用，難以管理。

**Q：如何確認執行個體正在執行？**

```bash
# 檢查各埠號是否有程序在監聽
lsof -i :18790
lsof -i :18791

# 或使用 nanobot status
nanobot status --config ~/.nanobot-work/config.json
nanobot status --config ~/.nanobot-personal/config.json
```

**Q：可以動態切換模型嗎？**

可以直接在聊天中要求 Agent 切換模型，或修改設定檔後重啟執行個體。模型設定也可透過 `--model` 旗標在命令列臨時覆蓋（僅 `nanobot agent` 支援）。
