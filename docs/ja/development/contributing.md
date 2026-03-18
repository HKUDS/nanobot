# コントリビュートガイド

nanobot への貢献をご検討いただきありがとうございます。

nanobot は「良いツールは落ち着いていて、明快で、人に優しいべきだ」というシンプルな信念を大切にしています。役に立つ機能を重視しつつ、それを **最小限のコードで実現する** ことも同じくらい重視します。解決策は強力でありながら重くなく、野心的でありながら無駄に複雑でないことを目指します。

## メンテナ

| メンテナ | 担当 |
|--------|---------|
| [@re-bin](https://github.com/re-bin) | プロジェクトオーナー、`main` ブランチ |
| [@chengyongru](https://github.com/chengyongru) | `nightly` ブランチ、実験的機能 |

## ブランチ戦略

nanobot は安定性と探索性のバランスを取るため、2 ブランチモデルを採用しています。

| ブランチ | 用途 | 安定性 |
|------|------|--------|
| `main` | 安定版リリース | 本番利用向け |
| `nightly` | 実験的機能 | バグや破壊的変更が含まれる可能性あり |

### どのブランチを狙うべき？

**`nightly` を狙うケース:**

- 新機能/新能力
- 既存挙動に影響しうるリファクタ
- API や設定の変更
- 判断に迷う場合

**`main` を狙うケース:**

- 挙動を変えないバグ修正
- ドキュメント改善
- 機能に影響しない小さな調整

> **迷ったら `nightly` を推奨します。** 安定した内容を `nightly` から `main` へ持っていく方が、`main` に入ったリスクのある変更を取り消すよりはるかに容易です。

### nightly はどうやって main に入る？

`nightly` ブランチ全体をマージすることはありません。安定した機能を **cherry-pick** して、個別の PR として `main` に取り込みます。

```
nightly  ──┬── 機能 A（安定）──► PR ──► main
           ├── 機能 B（テスト中）
           └── 機能 C（安定）──► PR ──► main
```

これは概ね週 1 回程度ですが、実際のタイミングは各機能の成熟度次第です。

### ブランチ選択の早見表

| 変更の種類 | ターゲット |
|------------|---------|
| 新機能 | `nightly` |
| バグ修正 | `main` |
| ドキュメント | `main` |
| リファクタ | `nightly` |
| 不明 | `nightly` |

## 開発環境セットアップ

### リポジトリを取得

```bash
git clone https://github.com/HKUDS/nanobot.git
cd nanobot
```

### 依存関係をインストール

nanobot はパッケージマネージャとして [`uv`](https://github.com/astral-sh/uv) を使います。

```bash
# uv をインストール（未インストールの場合）
curl -LsSf https://astral.sh/uv/install.sh | sh

# すべての依存関係（開発依存を含む）をインストール
uv sync
```

### 動作確認

```bash
# テストを実行して環境を確認
uv run pytest tests/

# CLI を実行
uv run nanobot status
```

## コードスタイル

私たちが重視するのは単に lint を通すことではなく、nanobot を小さく、落ち着いた、読みやすいコードベースとして保つことです。

貢献時は、コードが次の性質を持つことを目指してください。

- **シンプル**: 本当に必要な問題を解く最小の変更を好む
- **明快**: 賢さの誇示より、次の読者に最適化する
- **疎結合**: 境界を明確にし、不要な抽象化を避ける
- **誠実**: 複雑さを隠さないが、余計な複雑さも作らない
- **耐久**: 保守/テスト/拡張がしやすい解決策を選ぶ

### 具体ルール

- **行長**: 100 文字（`ruff` が強制。E501 は無視）
- **Python**: 3.11+
- **Lint**: `ruff`（E / F / I / N / W）
- **非同期**: `asyncio` を全面採用。テストは `asyncio_mode = "auto"`
- 魔法のようなコードより可読性を優先
- 大規模な書き換えより、焦点の合った小さなパッチを優先
- 新しい抽象を導入する場合は、複雑さを「移動」するのではなく「減らす」ことが必須

### Lint とフォーマット

```bash
# lint をチェック
uv run ruff check nanobot/

# 自動修正可能な問題を修正
uv run ruff check nanobot/ --fix

# フォーマット
uv run ruff format nanobot/
```

## テストの実行

### すべてのテスト

```bash
uv run pytest tests/
```

### 特定のテストファイル

```bash
uv run pytest tests/test_channels.py -v
```

### 特定のテスト関数

```bash
uv run pytest tests/test_commands.py::test_function_name -v
```

### テストフレームワーク

- テスト: `pytest`
- 非同期: `pytest-asyncio`、`asyncio_mode = "auto"`（すべてのテストはデフォルトで async）
- テストは `tests/` ディレクトリ
- 統合テストケースは `case/` ディレクトリ

## テストを書く

### 基本構造

```python
# tests/test_my_feature.py
import pytest
from nanobot.agent.loop import AgentLoop


async def test_agent_handles_simple_message():
    """エージェントは単純なテキストメッセージを処理できるべき。"""
    # 準備
    # ...

    # 実行
    result = await some_function()

    # 検証
    assert result == expected
```

### 非同期コードのテスト

`asyncio_mode = "auto"` のため、`@pytest.mark.asyncio` を手動で付ける必要はありません。

```python
# async テスト関数を定義するだけで OK
async def test_channel_receives_message():
    channel = MockChannel()
    await channel.start()
    # ...
```

### 外部依存のモック

```python
from unittest.mock import AsyncMock, patch

async def test_llm_call():
    with patch("nanobot.providers.litellm_provider.LiteLLMProvider.chat") as mock_chat:
        mock_chat.return_value = AsyncMock(return_value="モック応答")
        # テスト実行
        ...
```

## Pull Request を送る

### PR 前チェックリスト

- [ ] すべてのテストが通る: `uv run pytest tests/`
- [ ] lint が通る: `uv run ruff check nanobot/`
- [ ] フォーマット済み: `uv run ruff format nanobot/`
- [ ] ターゲットブランチが正しい（`main` / `nightly`）
- [ ] PR の説明が、目的と影響を明確にしている

### PR 説明のガイド

良い PR 説明には次を含めます。

1. **変更の要約**: 1〜2 文で何をしたか
2. **理由**: 解決したい問題/要求
3. **テスト方法**: どうやって有効性を確認したか

### main への cherry-pick

`nightly` で安定した機能は、メンテナが `main` へ cherry-pick する場合があります。

```bash
# メンテナ側の操作例
git checkout main
git cherry-pick <commit-hash>
# main 向けに新しい PR を作成
```

## 連絡先とコミュニティ

質問、アイデア、まだ形になりきっていない気づきも歓迎します。

- [GitHub Issue を作成](https://github.com/HKUDS/nanobot/issues)
- [Discord コミュニティに参加](https://discord.gg/MnCvHqpUGB)
- [Feishu/WeChat グループに参加](https://github.com/HKUDS/nanobot/blob/main/COMMUNICATION.md)
- Email: Xubin Ren (@Re-bin) — xubinrencs@gmail.com

nanobot に時間と労力を割いてくださりありがとうございます。大小を問わず、あらゆる貢献を心より歓迎します。
