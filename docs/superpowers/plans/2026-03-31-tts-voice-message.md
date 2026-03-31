# TTS Voice Message Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Send a synthesised voice message (CosyVoice v3.5-plus, Alibaba Cloud Bailian) alongside the normal text reply when the user's WeChat message contains trigger phrases like "你说，".

**Architecture:** Keyword detection in `WeixinChannel.receive()` marks a per-session voice flag; `WeixinChannel.send()` checks the flag, calls `CosyVoiceTTSProvider.synthesize()` to produce an MP3, uploads it as `ITEM_VOICE` via the existing CDN upload protocol, then sends text as normal. All failures are non-fatal — text is always guaranteed.

**Tech Stack:** Python 3.11+, dashscope (`SpeechSynthesizer` from `dashscope.audio.tts_v3`), Pydantic V2, asyncio, pytest

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `nanobot/providers/tts.py` | `CosyVoiceTTSProvider` — calls dashscope, writes MP3 |
| Modify | `nanobot/config/schema.py` | Add `TTSConfig`; add `tts` field to `WeixinConfig` |
| Modify | `nanobot/channels/weixin.py` | Keyword detection, `_voice_sessions`, ITEM_VOICE send, TTS wiring |
| Create | `tests/providers/test_tts.py` | 5 unit tests for `CosyVoiceTTSProvider` |
| Create | `tests/channels/test_weixin_tts.py` | 5 unit tests for WeChat TTS integration |

---

## Task 1: TTSConfig in config/schema.py

**Files:**
- Modify: `nanobot/config/schema.py` (after `TranscriptionConfig`, before `ChannelsConfig`)

- [ ] **Step 1: Add `TTSConfig` and `WeixinConfig.tts` field**

In `nanobot/config/schema.py`, insert `TTSConfig` right after `TranscriptionConfig` (line ~23):

```python
class TTSConfig(Base):
    """TTS (text-to-speech) configuration for voice message synthesis."""

    provider: str = "cosyvoice"   # only cosyvoice implemented
    api_key: str = ""             # falls back to DASHSCOPE_API_KEY env var
    voice: str = "Asuka-Plus"     # CosyVoice voice ID
    model: str = "cosyvoice-v2-plus"  # confirm against Bailian docs at runtime
    format: str = "mp3"           # output audio format
```

In `nanobot/channels/weixin.py`, add to `WeixinConfig` (after `poll_timeout`):

```python
from nanobot.config.schema import Base, TTSConfig   # add TTSConfig to imports

class WeixinConfig(Base):
    enabled: bool = False
    allow_from: list[str] = Field(default_factory=list)
    base_url: str = "https://ilinkai.weixin.qq.com"
    cdn_base_url: str = "https://novac2c.cdn.weixin.qq.com/c2c"
    route_tag: str | int | None = None
    token: str = ""
    state_dir: str = ""
    poll_timeout: int = DEFAULT_LONG_POLL_TIMEOUT_S
    tts: TTSConfig = Field(default_factory=TTSConfig)  # ← new
```

- [ ] **Step 2: Verify schema parses correctly**

```bash
cd /path/to/.worktrees/feat-tts
uv run python -c "
from nanobot.channels.weixin import WeixinConfig
from nanobot.config.schema import TTSConfig
c = WeixinConfig()
print(c.tts.voice)        # Asuka-Plus
print(c.tts.model)        # cosyvoice-v2-plus
c2 = WeixinConfig.model_validate({'tts': {'voice': 'MyVoice', 'api_key': 'sk-x'}})
print(c2.tts.voice)       # MyVoice
print(c2.tts.api_key)     # sk-x
"
```

Expected output:
```
Asuka-Plus
cosyvoice-v2-plus
MyVoice
sk-x
```

- [ ] **Step 3: Commit**

```bash
git add nanobot/config/schema.py nanobot/channels/weixin.py
git commit -m "feat(tts): add TTSConfig schema and WeixinConfig.tts field"
```

