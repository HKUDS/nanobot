# Nanobot Performance and Scalability Analysis

**Date:** 2026-03-18
**Scope:** `/home/carlos/nanobot/nanobot/` — full codebase
**Analyst role:** Performance Engineer

> Phase 1 findings (H-3, H-4, C-3, L-1, A-M6, L-3) are excluded from this report.

---

## Summary Table

| ID | Severity | Area | File |
|----|----------|------|------|
| P-01 | High | BM25 index rebuilt from disk on every query | `agent/memory/retrieval.py`, `store.py` |
| P-02 | High | `events.jsonl` scanned in full on every retrieve call | `agent/memory/store.py` |
| P-03 | High | Bootstrap files re-read from disk on every LLM turn | `agent/context.py` |
| P-04 | High | `SkillsLoader` re-scans filesystem and re-parses YAML on every turn | `agent/skills.py` |
| P-05 | High | `_evict_disk` reads + rewrites entire cache file on every store | `agent/tools/result_cache.py` |
| P-06 | High | SQLite connections opened without pooling; called on every `MemoryStore.__init__` | `agent/memory/store.py` |
| P-07 | Medium | `httpx.AsyncClient` created fresh per request in `WebSearchTool` | `agent/tools/web.py` |
| P-08 | Medium | `summarize_and_compress` rebuilds identical `json.dumps` for hashing on every call | `agent/context.py` |
| P-09 | Medium | `ConsolidationOrchestrator._locks` grows unboundedly across sessions | `agent/consolidation.py` |
| P-10 | Medium | `tool_result_cache._args_index` secondary index is never consulted (dead code) | `agent/tools/result_cache.py` |
| P-11 | Medium | `ToolResultCache` holds full raw output strings indefinitely in process memory | `agent/tools/result_cache.py` |
| P-12 | Medium | `_dispatch_outbound` busy-loops on 1 s timeout regardless of queue depth | `channels/manager.py` |
| P-13 | Medium | `platform.system()` and `platform.python_version()` called on every system-prompt build | `agent/context.py` |
| P-14 | Medium | `shutil.which` invoked per-skill per-turn for requirement checks | `agent/skills.py` |
| P-15 | Low | `estimate_messages_tokens` iterates all messages twice in `compress_context` | `agent/context.py` |
| P-16 | Low | `strip_think` compiles regex patterns on every call | `agent/streaming.py` |
| P-17 | Low | `_retrieve_core` performs a double `retrieve` under shadow mode, doubling vector costs | `agent/memory/store.py` |
| P-18 | Low | `WebFetchTool._extract` lazy-imports `readability` and `markdownify` on every HTML fetch | `agent/tools/web.py` |
| P-19 | Low | `_slice_output` calls `json.loads` on the full cached output to extract a few rows | `agent/tools/result_cache.py` |
| P-20 | Low | `run_tool_loop` calls `tools.get_definitions()` once per LLM iteration | `agent/tool_loop.py` |

---

## Detailed Findings

---

### P-01 — High: BM25 index rebuilt from disk on every retrieval query

**File:** `nanobot/agent/memory/retrieval.py` (line 91–123) and `nanobot/agent/memory/store.py` (`retrieve`, line 2656)

**Impact:** Every call to `retrieve()` when mem0 is unavailable calls `_build_bm25_index(events)` from scratch. That function iterates every event, tokenises its text, and builds a document-frequency map. With 500 events this is O(N·T) where T is the average token count per event. This runs once per user message in the fallback path.

**Root Cause:**
```python
# store.py ~line 2656 — called synchronously from build_system_prompt() on every turn
candidates = _local_retrieve(
    events,           # full list loaded from disk above
    augmented_query,
    top_k=candidate_k,
    ...
)
```
Inside `_local_retrieve`, `_build_bm25_index(active_events)` is called every time with no caching.

**Recommendation:** Cache the BM25 index on `MemoryStore` and invalidate it only when `events.jsonl` changes (mtime comparison). A 64-bit file mtime + size fingerprint is sufficient:

