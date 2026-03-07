---
name: fanqie-publisher
description: Publish a novel markdown file to Fanqie writer web editor (番茄小说) as one chapter using browser automation with session reuse. Use when the user asks to upload/post/publish an md chapter to Fanqie.
metadata: {"nanobot":{"emoji":"📝","os":["darwin","linux"],"requires":{"bins":["python3"]}}}
---

# Fanqie Publisher

Publish one Markdown document to a Fanqie chapter editor page.

## Workflow

1. Parse `.md` into a chapter payload
   - chapter title: first H1 (`# ...`), fallback to file name
   - recommended H1 format: `# 第19章：章节名` (chapter number should be Arabic digits)
   - body: markdown converted to plain text while keeping headings/paragraphs/tables/code blocks readable
2. Open Fanqie chapter edit URL with persistent browser profile
3. Wait for manual login on first run
4. Fill title + body fields
5. If `--publish true`, script follows fixed SOP (no page refresh):
   - click `存草稿` once
   - never refresh page
   - click top-right `下一步`
   - if typo modal appears (`检测到你还有错别字未修改`), click `提交`
   - if risk-check modal appears (`是否进行内容风险检测`), click `取消`
   - in publish settings modal, choose AI `是/否`, then click `确认发布`
   - success when redirected to `chapter-manage` URL (or success toast/page signal)
6. If `--publish false`, stop and let user click Publish manually
   - script auto-clicks top-right `下一步` after filling (`--auto-next-step true`)

## Prerequisites

- Install Playwright once:

```bash
pip install playwright
playwright install chromium
```

- Prepare:
  - markdown file path
  - Fanqie chapter edit page URL (`--work-url`)

## Commands

Dry-run parse preview (no browser):

```bash
python nanobot/skills/fanqie-publisher/scripts/publish_fanqie.py \
  --md-path /path/to/chapter.md \
  --dry-run true
```

Fill editor, then publish manually:

```bash
python nanobot/skills/fanqie-publisher/scripts/publish_fanqie.py \
  --md-path /path/to/chapter.md \
  --work-url "https://fanqienovel.com/writer/..." \
  --headless false \
  --publish false \
  --manual-wait-seconds 120
```

Automatic publish click (recommended):

```bash
python nanobot/skills/fanqie-publisher/scripts/publish_fanqie.py \
  --md-path /path/to/chapter.md \
  --work-url "https://fanqienovel.com/main/writer/<author_id>/publish/?enter_from=newchapter" \
  --headless false \
  --publish true \
  --ai-generated true \
  --publish-wait-seconds 120 \
  --hard-timeout-seconds 600
```

`--ai-generated` defaults to `true` (自动选“是”). Pass `--ai-generated false` if needed.
`--publish-wait-seconds` defaults to `25`; increase it (for example `120`) when publish dialogs are slow.
`--hard-timeout-seconds` defaults to `420`; browser flow auto-stops and closes when timeout is reached.
`--manual-wait-seconds` defaults to `0`; with `--publish=false` it limits manual wait time in TTY mode.

## Notes

- First run can require manual login and verification in browser.
- Browser session is persisted under `~/.nanobot/fanqie_profile`.
- Use writer `newchapter` URL for new chapter publishing: `.../publish/?enter_from=newchapter`.
- If you accidentally pass `.../publish/<chapter_id>?enter_from=newchapter`, script auto-normalizes to `.../publish/?enter_from=newchapter`.
- Do not refresh manually during publish flow.
- In `--publish=false` mode, if stdin is non-interactive (not a TTY), script exits instead of hanging on `input()`.
- After `存草稿`, if Fanqie clears fields asynchronously, script auto-refills and waits for stable state before `下一步`.
- If `下一步` stays unavailable, check chapter number format first (must be Arabic digits in chapter-number input).
- If a modal blocks pointer events, script avoids force-clicking behind the modal and waits for modal handling.
- Publish settings modal has two debug phases in trace logs:
  - `Publish modal visible (phase 1)` = modal is visible
  - `Publish modal interactive (phase 2)` = controls are actionable and script starts AI/confirm clicks
- On selector failure, screenshot and HTML debug artifacts are saved under `~/.nanobot/fanqie_logs`.
- If Fanqie page structure changes, update selectors by following
  `nanobot/skills/fanqie-publisher/references/fanqie_selectors.md`.
