# チャンネルプラグインガイド

カスタム nanobot チャンネルは 3 ステップで作れます: サブクラス化、パッケージ化、インストール。

## 仕組み

nanobot は Python の [entry points](https://packaging.python.org/en/latest/specifications/entry-points/) を通じてチャンネルプラグインを検出します。`nanobot gateway` の起動時に、次をスキャンします。

1. `nanobot/channels/` にある内蔵チャンネル
2. `nanobot.channels` entry point グループに登録された外部パッケージ

対応する config セクションに `"enabled": true` があると、そのチャンネルがインスタンス化され起動します。

## クイックスタート

HTTP POST でメッセージを受け取り、返信を送り返す最小の webhook チャンネルを作ります。

### プロジェクト構成

```
nanobot-channel-webhook/
├── nanobot_channel_webhook/
│   ├── __init__.py          # WebhookChannel を再エクスポート
│   └── channel.py           # チャンネル実装
└── pyproject.toml
```

### 1. チャンネルを作成

```python
# nanobot_channel_webhook/__init__.py
from nanobot_channel_webhook.channel import WebhookChannel

__all__ = ["WebhookChannel"]
```

```python
# nanobot_channel_webhook/channel.py
import asyncio
from typing import Any

from aiohttp import web
from loguru import logger

from nanobot.channels.base import BaseChannel
from nanobot.bus.events import OutboundMessage


class WebhookChannel(BaseChannel):
    name = "webhook"
    display_name = "Webhook"

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return {"enabled": False, "port": 9000, "allowFrom": []}

    async def start(self) -> None:
        """受信メッセージを待ち受ける HTTP サーバーを起動する。

        重要: start() は永久にブロックし続ける（または stop() が呼ばれるまで）。
        戻ってしまうとチャンネルは停止（dead）扱いになる。
        """
        self._running = True
        port = self.config.get("port", 9000)

        app = web.Application()
        app.router.add_post("/message", self._on_request)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()
        logger.info("Webhook listening on :{}", port)

        # stop されるまでブロック
        while self._running:
            await asyncio.sleep(1)

        await runner.cleanup()

    async def stop(self) -> None:
        self._running = False

    async def send(self, msg: OutboundMessage) -> None:
        """送信メッセージを配信する。

        msg.content  — markdown テキスト（必要に応じてプラットフォーム形式に変換）
        msg.media    — 添付するローカルファイルパスのリスト
        msg.chat_id  — 送信先（_handle_message に渡した chat_id と同じ値）
        msg.metadata — ストリーミング分割送信のため "_progress": True を含む場合がある
        """
        logger.info("[webhook] -> {}: {}", msg.chat_id, msg.content[:80])
        # 実運用のプラグインでは、コールバック URL へ POST したり SDK 経由で送信したりします。

    async def _on_request(self, request: web.Request) -> web.Response:
        """受信した HTTP POST を処理する。"""
        body = await request.json()
        sender = body.get("sender", "unknown")
        chat_id = body.get("chat_id", sender)
        text = body.get("text", "")
        media = body.get("media", [])       # URL のリスト

        # ここが重要: allowFrom を検証した上で、
        # agent が処理できるようにメッセージを bus に流す。
        await self._handle_message(
            sender_id=sender,
            chat_id=chat_id,
            content=text,
            media=media,
        )

        return web.json_response({"ok": True})
```

### 2. Entry Point を登録

```toml
# pyproject.toml
[project]
name = "nanobot-channel-webhook"
version = "0.1.0"
dependencies = ["nanobot", "aiohttp"]

[project.entry-points."nanobot.channels"]
webhook = "nanobot_channel_webhook:WebhookChannel"

[build-system]
requires = ["setuptools"]
build-backend = "setuptools.backends._legacy:_Backend"
```

キー（`webhook`）は config セクション名になります。値は `BaseChannel` サブクラスを指します。

### 3. インストール & 設定

```bash
pip install -e .
nanobot plugins list      # "Webhook" が "plugin" として表示されることを確認
nanobot onboard           # 検出されたプラグインのデフォルト設定を自動追加
```

`~/.nanobot/config.json` を編集します。

```json
{
  "channels": {
    "webhook": {
      "enabled": true,
      "port": 9000,
      "allowFrom": ["*"]
    }
  }
}
```

### 4. 実行 & テスト

```bash
nanobot gateway
```

別ターミナルで:

```bash
curl -X POST http://localhost:9000/message \
  -H "Content-Type: application/json" \
  -d '{"sender": "user1", "chat_id": "user1", "text": "Hello!"}'
```

agent がメッセージを受信して処理します。返信は `send()` メソッドに到達します。

## BaseChannel API

### 必須（abstract）

| メソッド | 説明 |
|--------|-------------|
| `async start()` | **必ずブロックし続ける必要があります。** プラットフォームへ接続し、メッセージを待ち受け、各メッセージで `_handle_message()` を呼びます。これが戻るとチャンネルは停止扱いです。 |
| `async stop()` | `self._running = False` を設定してクリーンアップします。gateway 停止時に呼ばれます。 |
| `async send(msg: OutboundMessage)` | プラットフォームへ送信メッセージを配信します。 |

### BaseChannel が提供するもの

| メソッド / プロパティ | 説明 |
|-------------------|-------------|
| `_handle_message(sender_id, chat_id, content, media?, metadata?, session_key?)` | **メッセージを受信したらこれを呼びます。** `is_allowed()` を確認し、bus へ publish します。 |
| `is_allowed(sender_id)` | `config["allowFrom"]` に対してチェックします。`"*"` は全許可、`[]` は全拒否です。 |
| `default_config()`（classmethod） | `nanobot onboard` 用のデフォルト config dict を返します。フィールドを宣言するために override してください。 |
| `transcribe_audio(file_path)` | Groq Whisper（設定済みの場合）で音声を文字起こしします。 |
| `is_running` | `self._running` を返します。 |

### メッセージ型

```python
@dataclass
class OutboundMessage:
    channel: str        # チャンネル名
    chat_id: str        # 送信先（_handle_message に渡した chat_id と同じ値）
    content: str        # markdown テキスト（必要に応じてプラットフォーム形式に変換）
    media: list[str]    # 添付するローカルファイルパス（画像/音声/ドキュメントなど）
    metadata: dict      # ストリーミング分割送信用に "_progress"（bool）を含む場合がある,
                        #              "message_id"（スレッド返信用）
```

## Config

チャンネルは config をプレーンな `dict` として受け取ります。`.get()` で参照してください。

```python
async def start(self) -> None:
    port = self.config.get("port", 9000)
    token = self.config.get("token", "")
```

`allowFrom` は `_handle_message()` が自動処理するので、プラグイン側でチェックする必要はありません。

`default_config()` を override すると、`nanobot onboard` が検出したプラグインのデフォルト設定を `config.json` に自動追加できます。

```python
@classmethod
def default_config(cls) -> dict[str, Any]:
    return {"enabled": False, "port": 9000, "allowFrom": []}
```

override しない場合、ベースクラスは `{"enabled": false}` を返します。

## 命名規約

| 対象 | 形式 | 例 |
|------|--------|---------|
| PyPI パッケージ | `nanobot-channel-{name}` | `nanobot-channel-webhook` |
| Entry point キー | `{name}` | `webhook` |
| Config セクション | `channels.{name}` | `channels.webhook` |
| Python パッケージ | `nanobot_channel_{name}` | `nanobot_channel_webhook` |

## ローカル開発

```bash
git clone https://github.com/you/nanobot-channel-webhook
cd nanobot-channel-webhook
pip install -e .
nanobot plugins list    # "Webhook" が "plugin" として表示されるはず
nanobot gateway         # エンドツーエンドでテスト
```

## 確認

```bash
$ nanobot plugins list

  Name       Source    Enabled
  telegram   builtin  yes
  discord    builtin  no
  webhook    plugin   yes
```