```python
# In MemoryStore.__init__
self._bm25_cache: tuple[int, int, tuple, dict, float] | None = None  # (mtime_ns, size, doc_tokens, df, avg_dl)

def _get_bm25_index(self, events):
    stat = self.events_file.stat() if self.events_file.exists() else None
    key = (stat.st_mtime_ns, stat.st_size) if stat else (0, 0)
    if self._bm25_cache and self._bm25_cache[:2] == key:
        return self._bm25_cache[2:]   # doc_tokens_list, df, avg_dl
    doc_tokens, df, avg_dl = _build_bm25_index(events)
    self._bm25_cache = (*key, doc_tokens, df, avg_dl)
    return doc_tokens, df, avg_dl
```

---

### P-02 — High: `events.jsonl` scanned in full on every retrieve call

**File:** `nanobot/agent/memory/store.py` (line 2626, 3636, 3688)

**Impact:** `read_events()` calls `persistence.read_jsonl(self.events_file)` which opens, reads, and parses the entire JSONL file on every invocation. A single user turn that reaches `get_memory_context()` can call `read_events()` twice or three times:
- Line 2626 — inside `retrieve()` for BM25 path
- Line 3688 — for `_recent_unresolved(self.read_events(limit=60), ...)`
- Indirectly from `read_events(limit=None)` in other consolidation paths

With 1,000+ events the file may be hundreds of KB. Each call opens, reads, parses, and garbage-collects the list independently.

**Recommendation:** Cache the parsed event list and invalidate on mtime change, similar to P-01. The same file-fingerprint approach applies. A single call per turn is the target:

```python
def _load_events_cached(self) -> list[dict[str, Any]]:
    stat = self.events_file.stat() if self.events_file.exists() else None
    key = (stat.st_mtime_ns, stat.st_size) if stat else (0, 0)
    if self._events_cache_key == key:
        return self._events_cache
    self._events_cache = self.persistence.read_jsonl(self.events_file)
    self._events_cache_key = key
    return self._events_cache
```

---

### P-03 — High: Bootstrap files re-read from disk on every LLM turn

**File:** `nanobot/agent/context.py` (lines 585–595)

**Impact:** `_load_bootstrap_files()` is called inside `build_system_prompt()`, which is called for every LLM iteration of every turn. It reads up to 5 files (`AGENTS.md`, `SOUL.md`, `USER.md`, `TOOLS.md`, `IDENTITY.md`) from disk unconditionally. These files are static between restarts, making every re-read wasteful.

```python
def _load_bootstrap_files(self) -> str:
    parts = []
    for filename in self.BOOTSTRAP_FILES:
        file_path = self.workspace / filename
        if file_path.exists():
            content = file_path.read_text(encoding="utf-8")  # disk read every call
            parts.append(f"## {filename}\n\n{content}")
    return "\n\n".join(parts) if parts else ""
```

The call chain is: `build_messages()` → `build_system_prompt()` → `_load_bootstrap_files()`. In a single turn with 10 iterations, this reads these files 10 times.

**Recommendation:** Cache the concatenated bootstrap content at the `ContextBuilder` level and invalidate only when the file mtime changes (or simply cache once at first call, since these are configuration files):

```python
def __init__(self, ...):
    self._bootstrap_cache: str | None = None
    self._bootstrap_mtime: dict[str, float] = {}

def _load_bootstrap_files(self) -> str:
    # Invalidate if any file has changed
    for filename in self.BOOTSTRAP_FILES:
        fp = self.workspace / filename
        mtime = fp.stat().st_mtime if fp.exists() else 0.0
        if self._bootstrap_mtime.get(filename) != mtime:
            self._bootstrap_cache = None
            break
    if self._bootstrap_cache is not None:
        return self._bootstrap_cache
    # ... build as before, then cache
    self._bootstrap_cache = result
    return result
```

---

### P-04 — High: `SkillsLoader` re-scans filesystem and re-parses YAML on every turn

**File:** `nanobot/agent/skills.py` (lines 35–75, 111–128, 194–202, 341–396)

