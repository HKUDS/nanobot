# 貢獻指南

感謝您願意為 nanobot 貢獻代碼。

nanobot 秉持一個簡單的信念：好的工具應該沉穩、清晰、對人友善。我們在乎有用的功能，也在乎以最少的代碼實現它——解決方案應該強大而不沉重，雄心勃勃而不無謂複雜。

## 維護者

| 維護者 | 負責範圍 |
|--------|---------|
| [@re-bin](https://github.com/re-bin) | 專案負責人，`main` 分支 |
| [@chengyongru](https://github.com/chengyongru) | `nightly` 分支，實驗性功能 |

## 分支策略

nanobot 使用雙分支模型，在穩定性和探索性之間取得平衡：

| 分支 | 用途 | 穩定性 |
|------|------|--------|
| `main` | 穩定發布版本 | 生產就緒 |
| `nightly` | 實驗性功能 | 可能含有錯誤或破壞性變更 |

### 我應該瞄準哪個分支？

**瞄準 `nightly` 的情況：**

- 新功能或新能力
- 可能影響現有行為的重構
- API 或配置的變更
- 不確定時

**瞄準 `main` 的情況：**

- 不改變行為的錯誤修復
- 文件改善
- 不影響功能的細微調整

> **建議：如有疑問，瞄準 `nightly`。** 把穩定的想法從 `nightly` 移到 `main` 比撤銷已落地 `main` 的風險變更容易得多。

### Nightly 如何合併至 Main？

我們不會合併整個 `nightly` 分支。穩定的功能會以**cherry-pick**方式，透過獨立的 PR 帶入 `main`：

```
nightly  ──┬── 功能 A（穩定）──► PR ──► main
           ├── 功能 B（測試中）
           └── 功能 C（穩定）──► PR ──► main
```

這大約每週發生一次，但實際時間取決於功能何時足夠穩定。

### 分支選擇快速參考

| 您的變更類型 | 目標分支 |
|------------|---------|
| 新功能 | `nightly` |
| 錯誤修復 | `main` |
| 文件 | `main` |
| 重構 | `nightly` |
| 不確定 | `nightly` |

## 開發環境設定

### 複製儲存庫

```bash
git clone https://github.com/HKUDS/nanobot.git
cd nanobot
```

### 安裝依賴

nanobot 使用 [`uv`](https://github.com/astral-sh/uv) 作為套件管理器：

```bash
# 安裝 uv（若尚未安裝）
curl -LsSf https://astral.sh/uv/install.sh | sh

# 安裝所有依賴（包含開發依賴）
uv sync
```

### 驗證安裝

```bash
# 執行測試確認環境正常
uv run pytest tests/

# 執行 CLI
uv run nanobot status
```

## 代碼風格

我們在乎的不只是通過 lint 檢查，而是讓 nanobot 保持小巧、沉穩、可讀。

貢獻時請追求讓代碼感覺：

- **簡單**：偏好解決真正問題的最小變更
- **清晰**：為下一位讀者優化，而非展示聰明
- **解耦**：保持邊界清晰，避免不必要的新抽象
- **誠實**：不隱藏複雜性，也不製造額外複雜性
- **耐久**：選擇易於維護、測試和擴展的解決方案

### 具體規範

- **行長度**：100 字元（由 `ruff` 強制，E501 忽略）
- **Python 版本**：3.11+
- **Lint 工具**：`ruff`，規則集 E、F、I、N、W
- **非同步**：全面使用 `asyncio`，測試使用 `asyncio_mode = "auto"`
- 偏好可讀代碼而非魔法代碼
- 偏好專注的小補丁而非大規模重寫
- 若引入新抽象，必須明確降低複雜性而非只是移動複雜性

### 執行 Lint 和格式化

```bash
# 檢查 lint 問題
uv run ruff check nanobot/

# 自動修復可修復的問題
uv run ruff check nanobot/ --fix

# 格式化代碼
uv run ruff format nanobot/
```

## 執行測試

### 執行所有測試

```bash
uv run pytest tests/
```

### 執行特定測試文件

```bash
uv run pytest tests/test_channels.py -v
```

### 執行特定測試函數

```bash
uv run pytest tests/test_commands.py::test_function_name -v
```

### 測試框架說明

- 測試框架：`pytest`
- 非同步模式：`pytest-asyncio`，`asyncio_mode = "auto"`（所有測試預設為非同步）
- 測試文件位於 `tests/` 目錄
- 整合測試案例位於 `case/` 目錄

## 撰寫測試

### 基本結構

```python
# tests/test_my_feature.py
import pytest
from nanobot.agent.loop import AgentLoop


async def test_agent_handles_simple_message():
    """代理應該能處理簡單的文字訊息。"""
    # 準備
    # ...

    # 執行
    result = await some_function()

    # 驗證
    assert result == expected
```

### 測試異步代碼

由於 `asyncio_mode = "auto"`，不需要手動標記 `@pytest.mark.asyncio`：

```python
# 直接定義 async 測試函數即可
async def test_channel_receives_message():
    channel = MockChannel()
    await channel.start()
    # ...
```

### 模擬外部依賴

```python
from unittest.mock import AsyncMock, patch

async def test_llm_call():
    with patch("nanobot.providers.litellm_provider.LiteLLMProvider.chat") as mock_chat:
        mock_chat.return_value = AsyncMock(return_value="模擬回應")
        # 執行測試
        ...
```

## 提交 Pull Request

### PR 前清單

- [ ] 所有測試通過：`uv run pytest tests/`
- [ ] Lint 無錯誤：`uv run ruff check nanobot/`
- [ ] 代碼已格式化：`uv run ruff format nanobot/`
- [ ] 目標分支正確（`main` 或 `nightly`）
- [ ] PR 描述清楚說明變更的目的和影響

### PR 描述建議

好的 PR 描述應包含：

1. **變更摘要**：一兩句話說明做了什麼
2. **為什麼**：說明問題或需求
3. **如何測試**：如何驗證這個變更有效

### Cherry-pick 至 Main

若您的功能在 `nightly` 分支已穩定，維護者可能會將其 cherry-pick 至 `main`：

```bash
# 維護者操作
git checkout main
git cherry-pick <commit-hash>
# 建立新的 PR 至 main
```

## 聯絡與社群

若您有問題、想法，或半成型的見解，我們誠摯歡迎您：

- 開啟 [GitHub Issue](https://github.com/HKUDS/nanobot/issues)
- 加入 [Discord 社群](https://discord.gg/MnCvHqpUGB)
- 加入 [飛書/微信群組](https://github.com/HKUDS/nanobot/blob/main/COMMUNICATION.md)
- 電子郵件：Xubin Ren (@Re-bin) — xubinrencs@gmail.com

感謝您花時間和心力在 nanobot 上。我們真誠歡迎各種規模的貢獻。