---

## Task 2: CosyVoiceTTSProvider (TDD)

**Files:**
- Create: `nanobot/providers/tts.py`
- Create: `tests/providers/test_tts.py`

- [ ] **Step 1: Write all 5 failing tests**

Create `tests/providers/test_tts.py`:

```python
"""Tests for CosyVoiceTTSProvider."""

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from nanobot.config.schema import TTSConfig
from nanobot.providers.tts import CosyVoiceTTSProvider


def _provider(api_key: str = "sk-test") -> CosyVoiceTTSProvider:
    return CosyVoiceTTSProvider(TTSConfig(api_key=api_key, voice="Asuka-Plus", model="cosyvoice-v2-plus"))


@pytest.mark.asyncio
async def test_cosyvoice_no_api_key_returns_false(tmp_path, monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    provider = CosyVoiceTTSProvider(TTSConfig(api_key=""))
    result = await provider.synthesize("hello", tmp_path / "out.mp3")
    assert result is False


@pytest.mark.asyncio
async def test_cosyvoice_import_error_returns_false(tmp_path, monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    provider = _provider()
    with patch.dict("sys.modules", {"dashscope": None, "dashscope.audio": None, "dashscope.audio.tts_v3": None}):
        result = await provider.synthesize("hello", tmp_path / "out.mp3")
    assert result is False


@pytest.mark.asyncio
async def test_cosyvoice_empty_audio_returns_false(tmp_path, monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    provider = _provider()
    mock_result = MagicMock()
    mock_result.get_audio_data.return_value = None
    mock_synthesizer = MagicMock()
    mock_synthesizer.call.return_value = mock_result
    with patch.dict("sys.modules", {"dashscope": MagicMock(), "dashscope.audio": MagicMock(), "dashscope.audio.tts_v3": MagicMock(SpeechSynthesizer=mock_synthesizer)}):
        result = await provider.synthesize("hello", tmp_path / "out.mp3")
    assert result is False


@pytest.mark.asyncio
async def test_cosyvoice_happy_path(tmp_path, monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    provider = _provider()
    mock_result = MagicMock()
    mock_result.get_audio_data.return_value = b"fake-mp3-bytes"
    mock_synthesizer = MagicMock()
    mock_synthesizer.call.return_value = mock_result
    out = tmp_path / "voice.mp3"
    with patch.dict("sys.modules", {"dashscope": MagicMock(), "dashscope.audio": MagicMock(), "dashscope.audio.tts_v3": MagicMock(SpeechSynthesizer=mock_synthesizer)}):
        result = await provider.synthesize("你好，世界", out)
    assert result is True
    assert out.exists()
    assert out.read_bytes() == b"fake-mp3-bytes"


@pytest.mark.asyncio
async def test_cosyvoice_api_exception_returns_false(tmp_path, monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    provider = _provider()
    mock_synthesizer = MagicMock()
    mock_synthesizer.call.side_effect = RuntimeError("API error")
    with patch.dict("sys.modules", {"dashscope": MagicMock(), "dashscope.audio": MagicMock(), "dashscope.audio.tts_v3": MagicMock(SpeechSynthesizer=mock_synthesizer)}):
        result = await provider.synthesize("hello", tmp_path / "out.mp3")
    assert result is False
```

- [ ] **Step 2: Run tests to confirm RED**

```bash
cd /path/to/.worktrees/feat-tts
uv run pytest tests/providers/test_tts.py -v 2>&1 | head -20
```

Expected: `ERROR` — `ModuleNotFoundError: No module named 'nanobot.providers.tts'`

- [ ] **Step 3: Create `nanobot/providers/tts.py`**

