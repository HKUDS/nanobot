---
name: tts
description: Convert text to speech using DeepDub's emotional TTS API.
homepage: https://deepdub.ai
metadata: {"nanobot":{"emoji":"🔊","requires":{"env":["DEEPDUB_API_KEY"]}}}
---

# Text-to-Speech (TTS)

Convert text to natural-sounding speech using DeepDub's emotional TTS (eTTS) API.

## Quick Start

Use the `say` tool to generate speech:

```
say(text="Hello, how are you today?")
```

With custom filename and format:

```
say(text="Welcome to the app!", filename="welcome.mp3")
```

## Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| text | Text to convert to speech | (required) |
| filename | Output filename (extension sets format) | auto-generated |
| voice_prompt_id | Voice to use | configured default |
| locale | Language/accent (e.g., "en-US", "es-ES") | en-US |
| sample_rate | Audio quality: 8000-48000 Hz | 48000 |

## Output Formats

Format is determined by filename extension:

| Extension | Format | Use Case |
|-----------|--------|----------|
| .wav | Uncompressed | Best quality, editing |
| .mp3 | Compressed | General use, sharing |
| .ogg | Open format | Web, streaming |
| .opus | Low latency | Real-time, VoIP |

## Supported Locales

Common locales:
- `en-US` - English (US)
- `en-GB` - English (UK)
- `es-ES` - Spanish (Spain)
- `es-MX` - Spanish (Mexico)
- `fr-FR` - French
- `de-DE` - German
- `it-IT` - Italian
- `pt-BR` - Portuguese (Brazil)
- `ja-JP` - Japanese
- `ko-KR` - Korean
- `he-IL` - Hebrew

Full list: ar-EG, ar-LB, ar-QA, ar-SA, cs-CZ, da-DK, de-DE, en-AU, en-CA, en-GB, en-IE, en-US, es-AR, es-CL, es-ES, es-MX, es-PE, es-XL, fr-CA, fr-FR, he-IL, hi-IN, hu-HU, it-IT, ja-JP, ko-KR, no-NO, pl-PL, pt-BR, pt-PT, ro-RO, ru-RU, sv-SE, ta-IN, th-TH, tr-TR

## Sample Rates

| Rate | Quality | Use Case |
|------|---------|----------|
| 48000 | Studio | Default, best quality |
| 44100 | CD | Music, high quality |
| 22050 | FM | Voice, good quality |
| 16000 | Wideband | Phone HD, voice assistants |
| 8000 | Narrowband | Phone, low bandwidth |

## Examples

### Basic usage
```
say(text="The weather today is sunny with a high of 72 degrees.")
```

### Different voices/locales
```
say(text="Bonjour, comment allez-vous?", locale="fr-FR", filename="french_greeting.mp3")
```

### Phone-quality audio
```
say(text="Press 1 for sales, press 2 for support.", sample_rate=8000, filename="ivr_menu.wav")
```

### Generate multiple files
```
say(text="Chapter 1: The Beginning", filename="chapter1.mp3")
say(text="Chapter 2: The Journey", filename="chapter2.mp3")
```

## Configuration

Requires `DEEPDUB_API_KEY` environment variable or configuration in nanobot settings:

```yaml
providers:
  deepdub:
    api_key: "your-api-key"
    voice_prompt_id: "59da0f21-63de-4aef-9ade-e5cabfe639ab"
    model: "dd-etts-3.0"
    locale: "en-US"
```

Get your API key at: https://app.deepdub.ai/signup

## Model

Uses `dd-etts-3.0` - DeepDub's latest emotional TTS model with excellent quality and low latency.
