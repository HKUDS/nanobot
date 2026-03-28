# Testing Strategy & Coverage Review — Nanobot Agent Framework

**Date:** 2026-03-18
**Reviewer:** Test Automation Engineer (Claude Sonnet 4.6)

---

## Executive Summary

The nanobot test suite is **large and structurally sound** (1,738 collected tests, ~31,000 lines across 113 test files), with good coverage of the core agent loop, memory subsystem, and tool correctness. The suite includes contract tests, golden scenario tests, and end-to-end workflow tests. However, several **critical security paths are untested**, performance regression guards are **partially missing**, and a handful of test patterns introduce fragility.

---

## 1. Test Coverage Overview

### What Is Well-Covered

| Area | Assessment |
|---|---|
| `AgentLoop` core orchestration | Strong — `test_agent_loop.py` (900 lines) covers single-turn, multi-turn, tool failure, max iterations, compression, planning, consecutive errors, tool suppression, role switching |
| Shell `_guard_command` | Strong — 40+ parametrized cases in `test_shell_safety.py`, including bypass attempts (hex-escape, base64-pipe, curl-pipe, backtick, `$()`) |
| Filesystem tools | Good — `test_filesystem_tools.py` covers read/write/edit/list, path traversal, missing files, sensitive path denylist (SEC-M5) |
| Memory subsystem | Strong — contract tests, hybrid retrieval, consolidation offsets, mem0 adapter branches, event persistence |
| Contract tests | Good — `tests/contract/` covers `ToolResult`, `LLMResponse`, `LLMProvider`, channel `BaseChannel`, `MemoryStore` |
| Golden scenarios | Present — `tests/golden/test_golden_scenarios.py` (613 lines) freezes orchestration behavior |
| Channel retry / health tracking | Covered in `test_channel_retry.py`, `test_health_tracking.py` |
| Coordinator / multi-agent routing | Covered in `test_coordinator.py` (560 lines) |
| Concurrency (parallel delegation) | Covered in `test_parallel_delegation.py` |

### What Is Covered but Thin

| Area | Issue |
|---|---|
| `ContextBuilder._load_bootstrap_files` | Only `test_context_prompt_cache.py` (64 lines); stability test exists, but no caching/memoization verification |
| Telegram ACL enforcement | `test_config_errors_channel_wave2.py` tests `is_allowed()` in isolation, but the ordering of ACL vs. media download in `_on_message` is not tested |
| Web API upload paths | `test_web_api.py` tests `_strip_attachments` but not `_extract_binary_files` with malicious filenames |

---

## 2. Security Test Gaps

### SEC-01 — Shell Guard Multi-Line Bypass

**Severity: Medium**

**Finding:** Multi-line command bypass (`"ls\nrm -rf /"`) is tested and confirmed blocked by existing deny patterns (the `\brm\s+-[rf]{1,2}\b` pattern matches across newlines). **This is not an untested gap** — the deny patterns operate on the full lowercased string including newline characters.

However, a subtler bypass is confirmed to pass the guard:

```python
# These pass _guard_command in denylist mode:
"echo x | bash -s"        # piping via bash -s
"echo x | sh -c id"       # piping via sh -c
"python3 -c 'import subprocess; subprocess.run([\"rm\", \"-rf\", \"/\"])'  # subprocess bypass
```

The `echo x | bash -s` case is a real bypass: it pipes arbitrary content into a shell interpreter. The deny list catches `curl ... | bash` and `wget ... | bash`, but not the generic `| bash -s` form or `| sh -c`.

**Recommended test:**
```python
@pytest.mark.parametrize("cmd", [
    "echo 'rm -rf /' | bash -s",
    "echo 'id' | sh -c 'bash'",
    "python3 -c 'import subprocess; subprocess.run([\"id\"])'",
])
def test_blocks_interpreter_piping_bypass(self, tool, cmd):
    assert tool._guard_command(cmd, "/tmp") is not None
```

### SEC-02 — SSRF via WebFetchTool (No Private IP Blocking)

**Severity: Critical**

**Finding:** `_validate_url()` in `nanobot/agent/tools/web.py` accepts any `http`/`https` URL with a valid netloc. It does **not** block private IP ranges. All of the following pass validation:

```
http://127.0.0.1/admin   → valid=True
http://localhost/api     → valid=True
http://10.0.0.1/internal → valid=True
http://192.168.1.1/router → valid=True
http://169.254.169.254/metadata/v1 → valid=True  (AWS metadata endpoint)
http://[::1]/ipv6-loopback → valid=True
```

There are **zero tests** for SSRF protection in `test_web_tools.py`. The test file tests invalid schemes (`ftp://`) and error handling, but nothing for private/loopback/link-local addresses.

