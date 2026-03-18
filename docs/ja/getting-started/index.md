# 入門ガイド

**nanobot** へようこそ。nanobot は超軽量な個人向け AI アシスタントフレームワークで、16+ のチャットプラットフォーム、複数の LLM プロバイダ、そして MCP 統合に対応しています。

このセクションでは、インストールから AI アシスタントとの最初の会話までを数分で完了できるように案内します。

---

## このセクションの内容

<div class="grid cards" markdown>

-   :material-download-box:{ .lg .middle } **インストール**

    ---

    システム要件、インストール方法（pip / uv / ソース / Docker）、よくあるトラブルシュート。

    [:octicons-arrow-right-24: インストールガイド](installation.md)

-   :material-rocket-launch:{ .lg .middle } **クイックスタート**

    ---

    5 分でセットアップして、nanobot を Telegram または CLI で動かします。

    [:octicons-arrow-right-24: クイックスタート](quick-start.md)

-   :material-wizard-hat:{ .lg .middle } **Onboarding ウィザード**

    ---

    `nanobot onboard` ウィザードの各ステップと、workspace テンプレートのカスタマイズ方法を詳しく説明します。

    [:octicons-arrow-right-24: Onboarding ウィザード](onboarding.md)

</div>

---

## 学習の流れ

```
nanobot をインストール
    ↓
nanobot onboard を実行（設定と workspace を初期化）
    ↓
~/.nanobot/config.json を編集（API キーとモデルを設定）
    ↓
nanobot agent（CLI で対話）
    ↓
チャットプラットフォームに接続（Telegram / Discord / Slack など）
    ↓
nanobot gateway（Gateway を起動しリアルタイムメッセージを受信）
```

## 事前準備

開始前に、次を用意してください。

| 要件 | 説明 |
|------|------|
| **Python 3.11+** | nanobot は Python 3.11 以降が必要です |
| **uv**（推奨）または **pip** | Python パッケージ管理ツール |
| **LLM API キー** | 例: OpenRouter、Anthropic、OpenAI など |
| **（任意）チャットプラットフォームの Bot Token** | チャットプラットフォーム連携が必要な場合（例: Telegram Bot Token） |

!!! tip "初めての方におすすめ"
    API キーの入手先が分からない場合は、[OpenRouter](https://openrouter.ai/keys) がおすすめです。主要モデルに幅広く対応し、無料枠もあります。

## よくある質問

**Q: nanobot はどの LLM をサポートしていますか？**

OpenAI、Anthropic Claude、Google Gemini、DeepSeek、Qwen、ローカル Ollama など、20+ の LLM プロバイダに対応しています。詳しくは [Providers ドキュメント](../providers/index.md) を参照してください。

**Q: 公開 IP は必要ですか？**

不要です。多くのチャットチャンネル（Telegram、Discord、Feishu、DingTalk、Slack）は WebSocket の長期接続や Socket Mode を利用するため、公開 IP を必要としません。

**Q: nanobot のリソース使用量はどの程度ですか？**

非常に小さいです。nanobot のコアは約 16,000 行の Python で構成され、起動が速く、メモリ使用量も最小限です。
