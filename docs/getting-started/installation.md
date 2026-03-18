# 安裝指南

本頁說明如何在您的系統上安裝 nanobot，涵蓋多種安裝方式及常見問題排解。

---

## 系統需求

| 需求 | 版本 |
|------|------|
| **Python** | 3.11 或更新版本 |
| **作業系統** | macOS、Linux、Windows（WSL 推薦） |
| **uv**（推薦）| 最新版本 |
| **Node.js**（選用）| ≥18，僅 WhatsApp 頻道需要 |

!!! tip "確認 Python 版本"
    ```bash
    python3 --version
    # 應輸出 Python 3.11.x 或更新版本
    ```

---

## 安裝 uv（推薦）

[uv](https://github.com/astral-sh/uv) 是 nanobot 推薦使用的套件管理工具，速度極快。

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

安裝後，重新開啟終端機並確認：

```bash
uv --version
```

---

## 安裝 nanobot

### 方式一：使用 uv（推薦）

```bash
uv tool install nanobot-ai
```

這是最快速的安裝方式，nanobot 會被安裝為獨立的命令列工具。

**更新至最新版本：**

```bash
uv tool upgrade nanobot-ai
nanobot --version
```

### 方式二：使用 pip

```bash
pip install nanobot-ai
```

**更新至最新版本：**

```bash
pip install -U nanobot-ai
nanobot --version
```

### 方式三：從源碼安裝（開發者推薦）

適合想取得最新功能或參與開發的用戶。

```bash
git clone https://github.com/HKUDS/nanobot.git
cd nanobot
uv sync
```

!!! note "從源碼執行"
    從源碼安裝後，使用 `uv run nanobot` 代替直接輸入 `nanobot`：
    ```bash
    uv run nanobot --version
    uv run nanobot onboard
    uv run nanobot agent
    ```

---

## 使用 Docker 安裝

不想在本機安裝 Python 環境？可使用 Docker。

### 前置需求

- [Docker](https://docs.docker.com/get-docker/) 已安裝並運行

### 方式一：Docker Compose（推薦）

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

常用 Docker Compose 指令：

```bash
# 執行 CLI 模式對話
docker compose run --rm nanobot-cli agent -m "Hello!"

# 查看 gateway 日誌
docker compose logs -f nanobot-gateway

# 停止 gateway
docker compose down
```

### 方式二：直接使用 Docker

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

!!! tip "資料持久化"
    `-v ~/.nanobot:/root/.nanobot` 旗標會將您本機的設定目錄掛載至容器中，確保設定與 workspace 在容器重啟後仍然保留。

!!! note "Docker 互動式 OAuth 登入"
    若需要互動式 OAuth 登入（例如 OpenAI Codex），請加上 `-it` 旗標：
    ```bash
    docker run -it -v ~/.nanobot:/root/.nanobot --rm nanobot provider login openai-codex
    ```

---

## 安裝選用依賴

部分頻道需要額外安裝依賴：

| 頻道 | 安裝指令 |
|------|----------|
| **Matrix** | `pip install nanobot-ai[matrix]` |
| **WeCom（企業微信）** | `pip install nanobot-ai[wecom]` |
| **WhatsApp** | 需要 Node.js ≥18；執行 `nanobot channels login` 時會自動安裝橋接器 |

---

## 驗證安裝

安裝完成後，執行以下指令確認：

```bash
nanobot --version
```

預期輸出範例：

```
nanobot 0.1.4.post5
```

接著嘗試查看狀態：

```bash
nanobot status
```

如果安裝正確，您會看到目前的設定狀態概覽。

---

## 常見安裝問題

### `nanobot: command not found`

**原因：** uv tool 安裝後，`~/.local/bin` 尚未加入 `PATH`。

**解決方法：**

```bash
# 將以下內容加入 ~/.bashrc 或 ~/.zshrc
export PATH="$HOME/.local/bin:$PATH"

# 重新載入設定
source ~/.bashrc   # 或 source ~/.zshrc
```

### Python 版本不符

**錯誤訊息：** `requires Python >=3.11`

**解決方法：** 安裝 Python 3.11+。推薦使用 [pyenv](https://github.com/pyenv/pyenv)：

```bash
pyenv install 3.11
pyenv global 3.11
```

### pip 安裝權限問題（Linux / macOS）

**解決方法：** 加上 `--user` 旗標或使用 virtual environment：

```bash
pip install --user nanobot-ai
```

或建立 virtual environment：

```bash
python3 -m venv venv
source venv/bin/activate
pip install nanobot-ai
```

### WhatsApp 橋接器建置失敗

**原因：** Node.js 版本過舊或未安裝。

**解決方法：**

```bash
# 確認 Node.js 版本（需要 ≥18）
node --version

# 重建橋接器
rm -rf ~/.nanobot/bridge
nanobot channels login
```

### SSL 憑證錯誤（企業網路 / 代理）

**解決方法：** 在 `~/.nanobot/config.json` 中設定 proxy：

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

## 下一步

安裝完成後，前往 [快速開始](quick-start.md) 在 5 分鐘內完成您的第一個 nanobot 設定。
