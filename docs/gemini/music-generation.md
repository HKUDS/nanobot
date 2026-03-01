# Music Generation — Lyria

> **Status: Implemented**
> **Gemini docs:** https://ai.google.dev/gemini-api/docs/music-generation

## What It Is

Real-time streaming music generation via WebSocket. Instrumental only. Uses the Live API for persistent, bidirectional, low-latency audio streaming.

## Gemini API Capabilities

### Model

`models/lyria-realtime-exp` (experimental)

### Audio specs

- **Format:** raw 16-bit PCM
- **Sample rate:** 48kHz
- **Channels:** 2 (stereo)
- **SynthID watermark** on all output

### Creative controls

| Parameter | Range | Default | Description |
|-----------|-------|---------|-------------|
| guidance | 0.0–6.0 | 4.0 | How strictly model follows prompts |
| bpm | 60–200 | — | Beats per minute (requires context reset) |
| density | 0.0–1.0 | — | Sparsity/fullness of notes |
| brightness | 0.0–1.0 | — | Tonal quality (treble emphasis) |
| scale | 12 keys + default | — | Musical key (requires context reset) |
| temperature | 0.0–3.0 | 1.1 | Randomness |
| top_k | 1–1000 | 40 | Sampling |

### Modes

- **QUALITY** (default) — best fidelity
- **DIVERSITY** — more variation
- **VOCALIZATION** — vocal-like sounds

### Features

- Weighted prompts with customizable weights
- Real-time prompt steering (smooth transitions during playback)
- Instrument muting: `mute_bass`, `mute_drums`, `only_bass_and_drums`
- Playback control: play, pause, stop, reset_context
- Instrumental only (no lyrics/vocals)

## Nanobot Implementation

**File:** `scorpion/agent/tools/creative.py` (lines 264-376)

```python
# Lines 332-358: Live music streaming
async with client.aio.live.music.connect(
    model="models/lyria-realtime-exp",
    config=types.LiveMusicGenerationConfig(...)
) as session:
    session.play(
        prompts=[types.WeightedPrompt(text=prompt, weight=1.0)],
        music_generation_config=types.MusicGenerationConfig(
            bpm=bpm, density=density, brightness=brightness,
            guidance=guidance, temperature=temperature,
        ),
    )
    # Stream and collect audio chunks
    async for msg in session:
        data = msg.server_content.audio_chunks
        audio_chunks.extend(data)
```

**What's implemented:**
- `lyria-realtime-exp` model via Live API WebSocket
- Weighted prompts
- All creative controls (BPM, density, brightness, guidance, temperature)
- Real-time chunk streaming
- WAV file export (48kHz stereo 16-bit)
- Duration control (5-120s)

**What's missing:**
- Music generation modes (QUALITY/DIVERSITY/VOCALIZATION)
- Instrument muting (mute_bass, mute_drums, only_bass_and_drums)
- Scale/key selection
- Real-time prompt steering (mid-stream changes)
- Playback session management (pause/resume)
