## Conversation History
History file: {{ path }}
Read lines {{ start_line }}-{{ end_line }} (inclusive): {{ count }} pending records, with {{ since_cursor }} < cursor <= {{ last_cursor }}.

Use read_file with offset and limit to read this entire range, oldest first. Choose manageable page sizes and keep each request within the end line above. Continue from the last line actually returned, not the requested page size. Stop at the fixed end line even if the file grows.

Each JSONL record contains timestamp, content, and cursor; read the full content, including escaped newlines. Skip malformed records and cursors outside this range. You may update memory as you go, but finish only after reading and consolidating all pending records. If a read cannot fit, request fewer lines; a truncated line is not a complete record. Do not treat a read error as processed history.

Do not edit the journal or cursors; the runtime advances progress after this task.
