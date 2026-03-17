# Voice Control

Nanobot supports two voice control channels: **ESPHome Voice** (local, hardware satellites) and **Amazon Alexa** (cloud, Custom Skill).

Both channels inject a voice hint into the agent context that encourages short, spoken-style responses without markdown formatting.

---

## ESPHome Voice (Recommended)

Connects to ESPHome-compatible voice satellites (ESP32-S3 devices, [linux-voice-assistant](https://github.com/OHF-Voice/linux-voice-assistant)) and runs the full voice pipeline locally:

- **Wake word detection** — on the satellite (microWakeWord / openWakeWord)
- **Voice Activity Detection** — server-side using silero VAD
- **Speech-to-Text** — local (faster-whisper) or cloud (Groq Whisper API)
- **Agent** — nanobot processes the transcript and responds
- **Text-to-Speech** — local piper-tts, served to the satellite via HTTP

### Architecture

```
[Satellite]                          [Nanobot Server]
ESP32 / Pi / Desktop                       |
  - microphone                     ESPHome channel
  - speaker                          - aioesphomeapi (satellite connection)
  - wake word detection              - silero VAD (speech detection)
  - ESPHome Native API               - faster-whisper or Groq (STT)
        |                            - piper-tts (TTS)
        +--- TCP (port 6053) --------+
                                     - HTTP (TTS audio serving)
```

### Install Dependencies

```bash
uv pip install 'nanobot-ai-tng[voice]'
```

Or individually:

```bash
uv pip install aioesphomeapi faster-whisper piper-tts
```

### Models

Both STT and TTS models are **downloaded automatically** on first startup. No manual setup required.

- **TTS voices**: Downloaded from [rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices/tree/main) on first use. Medium quality voices are recommended for responsive interactions; high quality voices are noticeably slower.
- **STT models** (local only): Downloaded by faster-whisper on first use. `distil-small.en` is a good default.

### Set Up a Satellite

The easiest way is [linux-voice-assistant](https://github.com/OHF-Voice/linux-voice-assistant) via Docker:

```bash
mkdir lva && cd lva
LVA_VERSION=$(curl -s https://api.github.com/repos/ohf-voice/linux-voice-assistant/releases/latest | jq -r .tag_name)
curl -sLO "https://raw.githubusercontent.com/ohf-voice/linux-voice-assistant/refs/tags/$LVA_VERSION/docker-compose.yml"
curl -sLO "https://raw.githubusercontent.com/ohf-voice/linux-voice-assistant/refs/tags/$LVA_VERSION/.env.example"
cp .env.example .env
```

Edit `.env` to configure:

```bash
# Wake word (options: okay_nabu, alexa, hey_jarvis, hey_mycroft,
#   hey_luna, hey_home_assistant, okay_computer, choo_choo_homie)
WAKE_MODEL="okay_computer"
```

Start it:

```bash
docker compose up -d
```

The satellite listens on port 6053 by default.

### Configure Nanobot

Add to `~/.nanobot/config.json` under `channels`:

```json
{
  "esphome": {
    "enabled": true,
    "host": "192.168.1.100",
    "satellites": [
      {
        "name": "living-room",
        "host": "192.168.1.50",
        "port": 6053
      }
    ],
    "stt": {
      "provider": "groq"
    },
    "tts": {
      "model": "en_GB-cori-medium"
    }
  }
}
```

Set `host` to the IP address that satellites can reach the nanobot server on (used for TTS audio URLs).

For local STT instead of Groq cloud:

```json
{
  "stt": {
    "provider": "local",
    "model": "distil-small.en",
    "device": "cpu"
  }
}
```

### Full Configuration Reference

| Key | Default | Description |
|-----|---------|-------------|
| `enabled` | `false` | Enable the ESPHome voice channel |
| `host` | `"0.0.0.0"` | IP address satellites use to reach this server |
| `ttsPort` | `18791` | HTTP port for serving TTS audio |
| `satellites` | `[]` | List of satellite targets (see below) |
| `stt.provider` | `"local"` | `"local"` (faster-whisper) or `"groq"` |
| `stt.model` | `"distil-small.en"` | Whisper model name (local only) |
| `stt.device` | `"cpu"` | `"cpu"` or `"cuda"` (local only) |
| `stt.language` | `null` | Language code, e.g. `"en"` (null = auto-detect) |
| `tts.model` | `"en_US-lessac-medium"` | Piper voice model name |
| `tts.dataDir` | `"~/.local/share/piper-tts"` | Directory containing .onnx model files |
| `tts.speakerId` | `null` | Speaker ID for multi-speaker models |
| `responseTimeout` | `30.0` | Max seconds to wait for agent response |
| `silenceTimeoutSeconds` | `0.8` | Seconds of silence after speech to trigger STT |
| `speechThreshold` | `0.5` | VAD probability threshold (0.0–1.0) |
| `reconnectInterval` | `5.0` | Seconds between reconnect attempts |
| `allowFrom` | `["*"]` | Allowed satellite names (`"*"` = all) |

Each satellite target:

| Key | Default | Description |
|-----|---------|-------------|
| `name` | `"default"` | Satellite identifier (used as session key) |
| `host` | `"localhost"` | Satellite IP or hostname |
| `port` | `6053` | ESPHome Native API port |
| `password` | `""` | Legacy API password (if set on satellite) |
| `encryptionKey` | `""` | Noise PSK for encrypted connections |

### Voice Commands

Say these after the wake word to control the session:

| Phrase | Action |
|--------|--------|
| "new conversation" / "start over" / "reset" | Clear conversation history |
| "stop" / "cancel" / "nevermind" | Cancel current task |

### Performance Tips

- Use **Groq cloud STT** (`"provider": "groq"`) for fastest transcription (~0.4s vs ~1s local)
- Use **medium quality** TTS voices (high quality models are 2-5x slower)
- Lower `silenceTimeoutSeconds` for snappier response (0.6–1.0s), raise it if speech gets cut off
- The LLM response time is typically the biggest bottleneck — use a fast model

---

## Amazon Alexa

Runs an HTTP server that receives Alexa Custom Skill requests. Requires an Alexa Developer account and a publicly accessible HTTPS endpoint.

### Configure Nanobot

Add to `~/.nanobot/config.json` under `channels`:

```json
{
  "alexa": {
    "enabled": true,
    "port": 8443,
    "verifySignatures": true,
    "endpointPath": "/alexa",
    "launchMessage": "Hi, I'm nanobot. What can I help you with?"
  }
}
```

### Configuration Reference

| Key | Default | Description |
|-----|---------|-------------|
| `enabled` | `false` | Enable the Alexa channel |
| `host` | `"0.0.0.0"` | Listen address |
| `port` | `8443` | Listen port (Alexa requires 443, 8443, or 10443) |
| `endpointPath` | `"/alexa"` | HTTP path for skill requests |
| `verifySignatures` | `true` | Verify Alexa request signatures |
| `allowFrom` | `["*"]` | Allowed Alexa user IDs |
| `launchMessage` | `"Hi, I'm nanobot..."` | Greeting when skill is launched |

### Alexa Skill Setup

1. Create a Custom Skill in the [Alexa Developer Console](https://developer.amazon.com/alexa/console/ask)
2. Set the endpoint to your server's public URL (e.g. `https://your-domain:8443/alexa`)
3. Create a `CatchAllIntent` with a slot named `utterance` of type `AMAZON.SearchQuery`
4. The skill forwards all speech to nanobot and speaks back the response

### Limitations

- Alexa enforces a ~8 second response timeout — complex queries may time out
- Requires a public HTTPS endpoint with a valid certificate
- STT and TTS are handled by Amazon's cloud (no local option)