**Impact:** `build_system_prompt()` calls `get_always_skills()` and `build_skills_summary()` on every turn. Each of these calls `list_skills()` which calls `_find_all_skill_dirs()` — a recursive `rglob("SKILL.md")` filesystem walk across both the workspace and builtin directories. After the walk, `_check_requirements()` calls `shutil.which()` for every binary requirement of every skill and `os.environ.get()` for every environment variable. Additionally, `build_skills_summary()` calls `_get_skill_description()` → `get_skill_metadata()` → `load_skill()` → file read + YAML parse for every skill on every turn.

For a deployment with 20+ builtin skills, this incurs 20+ `Path.read_text` + `yaml.safe_load` calls per turn.

**Recommendation:** Cache the skill list and metadata with filesystem-mtime invalidation. Binary availability (`shutil.which`) results should be cached at process startup since the PATH does not change at runtime. YAML frontmatter should be parsed once and stored in a `dict[str, dict]`.

---

### P-05 — High: `_evict_disk` reads and rewrites the entire cache file on every store operation

**File:** `nanobot/agent/tools/result_cache.py` (lines 319–329)

**Impact:** Every call to `_persist_entry()` (which happens on every tool result cache write) calls `_evict_disk()`. That method:
1. Reads the entire JSONL file into memory (`self._disk_path.read_text(...)`)
2. Splits into lines
3. If over limit, rewrites the entire file

For a session that executes 50 tool calls, this means 50 full-file reads and up to 50 full-file writes. This is O(N²) in disk I/O across a session. With `_MAX_DISK_ENTRIES = 50` and entries up to 200 KB each, the file can be up to 10 MB, and each eviction writes 10 MB.

```python
def _evict_disk(self) -> None:
    lines = self._disk_path.read_text(encoding="utf-8").strip().splitlines()
    if len(lines) > _MAX_DISK_ENTRIES:
        keep = lines[-_MAX_DISK_ENTRIES:]
        self._disk_path.write_text("\n".join(keep) + "\n", encoding="utf-8")  # full rewrite
```

**Recommendation:** Track the line count in memory. Only trigger eviction when the count exceeds `_MAX_DISK_ENTRIES`, and do so by maintaining a pointer to the start of the "live" entries rather than rewriting every time. Alternatively, defer eviction to a background task or batch it (every N writes):

```python
def __init__(self, ...):
    self._disk_line_count = 0  # tracked in memory

def _persist_entry(self, entry):
    ...
    self._disk_line_count += 1
    if self._disk_line_count > _MAX_DISK_ENTRIES + 10:  # batch threshold
        self._evict_disk()
```

---

### P-06 — High: SQLite connections opened without pooling; blocking calls from MemoryStore init

**File:** `nanobot/agent/memory/store.py` (lines 960–968, 976–988)

**Impact:** `_vector_points_count()` and `_history_row_count()` each open SQLite connections, execute queries, and close connections. Both are called from:
- `_ensure_vector_health()` — called from `MemoryStore.__init__()` (i.e., at agent startup for every session)
- `get_observability_report()` — called on demand

These are synchronous SQLite calls in a fully async codebase. When called from a coroutine context they block the event loop for the duration of the disk seek + query. The `_vector_points_count()` method iterates all Qdrant collection subdirectories, opening a separate connection per collection.

```python
# store.py ~960 — called from __init__, blocks event loop
conn = sqlite3.connect(storage)
cur = conn.cursor()
cur.execute("SELECT COUNT(*) FROM points")
total += int(cur.fetchone()[0])
conn.close()
```

**Recommendation:** Either:
1. Wrap in `asyncio.to_thread()` to avoid blocking the event loop
2. Cache the result with a TTL (e.g., 60 seconds), since vector counts change infrequently
3. Move `_ensure_vector_health()` out of `__init__` and into a lazy `async` startup method

---

### P-07 — Medium: `httpx.AsyncClient` created fresh per web request

**File:** `nanobot/agent/tools/web.py` (lines 105–113, 209–213)

**Impact:** Both `WebSearchTool.execute()` and `WebFetchTool.execute()` construct a new `httpx.AsyncClient()` via `async with httpx.AsyncClient(...) as client:` on every invocation. Creating a client opens a new connection pool; destroying it closes all connections. When the LLM issues multiple web fetches in a single turn (common for research tasks), each fetch pays the full TCP handshake + TLS negotiation overhead with no connection reuse.

