# Linux systemd 服務指南

本指南說明如何將 nanobot Gateway 設定為 systemd 使用者服務，實現開機自動啟動、崩潰自動重啟，並整合系統日誌管理。

## 為什麼使用 systemd？

- **開機自動啟動**：登入後 Gateway 自動運行
- **崩潰自動重啟**：服務異常退出時自動重啟
- **系統日誌整合**：透過 `journalctl` 集中管理日誌
- **標準化管理**：使用熟悉的 `systemctl` 指令操作

## 前置步驟

### 確認 nanobot 已安裝

```bash
which nanobot
# 應輸出類似：/home/user/.local/bin/nanobot
```

若未找到，先安裝 nanobot：

```bash
pip install nanobot-ai
# 或使用 uv
uv pip install nanobot-ai
```

### 完成初始設定

```bash
nanobot onboard
# 依提示填入 API 金鑰與頻道配置
```

## 建立 systemd 使用者服務

### 第一步：確認 nanobot 路徑

```bash
which nanobot
# 例如：/home/user/.local/bin/nanobot
```

### 第二步：建立服務文件目錄

```bash
mkdir -p ~/.config/systemd/user
```

### 第三步：建立服務文件

在 `~/.config/systemd/user/nanobot-gateway.service` 建立以下內容（若 `nanobot` 不在 `~/.local/bin/`，請修改 `ExecStart` 路徑）：

```ini
[Unit]
Description=Nanobot Gateway
After=network.target

[Service]
Type=simple
ExecStart=%h/.local/bin/nanobot gateway
Restart=always
RestartSec=10
NoNewPrivileges=yes
ProtectSystem=strict
ReadWritePaths=%h

[Install]
WantedBy=default.target
```

> **說明：** `%h` 是 systemd 的展開符號，代表使用者的家目錄（`$HOME`）。

### 第四步：啟用並啟動服務

```bash
# 重新載入 systemd 設定
systemctl --user daemon-reload

# 啟用並立即啟動服務
systemctl --user enable --now nanobot-gateway
```

## 日常管理指令

```bash
# 查看服務狀態
systemctl --user status nanobot-gateway

# 啟動服務
systemctl --user start nanobot-gateway

# 停止服務
systemctl --user stop nanobot-gateway

# 重啟服務（修改配置後）
systemctl --user restart nanobot-gateway

# 停用自動啟動（但不停止當前運行）
systemctl --user disable nanobot-gateway
```

## 日誌查看

```bash
# 即時追蹤日誌
journalctl --user -u nanobot-gateway -f

# 查看最近 100 行日誌
journalctl --user -u nanobot-gateway -n 100

# 查看今日日誌
journalctl --user -u nanobot-gateway --since today

# 查看指定時間範圍的日誌
journalctl --user -u nanobot-gateway --since "2026-01-01 09:00" --until "2026-01-01 18:00"

# 以 JSON 格式輸出（適合日誌分析）
journalctl --user -u nanobot-gateway -o json
```

## 修改服務文件

若需要修改服務文件（例如更改埠號或配置文件路徑），需要重新載入設定：

```bash
# 編輯服務文件
vim ~/.config/systemd/user/nanobot-gateway.service

# 重新載入設定（必要步驟）
systemctl --user daemon-reload

# 重啟服務使修改生效
systemctl --user restart nanobot-gateway
```

## 登出後保持運行

預設情況下，使用者服務只在登入期間運行。若需要在登出後繼續運行（例如伺服器環境），啟用 **lingering**：

```bash
loginctl enable-linger $USER
```

驗證已啟用：

```bash
loginctl show-user $USER | grep Linger
# Linger=yes
```

## 多實例部署

若需要同時運行多個 nanobot 實例（連接不同頻道），可建立多個服務文件：

### Telegram 實例

```ini
# ~/.config/systemd/user/nanobot-telegram.service
[Unit]
Description=Nanobot Gateway (Telegram)
After=network.target

[Service]
Type=simple
ExecStart=%h/.local/bin/nanobot gateway --config %h/.nanobot-telegram/config.json
Restart=always
RestartSec=10
NoNewPrivileges=yes
ProtectSystem=strict
ReadWritePaths=%h

[Install]
WantedBy=default.target
```

### Discord 實例

```ini
# ~/.config/systemd/user/nanobot-discord.service
[Unit]
Description=Nanobot Gateway (Discord)
After=network.target

[Service]
Type=simple
ExecStart=%h/.local/bin/nanobot gateway --config %h/.nanobot-discord/config.json --port 18791
Restart=always
RestartSec=10
NoNewPrivileges=yes
ProtectSystem=strict
ReadWritePaths=%h

[Install]
WantedBy=default.target
```

啟用所有實例：

```bash
systemctl --user daemon-reload
systemctl --user enable --now nanobot-telegram
systemctl --user enable --now nanobot-discord
```

## 完整服務文件範例（含環境變數）

以下是包含環境變數設定的完整服務文件範例：

```ini
[Unit]
Description=Nanobot Gateway
Documentation=https://github.com/HKUDS/nanobot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple

# nanobot 執行路徑（依實際安裝位置調整）
ExecStart=%h/.local/bin/nanobot gateway

# 環境變數（可選，也可直接寫入 config.json）
# Environment=ANTHROPIC_API_KEY=sk-ant-xxx
# Environment=TELEGRAM_BOT_TOKEN=xxx

# 重啟策略
Restart=always
RestartSec=10

# 安全限制
NoNewPrivileges=yes
ProtectSystem=strict
ReadWritePaths=%h

# 日誌設定
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
```

## 設定環境變數

有兩種方式設定環境變數：

**方式一：直接寫入 config.json（推薦）**

```bash
vim ~/.nanobot/config.json
# 在配置文件中填入 API 金鑰
```

**方式二：使用 EnvironmentFile**

```ini
[Service]
EnvironmentFile=%h/.nanobot/nanobot.env
ExecStart=%h/.local/bin/nanobot gateway
```

```bash
# ~/.nanobot/nanobot.env
ANTHROPIC_API_KEY=sk-ant-xxx
TELEGRAM_BOT_TOKEN=xxx
```

## 常見問題排解

**服務啟動失敗**

```bash
# 查看詳細錯誤訊息
journalctl --user -u nanobot-gateway -n 50

# 手動測試啟動指令
/home/user/.local/bin/nanobot gateway
```

**服務不斷重啟**

```bash
# 查看重啟原因
systemctl --user status nanobot-gateway
journalctl --user -u nanobot-gateway --since "5 minutes ago"
```

**找不到 nanobot 執行檔**

```bash
# 確認安裝路徑
which nanobot
pip show nanobot-ai | grep Location

# 使用完整路徑
ExecStart=/full/path/to/nanobot gateway
```