```python
"""TTS (text-to-speech) providers."""

import asyncio
import os
from pathlib import Path

from loguru import logger

from nanobot.config.schema import TTSConfig


class CosyVoiceTTSProvider:
    """
    TTS provider using Alibaba Cloud Bailian CosyVoice.

    Synthesises text to MP3 audio via dashscope.audio.tts_v3.SpeechSynthesizer.
    Requires: pip install dashscope  (included in qwen3-asr extra)
    API key: https://dashscope.console.aliyun.com/
    """

    def __init__(self, config: TTSConfig):
        self.config = config
        self.api_key = config.api_key or os.environ.get("DASHSCOPE_API_KEY", "")

    async def synthesize(self, text: str, output_path: Path) -> bool:
        """
        Synthesise text to audio and write to output_path.

        Returns True on success, False on any failure (non-fatal).
        """
        if not self.api_key:
            logger.warning("TTS: no api_key configured, skipping voice synthesis")
            return False

        try:
            from dashscope.audio.tts_v3 import SpeechSynthesizer
        except ImportError:
            logger.error("dashscope not installed. Run: pip install dashscope")
            return False

        try:
            result = await asyncio.to_thread(
                SpeechSynthesizer.call,
                model=self.config.model,
                text=text,
                voice=self.config.voice,
                format=self.config.format,
                api_key=self.api_key,
            )
            audio_data = result.get_audio_data()
            if not audio_data:
                logger.warning("TTS: CosyVoice returned empty audio for text length={}", len(text))
                return False
            Path(output_path).write_bytes(audio_data)
            logger.debug("TTS: synthesised {} bytes → {}", len(audio_data), output_path)
            return True
        except Exception as e:
            logger.warning("TTS synthesis failed: {}", e)
            return False
```

- [ ] **Step 4: Run tests to confirm GREEN**

```bash
uv run pytest tests/providers/test_tts.py -v
```

Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add nanobot/providers/tts.py tests/providers/test_tts.py
git commit -m "feat(tts): add CosyVoiceTTSProvider with dashscope integration"
```

---

## Task 3: WeChat keyword detection + voice session state (TDD)

**Files:**
- Modify: `nanobot/channels/weixin.py`
- Create: `tests/channels/test_weixin_tts.py`

- [ ] **Step 1: Write 3 failing tests for keyword detection**

Create `tests/channels/test_weixin_tts.py`:

```python
"""Tests for WeChat TTS voice message integration."""

import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.weixin import WeixinChannel, WeixinConfig
from nanobot.config.schema import TTSConfig


def _make_channel(tts_api_key: str = "") -> WeixinChannel:
    bus = MessageBus()
    return WeixinChannel(
        WeixinConfig(
            enabled=True,
            allow_from=["*"],
            state_dir=tempfile.mkdtemp(prefix="nanobot-weixin-tts-test-"),
            tts=TTSConfig(api_key=tts_api_key, voice="Asuka-Plus", model="cosyvoice-v2-plus"),
        ),
        bus,
    )


def test_wants_voice_triggers_on_keywords():
    ch = _make_channel()
    assert ch._wants_voice("你说，今天天气怎么样") is True
    assert ch._wants_voice("你来说一下市场分析") is True
    assert ch._wants_voice("说给我听，关于这个问题") is True
    assert ch._wants_voice("用语音回答我") is True
    assert ch._wants_voice("语音回复") is True


def test_wants_voice_no_trigger_on_normal_text():
    ch = _make_channel()
    assert ch._wants_voice("帮我分析一下市场") is False
    assert ch._wants_voice("今天天气怎么样") is False
    assert ch._wants_voice("你好") is False
    assert ch._wants_voice("") is False


def test_voice_sessions_initialised_empty():
    ch = _make_channel()
    assert ch._voice_sessions == {}
