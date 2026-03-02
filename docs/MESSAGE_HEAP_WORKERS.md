# Message Heap + Background Workers for Non-Blocking Generation

## Overview

Creative generation tools (video, image, music, speech) previously blocked the
main agent or spawned full LLM subagents for offloading. This PR replaces both
approaches with **lightweight asyncio workers** and a **session-scoped message
heap** (`PendingResults`).

```
Turn 1: User says "generate a video of a cat"
  → Agent calls generate_video("a cat")
  → Tool registers result in heap, spawns asyncio worker, returns immediately
  → Agent responds: "Video generation started in the background!"

[Worker polls Veo API, saves file, calls pending.complete()]

Turn 2: User sends any message
  → build_context_block() injected into prompt:
      [COMPLETED] video generation "a cat" → /home/.../.scorpion/media/videos/video_....mp4
  → Agent calls send_message(media=[path]) to deliver the file
  → Result drained from heap (shown only once)
```

---

## Architecture

### New Files

#### `scorpion/adk/pending.py` — Message Heap

```python
class GenerationResult:   # dataclass: id, kind, prompt, status, file_paths, error, ...
class PendingResults:     # session-scoped heap
    add(session_key, kind, prompt, params) -> result_id
    complete(result_id, file_paths)
    fail(result_id, error)
    register_task(result_id, task)       # for /stop cancellation
    drain(session_key) -> list[result]   # pop completed/failed (shown once)
    get_running(session_key) -> list     # still in-flight
    build_context_block(session_key) -> str  # injected into next turn
    cancel_by_session(session_key) -> int    # /stop support
    wait_running(session_key, timeout)       # CLI blocking await
```

**Drain-on-read semantics:** `build_context_block()` internally calls `drain()`
so completed results are shown exactly once and removed from the heap.

#### `scorpion/adk/workers.py` — Direct API Workers

Four async functions that call Google APIs directly without any LLM:

| Worker | API | Output |
|--------|-----|--------|
| `worker_generate_video` | Veo 3.1 (`veo-3.1-generate-preview`) | `.mp4` |
| `worker_generate_image` | Imagen 4 / Gemini | `.png` / `.jpg` |
| `worker_generate_music` | Lyria RealTime (`lyria-realtime-exp`) | `.wav` |
| `worker_generate_speech` | Gemini TTS | `.wav` |

Each worker:
1. Calls the Google API
2. Saves output to `~/.scorpion/media/{kind}/`
3. Calls `pending.complete(result_id, [path])` or `pending.fail(result_id, error)`
4. Handles `asyncio.CancelledError` cleanly (marks as failed, re-raises)
5. Maps 503 errors to a human-friendly message (video only)

---

### Modified Files

#### `scorpion/adk/tools.py` — Tools as Launchers

All four creative tools now follow this pattern:

```python
async def generate_video(prompt, ..., tool_context):
    api_key = _get_gemini_key()

    # Non-blocking path: gateway/bus mode
    bus_active = tool_context.state.get("app:bus_active") == "true"
    if _pending_results is not None and bus_active:
        session_key = _get_session_key(tool_context)  # "channel:chat_id"
        result_id = _pending_results.add(session_key, "video", prompt, {...})
        task = asyncio.create_task(worker_generate_video(..., _pending_results))
        _pending_results.register_task(result_id, task)
        return f"Video generation started in the background (id: {result_id})..."

    # Blocking fallback: CLI / process_direct (bus_active is false)
    # ... original blocking Veo polling code ...
```

**Key changes:**
- Added `_pending_results` module global and `pending_results` param to `set_runtime_refs()`
- Added `_get_session_key(tool_context)` helper
- Removed `generate_video` from `SUBAGENT_TOOLS` (no longer needs an LLM subagent)

#### `scorpion/adk/loop.py` — Wiring

| Location | Change |
|----------|--------|
| `__init__` | Creates `self._pending_results = PendingResults()`, passes to `set_runtime_refs()` |
| `_run_agent_adk` | Calls `build_context_block(session_key)` and prepends to user message |
| `_handle_stop` | Calls `pending_results.cancel_by_session()` alongside subagent cancellation |
| `_handle_new_session` | Calls `pending_results.cancel_by_session()` on `/new` |
| `process_direct` | After main response, awaits `wait_running()` then drains and appends file paths |

