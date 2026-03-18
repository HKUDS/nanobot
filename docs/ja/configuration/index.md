# 設定概要

Nanobot は 1 つの JSON 設定ファイルで、AI モデル、チャットチャンネル、ツール、Gateway サーバーなどすべての挙動を管理します。

---

## 設定ファイルの場所

デフォルトの設定ファイルパス:

```
~/.nanobot/config.json
```

`nanobot onboard` の対話式ウィザードを実行すると、このパスに自動で作成されます。

### カスタムパスを使う

`-c` / `--config` で任意のパスを指定できます。

```bash
# gateway 起動時に設定ファイルを指定
nanobot gateway --config ~/.nanobot-work/config.json

# CLI agent 実行時に設定ファイルを指定
nanobot agent -c ~/.nanobot-personal/config.json -m "こんにちは！"
```

> [!TIP]
> 複数インスタンス運用では、各インスタンスが独立した config パスを使います。詳しくは [複数インスタンスガイド](./multi-instance.md)。

---

## 設定ファイル形式

設定ファイルは標準 JSON です。キーは **camelCase** と **snake_case** の両方をサポートし、混在させることもできます。

```json
{
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5",
      "maxTokens": 8192,
      "max_tool_iterations": 40
    }
  }
}
```

> [!NOTE]
> 標準 JSON はコメント（`//`）をサポートしません。本ドキュメントの例で `// 説明` を使うことがありますが、実際の設定ファイルにはコメントを含めないでください。

---

## Pydantic による検証

Nanobot は [Pydantic](https://docs.pydantic.dev/) で設定を解析・検証します。起動時に形式が不正であれば即時にエラーになり、問題箇所が示されます（無効値を黙って無視しません）。

---

## 環境変数のサポート

すべての設定は環境変数で上書きできます。プレフィックスは `NANOBOT_`、ネストしたキーは `__`（ダブルアンダースコア）で区切ります。

| 環境変数 | 対応設定 |
|----------|----------|
| `NANOBOT_AGENTS__DEFAULTS__MODEL` | `agents.defaults.model` |
| `NANOBOT_PROVIDERS__ANTHROPIC__API_KEY` | `providers.anthropic.api_key` |
| `NANOBOT_GATEWAY__PORT` | `gateway.port` |
| `NANOBOT_TOOLS__EXEC__TIMEOUT` | `tools.exec.timeout` |

環境変数は設定ファイルより優先されるため、Docker や CI/CD で機密情報を注入するのに便利です。

```bash
# 例: 環境変数で API キーを設定
export NANOBOT_PROVIDERS__ANTHROPIC__API_KEY="sk-ant-..."
nanobot gateway
```

---

## トップレベルキー早見表

| キー | 型 | 説明 |
|----|------|------|
| [`agents`](./reference.md#agents) | オブジェクト | agent のデフォルト挙動（モデル、workspace、Token 制限など） |
| [`channels`](./reference.md#channels) | オブジェクト | チャンネル設定（Slack/Discord/Telegram など） |
| [`providers`](./reference.md#providers) | オブジェクト | LLM プロバイダの API キーとエンドポイント |
| [`gateway`](./reference.md#gateway) | オブジェクト | HTTP Gateway サーバー（ホスト、ポート、ハートビート） |
| [`tools`](./reference.md#tools) | オブジェクト | ツール設定（ウェブ検索、Shell 実行、MCP サーバーなど） |

---

## 最小構成の例

Telegram チャンネル + Anthropic モデルだけを使う最小構成例です。

```json
{
  "providers": {
    "anthropic": {
      "apiKey": "sk-ant-..."
    }
  },
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "allowFrom": ["YOUR_USER_ID"]
    }
  }
}
```

記載のないオプションはすべてデフォルト値が利用されるため、明示的に設定する必要はありません。

---

## 参考

- [設定リファレンス（完全版）](./reference.md) — 各オプションの詳細とデフォルト
- [複数インスタンスガイド](./multi-instance.md) — 複数の Nanobot インスタンスを同時に実行
- [CLI リファレンス](../cli-reference.md) — すべての CLI フラグ
