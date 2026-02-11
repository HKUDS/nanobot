# Скрипты workspace

Локальные интеграции для nanobot, которые вызываются через инструмент `exec`.

## Скрипты

- `searxng_search.py` — поиск через локальный SearXNG (`http://localhost:8080`)
- `qdrant_store.py` — генерация эмбеддинга через Mistral и сохранение в Qdrant
- `qdrant_find.py` — семантический поиск в Qdrant через Mistral embeddings

## Обязательные переменные окружения для Qdrant-скриптов

- `MISTRAL_API_KEY`

Опционально:
- `MISTRAL_API_BASE` (по умолчанию `https://api.mistral.ai/v1`)
- `QDRANT_URL` (по умолчанию `http://localhost:6333`)

## Быстрая проверка

```bash
python3 workspace/scripts/searxng_search.py "nanobot"
python3 workspace/scripts/qdrant_store.py "test memory"
python3 workspace/scripts/qdrant_find.py "test"
```
