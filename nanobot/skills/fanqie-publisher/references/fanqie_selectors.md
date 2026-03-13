# Fanqie Selector Notes

Use this file when the Fanqie page structure changes and `publish_fanqie.py` can no longer find editor fields.

## Current selector groups

- Title input (`TITLE_SELECTORS` in script):
  - `input.serial-editor-input-hint-area`
  - `input[placeholder*="请输入标题"]`
  - `input[placeholder*="标题"]`
  - `input[placeholder*="title" i]`
  - `input[placeholder*="chapter" i]`
  - `input[placeholder*="章节"]`

- Chapter number input (`CHAPTER_NUMBER_SELECTORS`):
  - `.serial-editor-title-left .left-input input`
  - `.serial-editor-title-left input`

- Content editor (`CONTENT_SELECTORS`):
  - `textarea[placeholder*="content" i]`
  - `textarea[placeholder*="正文"]`
  - `div[contenteditable="true"]`
  - `div[role="textbox"]`

- Publish button (`PUBLISH_SELECTORS`):
  - `button:has-text("发布")`
  - `button:has-text("发布章节")`
  - `button:has-text("确认发布")`
  - `button:has-text("提交")`
  - `button:has-text("Publish")`
  - `button[type="submit"]`

- Next-step button (`NEXT_STEP_SELECTORS`):
  - `button:has-text("下一步")`
  - `button:has-text("继续")`

- Save-draft button (`SAVE_DRAFT_SELECTORS`):
  - `button.auto-editor-save`
  - `button:has-text("保存草稿")`
  - `button:has-text("保存")`

- Success toast (`PUBLISH_SUCCESS_SELECTORS`):
  - `text=发布成功`
  - `text=发布完成`
  - `text=章节发布成功`
  - `text=Publish successful`

- Success redirect page (`PUBLISH_SUCCESS_PAGE_SELECTORS`):
  - `div.content-card-wrap.path-prefix-chapter-manage`
  - `div.chapter-table.auto-editor-chapter`

- Publish settings modal:
  - detect text: `是否使用AI`
  - choose `是` / `否` based on `--ai-generated`
  - confirm button: `button:has-text("确认发布")`

## How to refresh selectors safely

1. Run script once and collect debug files in `~/.nanobot/fanqie_logs`.
2. Inspect saved HTML to find stable attributes near title/body/publish controls.
3. Prefer placeholder text, ARIA labels, and explicit role selectors over brittle class names.
4. Keep at least 2 fallback selectors per field.
5. Re-test with:

```bash
python nanobot/skills/fanqie-publisher/scripts/publish_fanqie.py \
  --md-path /path/to/chapter.md \
  --work-url "https://fanqienovel.com/writer/..." \
  --publish false
```