**Recommended tests:**
```python
@pytest.mark.parametrize("url,desc", [
    ("http://127.0.0.1/admin", "loopback IPv4"),
    ("http://localhost/api", "loopback hostname"),
    ("http://10.0.0.1/internal", "private RFC1918"),
    ("http://192.168.1.1/router", "private RFC1918"),
    ("http://172.16.0.1/", "private RFC1918 class B"),
    ("http://169.254.169.254/metadata/", "AWS metadata IMDS"),
    ("http://[::1]/", "loopback IPv6"),
])
def test_validate_url_blocks_private_ips(url: str, desc: str) -> None:
    """_validate_url must reject private/loopback addresses (SSRF prevention)."""
    valid, err = _validate_url(url)
    assert not valid, f"Expected {url!r} ({desc}) to be rejected but it was accepted"
```

> Note: This also implies a production code fix is needed: `_validate_url` must be hardened to resolve the hostname and check against private ranges before allowing a fetch.

### SEC-07 — Web Upload Filename Path Traversal

**Severity: High**

**Finding:** In `nanobot/web/routes.py`, `_strip_attachments()` uses the filename from the `<attachment name="...">` tag directly:

```python
dest = uploads_dir / fname  # fname comes from the regex match — no sanitization
```

There is **no call to `Path(fname).name`** or any path-separator stripping before `uploads_dir / fname`. A crafted attachment name such as `../../etc/cron.d/evil` would write outside `uploads_dir`.

By contrast, `_extract_binary_files()` (the multimodal path) does call `Path(orig).name`, but `_strip_attachments()` (the text attachment path) does not.

The existing tests in `test_web_api.py` (`TestStripAttachments`) test normal filenames (`data.csv`, `report.xlsx`, `dup.txt`) but **do not test path-traversal filenames**.

**Recommended test:**
```python
@pytest.mark.parametrize("malicious_name", [
    "../../etc/cron.d/evil",
    "../secrets.txt",
    "/absolute/path/evil.sh",
    "subdir/evil.txt",
])
def test_strip_attachments_blocks_traversal(self, tmp_path, malicious_name):
    from nanobot.web.routes import _strip_attachments
    text = f'<attachment name="{malicious_name}">data</attachment>'
    _strip_attachments(text, tmp_path)
    # Verify nothing was written outside tmp_path
    written = list(tmp_path.rglob("*"))
    for f in written:
        assert str(f).startswith(str(tmp_path)), f"File written outside uploads_dir: {f}"
```

### SEC-13 — Telegram ACL Check After Media Download

**Severity: High**

**Finding:** In `nanobot/channels/telegram.py`, `_on_message()` downloads media files (calling `bot.get_file()` and `file.download_to_drive()`) **before** forwarding to `_handle_message()`, which performs the ACL check via `BaseChannel.is_allowed()`.

This means an unauthorized user can cause the bot to download arbitrary media files to the local filesystem (into `~/.nanobot/media/`) before the permission check rejects their message. The ACL check only prevents the message from being forwarded to the agent — it does not prevent the download.

**Zero tests** verify this ordering or test that media is NOT downloaded for unauthorized users.

**Recommended test:**
```python
async def test_acl_prevents_media_download_for_blocked_users(monkeypatch):
    """Unauthorized users must not trigger media download (SEC-13)."""
    ch = _channel()
    ch.config.allow_from = ["999"]  # Only user 999 is allowed

    download_called = False

    class _File:
        async def download_to_drive(self, path: str):
            nonlocal download_called
            download_called = True

    bot = SimpleNamespace(get_file=AsyncMock(return_value=_File()))
    ch._app = SimpleNamespace(bot=bot)

    user = SimpleNamespace(id=1, username="u", first_name="U")  # NOT in allow_from
    photo_stub = SimpleNamespace(file_id="abc123")
    msg = SimpleNamespace(
        chat_id=42, text="", caption="", photo=[photo_stub],
        voice=None, audio=None, document=None,
        message_id=9, chat=SimpleNamespace(type="private"),
    )
    upd = SimpleNamespace(message=msg, effective_user=user)

    await ch._on_message(upd, None)

    assert not download_called, "Media downloaded for unauthorized user (SEC-13)"
```

---

## 3. Performance Test Gaps

### P-01 + P-02 — Repeated `events.jsonl` Reads Not Guarded

**Severity: Medium**

**Finding:** `MemoryStore.read_events()` reads `events.jsonl` from disk on every call. Within a single `retrieve()` operation, `read_events()` is called **multiple times** (lines 2626, 2884, 3221 in `store.py`) for BM25 retrieval, supplementary graph-augmented BM25, topic-based fallback, etc. There is **no in-turn caching** of the events list.

Similarly, `ContextBuilder.build_system_prompt()` calls `memory.get_memory_context()` which triggers multiple `read_events()` calls, plus a separate `feedback_summary(events_file)` call that also reads the file.