```python
# web.py ~105 — new client + connection pool per search
async with httpx.AsyncClient() as client:
    r = await client.get("https://api.search.brave.com/...")
```

**Recommendation:** Use a module-level or class-level shared `httpx.AsyncClient` with appropriate limits, reusing connections across calls:

```python
_shared_client: httpx.AsyncClient | None = None

def _get_client() -> httpx.AsyncClient:
    global _shared_client
    if _shared_client is None or _shared_client.is_closed:
        _shared_client = httpx.AsyncClient(
            follow_redirects=True,
            max_redirects=MAX_REDIRECTS,
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
        )
    return _shared_client
```

Note: a shared client must be closed gracefully on shutdown.

---

### P-08 — Medium: `summarize_and_compress` serialises all middle messages to JSON for hashing

**File:** `nanobot/agent/context.py` (lines 232–235, 299)

**Impact:** `_hash_messages()` calls `json.dumps(msgs, sort_keys=True, default=str)` on the entire middle message list to compute a SHA-256 hash. This serialises potentially hundreds of KB of conversation history every time Phase 3 compression is triggered. In long conversations with frequent context compression, this is a redundant full serialisation.

```python
def _hash_messages(msgs: list[dict[str, Any]]) -> str:
    raw = json.dumps(msgs, sort_keys=True, default=str)  # full serialisation
    return hashlib.sha256(raw.encode()).hexdigest()[:24]
```

**Recommendation:** Build a lighter hash using message count + content length + first-and-last message fingerprint, avoiding full serialisation:

```python
def _hash_messages(msgs: list[dict[str, Any]]) -> str:
    # Cheap structural fingerprint: count + cumulative content length + boundary content
    parts = [str(len(msgs))]
    for i, m in enumerate(msgs):
        if i < 2 or i >= len(msgs) - 2:
            c = str(m.get("content", ""))[:64]
            parts.append(f"{m.get('role','')}{len(c)}{c}")
        else:
            parts.append(str(len(str(m.get("content", "")))))
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:24]
```

---

### P-09 — Medium: `ConsolidationOrchestrator._locks` grows unboundedly across sessions

**File:** `nanobot/agent/consolidation.py` (lines 32–45)

**Impact:** `get_lock(session_key)` creates a new `asyncio.Lock` per session key and stores it in `self._locks`. `prune_lock()` removes unlocked entries, but this is only called at specific call sites. In a deployment serving many users over time, the lock dictionary grows proportionally to the number of distinct session keys, none of which are evicted while the process is running unless all callers correctly call `prune_lock`. This is a mild memory leak — each `asyncio.Lock` is small (~200 bytes), but the keys themselves (strings like `"telegram:123456789"`) persist indefinitely.

```python
def get_lock(self, session_key: str) -> asyncio.Lock:
    lock = self._locks.get(session_key)
    if lock is None:
        lock = asyncio.Lock()
        self._locks[session_key] = lock  # never evicted unless prune_lock called
    return lock
```

**Recommendation:** Use a `weakref.WeakValueDictionary` or a capped LRU mapping (e.g., `functools.lru_cache` with maxsize) to bound the lock dictionary size:

```python
from collections import OrderedDict

class ConsolidationOrchestrator:
    _MAX_LOCKS = 1000

    def get_lock(self, session_key: str) -> asyncio.Lock:
        if session_key in self._locks:
            self._locks.move_to_end(session_key)
            return self._locks[session_key]
        lock = asyncio.Lock()
        self._locks[session_key] = lock
        if len(self._locks) > self._MAX_LOCKS:
            self._locks.popitem(last=False)  # evict oldest
        return lock
```

---

### P-10 — Medium: `_args_index` in `ToolResultCache` is populated but never queried (dead code)

**File:** `nanobot/agent/tools/result_cache.py` (lines 156–157, 200)

**Impact:** The secondary index `_args_index: dict[str, str]` is built in `store()` (`self._args_index[f"{tool_name}:{key}"] = key`) and cleared in `clear()`, but `has()` uses `_make_cache_key()` to directly check `self._entries` — never consulting `_args_index`. The secondary index therefore wastes memory (stores a duplicate key mapping) and write time without providing any lookup benefit.

