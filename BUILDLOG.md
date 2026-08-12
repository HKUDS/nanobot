# BUILDLOG

Source of truth for what exists in this fork (`albatrossflyon-coder/nanobot`, tracking upstream `HKUDS/nanobot`) beyond upstream's own docs.

## Tech Stack

- **Languages:** Python, TypeScript
- **Frameworks/Libraries:** FastAPI-style channel manager, React (webui), LangGraph-adjacent agent loop
- **Dev Tools:** pytest, ruff, basedpyright

---

## 2026-08-11 — Tool-call-markup-leak fix: 4 original gaps closed, 3 new gaps found by code-review

**Context:** A model finalizing with no tools offered could still emit literal `<tool_call><function=...>` text instead of a real answer, and that raw markup could reach a real user-facing channel. Confirmed live twice today via real email to Chris (`~/.nanobot/logs/gateway.log`, 14:02 and 14:27 CDT — `Response to email:...: <tool_call>` at INFO level, meaning it was never blocked; the filter that should have caught it was built but never actually committed/active in the running gateway).

**4 gaps from the prior session's `/code-review` pass — all fixed and tested this session:**
1. Dominant per-turn finalize path (`runner.py` `_run_core`, where most turns actually end) had no leak guard — only the max-iterations retry path did. Fixed: added `contains_leaked_tool_call_markup(clean)` check alongside the existing blank-content check, same pattern (fallback message, `stop_reason="leaked_tool_call_markup"`, drain injections, break).
2. Only the email channel had the egress filter; 15 other channels didn't. Fixed by centralizing instead of propagating: `ChannelManager._send_once` (the single funnel all non-streaming channel sends pass through, confirmed via `find_references`/`search_text`) now runs the check once for all 17 channels. Removed the now-redundant duplicate check from `EmailChannel.send()`.
3. Regex `<tool_call\b` missed the plural `<tool_calls>` wrapper tag. Verified live that **both** `<tool_calls>` and `</tool_calls>` failed to match (the prior session only caught the opening-tag case) — fixed to `<tool_calls?\b` / `</tool_calls?>`.
4. The blocked-leak warning log wrote the raw leaked content (potentially shell commands/session IDs) unredacted. Fixed at the source: the new centralized check in `_send_once` never logs the raw content at all (length only).

**Verification:** Full test suite 5914 passed / 44 skipped / 0 failed. `vuln-hunter scan_diff` clean except one unrelated pre-existing item (see below). New/moved tests: `tests/agent/test_runner_safety.py` (2 new — dominant-path leak rejection + clean-response negative case), `tests/channels/test_channel_manager_leak_filter.py` (3 new — centralized filter, plural-tag regression, normal-content passthrough), `nanobot/channels/email/tests/test_email_channel.py` (obsolete email-specific leak test removed, now covered at the manager level instead).

**3 new findings from a fresh `/code-review high` pass after the fix — triaged with Chris, not silently shipped-and-disclosed:**

1. **Streaming bypass (pre-existing, NOT introduced tonight, NOT fixed tonight).** The filter only runs in `_send_once`'s non-streaming branch. A leaked `<tool_call>` in a streaming response (webui/websocket) would already display live, token-by-token, before any finalize-time check runs — this gap existed before tonight's fix too (streaming had zero leak protection either way) and closing it properly needs mid-stream detection or buffering, a real design change, not a quick patch. **Status: open, tracked as a follow-up, not fixed.**
2. **MessageTool-suppression behavior for the new `leaked_tool_call_markup` stop_reason was a genuine design question, not a clear bug** (`loop.py` `_assemble_outbound`, line ~1594). `empty_final_response` always suppresses the fallback notice when `MessageTool` already sent real content this turn. `leaked_tool_call_markup` was following the general rule instead (suppress only if no new injections occurred) — a code-review report initially described this backwards (claimed the leak notice gets silently dropped when the empty one doesn't; direct code tracing showed the opposite: in the `had_injections=True` case, the leak notice was the one that got delivered, `empty_final_response` was the one still suppressed). Chris's call: always suppress, matching `empty_final_response` — real content already went out via MessageTool, so a leak on the wrap-up has nothing useful to add. **Status: fixed 2026-08-11** — `stop_reason in ("empty_final_response", "leaked_tool_call_markup")` now both suppress unconditionally. New test: `tests/tools/test_message_tool_suppress.py::test_injected_followup_with_message_tool_suppresses_leaked_markup_notice`.
3. **Regex `<function\s*=` / `TOOL_CALL:` can false-positive on legitimate prose** (e.g. an answer that explains or demonstrates the agent's own tool-call syntax). **Pre-existing** — both patterns were in `_LEAKED_TOOL_CALL_RE` before tonight; this session only touched the `<tool_call>`/`<tool_calls>` singular/plural portion. Checked `~/.nanobot/logs/gateway.log` for evidence this ever fired as a false positive in production — found none; the filter was never actually active before tonight (see Context above), so this risk hasn't manifested yet, but is real now that the filter is about to go live for real. **Status: open, not fixed tonight, worth a follow-up if it's ever observed firing on legitimate content.**

**Also caught tonight:** checked GitHub notifications before pushing and found CI already failing on this same branch from an earlier commit (`6e8e2755`) — a `basedpyright --strict` error in `runner.py` (`append`/`sorted` on a partially-unknown type). A follow-up commit (`7cd2b29f`) already fixed that one but was stuck on GitHub's `action_required` approval gate, unverified. Ran `basedpyright` locally against all files touched tonight and found a **new** instance of the same error class in my own new code (`runner.py:817`, `len(clean)` where `clean: str | None` — the `is_blank_text` guard proves it's non-empty at runtime but basedpyright doesn't narrow through that call). Fixed (`len(clean or "")`). Re-ran clean: 0 errors across all 9 touched files.

**Branch:** `fix/tool-call-loop-detection` in `C:\Repos\nanobot`. Committed (`0ac578b4`) and pushed to `fork` (`albatrossflyon-coder/nanobot`) — remote SHA independently verified via `gh api` to match local HEAD exactly. Not yet merged into `HKUDS/nanobot#5344` upstream; watch that PR for maintainer review.
