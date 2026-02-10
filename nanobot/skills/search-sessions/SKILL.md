---
name: search-sessions
description: Search and retrieve chat history from session files. Use when needing to recall past conversations, find what was discussed on a specific date, or search for mentions of specific topics/people across chat sessions.
---

# Search Sessions

Search chat history stored in `.jsonl` session files.

## Session File Location

Sessions are stored in: `/Users/jing1/.nanobot/sessions/`

File naming convention:
- DingTalk groups: `dingtalk_{chat_id}.jsonl`
- Telegram: `telegram_{chat_id}.jsonl`

## File Format

Each line is a JSON object:

```json
{"role": "user", "content": "[群:群名] 用户名: 消息内容", "timestamp": "2026-02-09T18:28:46.326705"}
{"role": "assistant", "content": "回复内容", "timestamp": "2026-02-09T18:28:46.326725"}
```

First line is metadata:
```json
{"_type": "metadata", "created_at": "...", "updated_at": "...", "metadata": {}}
```

## Search Methods

### Quick Search with grep

```bash
# Search for keyword
grep -i "关键词" /Users/jing1/.nanobot/sessions/*.jsonl

# Search with context (2 lines before/after)
grep -i -C 2 "关键词" /Users/jing1/.nanobot/sessions/*.jsonl

# Search specific date
grep "2026-02-09" /Users/jing1/.nanobot/sessions/*.jsonl | grep -i "关键词"

# Search user messages only
grep '"role": "user"' /Users/jing1/.nanobot/sessions/*.jsonl | grep -i "关键词"
```

### Read Full Session

For detailed context, read the entire session file:
```bash
cat /Users/jing1/.nanobot/sessions/dingtalk_xxx.jsonl
```

## Known Sessions

- **kaguya服务群（八卦群）**: `dingtalk_cidq1x6IakuxT2H5H_qfFikVQ==.jsonl`
- **Telegram私聊**: `telegram_1087968824.jsonl`

## Usage Tips

1. Use `grep` for quick keyword searches
2. Use `cat` or `read_file` for full context
3. Parse JSON lines with `jq` if needed:
   ```bash
   cat session.jsonl | jq -r 'select(.role=="user") | .content'
   ```