```python
# Populated but never read via any public method:
self._args_index[f"{tool_name}:{entry.tool_name}:{entry.cache_key}"] = key
```

**Recommendation:** Remove `_args_index` entirely, or implement and use it for the `has()` lookup path if there is a future deduplication use case. Removing it saves memory proportional to the number of cached entries.

---

### P-11 — Medium: `ToolResultCache` holds full raw outputs in process memory indefinitely

**File:** `nanobot/agent/tools/result_cache.py` (lines 151–157, 195–203)

**Impact:** Every `CacheEntry` stores `full_output: str` — the complete raw tool output, which can be up to `_MAX_DISK_ENTRY_BYTES = 200_000` characters (200 KB) for disk-persisted entries, and unlimited for memory-only entries. The in-memory `_entries` dict is never evicted during a process lifetime; only the disk file is capped at 50 entries. A long-running process that executes many large tool calls (file reads, Excel spreadsheets, web pages) will accumulate hundreds of MB of raw text in memory.

**Recommendation:** Apply an LRU eviction policy to the in-memory store (e.g., bounded to 50 entries or a configurable max-bytes threshold). The disk file already caps at 50 entries; the in-memory store should match:

```python
_MAX_MEMORY_ENTRIES = 100  # configurable

def store(self, ...):
    ...
    self._entries[key] = entry
    if len(self._entries) > _MAX_MEMORY_ENTRIES:
        # Evict oldest by creation_at
        oldest = min(self._entries, key=lambda k: self._entries[k].created_at)
        del self._entries[oldest]
```

---

### P-12 — Medium: `_dispatch_outbound` busy-loops with a 1-second timeout

**File:** `nanobot/channels/manager.py` (lines 231–261)

**Impact:** The outbound dispatcher polls `bus.consume_outbound()` with `asyncio.wait_for(..., timeout=1.0)`. When there are no outbound messages (the common case for the gap between turns), this coroutine wakes up every second, catches `asyncio.TimeoutError`, and loops. While lightweight, this introduces up to 1 second of unnecessary latency for the first outbound message after a quiet period, and keeps a coroutine alive doing no useful work. This is the same architectural issue as A-M6 but on the output side.

```python
while True:
    try:
        msg = await asyncio.wait_for(self.bus.consume_outbound(), timeout=1.0)
        ...
    except asyncio.TimeoutError:
        continue  # woken every second needlessly
```

