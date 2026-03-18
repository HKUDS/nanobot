# Docker 部署指南

本指南說明如何使用 Docker 或 Docker Compose 部署 nanobot，適合需要隔離環境或在伺服器上快速部署的情境。

## 前置需求

- [Docker](https://docs.docker.com/get-docker/) 20.10+
- [Docker Compose](https://docs.docker.com/compose/) v2（建議）

## Docker Compose 快速入門

這是推薦的部署方式，提供完整的服務管理能力。

### 第一次設定

```bash
# 1. 執行互動式設定精靈
docker compose run --rm nanobot-cli onboard

# 2. 編輯配置文件，填入 API 金鑰
vim ~/.nanobot/config.json

# 3. 背景啟動 Gateway
docker compose up -d nanobot-gateway
```

### 日常操作

```bash
# 執行 CLI 代理（一次性對話）
docker compose run --rm nanobot-cli agent -m "你好！"

# 查看 Gateway 即時日誌
docker compose logs -f nanobot-gateway

# 停止所有服務
docker compose down

# 重啟 Gateway（修改配置後）
docker compose restart nanobot-gateway
```

## Docker Compose 文件說明

專案根目錄的 `docker-compose.yml` 定義了兩個服務：

```yaml
x-common-config: &common-config
  build:
    context: .
    dockerfile: Dockerfile
  volumes:
    - ~/.nanobot:/root/.nanobot   # 掛載本地配置目錄

services:
  nanobot-gateway:
    container_name: nanobot-gateway
    <<: *common-config
    command: ["gateway"]
    restart: unless-stopped       # 容器崩潰時自動重啟
    ports:
      - 18790:18790               # Gateway 預設埠
    deploy:
      resources:
        limits:
          cpus: '1'
          memory: 1G
        reservations:
          cpus: '0.25'
          memory: 256M

  nanobot-cli:
    <<: *common-config
    profiles:
      - cli                       # 僅在明確指定時啟動
    command: ["status"]
    stdin_open: true
    tty: true
```

### 多頻道 Docker Compose 範例

若需要同時運行多個 Gateway 實例（各自連接不同頻道組合）：

```yaml
x-base: &base
  image: hkuds/nanobot:latest
  restart: unless-stopped

services:
  nanobot-telegram:
    <<: *base
    container_name: nanobot-telegram
    command: ["gateway", "--config", "/root/.nanobot-telegram/config.json"]
    ports:
      - "18790:18790"
    volumes:
      - ~/.nanobot-telegram:/root/.nanobot-telegram

  nanobot-discord:
    <<: *base
    container_name: nanobot-discord
    command: ["gateway", "--config", "/root/.nanobot-discord/config.json"]
    ports:
      - "18791:18790"
    volumes:
      - ~/.nanobot-discord:/root/.nanobot-discord

  nanobot-feishu:
    <<: *base
    container_name: nanobot-feishu
    command: ["gateway", "--config", "/root/.nanobot-feishu/config.json", "--port", "18792"]
    ports:
      - "18792:18792"
    volumes:
      - ~/.nanobot-feishu:/root/.nanobot-feishu
```

## Dockerfile 結構說明

專案 `Dockerfile` 採用多層快取策略：

```dockerfile
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# 安裝 Node.js 20（用於 WhatsApp Bridge）
RUN apt-get update && apt-get install -y nodejs ...

WORKDIR /app

# 第一層：僅安裝 Python 依賴（利用 Docker 快取）
COPY pyproject.toml README.md LICENSE ./
RUN uv pip install --system --no-cache .

# 第二層：複製完整原始碼
COPY nanobot/ nanobot/
COPY bridge/ bridge/
RUN uv pip install --system --no-cache .

# 建構 WhatsApp Bridge
WORKDIR /app/bridge
RUN npm install && npm run build

WORKDIR /app
RUN mkdir -p /root/.nanobot

EXPOSE 18790           # Gateway 預設埠

ENTRYPOINT ["nanobot"]
CMD ["status"]
```

**快取優化說明：** 先複製 `pyproject.toml` 並安裝依賴，再複製原始碼。這樣只要依賴未變更，Docker 就會重用快取層，大幅加快重建速度。

## 使用 Docker Hub 映像

可直接使用預建映像，無需從原始碼編譯：

```bash
# 拉取最新版本
docker pull hkuds/nanobot:latest

# 初始化配置
docker run -v ~/.nanobot:/root/.nanobot --rm hkuds/nanobot onboard

# 啟動 Gateway
docker run -v ~/.nanobot:/root/.nanobot -p 18790:18790 \
  --name nanobot-gateway \
  --restart unless-stopped \
  -d hkuds/nanobot gateway
```

## 從原始碼建構

```bash
# 複製儲存庫
git clone https://github.com/HKUDS/nanobot.git
cd nanobot

# 建構映像
docker build -t nanobot .

# 初始化配置
docker run -v ~/.nanobot:/root/.nanobot --rm nanobot onboard

# 編輯配置（在宿主機上）
vim ~/.nanobot/config.json

# 啟動 Gateway
docker run -v ~/.nanobot:/root/.nanobot -p 18790:18790 nanobot gateway
```

## Volume 掛載說明

| 宿主機路徑 | 容器內路徑 | 用途 |
|-----------|-----------|------|
| `~/.nanobot` | `/root/.nanobot` | 配置文件與工作區（必要） |
| `~/.ssh` | `/root/.ssh` | SSH 金鑰（若需要 Git 操作） |
| `/custom/workspace` | `/root/.nanobot/workspace` | 自訂工作區路徑 |

### 掛載 SSH 金鑰範例

```bash
docker run \
  -v ~/.nanobot:/root/.nanobot \
  -v ~/.ssh:/root/.ssh:ro \
  -p 18790:18790 \
  nanobot gateway
```

## 環境變數

可透過環境變數覆蓋配置，或傳入 API 金鑰：

```bash
docker run \
  -v ~/.nanobot:/root/.nanobot \
  -p 18790:18790 \
  -e ANTHROPIC_API_KEY=sk-ant-xxx \
  -e OPENAI_API_KEY=sk-xxx \
  nanobot gateway
```

在 Docker Compose 中使用 `.env` 文件：

```yaml
# docker-compose.yml
services:
  nanobot-gateway:
    env_file:
      - .env
```

```bash
# .env
ANTHROPIC_API_KEY=sk-ant-xxx
TELEGRAM_BOT_TOKEN=xxx
```

## 健康檢查

為 Docker Compose 添加健康檢查：

```yaml
services:
  nanobot-gateway:
    image: hkuds/nanobot:latest
    command: ["gateway"]
    healthcheck:
      test: ["CMD", "nanobot", "status"]
      interval: 60s
      timeout: 10s
      retries: 3
      start_period: 30s
    restart: unless-stopped
```

## 日誌管理

### 查看即時日誌

```bash
# Docker Compose
docker compose logs -f nanobot-gateway

# 純 Docker
docker logs -f nanobot-gateway
```

### 限制日誌大小

在 Docker Compose 中設定日誌輪替：

```yaml
services:
  nanobot-gateway:
    logging:
      driver: "json-file"
      options:
        max-size: "50m"
        max-file: "5"
```

### 輸出至 syslog

```yaml
services:
  nanobot-gateway:
    logging:
      driver: syslog
      options:
        syslog-address: "tcp://localhost:514"
        tag: "nanobot"
```

## 常見問題

**容器啟動後立即退出**

```bash
# 查看退出原因
docker logs nanobot-gateway

# 確認配置文件存在且有效
docker run -v ~/.nanobot:/root/.nanobot --rm nanobot status
```

**無法連接至 Gateway 埠**

確認埠映射正確，以及防火牆未封鎖該埠：

```bash
# 確認容器正在監聽
docker inspect nanobot-gateway | grep -A 10 "Ports"
```

**配置變更後需重新載入**

```bash
# 重啟 Gateway 使配置生效
docker compose restart nanobot-gateway
```
