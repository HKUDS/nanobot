# インストールガイド

このページでは、システムへの nanobot のインストール方法を説明します。複数のインストール手段と、よくあるトラブルシュートを含みます。

---

## システム要件

| 要件 | バージョン |
|------|------|
| **Python** | 3.11 以上 |
| **OS** | macOS / Linux / Windows（WSL 推奨） |
| **uv**（推奨）| 最新版 |
| **Node.js**（任意）| ≥18（WhatsApp チャンネルのみ必要） |

!!! tip "Python バージョンの確認"
    ```bash
    python3 --version
    # Python 3.11.x 以上が出力されるはずです
    ```

---

## uv をインストール（推奨）

[uv](https://github.com/astral-sh/uv) は nanobot が推奨するパッケージ管理ツールで、非常に高速です。

=== "macOS / Linux"

    ```bash
    curl -LsSf https://astral.sh/uv/install.sh | sh
    ```

=== "Windows"

    ```powershell
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    ```

=== "pip"

    ```bash
    pip install uv
    ```

インストール後にターミナルを開き直し、次で確認します。

```bash
uv --version
```

---

## nanobot をインストール

### 方法 1: uv を使う（推奨）

```bash
uv tool install nanobot-ai
```

最も手早い方法で、nanobot は独立した CLI ツールとしてインストールされます。

**最新版へアップデート:**

```bash
uv tool upgrade nanobot-ai
nanobot --version
```

### 方法 2: pip を使う

```bash
pip install nanobot-ai
```

**最新版へアップデート:**

```bash
pip install -U nanobot-ai
nanobot --version
```

### 方法 3: ソースからインストール（開発者向け推奨）

最新機能を使いたい場合や、開発に参加したい方向けです。

```bash
git clone https://github.com/HKUDS/nanobot.git
cd nanobot
uv sync
```

!!! note "ソースから実行する"
    ソースからのセットアップ後は、`nanobot` を直接実行する代わりに `uv run nanobot` を使います。
    ```bash
    uv run nanobot --version
    uv run nanobot onboard
    uv run nanobot agent
    ```

---

## Docker でインストール

ローカルに Python 環境を入れたくない場合は Docker を利用できます。

### 前提

- [Docker](https://docs.docker.com/get-docker/) をインストールして起動していること

### 方法 1: Docker Compose（推奨）

```bash
# 複製儲存庫
git clone https://github.com/HKUDS/nanobot.git
cd nanobot

# 初始化設定（第一次執行）
docker compose run --rm nanobot-cli onboard

# 編輯 config，加入 API 金鑰
vim ~/.nanobot/config.json

# 啟動 gateway
docker compose up -d nanobot-gateway
```

よく使う Docker Compose コマンド:

```bash
# 執行 CLI 模式對話
docker compose run --rm nanobot-cli agent -m "Hello!"

# 查看 gateway 日誌
docker compose logs -f nanobot-gateway

# 停止 gateway
docker compose down
```

### 方法 2: Docker を直接使う

```bash
# 建立映像檔
docker build -t nanobot .

# 初始化設定（第一次執行）
docker run -v ~/.nanobot:/root/.nanobot --rm nanobot onboard

# 編輯設定
vim ~/.nanobot/config.json

# 啟動 gateway
docker run -v ~/.nanobot:/root/.nanobot -p 18790:18790 nanobot gateway

# 或執行單次 CLI 指令
docker run -v ~/.nanobot:/root/.nanobot --rm nanobot agent -m "Hello!"
docker run -v ~/.nanobot:/root/.nanobot --rm nanobot status
```

!!! tip "データの永続化"
    `-v ~/.nanobot:/root/.nanobot` はホスト側の設定ディレクトリをコンテナへマウントし、コンテナ再起動後も設定と workspace を保持します。

!!! note "Docker での対話式 OAuth ログイン"
    OpenAI Codex などで対話式の OAuth ログインが必要な場合は `-it` を付けて実行します。
    ```bash
    docker run -it -v ~/.nanobot:/root/.nanobot --rm nanobot provider login openai-codex
    ```

---

## 任意依存関係のインストール

一部のチャンネルでは追加の依存関係が必要です。

| チャンネル | インストールコマンド |
|------|----------|
| **Matrix** | `pip install nanobot-ai[matrix]` |
| **WeCom（企業微信）** | `pip install nanobot-ai[wecom]` |
| **WhatsApp** | Node.js ≥18 が必要です。`nanobot channels login` 実行時にブリッジが自動インストールされます |

---

## インストールの確認

インストール後、次で確認します。

```bash
nanobot --version
```

期待される出力例:

```
nanobot 0.1.4.post5
```

続けてステータスを表示してみます。

```bash
nanobot status
```

正しくインストールできていれば、現在の設定状況の概要が表示されます。

---

## よくあるインストール問題

### `nanobot: command not found`

**原因:** uv tool でインストール後、`~/.local/bin` が `PATH` に入っていません。

**解決:**

```bash
# 將以下內容加入 ~/.bashrc 或 ~/.zshrc
export PATH="$HOME/.local/bin:$PATH"

# 重新載入設定
source ~/.bashrc   # 或 source ~/.zshrc
```

### Python バージョンが合わない

**エラー:** `requires Python >=3.11`

**解決:** Python 3.11+ をインストールしてください。[pyenv](https://github.com/pyenv/pyenv) の利用がおすすめです。

```bash
pyenv install 3.11
pyenv global 3.11
```

### pip の権限問題（Linux / macOS）

**解決:** `--user` を付けるか、virtual environment を使います。

```bash
pip install --user nanobot-ai
```

または virtual environment を作成:

```bash
python3 -m venv venv
source venv/bin/activate
pip install nanobot-ai
```

### WhatsApp ブリッジのビルドに失敗する

**原因:** Node.js が古い、または未インストールです。

**解決:**

```bash
# 確認 Node.js 版本（需要 ≥18）
node --version

# 重建橋接器
rm -rf ~/.nanobot/bridge
nanobot channels login
```

### SSL 証明書エラー（企業ネットワーク / プロキシ）

**解決:** `~/.nanobot/config.json` に proxy を設定します。

```json
{
  "tools": {
    "web": {
      "proxy": "http://your-proxy:7890"
    }
  }
}
```

---

## 次のステップ

インストールが完了したら、[クイックスタート](quick-start.md) で 5 分以内に最初の nanobot セットアップを完了しましょう。
