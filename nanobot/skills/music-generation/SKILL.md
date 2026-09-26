---
name: music-generation
description: Generate music and music-cover audio with MiniMax.
---

# Music Generation

Use the `generate_music` tool when the user asks to create, compose, generate, or cover audio.

If the `generate_music` tool is not available in the current tool list, tell the user that music generation is not enabled for this nanobot instance.

## When To Use

- Text-to-music: call `generate_music` with a concrete `prompt` and, when useful, `lyrics`.
- Cover generation: pass `audio_url`, `audio_base64`, or a `cover_feature_id` when one is already available.
- Generated audio is stored as a persistent artifact. After generating audio, call the `message` tool with the artifact paths in the `media` parameter to deliver it to the user.

## Prompt Rules

Write prompts with enough detail for music generation:

- Genre, mood, and instrumentation.
- Tempo, structure, and vocal style.
- Lyrics constraints, if any.
- Cover intent, if the task is to adapt an existing track.

Do not include raw paths, base64 payloads, or internal replay markers in user-facing replies.
