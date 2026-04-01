# nanobot: ультра-лёгкий персональный AI-ассистент

<div align="center">
  <img src="../nanobot_logo.png" alt="nanobot" width="500">
  <p>
    <a href="https://pypi.org/project/nanobot-ai/"><img src="https://img.shields.io/pypi/v/nanobot-ai" alt="PyPI"></a>
    <img src="https://img.shields.io/badge/python-≥3.11-blue" alt="Python">
    <img src="https://img.shields.io/badge/license-MIT-green" alt="License">
  </p>
</div>

**nanobot** — ультра-лёгкий персональный AI-ассистент, вдохновлённый [OpenClaw](https://github.com/openclaw/openclaw).

⚡ Содержит на **99% меньше кода**, чем OpenClaw, при сохранении основной функциональности агента.

## Что обновилось (2026-04-01)

- Добавлен режим `agents.defaults.shortMemory`: в память сохраняются только явно помеченные пользователем факты (например, "запомни", "remember", "/save-memory").
- Для `tools.exec` добавлен `internalUrlAllowlist`: можно разрешить доверенные внутренние URL (например, `localhost`, `127.0.0.1/8`, префикс `http://localhost:11434/`), не отключая общую защиту.
- Для Telegram добавлены `apiBaseUrl` и `apiBaseFileUrl` для работы через локальный Telegram Bot API, а также более понятная обработка ошибок при слишком больших файлах.

## Основные возможности

🪶 **Ультра-лёгкость** — минималистичная реализация, быстрый запуск и низкое потребление ресурсов.

🔬 **Исследовательский подход** — чистый, читаемый код, который легко изучать и расширять.

💎 **Простота** — развёртывание в несколько шагов.

## Установка

```bash
# Из исходников (рекомендуется для разработки)
git clone https://github.com/HKUDS/nanobot.git
cd nanobot
pip install -e .

# Через pip (стабильная версия)
pip install nanobot-ai

# Через uv
uv tool install nanobot-ai
```

## Быстрый старт

**1. Инициализация:**
```bash
nanobot onboard
```

**2. Настройка** (`~/.nanobot/config.json`):

Укажите API-ключ (например, OpenRouter):
```json
{
  "providers": {
    "openrouter": {
      "apiKey": "sk-or-v1-xxx"
    }
  }
}
```

Укажите модель:
```json
{
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5",
      "provider": "openrouter"
    }
  }
}
```

**3. Чат:**
```bash
nanobot agent
```

---

# Подробные инструкции

## Работа с провайдерами

nanobot поддерживает множество LLM-провайдеров. Конфигурация хранится в `~/.nanobot/config.json` в секции `providers`.

### Основные провайдеры

| Провайдер | Назначение | Где получить ключ |
|-----------|------------|-------------------|
| `openrouter` | Доступ ко многим моделям | [openrouter.ai](https://openrouter.ai) |
| `anthropic` | Claude | [console.anthropic.com](https://console.anthropic.com) |
| `openai` | GPT | [platform.openai.com](https://platform.openai.com) |
| `deepseek` | DeepSeek | [platform.deepseek.com](https://platform.deepseek.com) |
| `ollama` | Локальные модели | — |
| `custom` | Любой OpenAI-совместимый API | — |

### OAuth-провайдеры (без API-ключа)

Для провайдеров с OAuth используется команда входа:

```bash
nanobot provider login openai-codex    # ChatGPT Codex
nanobot provider login github-copilot  # GitHub Copilot
nanobot provider login qwen-oauth      # Qwen (qwen.ai, бесплатный tier)
```

После входа в `agents.defaults.model` укажите модель, например:
```json
{
  "agents": {
    "defaults": {
      "model": "qwen-oauth/coder-model"
    }
  }
}
```

### Провайдер по умолчанию

- `provider: "auto"` — nanobot сам выбирает провайдера по имени модели.
- `provider: "openrouter"` — жёсткая привязка к провайдеру.

### Добавление нового провайдера (для разработчиков)

1. Добавьте `ProviderSpec` в `nanobot/providers/registry.py`.
2. Добавьте поле в `ProvidersConfig` в `nanobot/config/schema.py`.

Подробности см. в [README.md](../README.md), раздел «Adding a New Provider».

---

## Инструменты (tools) и TOOLS.md

## Актуальные параметры конфигурации

Ниже параметры, которые важно учесть в свежих версиях:

| Параметр | Значение по умолчанию | Что делает |
|----------|------------------------|------------|
| `agents.defaults.shortMemory` | `false` | Сохраняет в долгосрочную память только явно помеченные пользователем важные факты. |
| `tools.exec.internalUrlAllowlist` | `[]` | Разрешает выбранные внутренние URL в `exec` (host/domain/CIDR/IP/URL-prefix), при сохранении блокировки остальных приватных адресов. |
| `channels.telegram.apiBaseUrl` | `null` | Базовый URL Telegram Bot API (например, локальный сервер). |
| `channels.telegram.apiBaseFileUrl` | `null` | Базовый file URL Telegram Bot API; особенно полезно для скачивания больших вложений. |

Пример:

```json
{
  "agents": {
    "defaults": {
      "shortMemory": true
    }
  },
  "tools": {
    "exec": {
      "internalUrlAllowlist": ["localhost", "127.0.0.1/8", "http://localhost:11434/"]
    }
  },
  "channels": {
    "telegram": {
      "apiBaseUrl": "http://127.0.0.1:8081/bot",
      "apiBaseFileUrl": "http://127.0.0.1:8081/file/bot"
    }
  }
}
```

Переменная окружения `TELEGRAM_BOT_API_MAX_DOWNLOAD_BYTES` позволяет изменить порог (по умолчанию `20971520` байт), после которого для cloud Bot API считается, что файл слишком большой для скачивания.

### Встроенные инструменты

nanobot включает набор инструментов, которые агент вызывает через function calling:

| Инструмент | Описание |
|------------|----------|
| `exec` | Выполнение shell-команд |
| `read_file` | Чтение файлов |
| `write_file` | Запись файлов |
| `edit_file` | Редактирование файлов |
| `list_dir` | Просмотр содержимого директорий |
| `web_search` | Поиск в интернете |
| `web_fetch` | Загрузка веб-страниц |
| `message` | Отправка ответа в канал |
| `spawn` | Запуск подзадач |
| `cron` | Планирование напоминаний |

### Зачем нужен TOOLS.md

**TOOLS.md** — это bootstrap-файл в workspace (`~/.nanobot/workspace/TOOLS.md`). Его содержимое загружается в системный промпт и помогает агенту:

- понимать ограничения инструментов (таймауты, блокировки опасных команд);
- знать, когда и как использовать тот или иной инструмент;
- документировать **кастомные скрипты** в workspace (например, `python generate_mtc_note.py`).

Если скрипт лежит в workspace и вызывается через `exec`, опишите его в TOOLS.md:

```markdown
## merge_pdfs — Объединение PDF

- Использовать, когда пользователь просит объединить несколько PDF в один.
- Команда: `python merge_pdfs.py file1.pdf file2.pdf` из директории workspace.
- Требования: `pip install pypdf`
```

Другие bootstrap-файлы: `AGENTS.md`, `SOUL.md`, `USER.md`.

---

## Создание навыков (skills)

**Skills** — это markdown-инструкции, которые расширяют возможности агента. Формат совместим с OpenClaw.

### Структура skill

```
skill-name/
├── SKILL.md          # обязательно: YAML frontmatter + markdown
├── scripts/          # опционально: исполняемый код
├── references/       # опционально: документация
└── assets/           # опционально: шаблоны, иконки и т.д.
```

### Пример SKILL.md

```yaml
---
name: weather
description: Получить погоду (wttr.in, Open-Meteo). Использовать при запросе погоды.
metadata: {"nanobot":{"emoji":"🌤️","requires":{"bins":["curl"]}}}
---

# Погода

## wttr.in
curl -s "wttr.in/Moscow?format=3"
```

### Где размещать skills

- **Встроенные:** `nanobot/skills/`
- **Пользовательские:** `~/.nanobot/workspace/skills/`

Skills из workspace имеют приоритет над встроенными.

### Создание нового skill

**skill-creator** — встроенный skill, который помогает проектировать и собирать новые skills. Два способа использования:

**1. Через агента** — попросите nanobot создать skill:
```
Создай skill для работы с PDF: объединение, разбивка, извлечение текста
```
Агент загрузит skill-creator, выполнит `init_skill.py` и заполнит шаблон.

**2. Скрипт init_skill.py** — ручной запуск (из корня репозитория nanobot):

```bash
# Базовый skill (только SKILL.md)
python nanobot/skills/skill-creator/scripts/init_skill.py my-skill --path ~/.nanobot/workspace/skills

# С директориями scripts, references, assets
python nanobot/skills/skill-creator/scripts/init_skill.py my-skill --path ~/.nanobot/workspace/skills --resources scripts,references,assets

# С примерами кода в шаблоне
python nanobot/skills/skill-creator/scripts/init_skill.py my-skill --path ~/.nanobot/workspace/skills --resources scripts --examples
```

Скрипт создаёт папку с SKILL.md (YAML frontmatter + заглушки разделов) и при необходимости — `scripts/`, `references/`, `assets/`. После генерации отредактируйте SKILL.md под свою задачу.

**3. Вручную** — создать папку и SKILL.md с нуля (см. структуру выше).

---

## Подключение MCP (Model Context Protocol)

MCP позволяет подключать внешние серверы инструментов — агент сможет вызывать их как обычные инструменты.

### Конфигурация

Добавьте MCP-серверы в `~/.nanobot/config.json`:

```json
{
  "tools": {
    "mcpServers": {
      "filesystem": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/dir"]
      },
      "my-remote-mcp": {
        "url": "https://example.com/mcp/sse",
        "headers": {
          "Authorization": "Bearer YOUR_TOKEN"
        }
      }
    }
  }
}
```

### Режимы транспорта

| Режим | Параметры | Пример |
|-------|-----------|--------|
| **Stdio** | `command` + `args` | Локальный процесс через `npx` / `uvx` |
| **HTTP/SSE** | `url` + `headers` (опционально) | Удалённый endpoint |

### Опции MCP-сервера

| Параметр | Описание | По умолчанию |
|----------|----------|--------------|
| `toolTimeout` | Таймаут вызова инструмента (сек) | 30 |
| `enabledTools` | Список инструментов или `["*"]` для всех | `["*"]` |
| `env` | Переменные окружения (для stdio) | `{}` |

### Пример: ограничить набор инструментов

```json
{
  "tools": {
    "mcpServers": {
      "filesystem": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home/user/docs"],
        "enabledTools": ["read_file", "write_file"]
      }
    }
  }
}
```

В `enabledTools` можно указывать как исходные имена (`read_file`), так и обёрнутые (`mcp_filesystem_read_file`).

### Совместимость

Формат конфигурации совместим с Claude Desktop и Cursor — можно копировать блоки из документации MCP-серверов.

После изменения конфигурации перезапустите `nanobot gateway`.

---

## Ссылки

- [README (англ.)](../README.md) — полная документация
- [Channel Plugin Guide](./CHANNEL_PLUGIN_GUIDE.md) — создание каналов
- [CONTRIBUTING](../CONTRIBUTING.md) — участие в разработке