**No test** verifies that `events.jsonl` is read a bounded (or minimal) number of times per agent turn.

**Recommended test:**
```python
async def test_retrieve_reads_events_jsonl_minimal_times(tmp_path):
    """events.jsonl should not be read more than N times per retrieve() call."""
    store = MemoryStore(tmp_path, embedding_provider="hash")
    store.append_events([{"id": "e1", "type": "fact", "summary": "test", ...}])

    read_count = 0
    original_read = store.persistence.read_jsonl

    def counting_read(path):
        nonlocal read_count
        if path == store.events_file:
            read_count += 1
        return original_read(path)

    store.persistence.read_jsonl = counting_read
    store.retrieve("test query", top_k=5)

    assert read_count <= 2, f"read_events called {read_count} times in a single retrieve()"
```

### P-03 — Bootstrap File Reads Not Cached Per Turn

**Severity: Low**

**Finding:** `ContextBuilder._load_bootstrap_files()` calls `file_path.read_text()` for each of the 5 bootstrap files on every call to `build_system_prompt()`. Since `build_messages()` calls `build_system_prompt()` at the start of every LLM call within a turn (not just once per turn), these files may be re-read during multi-iteration turns.

`test_context_prompt_cache.py` tests that the **content** of the system prompt is stable (same output for same inputs) but does not verify that file I/O is actually cached or minimized.

**Recommended test:**
```python
def test_bootstrap_files_not_re_read_on_repeated_calls(tmp_path, monkeypatch):
    """_load_bootstrap_files should use caching — files not re-read on every call."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "AGENTS.md").write_text("# Agents")

    read_count = 0
    original_read = Path.read_text

    def counting_read(self, *args, **kwargs):
        nonlocal read_count
        if self.name in ("AGENTS.md", "SOUL.md", "USER.md", "TOOLS.md", "IDENTITY.md"):
            read_count += 1
        return original_read(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counting_read)

    builder = ContextBuilder(workspace)
    builder.build_system_prompt()
    builder.build_system_prompt()  # Second call — files should be cached

    # With caching, each file read once; without caching, doubled
    assert read_count <= 5, f"Bootstrap files re-read without caching: {read_count} reads"
```

---

## 4. Test Quality Analysis

### Test Pyramid Ratio

- **Unit tests:** ~85% of test files — individual functions, classes, and tools in isolation
- **Integration tests:** ~12% — `test_agent_loop.py`, `test_workflow_e2e.py`, `test_delegation_dispatcher.py`
- **Contract tests:** ~3% — `tests/contract/` (4 files, 721 lines)
- **Golden/regression tests:** ~0.5% — `tests/golden/test_golden_scenarios.py`
- **E2E tests:** `test_workflow_e2e.py`, `test_extraction_e2e.py`

The ratio is **top-heavy with unit tests**. This is appropriate for a framework, but the golden scenario coverage (~613 lines) could be deeper given the complexity of the orchestration.

### Assertion Quality

Tests generally use **behavioral assertions** (checking `result.success`, `result.output`, session state) rather than testing implementation details. This is positive. However:

- Several tests in the "wave" files (e.g., `test_coverage_push_wave6.py`, `test_pass2_smoke.py`) use vague `assert out is not None` checks without verifying meaningful outputs — these test execution paths but not correctness.
- Delegation tests sometimes only check that a result was returned, not the content.

### Test Isolation

Test isolation is **good overall**:
- `tmp_path` fixtures are used consistently for file operations.
- `monkeypatch` is used for httpx, Telegram API, and external services.
- `conftest.py` disables mem0 (HuggingFace) globally to prevent slow imports and FPEs.
- `ScriptedProvider` is a well-designed deterministic LLM mock, reused across test files.

**Issue:** `ScriptedProvider` is **duplicated** in at least 4 files (`test_agent_loop.py`, `test_workflow_e2e.py`, `tests/golden/test_golden_scenarios.py`, `test_coverage_push_wave6.py`). It should be in `conftest.py` or a shared fixture module to prevent drift.

### Flaky Test Indicators

Several tests use **wall-clock `asyncio.sleep()`** for timing-sensitive assertions:

```python
# test_mission_manager.py, test_parallel_delegation.py, test_consolidate_offset.py
await asyncio.sleep(0.1)   # wait for background task
await asyncio.sleep(0.2)   # wait for concurrent dispatch
```

These are latent flakiness sources on CI systems under load. A total of **~30 tests** use `asyncio.sleep` for synchronization. The preferred pattern is to use events, queues, or `asyncio.Event` to gate progress rather than sleeping.

---

## 5. Missing Contract Tests

### ToolResult Metadata Contract

**Severity: Low**

