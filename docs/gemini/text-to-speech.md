# Text-to-Speech (TTS)

> **Status: Not implemented** — scorpion uses ElevenLabs for TTS
> **Gemini docs:** https://ai.google.dev/gemini-api/docs/speech-generation

## What It Is

Native Gemini speech synthesis with controllable style, pacing, and multi-speaker support. 30 prebuilt voices across 92 languages.

## Gemini API Capabilities

### Models

| Model | Features |
|-------|----------|
| `gemini-2.5-flash-preview-tts` | Single + multi-speaker |
| `gemini-2.5-pro-preview-tts` | Single + multi-speaker, higher fidelity |

### Voices (30 total)

Zephyr, Puck (Upbeat), Charon, Kore, Fenrir, Leda, Orus, Aoede, Callirrhoe, Autonoe, Enceladus (Breathy), Iapetus, Umbriel, Algieba, Despina, Erinome, Algenib, Rasalgethi, Laomedeia, Achernar, Alnilam, Schedar, Gacrux, Pulcherrima, Achird, Zubenelgenubi, Vindemiatrix, Sadachbia, Sadaltager, Sulafat

### Features

- **Multi-speaker** — up to 2 speakers with individual voice configs
- **Style control** — natural language direction for tone, accent, pacing, breathiness
- **92 languages** — auto-detected
- **Output:** 16-bit PCM mono, 24kHz sample rate
- **Context window:** 32K tokens
- **Controllable via prompting:** audio profile, scene description, director's notes

## Nanobot Implementation

**Current TTS:** ElevenLabs (`scorpion/channels/manager.py`)

```python
# Line 43-60: ElevenLabs TTS
_ELEVENLABS_TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
# Model: eleven_turbo_v2_5
# Voice: configurable via voice_id
```

Applied on every final response in channels (line 338-348 of manager.py).

**What Gemini TTS would enable:**
- Eliminate ElevenLabs dependency for TTS
- 30 built-in voices with no additional API key
- Multi-speaker dialogue synthesis
- Natural language style control
- 92-language support
- Single API key for everything (Gemini)
