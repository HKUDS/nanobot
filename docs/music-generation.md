# Music Generation

nanobot can expose MiniMax music generation as the `generate_music` tool. The tool is disabled by default and uses the existing `providers.minimax` credential and endpoint settings.

## Configuration

```json
{
  "providers": {
    "minimax": {
      "apiKey": "${MINIMAX_API_KEY}",
      "apiBase": "https://api.minimax.io/v1"
    }
  },
  "tools": {
    "musicGeneration": {
      "enabled": true,
      "provider": "minimax",
      "model": "music-3.0",
      "defaultOutputFormat": "hex",
      "defaultAudioFormat": "mp3",
      "defaultSampleRate": 44100,
      "defaultBitrate": 256000,
      "saveDir": "generated"
    }
  }
}
```

For a mainland China account, set `providers.minimax.apiBase` to `https://api.minimaxi.com/v1`. Both regional bases call `POST /v1/music_generation`.

## Models

Text and lyric generation models:

- `music-3.0`
- `music-2.6`
- `music-3.0-free`
- `music-2.6-free`

Cover models:

- `music-cover`
- `music-cover-free`

The configured model is the default. A `generate_music` call can provide a `model` override from the same list.

## Request Fields

`generate_music` exposes the endpoint request fields directly:

| Field | Description |
|---|---|
| `model` | Optional model override |
| `prompt` | Style, mood, and scenario description |
| `lyrics` | Lyrics with optional section tags |
| `stream` | Stream hexadecimal audio chunks |
| `output_format` | `hex` or `url`; streaming requires `hex` |
| `audio_setting` | `sample_rate`, `bitrate`, and `format` (`mp3`, `wav`, or `pcm`) |
| `lyrics_optimizer` | Generate lyrics from the prompt when lyrics are omitted |
| `is_instrumental` | Generate music without vocals |
| `audio_url` | Reference audio URL for a cover model |
| `audio_base64` | Base64 reference audio for a cover model |
| `cover_feature_id` | Preprocessed cover feature ID |
| `aigc_watermark` | Optional mainland China audio watermark for non-streaming output |

Cover requests accept exactly one of `audio_url`, `audio_base64`, or `cover_feature_id`. Direct reference audio must be 6 to 360 seconds and no larger than 50 MB. A `cover_feature_id` is valid for 24 hours and requires replacement lyrics.

## Output

Hexadecimal output is decoded and stored under nanobot's media directory. The tool returns the persistent artifact path for delivery with the `message` tool.

URL output is returned with a 24-hour expiry marker. Deliver or download the URL before it expires.