The existing `TestToolResultContract` does not test that `ToolResult.fail(msg, error_type="X")` stores the error_type in `metadata["error_type"]` — this is tested implicitly in tool-specific tests but not in the contract itself.

### BaseChannel ACL Contract

**Severity: Medium**

There is no contract test verifying that `BaseChannel._handle_message()` silently drops (not raises) messages from unauthorized senders. The ACL-is-ignored-when-allow_from-is-empty behavior is not tested at the contract level.

**Recommended test:**
```python
class TestBaseChannelACLContract:
    async def test_drops_unauthorized_sender_silently(self):
        """_handle_message must drop unauthorized messages without raising."""
        cfg = SimpleNamespace(allow_from=["allowed-user"])
        bus = MessageBus()
        ch = ConcreteChannel(cfg, bus)
        # Should complete without raising, and publish nothing
        await ch._handle_message("unauthorized-user", "chat1", "hello")
        # Bus queue should be empty
        assert bus.inbound_queue.empty()

    async def test_empty_allow_list_allows_all(self):
        """When allow_from is empty, any sender is permitted."""
        cfg = SimpleNamespace(allow_from=[])
        ...
```

### Tool.check_available() Contract

**Severity: Low**

Not all tools implementing `check_available()` are contract-tested. The `WebSearchTool.check_available()` (which checks for API key) is tested indirectly but not as a formal contract.

---

## 6. Edge Cases Not Tested

### AgentLoop Concurrency

No test exercises **two concurrent `_process_message()` calls** on the same session (same `chat_id`). The session manager uses file-backed JSONL with no locking; concurrent writes could corrupt session state.

### Memory Store Concurrent Writes

`test_scratchpad.py` tests concurrent scratchpad writes. But **concurrent calls to `store.append_events()`** from two coroutines are not tested. The `events.jsonl` file uses append mode (`mode="a"`), but JSONL line integrity under concurrent asyncio writes is assumed, not verified.

### WebFetchTool Cache Race

The `_url_cache` dict is a module-level mutable dictionary. Under concurrent `WebFetchTool.execute()` calls for the same URL, there could be a TOCTOU race between the cache check and the cache write. No test verifies thread/coroutine safety of the URL cache.

### Shell Timeout with Kill Failure

`test_shell_safety.py` tests that a timeout produces a failed result, but does not test the `asyncio.wait_for(process.wait(), timeout=5.0)` inner timeout (the "kill was slow" branch on lines 154-157 of `shell.py`).

---

## 7. Recommendations Summary

| Priority | Finding | Recommended Action |
|---|---|---|
| **Critical** | SSRF — private IPs not blocked in `_validate_url` | Add SSRF protection to `_validate_url` and add parametrized tests for all private ranges |
| **High** | SEC-07 — path traversal in `_strip_attachments` | Sanitize `fname` using `Path(fname).name`; add traversal tests |
| **High** | SEC-13 — Telegram downloads media before ACL check | Reorder `_on_message` to call `is_allowed` before any `get_file`/`download_to_drive`; add ordering test |
| **Medium** | SEC-01 shell bypass — `echo x \| bash -s` passes guard | Add deny pattern for `\|\s*(bash|sh|zsh)\b` (not just `curl/wget`-prefixed) and add test |
| **Medium** | P-01/P-02 — no test bounding `events.jsonl` reads per turn | Add call-count assertion test for `retrieve()` |
| **Medium** | `ScriptedProvider` duplicated in 4+ files | Consolidate into `conftest.py` fixture |
| **Medium** | ~30 tests use `asyncio.sleep()` for timing | Refactor to use `asyncio.Event` or callback gates where possible |
| **Medium** | BaseChannel ACL contract not tested | Add contract test for unauthorized-sender drop behavior |
| **Low** | P-03 — bootstrap file reads not verified as cached | Add read-count test for `_load_bootstrap_files` |
| **Low** | Concurrent `_process_message` on same session untested | Add concurrency test to detect session corruption |
| **Low** | "Wave" test files use weak `assert result is not None` assertions | Strengthen assertions to verify meaningful content |

---

## 8. Test Infrastructure Observations

- **`asyncio_mode = "auto"`** is configured in `pytest.ini`/`pyproject.toml` — all async tests run correctly without per-test `@pytest.mark.asyncio` decorators. Good.
- **85% coverage gate** in `make test-cov` is enforced in CI. However, line coverage does not capture security-critical execution ordering (the ACL-before-download bug passes line coverage).
- **`make memory-eval`** runs a separate deterministic memory benchmark against a case file with baseline comparisons — this is an excellent practice. Other subsystems lack equivalent regression benchmarks.
- **No performance benchmarks** exist (`pytest-benchmark` or similar is not in use). All performance claims are validated only through functional behavior tests.
