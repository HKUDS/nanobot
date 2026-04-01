# Xiaozhi ESP32 Client Support Guide

This guide explains how to connect ESP32-based devices (e.g., Freenove 2.8" TFT, Breadboard Mini) as voice clients for Nanobot.

## 1. Overview
Nanobot acts as a WebSocket gateway that:
- Receives compressed audio (Opus) from the device.
- Performs STT via Whisper/Speaches.
- Returns AI responses as voice (TTS) or text.
- Provides MCP (Model Context Protocol) device management.

## 2. Configuration

Add the `voice_server` channel to your `config.json`:

```json
{
  "channels": {
    "voice_server": {
      "enabled": true,
      "port": 18790,
      "local_ip": "192.168.x.x",
      "transcription_api_base": "http://your-whisper-server:8000/v1/audio/transcriptions",
      "transcription_model": "whisper-large-v3",
      "force_ota": false
    }
  }
}
```

## 3. Launch
Install dependencies: `pip install opuslib edge-tts httpx`. Start Nanobot as usual.

---

## РУССКИЙ ПЕРЕВОД (Russian Translation)

Этот гайд описывает подключение ESP32 (Freenove/Breadboard) к Nanobot.
1. **Обзор**: Nanobot принимает Opus-аудио, делает STT и возвращает ответ голосом или текстом через WebSocket.
2. **Настройка**: Добавьте канал `voice_server` в `config.json` с указанием порта и STT-провайдера.
3. **Запуск**: Установите зависимости `opuslib` и `edge-tts`, затем запустите Nanobot.