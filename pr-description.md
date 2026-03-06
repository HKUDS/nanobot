## fix(feishu): smart message format selection (fixes #1548)

### Problem

Currently, the Feishu channel sends **all** messages as interactive cards (`msg_type: "interactive"`). This is overkill for short, simple replies like "OK" or "收到" — they look heavy and unnatural compared to normal chat messages.

### Solution

Implement smart message format selection that picks the most appropriate Feishu message type based on content analysis:

| Content Type | Format | `msg_type` |
|---|---|---|
| Short plain text (≤ 200 chars, no markdown) | Text | `text` |
| Medium text with links (≤ 2000 chars, no complex formatting) | Rich Text Post | `post` |
| Long text, code blocks, tables, headings, bold/italic, lists | Interactive Card | `interactive` |

### How it works

1. **`_detect_msg_format(content)`** — Analyzes the message content and returns the optimal format:
   - Checks for complex markdown (code blocks, tables, headings) → `interactive`
   - Checks for simple markdown (bold, italic, lists) → `interactive`  
   - Checks for links → `post` (Feishu post format supports `<a>` tags natively)
   - Short plain text → `text`
   - Medium plain text → `post`

2. **`_markdown_to_post(content)`** — Converts markdown links `[text](url)` to Feishu post format with proper `a` tags. Each line becomes a paragraph in the post body.

3. **Modified `send()` method** — Uses `_detect_msg_format()` to choose the right format, then dispatches to the appropriate sending logic.

### Design decisions

- **Post format for links only**: Feishu's post format (`[[{"tag":"text",...}]]`) doesn't support bold/italic rendering, so we only use it for messages containing links (where the `a` tag adds real value). Messages with bold/italic/lists still use cards which render markdown properly.
- **Conservative thresholds**: 200 chars for text, 2000 chars for post — these keep the UX natural without being too aggressive.
- **Backward compatible**: The card rendering path is completely unchanged. Only the routing logic is new.

### Testing

Format detection tested against 13 cases covering all content types:
- ✅ Plain text → `text`
- ✅ Links → `post`  
- ✅ Bold/italic/code/tables/headings/lists → `interactive`
- ✅ Long content → `interactive`
- ✅ Post format generates valid Feishu post JSON with proper `a` tags

### Changes

- `nanobot/channels/feishu.py`: Added `_detect_msg_format()`, `_markdown_to_post()`, and updated `send()` method
