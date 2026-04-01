# nanobot: ультралегкий персональный AI-ассистент

<div align="center">
  <img src="../nanobot_logo.png" alt="nanobot" width="500">
</div>

`nanobot` — минималистичный персональный AI-ассистент, вдохновленный OpenClaw.
Проект делает ставку на компактное ядро, простую расширяемость и поддержку
нескольких каналов/провайдеров.

> Важно: этот файл — русская версия основной документации.
> Самая свежая и полная версия всегда в `README.md`.

## Ключевые возможности

- Легковесный агент с инструментами (`exec`, файловые операции, web, MCP и т.д.)
- Поддержка многих провайдеров (OpenRouter, OpenAI, Anthropic, Groq, Ollama и др.)
- Работа через разные каналы (Telegram, Discord, WhatsApp, WeChat, Feishu и т.д.)
- Поддержка мультиинстансов (`--config` + отдельные workspace)
- OpenAI-совместимый HTTP API (`nanobot serve`)
- Python SDK для встраивания в собственные приложения

## Установка

Из исходников:

```bash
git clone https://github.com/HKUDS/nanobot.git
cd nanobot
pip install -e .
```

Через `uv`:

```bash
uv tool install nanobot-ai
```

Через `pip`:

```bash
pip install nanobot-ai
```

## Быстрый старт

1) Инициализация:

```bash
nanobot onboard
```

2) Настройка `~/.nanobot/config.json` (минимум: API ключ + модель):

```json
{
  "providers": {
    "openrouter": {
      "apiKey": "sk-or-v1-xxx"
    }
  },
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5",
      "provider": "openrouter"
    }
  }
}
```

3) Запуск чата:

```bash
nanobot agent
```

## Каналы

`nanobot` поддерживает чат-каналы и плагинные каналы. Базовая идея:

- включаете канал в `channels.<name>.enabled = true`
- задаете его креды/параметры
- запускаете `nanobot gateway`

Примеры каналов: Telegram, Discord, WhatsApp, WeChat, Feishu, Slack, Matrix,
QQ, Wecom, DingTalk, Email, Mochat.

Подробности по созданию собственных каналов:
`docs/CHANNEL_PLUGIN_GUIDE.md`.

## Провайдеры

Конфиг хранится в `providers.*` + `agents.defaults.model`.

Популярные варианты:

- OpenRouter (универсальный gateway)
- OpenAI / Anthropic / Groq / DeepSeek
- Локальные: Ollama, vLLM, OVMS
- OAuth-провайдеры: OpenAI Codex, GitHub Copilot

Для OAuth используйте:

```bash
nanobot provider login openai-codex
nanobot provider login github-copilot
```

## MCP (Model Context Protocol)

Можно подключать внешние MCP-серверы и использовать их инструменты как
встроенные. Конфиг добавляется в `tools.mcpServers`.

## Безопасность

Рекомендуется:

- включать `"tools.restrictToWorkspace": true` в production
- использовать `allowFrom` для каналов
- отключать `tools.exec.enable`, если shell не нужен

## Python SDK

Минимальный пример:

```python
from nanobot import Nanobot

bot = Nanobot.from_config()
result = await bot.run("Summarize the README")
print(result.content)
```

Полная документация SDK:
`docs/PYTHON_SDK.md`.

## OpenAI-совместимый API

Запуск:

```bash
pip install "nanobot-ai[api]"
nanobot serve
```

Эндпоинт по умолчанию: `http://127.0.0.1:8900/v1/chat/completions`.

## Мультиинстансы

Для изоляции окружений используйте отдельные `--config` и `--workspace`.
Так можно запускать несколько ботов одновременно (например, под разные каналы
или команды).

## Docker / Linux service

В проекте есть:

- `Dockerfile`
- `docker-compose.yml`
- пример user-service для `systemd` в `README.md`

## Разработка и вклад

- Основная ветка: `main` (стабильная)
- Экспериментальная: `nightly`
- Перед PR смотрите `CONTRIBUTING.md`

---

Если нужен максимально детальный раздел (все параметры провайдеров/каналов,
развернутые примеры конфигурации, новости и changelog), см. `README.md`.
