#!/usr/bin/env python3
"""Publish one Markdown chapter to Fanqie writer editor using Playwright."""

from __future__ import annotations

import argparse
import re
import select
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from loguru import logger

DEFAULT_PROFILE_DIR = Path.home() / ".nanobot" / "fanqie_profile"
DEFAULT_LOG_DIR = Path.home() / ".nanobot" / "fanqie_logs"

TITLE_SELECTORS = [
    'input.serial-editor-input-hint-area',
    'input[placeholder*="请输入标题"]',
    'input[placeholder*="标题"]',
    'input[placeholder*="title" i]',
    'input[placeholder*="chapter" i]',
    'input[placeholder*="章节"]',
]

CHAPTER_NUMBER_SELECTORS = [
    ".serial-editor-title-left .left-input input",
    ".serial-editor-title-left input",
]

CONTENT_SELECTORS = [
    'div.serial-editor-content .ProseMirror[contenteditable="true"]',
    'div.serial-editor-container .ProseMirror[contenteditable="true"]',
    'div.ProseMirror[contenteditable="true"]',
    '.ProseMirror[contenteditable="true"]',
    'textarea[placeholder*="content" i]',
    'textarea[placeholder*="正文"]',
    'div[contenteditable="true"]',
    'div[role="textbox"]',
]

PUBLISH_SELECTORS = [
    'button:has-text("发布")',
    'button:has-text("发布章节")',
    'button:has-text("确认发布")',
    'button:has-text("提交")',
    'button:has-text("Publish")',
    'button[type="submit"]',
]

NEXT_STEP_SELECTORS = [
    'div.publish-header-right button.auto-editor-next:has-text("下一步")',
    'div.publish-header-right button:has-text("下一步")',
]

SUBMIT_SELECTORS = [
    'div.publish-header-right button:has-text("提交")',
    'button.auto-editor-next:has-text("提交")',
    'button:has-text("提交")',
]

SAVE_DRAFT_SELECTORS = [
    "button.auto-editor-save",
    'div.publish-header-right button:has-text("保存草稿")',
    'div.publish-header-right button:has-text("存草稿")',
    "div.publish-header-right button.arco-btn-secondary",
    'button:has-text("保存草稿")',
    'button:has-text("存草稿")',
    'button:has-text("草稿")',
    'button:has-text("保存")',
]

DRAFT_SAVED_HINTS = [
    "保存成功",
    "草稿已保存",
    "已保存",
]

PUBLISH_SUCCESS_SELECTORS = [
    "text=发布成功",
    "text=发布完成",
    "text=章节发布成功",
    "text=Publish successful",
]
PUBLISH_SUCCESS_PAGE_SELECTORS = [
    "div.content-card-wrap.path-prefix-chapter-manage",
    "div.chapter-table.auto-editor-chapter",
]

CHAPTER_TITLE_PATTERN = re.compile(r"^\s*第\s*(\d+)\s*章\s*(.*)$")
AI_REQUIRED_TEXT = "是否使用AI"
PUBLISH_CONFIRM_SELECTORS = [
    'button:has-text("确认发布")',
    'button:has-text("确认")',
    'button:has-text("发布")',
]
PUBLISH_MODAL_SELECTORS = [
    'div[role="dialog"]:has-text("发布设置")',
    'div[role="dialog"]:has-text("是否使用AI")',
    'div[role="dialog"]:has(button:has-text("确认发布"))',
]
CONTINUE_EDIT_MODAL_SELECTORS = [
    'div[role="dialog"]:has-text("是否继续编辑")',
    'div[role="dialog"]:has-text("有刚刚更新的章节")',
]
CONTINUE_EDIT_BUTTON_SELECTORS = [
    'button:has-text("继续编辑")',
    'button:has-text("继续")',
]
RISK_MODAL_HINTS = [
    "是否进行内容风险检测",
    "风险提示功能",
]
RISK_MODAL_CANCEL_SELECTORS = [
    'button:has-text("取消")',
    'button:has-text("关闭")',
    'button:has-text("稍后")',
]
TOUR_STEP_BUTTON_SELECTORS = [
    '#___reactour button:has-text("跳过")',
    '#___reactour button:has-text("知道了")',
    '#___reactour button:has-text("下一步")',
    '#___reactour button:has-text("完成")',
]

TYPO_MODAL_HINTS = [
    "检测到你还有错别字未修改",
    "错别字未修改",
    "错别字",
]
TYPO_MODAL_SUBMIT_SELECTORS = [
    'button:has-text("提交")',
    'button:has-text("继续提交")',
    'button:has-text("确认")',
]

HORIZONTAL_RULE_PATTERN = re.compile(r"^\s*([-*_]\s*){3,}$")
H1_PATTERN = re.compile(r"^\s*#\s+(.+?)\s*$", re.MULTILINE)
IMAGE_PATTERN = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
LINK_PATTERN = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
HTML_TAG_PATTERN = re.compile(r"<[^>]+>")
_PHASE_LOGGED_KEYS: set[str] = set()


@dataclass(slots=True)
class ChapterPayload:
    title: str
    body: str


def log_phase_once(phase_key: str, message: str, *args) -> None:
    """Log an info message only once per run for a given phase key."""
    if phase_key in _PHASE_LOGGED_KEYS:
        return
    _PHASE_LOGGED_KEYS.add(phase_key)
    logger.info(message, *args)


def log_debug_exception(context: str, exc: Exception) -> None:
    """Log lightweight debug exception context without interrupting retries."""
    logger.debug("{}: {}: {}", context, type(exc).__name__, exc)


def configure_logging(log_dir: Path, explicit_log_file: str | None) -> Path:
    """Configure loguru outputs and return trace log path."""
    if explicit_log_file:
        log_path = Path(explicit_log_file).expanduser().resolve()
    else:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        log_path = log_dir / f"fanqie-publish-{timestamp}.log"

    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger.remove()
    logger.add(sys.stderr, level="INFO")
    logger.add(log_path, level="DEBUG", encoding="utf-8")
    logger.debug("Logging initialized. log_file={}", log_path)
    return log_path


def parse_bool(value: str | bool) -> bool:
    """Parse booleans from CLI values."""
    if isinstance(value, bool):
        return value

    lowered = value.strip().lower()
    if lowered in {"1", "true", "t", "yes", "y", "on"}:
        return True
    if lowered in {"0", "false", "f", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"Invalid boolean value: {value}")


def extract_title(markdown_text: str, fallback_name: str) -> str:
    """Extract the first H1 title, then fallback to file stem."""
    match = H1_PATTERN.search(markdown_text)
    if match:
        title = match.group(1).strip()
        if title:
            return title
    return fallback_name.strip() or "Untitled chapter"


def split_chapter_title(raw_title: str) -> tuple[str | None, str]:
    """Split title into chapter number and chapter name when possible."""
    match = CHAPTER_TITLE_PATTERN.match(raw_title.strip())
    if not match:
        return None, raw_title.strip()

    chapter_number = match.group(1).strip() or None
    chapter_name = match.group(2).strip()
    if not chapter_name:
        chapter_name = raw_title.strip()
    return chapter_number, chapter_name


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", "", value or "").strip()