```

- [ ] **Step 2: Run tests to confirm RED**

```bash
uv run pytest tests/channels/test_weixin_tts.py -v 2>&1 | head -20
```

Expected: `AttributeError: 'WeixinChannel' object has no attribute '_wants_voice'`

- [ ] **Step 3: Add keyword detection + `_voice_sessions` to `weixin.py`**

At the top of `weixin.py`, add `import re` (if not present) and add the pattern constant after the existing `_VIDEO_EXTS` set (around line 79):

```python
# Voice trigger patterns — user requests a spoken reply
_VOICE_TRIGGER_PATTERNS = re.compile(
    r"(你说|你来说|说给我听|用语音(说|回答|回复)|语音回复)"
)
```

In `WeixinChannel.__init__` (around line 126, after existing state attrs), add:

```python
self._voice_sessions: dict[str, bool] = {}  # chat_id -> wants_voice flag
```

After `__init__`, add the method (e.g., after `_get_state_dir`):

```python
def _wants_voice(self, content: str) -> bool:
    """Return True if the message contains a voice-reply trigger phrase."""
    return bool(_VOICE_TRIGGER_PATTERNS.search(content))
```

- [ ] **Step 4: Run tests to confirm GREEN**

```bash
uv run pytest tests/channels/test_weixin_tts.py -v
```

Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add nanobot/channels/weixin.py tests/channels/test_weixin_tts.py
git commit -m "feat(tts): add voice trigger detection and session state to WeixinChannel"
```

---

## Task 4: ITEM_VOICE send + TTS wiring in send() (TDD)

**Files:**
- Modify: `nanobot/channels/weixin.py`
- Modify: `tests/channels/test_weixin_tts.py`

- [ ] **Step 1: Add 5 failing tests**

Append to `tests/channels/test_weixin_tts.py`:

```python
@pytest.mark.asyncio
async def test_inbound_voice_trigger_sets_session_flag():
    """After processing a message with a voice trigger, _voice_sessions is marked."""
    ch = _make_channel()
    ch._token = "tok"
    ch._context_tokens = {"wx-user": "ctx-1"}

    # Simulate _process_message setting the flag (we call _wants_voice + set directly
    # since _process_message requires a full HTTP stack)
    text = "你说，帮我分析一下"
    if ch._wants_voice(text):
        ch._voice_sessions["wx-user"] = True

    assert ch._voice_sessions.get("wx-user") is True


@pytest.mark.asyncio
async def test_send_calls_tts_and_sends_voice_when_session_flagged(tmp_path, monkeypatch):
    """When _voice_sessions is set, send() calls TTS and sends the MP3."""
    ch = _make_channel(tts_api_key="sk-test")
    ch._token = "tok"
    ch._context_tokens = {"wx-user": "ctx-1"}
    ch._voice_sessions["wx-user"] = True

    # Mock TTS provider to write a fake MP3
    async def fake_synthesize(text: str, output_path) -> bool:
        from pathlib import Path
        Path(output_path).write_bytes(b"fake-mp3")
        return True

    ch._tts_provider.synthesize = fake_synthesize  # type: ignore

    sent_media = []
    sent_text = []

    async def fake_send_media(to, path, ctx):
        sent_media.append(str(path))

    async def fake_send_text(to, text, ctx):
        sent_text.append(text)

    ch._send_media_file = fake_send_media  # type: ignore
    ch._send_text = fake_send_text  # type: ignore

    # Need a real client mock to avoid assertion in send()
    ch._client = MagicMock()

    msg = OutboundMessage(channel="weixin", chat_id="wx-user", content="这是回复内容")
    await ch.send(msg)

    assert len(sent_media) == 1
    assert sent_media[0].endswith(".mp3")
    assert sent_text == ["这是回复内容"]
    # Session flag consumed
    assert "wx-user" not in ch._voice_sessions


@pytest.mark.asyncio
async def test_send_text_still_sent_when_tts_fails(monkeypatch):
    """If TTS synthesis fails, text is still sent normally."""
    ch = _make_channel(tts_api_key="sk-test")
    ch._token = "tok"
    ch._context_tokens = {"wx-user": "ctx-1"}
    ch._voice_sessions["wx-user"] = True
    ch._client = MagicMock()

    async def failing_synthesize(text, output_path) -> bool:
        return False

    ch._tts_provider.synthesize = failing_synthesize  # type: ignore

    sent_text = []

    async def fake_send_text(to, text, ctx):
        sent_text.append(text)

    ch._send_media_file = AsyncMock()
    ch._send_text = fake_send_text  # type: ignore

    msg = OutboundMessage(channel="weixin", chat_id="wx-user", content="回复")
    await ch.send(msg)

    assert sent_text == ["回复"]
    ch._send_media_file.assert_not_called()


@pytest.mark.asyncio
async def test_send_skips_tts_when_no_provider():
    """If _tts_provider is None (no api_key), send() skips TTS silently."""
    ch = _make_channel(tts_api_key="")
    ch._token = "tok"
    ch._context_tokens = {"wx-user": "ctx-1"}
    ch._voice_sessions["wx-user"] = True
    ch._client = MagicMock()

    sent_media = []
    sent_text = []

    async def fake_send_media(to, path, ctx):  # pragma: no cover
        sent_media.append(path)

    async def fake_send_text(to, text, ctx):
        sent_text.append(text)

    ch._send_media_file = fake_send_media  # type: ignore
    ch._send_text = fake_send_text  # type: ignore

    msg = OutboundMessage(channel="weixin", chat_id="wx-user", content="回复")
    await ch.send(msg)

    assert sent_media == []
    assert sent_text == ["回复"]
```

