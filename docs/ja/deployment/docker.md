# Docker デプロイガイド

このガイドでは、Docker または Docker Compose を使って nanobot をデプロイする方法を説明します。環境分離が必要な場合や、サーバーで素早くデプロイしたい場合に適しています。

## 前提

- [Docker](https://docs.docker.com/get-docker/) 20.10+
- [Docker Compose](https://docs.docker.com/compose/) v2（推奨）

## Docker Compose クイックスタート

推奨のデプロイ方法です。サービス管理がしやすくなります。

### 初回セットアップ

```bash
# 1. 対話式セットアップを実行
docker compose run --rm nanobot-cli onboard

# 2. 設定ファイルを編集して API キーを入力
vim ~/.nanobot/config.json

# 3. Gateway をバックグラウンド起動
docker compose up -d nanobot-gateway
```

### 日常操作

```bash
# CLI エージェント（単発対話）
docker compose run --rm nanobot-cli agent -m "こんにちは！"

# Gateway のライブログ
docker compose logs -f nanobot-gateway

# 全サービス停止
docker compose down

# Gateway 再起動（設定変更後）
docker compose restart nanobot-gateway
```

## Docker Compose ファイルの説明

プロジェクトルートの `docker-compose.yml` には 2 つのサービスが定義されています。

```yaml
x-common-config: &common-config
  build:
    context: .
    dockerfile: Dockerfile
  volumes:
    - ~/.nanobot:/root/.nanobot   # ホストの設定ディレクトリをマウント

services:
  nanobot-gateway:
    container_name: nanobot-gateway
    <<: *common-config
    command: ["gateway"]
    restart: unless-stopped       # コンテナが落ちたら自動再起動
    ports:
      - 18790:18790               # Gateway のデフォルトポート
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
      - cli                       # 明示指定時のみ起動
    command: ["status"]
    stdin_open: true
    tty: true
```

### 複数チャンネル向け Docker Compose 例

複数の Gateway インスタンスを同時実行し、それぞれ異なるチャンネル構成を担当させたい場合の例です。

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

## Dockerfile の説明

プロジェクトの `Dockerfile` は複数レイヤのキャッシュ戦略を使っています。

```dockerfile
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# Node.js 20 をインストール（WhatsApp Bridge 用）
RUN apt-get update && apt-get install -y nodejs ...

WORKDIR /app

# レイヤ 1: Python 依存のみをインストール（キャッシュを効かせる）
COPY pyproject.toml README.md LICENSE ./
RUN uv pip install --system --no-cache .

# レイヤ 2: フルソースをコピー
COPY nanobot/ nanobot/
COPY bridge/ bridge/
RUN uv pip install --system --no-cache .

# WhatsApp Bridge をビルド
WORKDIR /app/bridge
RUN npm install && npm run build

WORKDIR /app
RUN mkdir -p /root/.nanobot

EXPOSE 18790           # Gateway のデフォルトポート

ENTRYPOINT ["nanobot"]
CMD ["status"]
```

**キャッシュ最適化:** 先に `pyproject.toml` をコピーして依存関係を入れ、次にソースをコピーします。依存が変わらない限りキャッシュレイヤが再利用され、再ビルドが大幅に速くなります。

## Docker Hub イメージを使う

事前ビルドされたイメージを使えば、ソースからビルドせずに実行できます。

```bash
# 最新版を取得
docker pull hkuds/nanobot:latest

# 設定を初期化
docker run -v ~/.nanobot:/root/.nanobot --rm hkuds/nanobot onboard

# Gateway を起動
docker run -v ~/.nanobot:/root/.nanobot -p 18790:18790 \
  --name nanobot-gateway \
  --restart unless-stopped \
  -d hkuds/nanobot gateway
```

## ソースからビルド

```bash
# リポジトリを取得
git clone https://github.com/HKUDS/nanobot.git
cd nanobot

# イメージをビルド
docker build -t nanobot .

# 設定を初期化
docker run -v ~/.nanobot:/root/.nanobot --rm nanobot onboard

# 設定を編集（ホスト側）
vim ~/.nanobot/config.json

# Gateway を起動
docker run -v ~/.nanobot:/root/.nanobot -p 18790:18790 nanobot gateway
```

## Volume マウント

| ホストパス | コンテナパス | 用途 |
|-----------|-----------|------|
| `~/.nanobot` | `/root/.nanobot` | 設定ファイルと workspace（必須） |
| `~/.ssh` | `/root/.ssh` | SSH キー（Git 操作が必要な場合） |
| `/custom/workspace` | `/root/.nanobot/workspace` | カスタム workspace パス |

### SSH キーをマウントする例

```bash
docker run \
  -v ~/.nanobot:/root/.nanobot \
  -v ~/.ssh:/root/.ssh:ro \
  -p 18790:18790 \
  nanobot gateway
```

## 環境変数

環境変数で設定を上書きしたり、API キーを注入できます。

```bash
docker run \
  -v ~/.nanobot:/root/.nanobot \
  -p 18790:18790 \
  -e ANTHROPIC_API_KEY=sk-ant-xxx \
  -e OPENAI_API_KEY=sk-xxx \
  nanobot gateway
```

Docker Compose で `.env` を使う例:

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

## ヘルスチェック

Docker Compose にヘルスチェックを追加する例:

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

## ログ管理

### ライブログを見る

```bash
# Docker Compose
docker compose logs -f nanobot-gateway

# Docker
docker logs -f nanobot-gateway
```

### ログサイズを制限

Docker Compose でログローテーションを設定する例:

```yaml
services:
  nanobot-gateway:
    logging:
      driver: "json-file"
      options:
        max-size: "50m"
        max-file: "5"
```

### syslog へ出力

```yaml
services:
  nanobot-gateway:
    logging:
      driver: syslog
      options:
        syslog-address: "tcp://localhost:514"
        tag: "nanobot"
```

## よくある問題

**コンテナが起動直後に終了する**

```bash
# 終了理由を確認
docker logs nanobot-gateway

# 設定ファイルが存在し有効か確認
docker run -v ~/.nanobot:/root/.nanobot --rm nanobot status
```

**Gateway ポートへ接続できない**

ポートマッピングが正しいこと、ファイアウォールでブロックされていないことを確認してください。

```bash
# コンテナのリスニングを確認
docker inspect nanobot-gateway | grep -A 10 "Ports"
```

**設定を変更したが反映されない**

```bash
# Gateway を再起動して設定を反映
docker compose restart nanobot-gateway
```
