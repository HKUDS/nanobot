## Conversation History
History file: {{ path }}
Read lines {{ start_line }}-{{ end_line }} (inclusive): {{ count }} pending records, with {{ since_cursor }} < cursor <= {{ last_cursor }}.

Read and consolidate the full content of these records, oldest first. Skip malformed records and cursors outside this range. Later records belong to the next Dream run. The runtime owns the journal and cursors.
