# TTS Voice Message — Design Spec

**Date:** 2026-03-31
**Branch:** feat/tts-voice-message
**Scope:** WeChat channel only (initial implementation)

---

## Context

When a user includes phrases like "你说，" in their message, nanobot should reply with both a text message and a synthesised voice message. TTS provider is Alibaba Cloud Bailian CosyVoice v3.5-plus with a custom voice "Asuka-Plus".

---

## Architecture & Data Flow

```
User: "你说，帮我分析今天的市场"
        ↓
WeixinChannel.receive()
  └─ _wants_voice(content) → True
  └─ _voice_sessions[chat_id] = True
        ↓
InboundMessage → MessageBus → AgentLoop
  (agent produces normal text response, unaware of TTS)
        ↓
OutboundMessage → WeixinChannel.send()
  └─ _voice_sessions.pop(chat_id) → True
  └─ CosyVoiceTTSProvider.synthesize(content) → /tmp/nanobot-tts-xxxx.mp3
  └─ _send_media_file(chat_id, mp3_path, ITEM_VOICE)   ← new
  └─ _send_text(chat_id, content)                       ← existing
  └─ tmp.unlink()                                       ← cleanup
```

**Files changed:**

| File | Change |
|------|--------|
| `providers/tts.py` | New — `CosyVoiceTTSProvider` |
| `config/schema.py` | New `TTSConfig`; add `tts` field to `WeixinConfig` |
| `channels/weixin.py` | Keyword detection, `_voice_sessions`, ITEM_VOICE send |
| `tests/providers/test_tts.py` | New |
| `tests/channels/test_weixin_tts.py` | New |
| `pyproject.toml` | No new dependencies (dashscope already in `qwen3-asr` extra) |

---

## Configuration

```python
class TTSConfig(Base):
    provider: str = "cosyvoice"       # extension point; only cosyvoice implemented
    api_key: str = ""                 # falls back to DASHSCOPE_API_KEY env var
    voice: str = "Asuka-Plus"         # CosyVoice voice ID
    model: str = "cosyvoice-v2-plus"  # model name — confirm against Bailian docs
    format: str = "mp3"               # output format

class WeixinConfig(Base):
    ...  # existing fields unchanged
    tts: TTSConfig = Field(default_factory=TTSConfig)
```

User config example (`~/.nanobot/config.json`):
```json
{
  "channels": {
    "weixin": {
      "tts": {
        "api_key": "sk-xxx",
        "voice": "Asuka-Plus",
        "model": "cosyvoice-v2-plus"
      }
    }
  }
}
```

---

## TTS Provider (`providers/tts.py`)

```python
class CosyVoiceTTSProvider:
    def __init__(self, config: TTSConfig):
        self.config = config
        self.api_key = config.api_key or os.environ.get("DASHSCOPE_API_KEY", "")

    async def synthesize(self, text: str, output_path: Path) -> bool:
        """Call CosyVoice API, write audio to output_path. Returns True on success."""
        if not self.api_key:
            logger.warning("TTS: no api_key, skipping")
            return False
        try:
            from dashscope.audio.tts_v3 import SpeechSynthesizer
            result = await asyncio.to_thread(
                SpeechSynthesizer.call,
                model=self.config.model,
                text=text,
                voice=self.config.voice,
                format=self.config.format,
                api_key=self.api_key,
            )
            if result.get_audio_data():
                output_path.write_bytes(result.get_audio_data())
                return True
            logger.warning("TTS: empty audio response")
            return False
        except Exception as e:
            logger.warning("TTS synthesis failed: {}", e)
            return False
```

Follows the same pattern as `Qwen3ASRTranscriptionProvider`: `api_key` passed per-call, sync SDK wrapped in `asyncio.to_thread`, all exceptions caught and logged.

---

## WeChat Channel Changes (`channels/weixin.py`)

### Keyword detection

```python
_VOICE_TRIGGER_PATTERNS = re.compile(
    r"(你说|你来说|说给我听|用语音(说|回答|回复)|语音回复)"
)

def _wants_voice(self, content: str) -> bool:
    return bool(_VOICE_TRIGGER_PATTERNS.search(content))
```

### Inbound: mark session

```python
# inside receive(), after extracting text_content:
if self._wants_voice(text_content):
    self._voice_sessions[chat_id] = True
```

`_voice_sessions: dict[str, bool]` is an instance attribute initialised in `__init__`.

### New constant

```python
UPLOAD_MEDIA_VOICE = 4   # value to be confirmed against WeChat ilink API docs
_VOICE_EXTS = {".mp3", ".ogg", ".wav", ".m4a"}
```

### `_send_media_file`: new voice branch

```python
elif ext in _VOICE_EXTS:
    upload_type = UPLOAD_MEDIA_VOICE
    item_type = ITEM_VOICE      # = 3, already defined
    item_key = "voice_item"
```

### `send()`: TTS post-processing

```python
async def send(self, msg: OutboundMessage) -> None:
    wants_voice = self._voice_sessions.pop(msg.chat_id, False)

    if wants_voice and msg.content and self._tts_provider:
        tmp = Path(tempfile.mktemp(suffix=".mp3", prefix="nanobot-tts-"))
        ok = await self._tts_provider.synthesize(msg.content, tmp)
        if ok:
            await self._send_media_file(chat_id, tmp, context_token)
            tmp.unlink(missing_ok=True)
        # TTS failure is non-fatal; text is always sent

    # existing text send logic unchanged
    if msg.content:
        await self._send_text(...)
```

### Provider injection

`WeixinChannel.__init__` constructs `_tts_provider` from `self._config.tts`. If `TTSConfig` has no `api_key` and `DASHSCOPE_API_KEY` is unset, `_tts_provider` is set to `None` and TTS is silently skipped.

---

## Error Handling

| Scenario | Behaviour |
|----------|-----------|
| `api_key` missing | Log warning, skip TTS, send text only |
| `dashscope` not installed | `ImportError` caught, return `False`, send text only |
| API returns empty audio | Log warning, skip voice message, send text only |
| API raises exception | Log warning, skip voice message, send text only |
| WeChat upload fails | Existing retry logic in `_send_media_file` applies |
| `UPLOAD_MEDIA_VOICE` constant wrong | WeChat returns error; logged, text still sent |

TTS failure is always non-fatal. Text response is guaranteed.

---

## Testing

**`tests/providers/test_tts.py`** (5 tests)

1. `test_cosyvoice_no_api_key_returns_false`
2. `test_cosyvoice_import_error_returns_false`
3. `test_cosyvoice_empty_audio_returns_false`
4. `test_cosyvoice_happy_path` — verifies file written, returns True
5. `test_cosyvoice_api_exception_returns_false`

**`tests/channels/test_weixin_tts.py`** (5 tests)

6. `test_wants_voice_triggers_on_keywords`
7. `test_wants_voice_no_trigger_on_normal_text`
8. `test_inbound_voice_trigger_sets_session_flag`
9. `test_send_calls_tts_when_session_flagged`
10. `test_send_text_still_sent_when_tts_fails`

---

## Open Question

`UPLOAD_MEDIA_VOICE` constant value needs to be confirmed against the WeChat ilink bot API docs before implementation. If WeChat does not accept MP3 via `ITEM_VOICE`, fallback is `ITEM_FILE` with MP3 (degrades gracefully, no code-path change needed).
