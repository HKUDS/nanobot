# Audio Understanding

> **Status: Not implemented** — scorpion uses ElevenLabs Scribe for STT
> **Gemini docs:** https://ai.google.dev/gemini-api/docs/audio

## What It Is

Gemini can natively analyze audio: transcription, translation, speaker diarization, emotion detection, and content description. Handles both speech and non-speech sounds.

## Gemini API Capabilities

- **Formats:** WAV, MP3, AIFF, AAC, OGG (Vorbis), FLAC
- **Max duration:** 9.5 hours per prompt (combined across files)
- **Token cost:** 32 tokens/second (downsampled to 16 Kbps mono)
- **Transcription & translation** across languages
- **Speaker diarization** — identify distinct speakers
- **Emotion detection** in speech and music
- **Non-speech sounds** — birdsong, sirens, etc.
- **Timestamp referencing** — `MM:SS` format for specific segments
- **Input methods:** Files API (>20MB) or inline data (<=20MB)

## Nanobot Implementation

**Current STT:** ElevenLabs Scribe (`scorpion/providers/transcription.py`)
```python
# Line 18: ElevenLabs endpoint
_ELEVENLABS_STT_URL = "https://api.elevenlabs.io/v1/speech-to-text"
# Line 39: Model
"model": "scribe_v1"
```

Gemini's native audio understanding is not used. Voice messages from channels (Telegram, etc.) are transcribed via ElevenLabs before being sent to the LLM as text.

**What Gemini would enable:**
- Direct audio input to the model (no external transcription service)
- Speaker diarization
- Emotion/tone analysis
- Non-speech audio analysis
- Eliminate ElevenLabs STT dependency