---

## Behaviour by Mode

| Mode | `bus_active` | `_pending_results` | Behaviour |
|------|--------------|--------------------|-----------|
| Gateway (Telegram/Discord) | `true` | set | Non-blocking worker spawned |
| CLI (`-m "..."`) | `false` | set | Blocking fallback (polls API directly) |
| Cron | `false` | set | Blocking fallback |
| No pending_results | any | `None` | Blocking fallback |

---

## Test Results

### Unit Tests — `tests/test_video_subagent.py`

Run with: `~/.venv/bin/python -m pytest tests/test_video_subagent.py -v -p no:twisted`

```
26 passed in 2.26s
```

| Test Class | Tests | Result |
|------------|-------|--------|
| `TestPendingResults` | 9 | ✅ all passed |
| `TestVideoNonBlocking` | 5 | ✅ all passed |
| `TestVideoBlocking` | 3 | ✅ all passed |
| `TestVideoErrorHandling` | 3 | ✅ all passed |
| `TestBusActiveFlag` | 2 | ✅ all passed |
| `TestLoopPendingWiring` | 2 | ✅ all passed |
| `TestSubagentStateFlag` | 2 | ✅ all passed |

### Real API Tests — `tests/test_creative_tools_execution.py`

Run with: `~/.venv/bin/python -m pytest tests/test_creative_tools_execution.py::TestImageGeneration tests/test_creative_tools_execution.py::TestSpeechGeneration -v -s -p no:twisted`

```
2 passed, 1 skipped in 82.36s
```

| Test | Result | Notes |
|------|--------|-------|
| `TestImageGeneration::test_generate_image_saves_to_disk` | ✅ PASSED | Generated `image_20260302_145243.png` via Imagen 4 in ~15s |
| `TestSpeechGeneration::test_generate_speech_saves_to_disk` | ✅ PASSED | Generated `speech_20260302_145247.wav` (92 686 bytes) in ~3s |
| `TestWeatherTool::test_weather_tool_direct` | ⏭ SKIPPED | Network unavailable in test env |
| `TestVideoGeneration` | ⏭ SKIPPED | Marked skip by default (5-10 min, run manually) |
| `TestMusicGeneration` | not run | Lyria connection requires specific network setup |

---

## Running Tests

### Prerequisites

```bash
# Use the project venv at home root
source ~/.venv/bin/activate

# Verify cloud deps
python -c "from google import genai; from google.adk.agents import LlmAgent; print('OK')"

# Ensure GEMINI_API_KEY is set (or present in ~/.scorpion/config.json)
```

### Unit Tests (no API, fast)

```bash
~/.venv/bin/python -m pytest tests/test_video_subagent.py -v -p no:twisted
```

### Real API — Image + Speech (~90s)

```bash
~/.venv/bin/python -m pytest \
  tests/test_creative_tools_execution.py::TestImageGeneration \
  tests/test_creative_tools_execution.py::TestSpeechGeneration \
  -v -s -p no:twisted
```

### Real API — Music (~60s)

```bash
~/.venv/bin/python -m pytest \
  tests/test_creative_tools_execution.py::TestMusicGeneration \
  -v -s -p no:twisted
```

### Real API — Video (5-10 min, manual only)

```bash
~/.venv/bin/python -m pytest \
  tests/test_creative_tools_execution.py::TestVideoGeneration \
  -v -s -p no:twisted \
  --run-video  # override the @skip marker
```

Or run the blocking path directly via CLI:

```bash
scorpion -m "generate a video of a sunset over the ocean"
```

### Full suite (skips video by default)

```bash
~/.venv/bin/python -m pytest tests/ -v -p no:twisted \
  --deselect tests/test_creative_tools_execution.py::TestVideoGeneration
```

---

## Media Output Locations

| Kind | Path |
|------|------|
| Images | `~/.scorpion/media/images/image_YYYYMMDD_HHMMSS.png` |
| Videos | `~/.scorpion/media/videos/video_YYYYMMDD_HHMMSS.mp4` |
| Music | `~/.scorpion/media/music/music_YYYYMMDD_HHMMSS.wav` |
| Speech | `~/.scorpion/media/voicemessage/speech_YYYYMMDD_HHMMSS.wav` |
