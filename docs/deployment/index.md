# 部署總覽

本節說明如何在不同環境下部署 nanobot，並協助您選擇最適合的部署方式。

## 部署方式比較

| 方式 | 指令 | 適用情境 | 持久性 |
|------|------|----------|--------|
| **CLI 代理** | `nanobot agent` | 一次性對話、測試、腳本 | 無（執行後結束） |
| **Gateway 服務** | `nanobot gateway` | 長期運行、連接聊天平台 | 需手動或以服務方式保持運行 |
| **Docker** | `docker compose up -d` | 容器化環境、CI/CD、隔離部署 | 透過 `restart: unless-stopped` 持久 |
| **systemd 服務** | `systemctl --user start nanobot-gateway` | Linux 伺服器、開機自動啟動 | 系統級持久，支援自動重啟 |

## 各方式說明

### CLI 代理（`nanobot agent`）

適合一次性互動或快速測試。執行單次對話後即結束，不保持連線。

```bash
nanobot agent -m "今天天氣如何？"
```

> **注意：** `nanobot agent` 啟動本地 CLI 代理，不會連接至已運行的 `nanobot gateway` 進程，兩者相互獨立。

### Gateway 服務（`nanobot gateway`）

Gateway 是 nanobot 的核心服務，負責連接所有啟用的聊天頻道（Telegram、Discord、Slack 等），持續監聽訊息並由代理循環處理回應。

詳見：[Gateway 服務指南](./gateway.md)

### Docker

適合需要隔離環境、快速部署，或在無法直接安裝 Python 環境的主機上運行。

詳見：[Docker 部署指南](./docker.md)

### Linux systemd 服務

適合在 Linux 伺服器上長期穩定運行，支援開機自動啟動、崩潰自動重啟，並整合系統日誌。

詳見：[Linux 服務指南](./linux-service.md)

## 生產環境 vs 開發環境

### 開發環境建議

- 使用 `nanobot agent` 快速測試功能
- 使用前台 `nanobot gateway` 直接查看日誌輸出
- 設定 `"restrictToWorkspace": false` 方便除錯

```bash
# 開發時前台啟動，可直接看到日誌
nanobot gateway
```

### 生產環境建議

- 使用 Docker Compose 或 systemd 服務確保持久運行
- 啟用 `"restrictToWorkspace": true` 限制工作區範圍
- 透過 `journalctl` 或 `docker compose logs` 集中管理日誌
- 設定自動重啟策略（`Restart=always` 或 `restart: unless-stopped`）

```bash
# 生產環境推薦：使用 Docker Compose
docker compose up -d nanobot-gateway

# 或使用 systemd（Linux）
systemctl --user enable --now nanobot-gateway
```

## 配置文件位置

所有部署方式共用同一份配置文件：

```
~/.nanobot/config.json          # 主要配置
~/.nanobot/workspace/           # 工作區目錄
~/.nanobot/workspace/HEARTBEAT.md  # 心跳任務定義
```

首次使用請執行互動式設定精靈：

```bash
nanobot onboard
```

## 延伸閱讀

- [Gateway 服務指南](./gateway.md)
- [Docker 部署指南](./docker.md)
- [Linux 服務指南](./linux-service.md)
- [架構說明](../development/architecture.md)