**Recommendation:** Remove the timeout and use `bus.consume_outbound()` directly (it blocks efficiently on the `asyncio.Queue`). Use an `asyncio.Event` for shutdown signalling (as the agent loop's `run()` method already does):

```python
async def _dispatch_outbound(self) -> None:
    while True:
        done, _ = await asyncio.wait(
            {asyncio.ensure_future(self.bus.consume_outbound()),
             asyncio.ensure_future(self._stop_event.wait())},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if self._stop_event.is_set():
            break
        msg = next(iter(done)).result()
        ...
```

---

### P-13 — Medium: `platform.system()` and `platform.python_version()` called on every system-prompt build

**File:** `nanobot/agent/context.py` (lines 524–525)

**Impact:** `_get_identity()` is called inside `build_system_prompt()`, which is called on every LLM iteration. `platform.system()`, `platform.machine()`, and `platform.python_version()` are all synchronous calls that read OS-level information. While individually fast (<1 ms), they are completely static for the lifetime of the process and their results should not be recomputed on every token-generation turn.

```python
def _get_identity(self) -> str:
    workspace_path = str(self.workspace.expanduser().resolve())  # I/O every call
    sys_name = platform.system()                                  # syscall every call
    runtime = f"{'macOS' if sys_name == 'Darwin' else sys_name} {platform.machine()}, Python {platform.python_version()}"
```

**Recommendation:** Compute `runtime` and `workspace_path` once at `ContextBuilder.__init__` time and store them as instance attributes:

```python
def __init__(self, workspace, ...):
    ...
    _ws = workspace.expanduser().resolve()
    self._workspace_path_str = str(_ws)
    _sys = platform.system()
    self._runtime_str = f"{'macOS' if _sys == 'Darwin' else _sys} {platform.machine()}, Python {platform.python_version()}"
```

---

### P-14 — Medium: `shutil.which` invoked per-skill per-turn for requirement checks

**File:** `nanobot/agent/skills.py` (lines 181–186, 134–136)

**Impact:** `_check_requirements(skill_meta)` calls `shutil.which(b)` for each binary requirement of each skill. `build_skills_summary()` calls `_check_requirements` for every skill on every turn. `list_skills(filter_unavailable=True)` also calls it. A deployment with 20 skills each requiring 2 binary checks executes 40 `shutil.which` calls per turn — each of which walks the `PATH` directories on disk.

**Recommendation:** Cache `shutil.which` results at process startup since `PATH` does not change at runtime:

```python
import functools

@functools.lru_cache(maxsize=None)
def _which_cached(binary: str) -> str | None:
    return shutil.which(binary)
```

Similarly, environment variable checks for requirements (`os.environ.get(env)`) are immutable after startup and should be cached.

---

### P-15 — Low: `estimate_messages_tokens` called redundantly in `compress_context`

**File:** `nanobot/agent/context.py` (lines 179–208)

**Impact:** `compress_context` calls `estimate_messages_tokens` multiple times per invocation — once to check whether compression is needed, and once after each trial (phases 1, 2, 3). Each call iterates the entire message list. In a turn with 50 messages, this is 3–4 full scans of the message list. The individual call is cheap, but it compounds across 10 iterations.

**Recommendation:** In phase transitions, maintain a running delta rather than recomputing from scratch. After phase 1 truncation, only the changed messages contribute a token delta — compute only those and update a running total.

---

### P-16 — Low: `strip_think` compiles regex patterns on every call

**File:** `nanobot/agent/streaming.py` (lines 35–50)

**Impact:** `re.sub(r"<think>[\s\S]*?</think>", "", text)` and `re.sub(r"^(assistant\s*)?analysis[^\n]*\n?", "", ...)` are called on every LLM response through `strip_think()`. Python's `re` module caches compiled patterns, but the while loop in `strip_think` compiles the inner regex on each iteration. This is a minor overhead but easily fixed.

**Recommendation:** Hoist the regex patterns to module-level compiled constants:

```python
_RE_THINK = re.compile(r"<think>[\s\S]*?</think>")
_RE_ANALYSIS_PREFIX = re.compile(r"^(assistant\s*)?analysis[^\n]*\n?", re.IGNORECASE)
```

---

### P-17 — Low: Shadow retrieval mode runs a full duplicate vector query

**File:** `nanobot/agent/memory/store.py` (lines 2755–2781)

**Impact:** When `memory_shadow_mode` is enabled and the shadow rate fires, `_retrieve_core()` is called a second time with the router setting toggled. This doubles the vector store query cost, LLM embedding cost (if any), and post-processing time for the affected fraction of requests. The shadow result is computed, overlap is computed, but no action is taken — the primary result is always returned.

**Recommendation:** The shadow mode is intentional for A/B testing, but the overlap computation result (`_overlap`) is computed and then discarded — it is assigned to a local variable with no further use. Either emit it as an observability metric or remove the computation:

```python
if primary_ids or shadow_ids:
    _overlap = len(set(primary_ids) & set(shadow_ids)) / max(...)
    # _overlap is computed but never logged or used — dead code
```

At minimum, wrap the entire shadow block in a background task so it does not add to the critical path latency of the primary retrieval response:

```python
asyncio.create_task(_run_shadow_retrieve(...))
```

---

### P-18 — Low: `WebFetchTool._extract` lazy-imports `readability` and `markdownify` on every HTML fetch

**File:** `nanobot/agent/tools/web.py` (lines 252, 265, 301–306)

**Impact:** `from readability import Document` and `from markdownify import markdownify` are inside the method body, so Python executes an attribute lookup in `sys.modules` on each call. When the module has been imported once this is a dict lookup (fast), but adding a module import statement inside a hot path is a code smell that prevents static analysis tools from detecting import errors early and creates confusing behaviour if the import fails mid-request.

**Recommendation:** Move these imports to the module top level, wrapped in a try/except to give a clear error on startup if the library is absent:

```python
try:
    from readability import Document as _ReadabilityDocument
    from markdownify import markdownify as _markdownify
    _READABILITY_AVAILABLE = True
except ImportError:
    _READABILITY_AVAILABLE = False
```

---

### P-19 — Low: `_slice_output` deserialises the entire JSON payload to extract a small slice

**File:** `nanobot/agent/tools/result_cache.py` (lines 337–363)

**Impact:** `cache_get_slice` calls `_slice_output(entry.full_output, start, end)`. For JSON-format outputs, `_slice_output` calls `json.loads(output)` on the full string — which could be the full 200 KB raw spreadsheet data — to then return `parsed[start:end]`. When the LLM pages through a 10,000-row dataset 25 rows at a time, each page request deserialises the entire payload.

**Recommendation:** Store the pre-parsed JSON representation separately from the raw string in `CacheEntry`, or use a streaming JSONL format where each row is on a separate line to enable O(1) line-based slicing without full deserialisation.

---

### P-20 — Low: `run_tool_loop` calls `tools.get_definitions()` on every iteration

**File:** `nanobot/agent/tool_loop.py` (line 44)

**Impact:** `tools.get_definitions()` iterates all registered tools and builds a list of JSON Schema dicts on every LLM call within the loop. Since the tool set does not change during a `run_tool_loop` execution, this is repeated work for every of the up to 15 iterations.

```python
response = await provider.chat(
    messages=messages,
    tools=tools.get_definitions(),  # rebuilt every iteration
    ...
)
```

**Recommendation:** Cache the definitions before the loop:

```python
tool_defs = tools.get_definitions()
while iteration < max_iterations:
    response = await provider.chat(messages=messages, tools=tool_defs, ...)
```

This mirrors the optimisation already present in `_run_agent_loop` with `_tools_def_cache`.

---

## Scalability Concerns

### SC-01: Single-process design limits horizontal scaling

**Severity:** High (by design — single-process is an explicit architectural choice)

The `MessageBus` uses `asyncio.Queue`, which is in-process. The `ToolResultCache`, `_summary_cache` in `context.py`, and the URL cache in `web.py` are all module-level or instance-level singletons. If nanobot is scaled horizontally (multiple processes behind a load balancer), each process has independent state:

- A URL cached in process A is re-fetched in process B
- A conversation session pinned to process A cannot be resumed in process B after restart
- The `ConsolidationOrchestrator._locks` do not prevent concurrent consolidation across processes

This is an acknowledged limitation of the single-process design documented in the architecture, but it should be noted for any future scale-out work. Mitigation paths include:
1. Sticky sessions (route all messages from a given `channel:chat_id` to the same process)
2. Replacing the in-process `asyncio.Queue` with a durable queue (Redis Streams, RabbitMQ) if multi-process becomes a requirement

### SC-02: `_ensure_vector_health()` runs expensive I/O on every `MemoryStore` instantiation

**Severity:** Medium

`_ensure_vector_health()` is called from `MemoryStore.__init__`. It queries the vector point count, history row count, and fires a probe search (`mem0.search("__health__", top_k=1)`). `ContextBuilder.__init__` instantiates `MemoryStore`, and `ContextBuilder` is instantiated inside `AgentLoop.__init__`. This means every time an `AgentLoop` is created (which happens at process startup, and potentially when new role configs are applied), a vector store probe executes synchronously on the calling thread. In tests or multi-agent setups that create multiple `AgentLoop` instances, this cost multiplies.

**Recommendation:** Make `_ensure_vector_health()` a lazy async method called once at first retrieval, rather than from `__init__`.

---

## LLM Token Efficiency

### TE-01: System prompt rebuilt from scratch on every LLM iteration

**Severity:** Medium

`build_messages()` → `build_system_prompt()` is called on every LLM iteration within `_run_agent_loop`. The system prompt includes static sections (identity, security advisory, bootstrap files, skills summary) that do not change within a turn. The memory context section does change (it is query-dependent), but only on the first call. For turns with 10 iterations, the system prompt is built 10 times but is identical after the first.

**Recommendation:** Build the system prompt once at the start of `_run_agent_loop`, before the iteration loop. Update only the memory context portion if re-retrieval is needed (it currently is not — memory retrieval only happens in `build_system_prompt` which is called from `build_messages`, but the query does not change within a turn).

### TE-02: `feedback_summary` reads `events.jsonl` on every system-prompt build

**Severity:** Low

**File:** `nanobot/agent/context.py` (line 468)

`feedback_summary(events_file)` is called inside `build_system_prompt()`, reading the events file again (in addition to the reads described in P-02). The feedback summary is computed from the events file but is effectively static within a session. Combined with P-02, this is an additional redundant disk read per iteration.

---

## Startup Performance

### ST-01: Skill tool discovery (`discover_tools`) executes arbitrary Python modules at startup

**Severity:** Medium

**File:** `nanobot/agent/skills.py` (lines 208–241)

`_register_default_tools()` in `AgentLoop.__init__` calls `self.context.skills.discover_tools()` when `config.skills_enabled` is True. This imports and executes every skill's `tools.py` module via `importlib.util.spec_from_file_location`. If any skill has slow module-level code (e.g., loading ML models, connecting to databases), it blocks the agent startup synchronously on the calling thread.

**Recommendation:** Make `discover_tools()` lazy — defer tool discovery until the first turn that activates the relevant skill, or run it in a background thread during startup.

### ST-02: `MemoryStore.__init__` performs multiple synchronous I/O and network operations

**Severity:** Medium

The `MemoryStore.__init__` chain includes:
1. `MemoryPersistence.__init__` → `ensure_dir()` (directory creation)
2. `_load_rollout_config()` — pure computation, fine
3. `_Mem0Adapter.__init__` — may attempt to connect to the mem0 vector store
4. `_ensure_vector_health()` — SQLite queries + vector store probe (P-06)
5. `CrossEncoderReranker.__init__` — may load a sentence-transformer model if reranker is enabled

All of this runs synchronously during `AgentLoop.__init__`, blocking the event loop if called from an async context. A cold start can take several seconds when the cross-encoder model is loaded.

**Recommendation:** Separate construction from initialisation with an async `async def start()` method, similar to channel lifecycle patterns in `channels/base.py`.

---

## Concurrency

### CC-01: `_run_agent_loop` accumulates shared mutable token counters without locking

**Severity:** Low

**File:** `nanobot/agent/loop.py` (lines 1184–1186)

```python
self._turn_tokens_prompt += response.usage.get("prompt_tokens", 0)
self._turn_tokens_completion += response.usage.get("completion_tokens", 0)
self._turn_llm_calls += 1
```

These are instance-level accumulators reset at the start of each turn. Since `AgentLoop` is designed as a single-consumer loop (one message processed at a time via the `MessageBus`), there is no data race in normal operation. However, if `_run_agent_loop` is ever called concurrently (e.g., via `process_direct` from multiple callers), these counters would produce incorrect totals without a lock. The current code relies on the single-consumer invariant being maintained by callers.

### CC-02: `_summary_cache` in `context.py` lacks write lock (existing Phase 1 finding P-L-3/H-4)

This finding is already tracked under H-4 from Phase 1. The `_summary_cache` in `context.py` is a module-level `OrderedDict` shared across all `AgentLoop` instances. Concurrent writes from multiple agents (e.g., multi-agent setups with parallel delegations) can corrupt the `OrderedDict` because Python's `OrderedDict.popitem()` and `__setitem__` are not atomic under the GIL for concurrent asyncio tasks that yield between the check and the write.

---

## Summary of High-Priority Recommendations

1. **P-01 + P-02:** Cache the BM25 index and parsed JSONL events with file-mtime invalidation. This eliminates the largest repeated I/O + computation cost in the memory path.
2. **P-03:** Cache bootstrap file contents with mtime invalidation; avoid re-reading static workspace config files on every LLM iteration.
3. **P-04 + P-14:** Cache skill metadata and binary availability checks; avoid per-turn YAML parsing and `shutil.which` calls.
4. **P-05:** Track disk entry count in memory; avoid read-then-write on every cache persist.
5. **P-06:** Move SQLite health checks to an async startup path and cache results.
6. **P-07:** Share a persistent `httpx.AsyncClient` across web tool invocations to enable connection reuse.
