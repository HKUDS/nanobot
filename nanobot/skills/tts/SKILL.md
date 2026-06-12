---
name: tts
description: Send voice messages using text-to-speech. Set tts=True on the message tool to synthesize content as speech.
metadata:
  nanobot:
    always: true
---

# Text-to-Speech (Voice Messages)

Use the `tts=True` parameter on the `message` tool to send a voice message instead of text.

## When To Use

- The user asks you to speak, read aloud, or send a voice message
- The user prefers audio responses (e.g., on mobile/messaging channels)
- You want to deliver content that is easier to consume by listening

## How It Works

Set `tts=True` on the `message` tool. The content text is synthesized into speech using the configured TTS provider and sent as a voice message attachment.

```text
message(content="Here's your update for today.", tts=True)
```

## Requirements

- TTS must be enabled in nanobot settings (`tts.enabled: true`)
- A TTS provider must be configured (openai, groq, or elevenlabs)
- The corresponding API key must be set

If TTS is not configured, the message tool will return an error. Tell the user that voice messages require TTS to be enabled in settings.

## Behavior

- The text content is synthesized into audio and sent as a voice message
- The original text is not sent alongside the audio — the recipient gets only the voice message
- Voice, speed, and format are determined by the TTS configuration in nanobot settings
- Long messages may be truncated based on the `max_char_length` setting

## Examples

Send a voice message to the current chat:

```text
message(content="The deployment finished successfully. All tests passed.", tts=True)
```

Send a voice message to a different channel:

```text
message(content="Reminder: standup in 5 minutes.", channel="telegram", chat_id="12345", tts=True)
```

## Notes

- Do not use `tts=True` for normal text replies — only when the user wants audio
- If the user asks for both text and audio, send the text reply normally first, then use `message` with `tts=True` for the audio version
- The `tts` parameter is only available on the `message` tool, not on direct replies