def strip_leading_duplicate_title(body: str, title: str) -> str:
    """Remove the first body line when it duplicates chapter title."""
    if not body:
        return body

    chapter_number, chapter_name = split_chapter_title(title)
    candidates = {
        _normalize_text(title),
        _normalize_text(chapter_name),
    }
    if chapter_number and chapter_name:
        candidates.add(_normalize_text(f"第{chapter_number}章 {chapter_name}"))
        candidates.add(_normalize_text(f"第{chapter_number}章{chapter_name}"))

    lines = body.splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    if not lines:
        return ""

    first_line_normalized = _normalize_text(lines[0])
    if first_line_normalized in candidates:
        lines.pop(0)
        while lines and not lines[0].strip():
            lines.pop(0)
    return "\n".join(lines).strip()


def remove_first_h1(markdown_text: str) -> str:
    """Remove only the first H1 to avoid repeating it in content."""
    return H1_PATTERN.sub("", markdown_text, count=1)


def _is_table_row(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    return stripped.count("|") >= 2


def _normalize_table_rows(rows: list[str]) -> list[str]:
    rendered: list[str] = []
    for row in rows:
        cells = [cell.strip() for cell in row.strip().strip("|").split("|")]
        if not cells:
            continue
        if all(re.fullmatch(r":?-{3,}:?", cell or "-") for cell in cells):
            continue
        rendered.append(" | ".join(cells))

    if not rendered:
        return []
    return ["[table]"] + rendered + ["[/table]"]


def _convert_inline_markdown(line: str) -> str:
    line = IMAGE_PATTERN.sub(
        lambda m: f"[image: {m.group(1).strip() or 'image'}] ({m.group(2).strip()})",
        line,
    )
    line = LINK_PATTERN.sub(lambda m: f"{m.group(1).strip()} ({m.group(2).strip()})", line)
    line = line.replace("`", "")
    line = HTML_TAG_PATTERN.sub("", line)
    return line


def markdown_to_editor_text(markdown_text: str) -> str:
    """Convert markdown to plain text while preserving structure."""
    output_lines: list[str] = []
    table_buffer: list[str] = []
    in_code_block = False

    for raw_line in markdown_text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw_line.rstrip()
        stripped = line.strip()

        if stripped.startswith("```"):
            if table_buffer:
                output_lines.extend(_normalize_table_rows(table_buffer))
                table_buffer = []

            if not in_code_block:
                code_language = stripped[3:].strip() or "plain"
                output_lines.append(f"[code block: {code_language}]")
                in_code_block = True
            else:
                output_lines.append("[/code block]")
                in_code_block = False
            continue

        if in_code_block:
            output_lines.append(line)
            continue

        if _is_table_row(line):
            table_buffer.append(line)
            continue

        if table_buffer:
            output_lines.extend(_normalize_table_rows(table_buffer))
            table_buffer = []

        if HORIZONTAL_RULE_PATTERN.match(stripped):
            output_lines.append("----------")
            continue

        heading_match = re.match(r"^\s*#{2,6}\s+(.+?)\s*$", line)
        if heading_match:
            output_lines.append(f"[{heading_match.group(1).strip()}]")
            continue

        line = re.sub(r"^\s*>\s?", "", line)
        line = re.sub(r"^\s*[-*+]\s+", "- ", line)
        line = _convert_inline_markdown(line)
        output_lines.append(line.strip())

    if table_buffer:
        output_lines.extend(_normalize_table_rows(table_buffer))

    compact_lines: list[str] = []
    previous_blank = False
    for line in output_lines:
        cleaned = line.rstrip()
        if not cleaned:
            if not previous_blank:
                compact_lines.append("")
            previous_blank = True
            continue
        previous_blank = False
        compact_lines.append(cleaned)

    return "\n".join(compact_lines).strip()


def build_payload(md_path: Path) -> ChapterPayload:
    """Build publish payload from markdown file."""
    markdown_text = md_path.read_text(encoding="utf-8")
    title = extract_title(markdown_text, md_path.stem)
    body_source = remove_first_h1(markdown_text)
    body = markdown_to_editor_text(body_source)
    body = strip_leading_duplicate_title(body, title)
    if not body:
        raise ValueError(f"No publishable content found in: {md_path}")
    return ChapterPayload(title=title, body=body)


def _load_playwright():
    """Import Playwright lazily so parser tests work without browser deps."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Playwright is required. Install with `pip install playwright` and "
            "`playwright install chromium`."
        ) from exc
    return sync_playwright


def normalize_newchapter_url(work_url: str) -> str:
    """Normalize newchapter URL to avoid editing an existing chapter id by mistake."""
    parsed = urlparse(work_url)
    query = parse_qs(parsed.query or "")
    enter_from = {v for values in query.values() for v in values}
    if "newchapter" not in enter_from:
        return work_url

    match = re.match(r"^(/main/writer/\d+/publish)/\d+/?$", parsed.path)
    if not match:
        return work_url

    normalized_path = f"{match.group(1)}/"
    normalized_query = urlencode(query, doseq=True)
    normalized_url = urlunparse(parsed._replace(path=normalized_path, query=normalized_query))
    if normalized_url != work_url:
        logger.warning(
            "Normalized work URL from '{}' to '{}' for new chapter creation",
            work_url,
            normalized_url,
        )
    return normalized_url


def _find_first_visible_selector(
    page, selectors: list[str], *, require_enabled: bool = False
) -> str | None:
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if locator.count() <= 0 or not locator.is_visible(timeout=800):
                continue
            if require_enabled and not locator.is_enabled(timeout=500):
                continue
            disabled_reason = _locator_disabled_reason(locator)
            if disabled_reason == "reactour-overlay":
                continue
            if require_enabled and disabled_reason:
                logger.debug(
                    "Selector '{}' is visible but disabled ({})",
                    selector,
                    disabled_reason,
                )
                continue
            return selector
        except Exception as exc:
            log_debug_exception(f"find-visible-selector:{selector}", exc)
            continue
    return None


def _locator_disabled_reason(locator) -> str | None:
    """Return disabled reason for clickable widgets, including aria/class-disabled states."""
    try:
        reason = locator.evaluate(
            """
            (el) => {
              const target =
                el.closest('button, [role="button"], [role="radio"], input, textarea') || el;
              if (!target) return null;

              const className = String(target.className || '');
              const ariaDisabled = String(target.getAttribute('aria-disabled') || '').toLowerCase();
              const hasDisabledAttr = target.hasAttribute('disabled');
              const propDisabled = typeof target.disabled === 'boolean' ? target.disabled : false;
              const classDisabled =
                /(\\bdisabled\\b|is-disabled|arco-btn-disabled|byte-btn-disabled)/i.test(className);
              const pointerDisabled = window.getComputedStyle(target).pointerEvents === 'none';
              const inReactour = !!(target.closest('#___reactour') || el.closest('#___reactour'));

              if (inReactour) return 'reactour-overlay';
              if (hasDisabledAttr || propDisabled) return 'disabled-attr';
              if (ariaDisabled === 'true') return 'aria-disabled';
              if (classDisabled) return `class:${className}`;
              if (pointerDisabled) return 'pointer-events:none';
              return null;
            }
            """,
            timeout=900,
        )
        if isinstance(reason, str) and reason.strip():
            return reason.strip()
    except Exception as exc:
        log_debug_exception("locator-disabled-reason", exc)
        return None
    return None


def _is_locator_actionable(locator, timeout_ms: int = 400) -> bool:
    """Check whether a locator is visible and not disabled/blocked."""
    try:
        if locator.count() <= 0 or not locator.is_visible(timeout=timeout_ms):
            return False
        if locator.get_attribute("disabled") is not None:
            return False
        return _locator_disabled_reason(locator) is None
    except Exception as exc:
        log_debug_exception("locator-actionable-check", exc)
        return False


def wait_for_editor(page, timeout_seconds: int) -> tuple[str, str] | None:
    """Wait until both title and body fields are available."""
    deadline = time.time() + timeout_seconds
    logger.info("Waiting for editor fields up to {}s", timeout_seconds)
    while time.time() < deadline:
        handle_blocking_overlays(page)
        title_selector = _find_first_visible_selector(page, TITLE_SELECTORS)
        content_selector = _find_first_visible_selector(page, CONTENT_SELECTORS)
        if title_selector and content_selector:
            logger.info(
                "Editor detected. title_selector='{}' content_selector='{}'",
                title_selector,
                content_selector,
            )
            return title_selector, content_selector
        page.wait_for_timeout(1000)
    logger.error("Editor fields not found within timeout")
    return None


def handle_blocking_overlays(page) -> bool:
    """Dismiss known blocking dialogs and first-run tour overlays."""
    handled = False

    for hint in RISK_MODAL_HINTS:
        modal = page.locator(f"div[role='dialog']:has-text('{hint}'), div.arco-modal-wrapper:has-text('{hint}')").first
        try:
            if modal.count() <= 0 or not modal.is_visible(timeout=500):
                continue
            for button_selector in RISK_MODAL_CANCEL_SELECTORS:
                button = modal.locator(button_selector).first
                if button.count() <= 0 or not button.is_visible(timeout=500):
                    continue
                if button.get_attribute("disabled") is not None:
                    continue
                if not safe_click(page, button, f"risk-modal:{button_selector}", timeout_ms=1500):
                    continue
                page.wait_for_timeout(350)
                handled = True
                logger.info("Dismissed risk modal via '{}'", button_selector)
                break
            if handled:
                break
        except Exception as exc:
            log_debug_exception(f"overlay-risk-modal:{hint}", exc)
            continue

    for modal_selector in CONTINUE_EDIT_MODAL_SELECTORS:
        modal = page.locator(modal_selector).first
        try:
            if modal.count() <= 0 or not modal.is_visible(timeout=500):
                continue
            for button_selector in CONTINUE_EDIT_BUTTON_SELECTORS:
                button = modal.locator(button_selector).first
                if button.count() <= 0 or not button.is_visible(timeout=500):
                    continue
                if button.get_attribute("disabled") is not None:
                    continue
                if not safe_click(page, button, f"continue-edit:{button_selector}", timeout_ms=1500):
                    continue
                page.wait_for_timeout(400)
                handled = True
                logger.info("Dismissed continue-edit modal via button '{}'", button_selector)
                break
            if handled:
                break
        except Exception as exc:
            log_debug_exception(f"overlay-continue-edit:{modal_selector}", exc)
            continue

    for _ in range(6):
        clicked = False
        for button_selector in TOUR_STEP_BUTTON_SELECTORS:
            button = page.locator(button_selector).first
            try:
                if button.count() <= 0 or not button.is_visible(timeout=400):
                    continue
                if button.get_attribute("disabled") is not None:
                    continue
                if not safe_click(page, button, f"tour:{button_selector}", timeout_ms=1200):
                    continue
                page.wait_for_timeout(250)
                handled = True
                logger.info("Dismissed tour overlay via '{}'", button_selector)
                clicked = True
                break
            except Exception as exc:
                log_debug_exception(f"overlay-tour:{button_selector}", exc)
                continue
        if not clicked:
            break

    try:
        tour_removed = bool(
            page.evaluate(
                """
                () => {
                  const root = document.querySelector('#___reactour');
                  if (!root) return false;
                  root.remove();
                  return true;
                }
                """
            )
        )
        handled = handled or tour_removed
        if tour_removed:
            logger.info("Removed #___reactour overlay directly")
    except Exception as exc:
        log_debug_exception("overlay-remove-reactour", exc)
        pass

    return handled


def snapshot_editor_state(page) -> dict[str, str]:
    """Collect small state snapshot for debugging publish failures."""
    state = page.evaluate(
        """
        () => {
          const numberInput = document.querySelector('.serial-editor-title-left .left-input input');
          const titleInput = document.querySelector('input.serial-editor-input-hint-area');
          const nextBtn = document.querySelector('button.auto-editor-next');
          const body = document.querySelector('.ProseMirror');
          const text = body ? (body.textContent || '') : '';
          return {
            url: location.href,
            number: numberInput ? (numberInput.value || '') : '',
            title: titleInput ? (titleInput.value || '') : '',
            next_disabled: nextBtn ? String(nextBtn.hasAttribute('disabled')) : 'unknown',
            body_chars: String(text.length),
          };
        }
        """
    )
    return {k: str(v) for k, v in state.items()}


def describe_selector_candidates(page, selector: str) -> list[dict[str, str]]:
    """Return compact selector candidate states for debug logs."""
    try:
        rows = page.evaluate(
            """
            (css) => {
              const toRect = (el) => {
                const r = el.getBoundingClientRect();
                return `${Math.round(r.x)},${Math.round(r.y)},${Math.round(r.width)}x${Math.round(r.height)}`;
              };
              return Array.from(document.querySelectorAll(css)).slice(0, 6).map((el, idx) => {
                const style = window.getComputedStyle(el);
                const text = (el.textContent || '').replace(/\\s+/g, ' ').trim();
                return {
                  idx: String(idx),
                  text: text.slice(0, 30),
                  class_name: String(el.className || '').slice(0, 120),
                  disabled_attr: String(el.hasAttribute('disabled')),
                  aria_disabled: String(el.getAttribute('aria-disabled') || ''),
                  visible: String(style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0'),
                  pointer_events: String(style.pointerEvents || ''),
                  in_reactour: String(!!el.closest('#___reactour')),
                  rect: toRect(el),
                };
              });
            }
            """,
            selector,
        )
        return [{k: str(v) for k, v in row.items()} for row in rows]
    except Exception as exc:
        log_debug_exception("describe-selector-candidates", exc)
        return []


def collect_ui_hints(page) -> list[str]:
    """Collect short visible toast/dialog hints for troubleshooting."""
    try:
        hints = page.evaluate(
            """
            () => {
              const selectors = [
                '.arco-message-notice-content',
                '.arco-notification-content',
                '.arco-modal-wrapper',
                '[role="alert"]',
              ];
              const items = [];
              for (const css of selectors) {
                for (const el of document.querySelectorAll(css)) {
                  const style = window.getComputedStyle(el);
                  if (style.display === 'none' || style.visibility === 'hidden') continue;
                  const text = (el.textContent || '').replace(/\\s+/g, ' ').trim();
                  if (text) items.push(text.slice(0, 120));
                }
              }
              return Array.from(new Set(items)).slice(0, 8);
            }
            """
        )
        return [str(item) for item in hints]
    except Exception as exc:
        log_debug_exception("collect-ui-hints", exc)
        return []


def is_publish_stage_ready(page) -> bool:
    """Detect whether page already moved past editor into publish/submit stages."""
    if _find_first_visible_selector(page, SUBMIT_SELECTORS, require_enabled=False):
        return True

    for selector in PUBLISH_MODAL_SELECTORS:
        modal = page.locator(selector).first
        try:
            if modal.count() > 0 and modal.is_visible(timeout=300):
                return True
        except Exception as exc:
            log_debug_exception(f"publish-stage-modal:{selector}", exc)
            continue

    for hint in TYPO_MODAL_HINTS + RISK_MODAL_HINTS:
        modal = page.locator(
            f"div[role='dialog']:has-text('{hint}'), div.arco-modal-wrapper:has-text('{hint}')"
        ).first
        try:
            if modal.count() > 0 and modal.is_visible(timeout=300):
                return True
        except Exception as exc:
            log_debug_exception(f"publish-stage-hint:{hint}", exc)
            continue
    return False


def has_visible_modal_dialog(page) -> bool:
    """Check whether a visible modal/dialog currently blocks page interactions."""
    try:
        return bool(
            page.evaluate(
                """
                () => {
                  const isVisible = (el) => {
                    const style = window.getComputedStyle(el);
                    if (style.display === 'none' || style.visibility === 'hidden') return false;
                    const rect = el.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                  };
                  return Array.from(
                    document.querySelectorAll('div.arco-modal-wrapper, div[role="dialog"]')
                  ).some(isVisible);
                }
                """
            )
        )
    except Exception as exc:
        log_debug_exception("has-visible-modal-dialog", exc)
        return False


def _set_element_value(locator, value: str) -> None:
    js_set_value = """
    (el, text) => {
      const editable =
        el.matches('input,textarea,[contenteditable="true"]')
          ? el
          : el.querySelector('input,textarea,[contenteditable="true"]');
      if (!editable) {
        throw new Error('No editable element found for selector.');
      }
      if (editable instanceof HTMLInputElement || editable instanceof HTMLTextAreaElement) {
        editable.focus();
        editable.value = text;
      } else {
        editable.focus();
        editable.textContent = text;
      }
      editable.dispatchEvent(new Event('input', { bubbles: true }));
      editable.dispatchEvent(new Event('change', { bubbles: true }));
    }
    """
    locator.evaluate(js_set_value, value)


def safe_click(page, locator, description: str, timeout_ms: int = 3000) -> bool:
    """Click with JS fallback when overlays intercept pointer events."""
    try:
        locator.click(timeout=timeout_ms)
        return True
    except Exception as exc:
        logger.warning("Native click failed for {}: {}. trying JS click fallback", description, exc)
        if "intercepts pointer events" in str(exc):
            target_in_modal = False
            try:
                target_in_modal = bool(
                    locator.evaluate(
                        "el => !!el.closest('div.arco-modal-wrapper, div[role=\"dialog\"]')",
                        timeout=800,
                    )
                )
            except Exception as exc:
                log_debug_exception("safe-click:target-in-modal-check", exc)
                pass
            if has_visible_modal_dialog(page) and not target_in_modal:
                logger.warning(
                    "Skip JS click fallback for {} because a modal dialog is blocking it",
                    description,
                )
                return False

    disabled_reason = _locator_disabled_reason(locator)
    if disabled_reason:
        logger.warning(
            "Skip JS click fallback for {} because element is disabled ({})",
            description,
            disabled_reason,
        )
        return False

    js_started_at = time.time()
    try:
        locator.evaluate(
            """
            (el) => {
              const target = el.closest('button, [role="button"]') || el;
              target.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true }));
              target.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true }));
              target.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
              if (typeof target.click === 'function') target.click();
            }
            """,
            timeout=min(timeout_ms, 1200),
        )
        page.wait_for_timeout(220)
        logger.debug(
            "JS click fallback succeeded for {} in {}ms",
            description,
            int((time.time() - js_started_at) * 1000),
        )
        return True
    except Exception as js_exc:
        logger.warning(
            "JS click fallback failed for {} in {}ms: {}",
            description,
            int((time.time() - js_started_at) * 1000),
            js_exc,
        )
        return False


def is_publish_success_state(page) -> bool:
    """Detect either a publish success toast or a success redirect page."""
    if _find_first_visible_selector(page, PUBLISH_SUCCESS_SELECTORS):
        logger.info("Detected publish success toast")
        return True

    try:
        if "/chapter-manage/" in page.url:
            logger.info("Detected publish success URL '{}'", page.url)
            return True
    except Exception as exc:
        log_debug_exception("publish-success:url-check", exc)
        pass

    for selector in PUBLISH_SUCCESS_PAGE_SELECTORS:
        locator = page.locator(selector).first
        try:
            if locator.count() > 0 and locator.is_visible(timeout=500):
                logger.info("Detected publish success page via selector '{}'", selector)
                return True
        except Exception as exc:
            log_debug_exception(f"publish-success:selector:{selector}", exc)
            continue
    return False


def context_has_success_page(page) -> bool:
    """Check other pages in same context for chapter-manage success URL."""
    try:
        for ctx_page in page.context.pages:
            try:
                if "/chapter-manage/" in ctx_page.url:
                    logger.info("Detected success in sibling page url='{}'", ctx_page.url)
                    return True
            except Exception as exc:
                log_debug_exception("context-success:sibling-url", exc)
                continue
    except Exception as exc:
        log_debug_exception("context-success:iterate-pages", exc)
        return False
    return False


def fill_input_exact(page, selectors: list[str], value: str, field_name: str) -> str:
    """Fill a text input and verify its final value exactly matches target."""
    errors: list[str] = []
    expected = value.strip()

    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if locator.count() <= 0 or not locator.is_visible(timeout=800):
                continue
            locator.scroll_into_view_if_needed(timeout=2000)

            locator.evaluate(
                """
                (el, text) => {
                  const inputEl =
                    el.matches('input,textarea') ? el : el.querySelector('input,textarea');
                  if (!inputEl) {
                    throw new Error('No input element found');
                  }
                  inputEl.focus();
                  const proto = Object.getPrototypeOf(inputEl);
                  const desc = Object.getOwnPropertyDescriptor(proto, 'value');
                  if (desc && typeof desc.set === 'function') {
                    desc.set.call(inputEl, text);
                  } else {
                    inputEl.value = text;
                  }
                  inputEl.dispatchEvent(new Event('input', { bubbles: true }));
                  inputEl.dispatchEvent(new Event('change', { bubbles: true }));
                  inputEl.dispatchEvent(new Event('blur', { bubbles: true }));
                }
                """,
                value,
            )

            actual = locator.input_value(timeout=2000).strip()
            if actual == expected:
                logger.debug("Filled {} using selector={} value='{}'", field_name, selector, expected)
                return selector

            try:
                locator.click(timeout=1500)
            except Exception as exc:
                log_debug_exception(f"fill-input:pre-click:{selector}", exc)
                pass
            locator.fill(value, timeout=2000)
            actual = locator.input_value(timeout=2000).strip()
            if actual == expected:
                logger.debug("Filled {} via fill() selector={} value='{}'", field_name, selector, expected)
                return selector

            errors.append(f"{selector}: value='{actual}'")
        except Exception as exc:
            errors.append(f"{selector}: {exc}")

    logger.error("Failed filling {}. errors={}", field_name, errors)
    raise RuntimeError(f"Unable to set {field_name} to '{value}'. Details: {'; '.join(errors)}")


def fill_field(page, selector: str, value: str, field_name: str) -> None:
    """Fill one field with fallback methods for different editors."""
    locator = page.locator(selector).first
    locator.scroll_into_view_if_needed(timeout=3000)
    errors: list[str] = []

    try:
        is_contenteditable = locator.evaluate(
            """(el) => {
                const target =
                  el.matches('input,textarea,[contenteditable="true"]')
                    ? el
                    : el.querySelector('input,textarea,[contenteditable="true"]');
                return !!(target && target.isContentEditable);
            }"""
        )
        if is_contenteditable:
            locator.click(timeout=3000)
            page.keyboard.press("Control+A")
            page.keyboard.press("Backspace")
            page.keyboard.insert_text(value)
            logger.debug("Filled {} via contenteditable keyboard", field_name)
            return
    except Exception as exc:
        errors.append(f"contenteditable-keyboard: {exc}")

    try:
        _set_element_value(locator, value)
        logger.debug("Filled {} via js-eval", field_name)
        return
    except Exception as exc:
        errors.append(f"js-eval: {exc}")

    try:
        locator.fill(value, timeout=3000)
        logger.debug("Filled {} via locator.fill", field_name)
        return
    except Exception as exc:
        errors.append(f"fill: {exc}")

    try:
        locator.click(timeout=3000)
        page.keyboard.press("Control+A")
        page.keyboard.insert_text(value)
        logger.debug("Filled {} via keyboard fallback", field_name)
        return
    except Exception as exc:
        errors.append(f"keyboard: {exc}")

    details = "; ".join(errors)
    logger.error("Failed filling {}. details={}", field_name, details)
    raise RuntimeError(f"Unable to fill {field_name} via selector `{selector}`. {details}")


def should_refill_after_draft_save(
    snapshot: dict[str, str], chapter_number: str | None, chapter_name: str, body_text: str
) -> bool:
    """Decide whether editor fields look reset after clicking save draft."""
    number = (snapshot.get("number") or "").strip()
    title = (snapshot.get("title") or "").strip()
    body_chars_raw = (snapshot.get("body_chars") or "0").strip()
    try:
        body_chars = int(body_chars_raw)
    except ValueError:
        body_chars = 0

    if chapter_number and number != chapter_number:
        return True
    if title != chapter_name:
        return True
    return body_chars < max(120, len(body_text) // 8)


def click_publish(page, timeout_seconds: int, ai_generated: bool) -> None:
    """Run fixed publish sequence: 下一步 -> 提交 -> 风险取消 -> AI设置确认."""
    deadline = time.time() + timeout_seconds
    action_taken = False
    publish_triggered = False
    next_click_count = 0
    last_publish_action_at = 0.0
    logger.info("Starting publish loop. timeout={}s ai_generated={}", timeout_seconds, ai_generated)

    while time.time() < deadline:
        try:
            if handle_blocking_overlays(page):
                action_taken = True
                continue

            if is_publish_success_state(page):
                return

            if publish_triggered and (time.time() - last_publish_action_at) < 3.5:
                page.wait_for_timeout(450)
                continue

            if handle_publish_modal(page, ai_generated=ai_generated):
                action_taken = True
                publish_triggered = True
                last_publish_action_at = time.time()
                next_click_count = 0
                logger.info("Handled publish settings modal and confirmed publish")
                continue

            if handle_typo_modal_submit(page):
                action_taken = True
                publish_triggered = True
                last_publish_action_at = time.time()
                next_click_count = 0
                logger.info("Handled typo warning modal and clicked submit")
                continue

            submit_selector = _find_first_visible_selector(page, SUBMIT_SELECTORS, require_enabled=True)
            if submit_selector:
                action_taken = True
                publish_triggered = True
                last_publish_action_at = time.time()
                next_click_count = 0
                logger.info("Clicking submit selector '{}' during publish loop", submit_selector)
                clicked = safe_click(
                    page,
                    page.locator(submit_selector).first,
                    f"submit:{submit_selector}",
                    timeout_ms=3000,
                )
                if not clicked:
                    page.wait_for_timeout(700)
                    continue
                page.wait_for_timeout(1200)
                continue
            submit_present = _find_first_visible_selector(page, SUBMIT_SELECTORS, require_enabled=False)
            if submit_present:
                logger.debug("Submit selector '{}' is visible but disabled; waiting.", submit_present)
                page.wait_for_timeout(900)
                continue

            next_selector = _find_first_visible_selector(page, NEXT_STEP_SELECTORS, require_enabled=True)
            if next_selector:
                action_taken = True
                next_click_count += 1
                logger.debug(
                    "Next-step candidates for '{}': {}",
                    next_selector,
                    describe_selector_candidates(page, next_selector),
                )
                logger.info("Clicking next-step selector '{}' during publish loop", next_selector)
                clicked = safe_click(
                    page,
                    page.locator(next_selector).first,
                    f"next-step:{next_selector}",
                    timeout_ms=3000,
                )
                if not clicked:
                    page.wait_for_timeout(700)
                    continue
                if next_click_count % 5 == 0:
                    logger.warning(
                        "Next-step clicked {} times; snapshot={} hints={}",
                        next_click_count,
                        snapshot_editor_state(page),
                        collect_ui_hints(page),
                    )
                page.wait_for_timeout(1000)
                continue

            page.wait_for_timeout(700)
        except Exception as exc:
            if "Target page, context or browser has been closed" in str(exc) and action_taken:
                if publish_triggered or context_has_success_page(page):
                    logger.warning("Page/context closed after publish trigger; probable success")
                    return
                if _find_first_visible_selector(page, NEXT_STEP_SELECTORS, require_enabled=False):
                    logger.warning(
                        "Page closed after next-step in publish phase; treating as probable success"
                    )
                    return
                raise RuntimeError(
                    "Page closed before publish was triggered. This run is not confirmed successful."
                ) from exc
            raise

    if is_publish_success_state(page):
        return

    raise RuntimeError("Publish sequence timed out before success confirmation.")


def click_save_draft_once(page, wait_seconds: int = 8) -> bool:
    """Save draft one time before publish and wait briefly for save feedback."""
    deadline = time.time() + wait_seconds
    selector = None
    while time.time() < deadline:
        handle_blocking_overlays(page)
        selector = _find_first_visible_selector(page, SAVE_DRAFT_SELECTORS, require_enabled=True)
        if selector:
            break
        page.wait_for_timeout(250)
    if not selector:
        logger.warning("Save-draft button not enabled/visible")
        return False

    logger.info("Clicking save-draft selector '{}'", selector)
    if not safe_click(page, page.locator(selector).first, f"save-draft:{selector}", timeout_ms=3000):
        logger.warning("Save-draft click skipped because button was blocked/disabled")
        return False

    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        handle_blocking_overlays(page)
        for hint in DRAFT_SAVED_HINTS:
            toast = page.locator(f"text={hint}").first
            try:
                if toast.count() > 0 and toast.is_visible(timeout=300):
                    logger.info("Detected draft-save hint '{}'", hint)
                    return True
            except Exception as exc:
                log_debug_exception(f"save-draft:toast:{hint}", exc)
                continue
        page.wait_for_timeout(250)

    logger.info("No explicit draft-save hint detected within {}s; continuing", wait_seconds)
    return True


def handle_typo_modal_submit(page) -> bool:
    """Handle typo warning modal by clicking submit."""
    for hint in TYPO_MODAL_HINTS:
        modal = page.locator(
            f"div[role='dialog']:has-text('{hint}'), div.arco-modal-wrapper:has-text('{hint}')"
        ).first
        try:
            if modal.count() <= 0 or not modal.is_visible(timeout=500):
                continue
            for button_selector in TYPO_MODAL_SUBMIT_SELECTORS:
                button = modal.locator(button_selector).first
                if button.count() <= 0 or not button.is_visible(timeout=500):
                    continue
                if button.get_attribute("disabled") is not None:
                    continue
                if not safe_click(page, button, f"typo-modal:{button_selector}", timeout_ms=1800):
                    continue
                page.wait_for_timeout(350)
                logger.info("Dismissed typo modal via '{}'", button_selector)
                return True
        except Exception as exc:
            log_debug_exception(f"typo-modal:{hint}", exc)
            continue
    return False


def click_next_step(page) -> bool:
    """Click the top-right next-step button if it is enabled and visible."""
    handle_blocking_overlays(page)
    selector = _find_first_visible_selector(page, NEXT_STEP_SELECTORS, require_enabled=True)
    if not selector:
        logger.warning("Next-step button not enabled/visible")
        return False
    logger.debug(
        "Next-step candidates for '{}': {}",
        selector,
        describe_selector_candidates(page, selector),
    )
    logger.info("Clicking next-step selector '{}'", selector)
    if not safe_click(page, page.locator(selector).first, f"next-step:{selector}", timeout_ms=3000):
        logger.warning("Next-step click skipped because target was blocked/disabled")
        return False
    page.wait_for_timeout(1000)
    return True


def wait_for_next_step_enabled(page, timeout_seconds: int) -> bool:
    """Wait until top-right next-step becomes enabled."""
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        handle_blocking_overlays(page)
        selector = _find_first_visible_selector(page, NEXT_STEP_SELECTORS, require_enabled=True)
        if selector:
            return True
        page.wait_for_timeout(350)
    logger.warning("Next-step not enabled after {}s. snapshot={}", timeout_seconds, snapshot_editor_state(page))
    return False


def refill_editor_fields(
    page,
    chapter_number: str | None,
    chapter_name: str,
    body_text: str,
    timeout_seconds: int,
) -> None:
    """Refill chapter number/title/body in editor and wait briefly."""
    editor = wait_for_editor(page, timeout_seconds=timeout_seconds)
    if not editor:
        raise RuntimeError("Editor fields missing; cannot refill chapter content.")

    if chapter_number:
        fill_input_exact(page, CHAPTER_NUMBER_SELECTORS, chapter_number, "chapter number")
    fill_input_exact(page, TITLE_SELECTORS, chapter_name, "chapter title")
    _, content_selector = editor
    fill_field(page, content_selector, body_text, "chapter body")
    page.wait_for_timeout(900)


def is_ai_option_selected(modal, ai_option: str) -> bool:
    """Check whether target AI radio option is selected in publish modal."""
    try:
        return bool(
            modal.evaluate(
                """
                (root, targetText) => {
                  const norm = (s) => (s || '').replace(/\\s+/g, '');
                  const target = norm(targetText);
                  const candidates = root.querySelectorAll(
                    'label, [role="radio"], .byte-radio-wrapper, .arco-radio, input[type="radio"]'
                  );
                  const isSelected = (el) => {
                    const className = String(el.className || '');
                    if (/checked|selected/.test(className)) return true;
                    const radio = el.matches('[role="radio"]')
                      ? el
                      : el.closest('[role="radio"]') || el.querySelector('[role="radio"]');
                    if (radio && radio.getAttribute('aria-checked') === 'true') return true;
                    const input = el.matches('input[type="radio"]')
                      ? el
                      : el.querySelector('input[type="radio"]')
                        || el.closest('label')?.querySelector('input[type="radio"]');
                    return !!(input && input.checked);
                  };
                  for (const item of candidates) {
                    const text = norm(item.textContent || '');
                    if (!text.includes(target)) continue;
                    if (target === '是' && text.includes('是否')) continue;
                    if (text.length > 8) continue;
                    if (isSelected(item)) return true;
                  }
                  return false;
                }
                """,
                ai_option,
            )
        )
    except Exception as exc:
        log_debug_exception("ai-option-selected", exc)
        return False


def force_select_ai_option(modal, ai_option: str) -> bool:
    """Force click target AI option using DOM fallback when normal locator clicks fail."""
    try:
        return bool(
            modal.evaluate(
                """
                (root, targetText) => {
                  const norm = (s) => (s || '').replace(/\\s+/g, '');
                  const target = norm(targetText);
                  const candidates = root.querySelectorAll(
                    'label, [role="radio"], .byte-radio-wrapper, .arco-radio, input[type="radio"]'
                  );
                  for (const item of candidates) {
                    const text = norm(item.textContent || '');
                    if (!text.includes(target)) continue;
                    if (target === '是' && text.includes('是否')) continue;
                    if (text.length > 8) continue;
                    const clickTarget =
                      item.matches('input[type="radio"]')
                        ? item
                        : item.querySelector('input[type="radio"]') || item;
                    clickTarget.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
                    clickTarget.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
                    clickTarget.dispatchEvent(new MouseEvent('click', { bubbles: true }));
                    if (typeof clickTarget.click === 'function') clickTarget.click();
                    const input = item.matches('input[type="radio"]')
                      ? item
                      : item.querySelector('input[type="radio"]') || item.closest('label')?.querySelector('input[type="radio"]');
                    if (input && !input.checked) {
                      input.checked = true;
                      input.dispatchEvent(new Event('input', { bubbles: true }));
                      input.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                    return true;
                  }
                  return false;
                }
                """,
                ai_option,
            )
        )
    except Exception as exc:
        log_debug_exception("ai-option-force-select", exc)
        return False


def handle_publish_modal(page, ai_generated: bool) -> bool:
    """Handle Fanqie publish settings modal if it appears."""
    modal = None
    for selector in PUBLISH_MODAL_SELECTORS:
        candidate = page.locator(selector).first
        try:
            if candidate.count() > 0 and candidate.is_visible(timeout=800):
                modal = candidate
                break
        except Exception as exc:
            log_debug_exception(f"publish-modal:probe:{selector}", exc)
            continue
    if modal is None:
        return False

    log_phase_once(
        "publish_modal_visible",
        "Publish modal visible (phase 1). waiting for interactive controls",
    )

    ai_option = "是" if ai_generated else "否"
    logger.info("Publish modal detected. Selecting AI option '{}'", ai_option)
    option_candidates = [
        f'[role="radio"]:has-text("{ai_option}")',
        f".arco-radio:has-text('{ai_option}')",
        f".byte-radio-wrapper:has-text('{ai_option}')",
        f"label:has-text('{ai_option}')",
    ]

    ai_ready = False
    for selector in option_candidates:
        if _is_locator_actionable(modal.locator(selector).first):
            ai_ready = True
            break
    confirm_ready = False
    for selector in PUBLISH_CONFIRM_SELECTORS:
        if _is_locator_actionable(modal.locator(selector).first):
            confirm_ready = True
            break
    if ai_ready and confirm_ready:
        log_phase_once(
            "publish_modal_interactive",
            "Publish modal interactive (phase 2). selecting AI + confirm",
        )
    else:
        logger.debug(
            "Publish modal visible but not fully interactive yet. ai_ready={} confirm_ready={}",
            ai_ready,
            confirm_ready,
        )

    ai_clicked = False
    for selector in option_candidates:
        option = modal.locator(selector).first
        try:
            if option.count() > 0 and option.is_visible(timeout=600):
                if not safe_click(page, option, f"ai-option:{selector}", timeout_ms=1200):
                    continue
                page.wait_for_timeout(250)
                ai_clicked = True
                logger.info("Clicked AI option via selector '{}'", selector)
                break
        except Exception as exc:
            log_debug_exception(f"publish-modal:ai-option:{selector}", exc)
            continue

    if not ai_clicked:
        ai_clicked = force_select_ai_option(modal, ai_option)
        if ai_clicked:
            logger.info("Clicked AI option via modal.evaluate fallback")

    if not ai_clicked or not is_ai_option_selected(modal, ai_option):
        if is_publish_success_state(page):
            return True
        logger.warning(
            "AI option '{}' not selected in publish modal yet; will retry.",
            ai_option,
        )
        return False

    confirm_found = False
    for selector in PUBLISH_CONFIRM_SELECTORS:
        confirm = modal.locator(selector).first
        try:
            if confirm.count() > 0 and confirm.is_visible(timeout=600):
                confirm_found = True
                if confirm.get_attribute("disabled") is not None:
                    continue
                if not safe_click(page, confirm, f"publish-confirm:{selector}", timeout_ms=2000):
                    continue
                logger.info("Clicked publish-confirm selector '{}'", selector)
                try:
                    page.wait_for_timeout(600)
                except Exception as exc:
                    if "Target page, context or browser has been closed" in str(exc):
                        return True
                    raise
                return True
        except Exception as exc:
            log_debug_exception(f"publish-modal:confirm:{selector}", exc)
            continue

    if is_publish_success_state(page):
        return True

    if confirm_found:
        logger.info("Publish confirm button is present but not clickable yet; retrying.")
    else:
        logger.warning("Publish modal confirm button not found; modal may be transient.")
    return False


def save_debug_artifacts(page, log_dir: Path) -> tuple[Path, Path]:
    """Save screenshot and page HTML for selector debugging."""
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    screenshot_path = log_dir / f"fanqie-error-{timestamp}.png"
    html_path = log_dir / f"fanqie-error-{timestamp}.html"
    page.screenshot(path=str(screenshot_path), full_page=True)
    html_path.write_text(page.content(), encoding="utf-8")
    return screenshot_path, html_path


def run_publish(
    payload: ChapterPayload,
    work_url: str,
    profile_dir: Path,
    headless: bool,
    publish: bool,
    auto_next_step: bool,
    ai_generated: bool,
    editor_wait_seconds: int,
    publish_wait_seconds: int,
    hard_timeout_seconds: int,
    manual_wait_seconds: int,
    log_dir: Path,
) -> None:
    """Open browser, wait for login/editor, fill fields, and optionally publish."""
    _PHASE_LOGGED_KEYS.clear()
    sync_playwright = _load_playwright()
    profile_dir.mkdir(parents=True, exist_ok=True)
    logger.info(
        "Run publish start. work_url='{}' publish={} headless={} profile_dir='{}'",
        work_url,
        publish,
        headless,
        profile_dir,
    )
    run_started_at = time.time()

    def remaining_seconds(stage: str) -> int:
        if hard_timeout_seconds <= 0:
            return 10**9
        elapsed = time.time() - run_started_at
        left = int(hard_timeout_seconds - elapsed)
        if left <= 0:
            raise RuntimeError(f"Hard timeout reached at stage: {stage}")
        return left

    work_url = normalize_newchapter_url(work_url)
    logger.info("Resolved work_url='{}'", work_url)

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=headless,
            args=["--start-maximized"],
            viewport={"width": 1440, "height": 900},
        )
        page = context.pages[0] if context.pages else context.new_page()

        try:
            page.goto(work_url, wait_until="domcontentloaded")
            logger.info("Opened page url='{}'", page.url)
            handle_blocking_overlays(page)
            editor = wait_for_editor(
                page,
                timeout_seconds=min(editor_wait_seconds, remaining_seconds("wait_for_editor")),
            )
            if not editor:
                raise RuntimeError(
                    "Editor fields not detected. Login manually and ensure the URL is "
                    "a chapter edit page, then rerun."
                )
            handle_blocking_overlays(page)

            chapter_number, chapter_name = split_chapter_title(payload.title)
            logger.info(
                "Parsed title. raw='{}' chapter_number='{}' chapter_name='{}'",
                payload.title,
                chapter_number,
                chapter_name,
            )
            refill_editor_fields(
                page,
                chapter_number,
                chapter_name,
                payload.body,
                timeout_seconds=min(20, remaining_seconds("initial_fill")),
            )
            print("Filled chapter title and body.")
            logger.info("Filled body chars={}", len(payload.body))
            logger.debug("Editor snapshot after fill: {}", snapshot_editor_state(page))

            if publish:
                if click_save_draft_once(
                    page,
                    wait_seconds=min(8, max(2, remaining_seconds("click_save_draft_once"))),
                ):
                    print("Saved draft once.")
                    for round_idx in range(6):
                        after_save_snapshot = snapshot_editor_state(page)
                        logger.debug(
                            "Editor snapshot after draft save round {}: {}",
                            round_idx + 1,
                            after_save_snapshot,
                        )
                        needs_refill = should_refill_after_draft_save(
                            after_save_snapshot, chapter_number, chapter_name, payload.body
                        )
                        if not needs_refill:
                            page.wait_for_timeout(1200)
                            stable_snapshot = snapshot_editor_state(page)
                            logger.debug(
                                "Editor stability snapshot after round {}: {}",
                                round_idx + 1,
                                stable_snapshot,
                            )
                            needs_refill = should_refill_after_draft_save(
                                stable_snapshot, chapter_number, chapter_name, payload.body
                            )
                        if not needs_refill:
                            break
                        logger.warning(
                            "Editor content reset/unstable after draft-save (round {}); refilling fields",
                            round_idx + 1,
                        )
                        refill_editor_fields(
                            page,
                            chapter_number,
                            chapter_name,
                            payload.body,
                            timeout_seconds=min(20, remaining_seconds("wait_for_editor_after_save")),
                        )
                    else:
                        raise RuntimeError("Editor kept resetting after draft-save; aborting publish.")
                    logger.debug(
                        "Editor snapshot before publish actions: {}",
                        snapshot_editor_state(page),
                    )

                wait_for_next_step_enabled(
                    page,
                    timeout_seconds=min(25, max(3, remaining_seconds("wait_for_next_step_enabled"))),
                )
                remaining_seconds("click_next_step")
                for next_attempt in range(3):
                    if click_next_step(page):
                        print("Clicked next step.")
                    after_next_snapshot = snapshot_editor_state(page)
                    logger.debug(
                        "Editor snapshot after next-step attempt {}: {}",
                        next_attempt + 1,
                        after_next_snapshot,
                    )
                    if is_publish_stage_ready(page):
                        logger.info("Publish stage detected after next-step attempt {}", next_attempt + 1)
                        break
                    if not should_refill_after_draft_save(
                        after_next_snapshot, chapter_number, chapter_name, payload.body
                    ):
                        break
                    logger.warning(
                        "Editor reset after next-step attempt {}; refilling and retrying",
                        next_attempt + 1,
                    )
                    refill_editor_fields(
                        page,
                        chapter_number,
                        chapter_name,
                        payload.body,
                        timeout_seconds=min(20, remaining_seconds("refill_after_next_step")),
                    )
                click_publish(
                    page,
                    timeout_seconds=min(publish_wait_seconds, remaining_seconds("click_publish")),
                    ai_generated=ai_generated,
                )
                print("Publish action completed and success confirmation detected.")
                logger.info("Publish branch completed")
                return

            if auto_next_step:
                if click_next_step(page):
                    print("Clicked next step.")
                else:
                    print("Next step button is not enabled yet. Please click it manually.")

            if headless:
                print("Headless mode + --publish=false: close now because manual review is impossible.")
                return

            wait_for_manual_review_exit(manual_wait_seconds)
        except Exception as exc:
            logger.exception("Publish flow failed: {}", exc)
            try:
                screenshot_path, html_path = save_debug_artifacts(page, log_dir=log_dir)
                logger.error(
                    "Saved debug artifacts screenshot='{}' html='{}'",
                    screenshot_path,
                    html_path,
                )
            except Exception as artifact_error:
                logger.error("Failed saving debug artifacts: {}", artifact_error)
                raise RuntimeError(
                    f"{exc} (Also failed to save debug artifacts: {artifact_error})"
                ) from exc
            raise RuntimeError(
                f"{exc} Debug artifacts: {screenshot_path} and {html_path}"
            ) from exc
        finally:
            try:
                context.close()
            except Exception as exc:
                log_debug_exception("context-close", exc)
                pass


def preview_payload(payload: ChapterPayload) -> None:
    """Print transformed content preview for dry-run."""
    body_preview = payload.body[:500]
    print(f"Title: {payload.title}")
    print(f"Body length: {len(payload.body)} chars")
    print("Body preview:")
    print("-" * 40)
    print(body_preview)
    if len(payload.body) > len(body_preview):
        print("...")
    print("-" * 40)


def wait_for_manual_review_exit(manual_wait_seconds: int) -> None:
    """Wait for manual confirmation without hanging in non-interactive environments."""
    print("Please review the editor and click Publish manually.")
    if not sys.stdin.isatty():
        logger.warning("STDIN is not a TTY. Skip manual wait to avoid hanging.")
        print("Non-interactive stdin detected. Closing now.")
        return

    if manual_wait_seconds > 0:
        logger.info("Waiting for manual confirmation up to {}s", manual_wait_seconds)
        print(f"Press Enter to close now, or wait {manual_wait_seconds}s to auto-close.")
        deadline = time.time() + manual_wait_seconds
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                logger.info("Manual wait timed out after {}s", manual_wait_seconds)
                print(f"Timed out after {manual_wait_seconds}s, closing now.")
                return
            try:
                ready, _, _ = select.select([sys.stdin], [], [], min(1.0, remaining))
            except Exception as exc:
                log_debug_exception("manual-wait:select", exc)
                time.sleep(min(1.0, remaining))
                continue
            if ready:
                try:
                    sys.stdin.readline()
                except Exception as exc:
                    log_debug_exception("manual-wait:readline", exc)
                logger.info("Manual confirmation received via stdin")
                return

    print("Press Enter here after publishing to close browser.")
    try:
        input()
        logger.info("Manual confirmation received via blocking input")
    except EOFError:
        logger.warning("EOF on stdin while waiting for manual confirmation; closing.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Publish one Markdown document as a single Fanqie chapter."
    )
    parser.add_argument("--md-path", required=True, help="Path to source Markdown file")
    parser.add_argument("--work-url", help="Fanqie chapter edit URL for your target work")
    parser.add_argument(
        "--profile-dir",
        default=str(DEFAULT_PROFILE_DIR),
        help="Persistent browser profile path for session reuse",
    )
    parser.add_argument(
        "--headless",
        type=parse_bool,
        nargs="?",
        const=True,
        default=False,
        help="Run browser in headless mode (default: false)",
    )
    parser.add_argument(
        "--publish",
        type=parse_bool,
        nargs="?",
        const=True,
        default=False,
        help="Click publish automatically (default: false)",
    )
    parser.add_argument(
        "--auto-next-step",
        type=parse_bool,
        nargs="?",
        const=True,
        default=True,
        help="Click the top-right next-step button after filling content (default: true)",
    )
    parser.add_argument(
        "--ai-generated",
        type=parse_bool,
        nargs="?",
        const=True,
        default=True,
        help="Value to select in publish modal '是否使用AI' (default: true => 选是)",
    )
    parser.add_argument(
        "--dry-run",
        type=parse_bool,
        nargs="?",
        const=True,
        default=False,
        help="Only parse markdown and print preview (default: false)",
    )
    parser.add_argument(
        "--editor-wait-seconds",
        type=int,
        default=300,
        help="Seconds to wait for editor fields (for first-time login)",
    )
    parser.add_argument(
        "--publish-wait-seconds",
        type=int,
        default=25,
        help="Seconds to wait for publish success message",
    )
    parser.add_argument(
        "--hard-timeout-seconds",
        type=int,
        default=420,
        help="Hard timeout for whole browser flow; on timeout browser is auto-closed",
    )
    parser.add_argument(
        "--manual-wait-seconds",
        type=int,
        default=0,
        help="Only for --publish=false: wait up to N seconds for manual Enter; 0 means unlimited in TTY",
    )
    parser.add_argument(
        "--log-dir",
        default=str(DEFAULT_LOG_DIR),
        help="Path for debug screenshots/html on failure",
    )
    parser.add_argument(
        "--trace-log-file",
        default="",
        help="Optional path for detailed loguru trace log file",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    log_dir = Path(args.log_dir).expanduser().resolve()
    trace_log = configure_logging(log_dir, args.trace_log_file or None)
    logger.info("Trace log file: {}", trace_log)
    if args.manual_wait_seconds < 0:
        parser.error("--manual-wait-seconds must be >= 0")
    logger.info(
        "CLI args: md_path='{}' work_url='{}' publish={} headless={} ai_generated={} hard_timeout_seconds={} manual_wait_seconds={}",
        args.md_path,
        args.work_url,
        args.publish,
        args.headless,
        args.ai_generated,
        args.hard_timeout_seconds,
        args.manual_wait_seconds,
    )

    md_path = Path(args.md_path).expanduser().resolve()
    if not md_path.exists() or not md_path.is_file():
        parser.error(f"Markdown file does not exist: {md_path}")

    if not args.dry_run and not args.work_url:
        parser.error("--work-url is required unless --dry-run=true")

    payload = build_payload(md_path)
    logger.info("Payload ready. title='{}' body_chars={}", payload.title, len(payload.body))
    if args.dry_run:
        preview_payload(payload)
        return 0

    try:
        run_publish(
            payload=payload,
            work_url=args.work_url,
            profile_dir=Path(args.profile_dir).expanduser().resolve(),
            headless=args.headless,
            publish=args.publish,
            auto_next_step=args.auto_next_step,
            ai_generated=args.ai_generated,
            editor_wait_seconds=args.editor_wait_seconds,
            publish_wait_seconds=args.publish_wait_seconds,
            hard_timeout_seconds=args.hard_timeout_seconds,
            manual_wait_seconds=args.manual_wait_seconds,
            log_dir=log_dir,
        )
    except Exception as exc:
        print(f"Publish failed: {exc}", file=sys.stderr)
        print(
            "Tip: run with --dry-run=true first, then tune selectors in "
            "nanobot/skills/fanqie-publisher/references/fanqie_selectors.md if needed.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
