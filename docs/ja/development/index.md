# 開発ドキュメント概要

nanobot の開発ドキュメントへようこそ。このセクションでは、nanobot のアーキテクチャ、コントリビュート方法、そしてカスタムプラグイン開発に必要な情報を提供します。

## 目次

| ドキュメント | 説明 |
|------|------|
| [アーキテクチャ](./architecture.md) | システム設計、モジュール関係、データフロー |
| [コントリビュート](./contributing.md) | ブランチ戦略、コードスタイル、PR の作り方 |
| [チャンネルプラグイン開発](./channel-plugin.md) | カスタムチャットプラットフォームプラグインの開発 |

## クイックスタート

### 環境セットアップ

```bash
# リポジトリを取得
git clone https://github.com/HKUDS/nanobot.git
cd nanobot

# 依存関係をインストール（開発依存も含む）
uv sync

# テストを実行
uv run pytest tests/

# ローカル agent を起動してテスト
uv run nanobot agent
```

### 重要な原則

nanobot のコア設計理念は「最小限のコードで最も本質的な機能を実現する」です。

- **軽量**: 約 16k 行の Python でフル機能のエージェントを実装
- **非同期優先**: `async/await` を全面採用してブロッキング呼び出しを回避
- **イベント駆動**: メッセージは bus でルーティングされ、各コンポーネントは疎結合
- **拡張性**: プラグイン機構でカスタムチャンネルやスキルをサポート

## プロジェクト構成

```
nanobot/
├── agent/          # コアのエージェントロジック
│   ├── loop.py     #   メインループ（LLM ↔ ツール実行）
│   ├── context.py  #   プロンプト構築
│   ├── memory.py   #   メモリ統合
│   └── tools/      #   ツール実装
├── bus/            # メッセージバス
├── channels/       # チャットプラットフォームアダプタ（プラグイン対応）
├── providers/      # LLM プロバイダ
├── session/        # セッション管理
├── config/         # 設定スキーマ（Pydantic）
├── skills/         # 組み込みスキル
├── cron/           # スケジュールタスク
└── heartbeat/      # ハートビート（定期起動）
```

## 関連リソース

- [GitHub リポジトリ](https://github.com/HKUDS/nanobot)
- [Issue で報告](https://github.com/HKUDS/nanobot/issues)
- [Discord コミュニティ](https://discord.gg/MnCvHqpUGB)
- [チャンネルプラグインガイド（英語）](../CHANNEL_PLUGIN_GUIDE.md)
