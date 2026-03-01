# Live API

> **Status: Partial** — used for music generation only
> **Gemini docs:** https://ai.google.dev/gemini-api/docs/live

## What It Is

Low-latency, real-time voice and video interactions with Gemini. Bidirectional WebSocket streaming for continuous audio/video input and spoken responses.

## Gemini API Capabilities

### Model

`gemini-2.5-flash-native-audio-preview-12-2025`

### Features

- **Voice activity detection** — natural speech interruptions
- **Bidirectional audio streaming** — continuous input/output
- **Video streaming** — real-time camera/screen input
- **Native audio processing** — direct audio I/O (no transcription step)
- **Tool use** — function calling within live sessions
- **Session management** — extended conversation state
- **Ephemeral tokens** — secure client-side auth without exposing API keys

### Audio specs

- **Input:** 16-bit PCM, 16kHz, mono
- **Output:** 24kHz sample rate

### Integration partners

Pipecat, LiveKit, Fishjam, Agent Development Kit, Vision Agents, Voximplant

## Nanobot Implementation

**Music only:** `scorpion/agent/tools/creative.py` (line 332)

```python
# Live API used exclusively for Lyria music streaming
async with client.aio.live.music.connect(
    model="models/lyria-realtime-exp",
    config=types.LiveMusicGenerationConfig(...)
) as session:
    ...
```

The Live API WebSocket infrastructure is proven working (for music). It is not used for:

- Real-time voice conversations
- Video streaming input
- Audio I/O for chat
- Voice-based interaction

**What's needed for full Live API:**
- Voice chat mode using `gemini-2.5-flash-native-audio-preview`
- Audio input/output streaming via channels (Telegram voice, etc.)
- Session management for ongoing conversations
- Tool use within live sessions