- [ ] **Step 2: Run tests to confirm RED**

```bash
uv run pytest tests/channels/test_weixin_tts.py -v
```

Expected: 3 pass (existing), 4 fail (new ones — `_tts_provider` not yet set, `_assert_session_active` raises on mock client)

- [ ] **Step 3: Add `import tempfile` + ITEM_VOICE constant + voice branch in `_send_media_file`**

In `weixin.py`, add `import tempfile` to the imports block (alongside the other stdlib imports at the top).

Add constant after `UPLOAD_MEDIA_FILE = 3` (line 75):

```python
UPLOAD_MEDIA_VOICE = 4          # value to verify against WeChat ilink API docs
_VOICE_EXTS = {".mp3", ".ogg", ".wav", ".m4a"}
```

In `_send_media_file`, replace the `else` branch (around line 828) with:

```python
        elif ext in _VOICE_EXTS:
            upload_type = UPLOAD_MEDIA_VOICE
            item_type = ITEM_VOICE
            item_key = "voice_item"
        else:
            upload_type = UPLOAD_MEDIA_FILE
            item_type = ITEM_FILE
            item_key = "file_item"
```

In the `media_item` field assignment block (around line 902), add a voice branch:

```python
        if item_type == ITEM_IMAGE:
            media_item["mid_size"] = padded_size
        elif item_type == ITEM_VIDEO:
            media_item["video_size"] = padded_size
        elif item_type == ITEM_VOICE:
            media_item["voice_size"] = raw_size
        elif item_type == ITEM_FILE:
            media_item["file_name"] = p.name
            media_item["len"] = str(raw_size)
```

- [ ] **Step 4: Wire `_tts_provider` in `__init__` and TTS logic in `send()`**

In `WeixinChannel.__init__`, add after `self._voice_sessions`:

```python
        from nanobot.providers.tts import CosyVoiceTTSProvider
        self._tts_provider: CosyVoiceTTSProvider | None = (
            CosyVoiceTTSProvider(self.config.tts)
            if (self.config.tts.api_key or os.environ.get("DASHSCOPE_API_KEY"))
            else None
        )
```

In `send()`, insert TTS post-processing after the `ctx_token` early-return check and before the media loop (around line 732). Replace the existing media+text block with:

