# Telegram Healthcheck Installation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Safely apply the Telegram polling healthcheck patch to the current nanobot checkout, verify it with tests, and confirm the repo remains buildable.

**Architecture:** The patch adds a small JSON-backed Telegram polling liveness tracker, wires it into the Telegram channel polling request path, and exposes a Docker `HEALTHCHECK` entrypoint that reports healthy only when Telegram polling is fresh. Installation should use TDD for the newly introduced behavior, then apply the minimal production changes, then verify targeted tests and patch application state.

**Tech Stack:** Python 3.11+, pytest, uv, Dockerfile/docker-compose, python-telegram-bot.

---

### Task 1: Add failing tests for the new healthcheck modules

**Files:**
- Create: `tests/channels/test_telegram_healthcheck.py`
- Test: `tests/channels/test_telegram_healthcheck.py`

**Step 1: Write the failing test**

Add tests for:
- `TelegramHealthState.mark_ok()` writing a JSON state file with `status == "ok"` and `last_ok`
- `run_healthcheck()` returning success when Telegram is disabled in config
- `run_healthcheck()` returning failure when Telegram is enabled but state file is missing
- `TelegramPollingHealthRequest.do_request()` marking success/error around delegated requests

**Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest -q tests/channels/test_telegram_healthcheck.py`
Expected: FAIL because the healthcheck modules do not exist yet.

**Step 3: Write minimal implementation**

Use the patch contents to add:
- `nanobot/telegram_polling_health.py`
- `nanobot/telegram_healthcheck.py`

**Step 4: Run test to verify it passes**

Run: `uv run --extra dev pytest -q tests/channels/test_telegram_healthcheck.py`
Expected: PASS.

**Step 5: Commit**

```bash
git add tests/channels/test_telegram_healthcheck.py nanobot/telegram_polling_health.py nanobot/telegram_healthcheck.py
git commit -m "test: cover telegram healthcheck modules"
```

### Task 2: Add failing integration tests for Telegram channel wiring

**Files:**
- Modify: `tests/channels/test_telegram_channel.py`
- Modify: `nanobot/channels/telegram.py`
- Test: `tests/channels/test_telegram_channel.py`

**Step 1: Write the failing test**

Add tests that verify:
- `TelegramChannel` initializes `_health_state`
- `_on_polling_error()` calls `mark_error()`
- startup marks starting/ok around polling setup if that path is unit-testable without real network I/O

**Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest -q tests/channels/test_telegram_channel.py -k health`
Expected: FAIL because the channel is not wired to the health state yet.

**Step 3: Write minimal implementation**

Apply the minimal `nanobot/channels/telegram.py` changes from the patch.

**Step 4: Run test to verify it passes**

Run: `uv run --extra dev pytest -q tests/channels/test_telegram_channel.py -k health`
Expected: PASS.

**Step 5: Commit**

```bash
git add tests/channels/test_telegram_channel.py nanobot/channels/telegram.py
git commit -m "feat: track telegram polling health"
```

### Task 3: Apply container healthcheck changes and verify config/build files

**Files:**
- Modify: `Dockerfile`
- Modify: `docker-compose.yml`
- Test: `Dockerfile`
- Test: `docker-compose.yml`

**Step 1: Write the failing test**

Use a lightweight assertion test or command-based check that confirms:
- `Dockerfile` contains `HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=1`
- `Dockerfile` runs `python -m nanobot.telegram_healthcheck`
- `docker-compose.yml` exports `NANOBOT_TELEGRAM_HEALTH_PATH` and `NANOBOT_TELEGRAM_HEALTH_MAX_AGE_S`

**Step 2: Run test to verify it fails**

Run: `python - <<'PY'
from pathlib import Path
text = Path('Dockerfile').read_text()
assert 'nanobot.telegram_healthcheck' in text
PY`
Expected: FAIL before the file is changed.

**Step 3: Write minimal implementation**

Apply the `Dockerfile` and `docker-compose.yml` changes from the patch.

**Step 4: Run test to verify it passes**

Run the same assertions again and expect success.

**Step 5: Commit**

```bash
git add Dockerfile docker-compose.yml
git commit -m "chore: add docker telegram healthcheck"
```

### Task 4: Full verification

**Files:**
- Test: `tests/channels/test_telegram_healthcheck.py`
- Test: `tests/channels/test_telegram_channel.py`
- Test: `Dockerfile`
- Test: `docker-compose.yml`

**Step 1: Run targeted tests**

```bash
uv run --extra dev pytest -q tests/channels/test_telegram_healthcheck.py tests/channels/test_telegram_channel.py
```

Expected: PASS.

**Step 2: Run lint-style sanity checks for changed container files**

```bash
python -m nanobot.telegram_healthcheck || true
python - <<'PY'
from pathlib import Path
assert 'HEALTHCHECK' in Path('Dockerfile').read_text()
assert 'NANOBOT_TELEGRAM_HEALTH_PATH' in Path('docker-compose.yml').read_text()
print('container file checks ok')
PY
```

Expected: module import succeeds and file assertions pass.

**Step 3: Inspect final diff**

```bash
git diff -- Dockerfile docker-compose.yml nanobot/channels/telegram.py nanobot/telegram_healthcheck.py nanobot/telegram_polling_health.py tests/channels/test_telegram_healthcheck.py tests/channels/test_telegram_channel.py
```

Expected: only the intended Telegram healthcheck changes appear.