```python
        wants_voice = self._voice_sessions.pop(msg.chat_id, False)

        # --- TTS voice message (before text, matching media-first pattern) ---
        if wants_voice and msg.content and self._tts_provider:
            import tempfile
            tmp = Path(tempfile.mktemp(suffix=".mp3", prefix="nanobot-tts-"))
            ok = await self._tts_provider.synthesize(content, tmp)
            if ok:
                try:
                    await self._send_media_file(msg.chat_id, str(tmp), ctx_token)
                except Exception as e:
                    logger.error("Failed to send WeChat TTS voice: {}", e)
                finally:
                    tmp.unlink(missing_ok=True)

        # --- Send existing media files ---
        for media_path in (msg.media or []):
            try:
                await self._send_media_file(msg.chat_id, media_path, ctx_token)
            except Exception as e:
                filename = Path(media_path).name
                logger.error("Failed to send WeChat media {}: {}", media_path, e)
                await self._send_text(
                    msg.chat_id, f"[Failed to send: {filename}]", ctx_token,
                )

        # --- Send text content ---
        if not content:
            return

        try:
            chunks = split_message(content, WEIXIN_MAX_MESSAGE_LEN)
            for chunk in chunks:
                await self._send_text(msg.chat_id, chunk, ctx_token)
        except Exception as e:
            logger.error("Error sending WeChat message: {}", e)
            raise
```

Also need to handle the `_assert_session_active` call in `send()` — the tests mock `_client` to a `MagicMock` which passes the `if not self._client` check. However `_assert_session_active` checks `self._session_pause_until`. Verify the tests pass without mocking it (default value `0.0` means not paused).

- [ ] **Step 5: Run full test suite**

```bash
uv run pytest tests/channels/test_weixin_tts.py -v
```

Expected: `8 passed`

Then run full suite to check for regressions:

```bash
uv run pytest tests/ -q
```

Expected: all existing tests pass + 8 new tests.

- [ ] **Step 6: Lint**

```bash
uv run ruff check nanobot/providers/tts.py nanobot/channels/weixin.py nanobot/config/schema.py
uv run ruff check --fix nanobot/providers/tts.py nanobot/channels/weixin.py nanobot/config/schema.py
```

- [ ] **Step 7: Commit**

```bash
git add nanobot/channels/weixin.py tests/channels/test_weixin_tts.py
git commit -m "feat(tts): wire CosyVoice TTS into WeixinChannel send() with ITEM_VOICE support"
```

---

## Task 5: Push branch and open PR

- [ ] **Step 1: Push branch**

```bash
git push -u origin feat/tts-voice-message
```

- [ ] **Step 2: Open PR**

```bash
gh pr create \
  --title "feat(tts): WeChat voice message via CosyVoice TTS" \
  --body "$(cat <<'EOF'
## Summary
- Add `CosyVoiceTTSProvider` (`providers/tts.py`) using dashscope `SpeechSynthesizer`
- Add `TTSConfig` to config schema; `WeixinConfig` gets a `tts` field
- `WeixinChannel` detects trigger phrases (\"你说,\" etc.) and synthesises a voice MP3
- Voice (ITEM_VOICE) + text both sent; TTS failure is non-fatal
- 10 new tests (5 provider, 5 channel)

## Test plan
- [ ] `uv run pytest tests/providers/test_tts.py tests/channels/test_weixin_tts.py -v`
- [ ] Full suite: `uv run pytest tests/ -q`
- [ ] Manual test on WeChat: send \"你说，今天天气怎么样\" and verify voice + text reply

## Open question
`UPLOAD_MEDIA_VOICE` constant set to `4` — confirm against WeChat ilink bot API docs before merge.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Verification

End-to-end manual test after deploying to Mac Mini:

1. Open WeChat and message the bot: `你说，简单介绍一下你自己`
2. Expected: receive a voice message (mp3 playable in WeChat) + text reply
3. Send a normal message: `你好`
4. Expected: receive text only, no voice

Config to add in `~/.nanobot/config.json` on Mac Mini:
```json
{
  "channels": {
    "weixin": {
      "tts": {
        "api_key": "<DASHSCOPE_API_KEY>",
        "voice": "Asuka-Plus",
        "model": "cosyvoice-v2-plus"
      }
    }
  }
}
```
