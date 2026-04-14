# Proposal: Integrate cave-agent Python Primitives Runtime into nanobot

> Status: **Phase 1 Complete (PoC)** | Branch: `poc/cave-agent-runtime` | Date: 2026-04-14
> Fork: https://github.com/Luck9Star/nanobot

## 1. Background & Motivation

### The Problem

nanobot uses **JSON Schema-based tool calling** (OpenAI function calling protocol). Each `ExecTool` invocation spawns an **independent subprocess** — variables, imports, and function definitions do NOT persist across calls. This severely limits nanobot's ability to handle complex, multi-step Python workflows.

### The Solution

[cave-agent](https://github.com/acodercat/cave-agent) provides a **stateful Python runtime** backed by IPython/IPyKernel:

- **Variable/Function/Type injection**: Inject any Python object into the runtime namespace
- **State persistence**: Variables, imports, and definitions persist across calls (Jupyter-like)
- **Complex object manipulation**: LLM can directly operate on DataFrames, DB connections, ML models, etc.
- **AST-based security**: `SecurityChecker` with fine-grained rules (ImportRule, FunctionRule, AttributeRule, RegexRule)
- **Two backends**: `IPythonRuntime` (in-process) and `IPyKernelRuntime` (process-isolated)

### Key Insight (from cave-agent paper)

LLMs are naturally good at generating code. JSON Schema tool calling is an artificial constraint. Letting LLMs generate Python code to directly manipulate objects yields **significantly higher success rates** than JSON tool calling.

## 2. Architecture

### Current nanobot Flow

```
LLM → JSON tool_calls → ToolRegistry.execute() → Tool.execute(**kwargs)
                          {"name":"exec",
                           "args":{"command":"pip install X"}}
                                               → subprocess (stateless)
```

### Proposed Flow

```
LLM → JSON tool_calls → ToolRegistry.execute()
                          {"name":"python",
                           "args":{"code":"import pandas as pd\ndf = pd.read_csv('data.csv')"}}
                                               → PythonRuntimeTool.execute(code)
                                                   → cave-agent IPythonRuntime.execute(code)
                                                   → stateful IPython namespace
                                                   → variables persist across calls!
```

### Component Diagram

```
nanobot AgentLoop
    │
    ├── ExecTool              (existing, subprocess, stateless)
    ├── ReadFileTool          (existing)
    ├── WriteFileTool         (existing)
    │   ...
    │
    └── PythonRuntimeTool     (NEW ← cave-agent)
            │
            ├── IPythonRuntime / IPyKernelRuntime
            │     ├── IPythonExecutor (stateful execution)
            │     ├── inject_into_namespace() (Variable/Function/Type)
            │     └── execute(code) → ExecutionResult
            │
            ├── SecurityChecker (cave-agent's AST security validation)
            └── Namespace descriptor (generates prompt text for LLM)
```

## 3. Integration Design

### 3.1 New Tool: `PythonRuntimeTool`

Located at: `nanobot/agent/tools/python_runtime.py`

**Core API:**
```python
class PythonRuntimeTool(Tool):
    async def execute(self, code: str) -> str:
        """Execute Python code in stateful runtime, return output."""
        
    def inject_variable(self, name: str, value: Any, description: str = ""):
        """Inject a Python object into the namespace."""
        
    def inject_function(self, func: Callable, description: str = ""):
        """Inject a callable into the namespace."""
        
    def inject_type(self, cls: type, description: str = ""):
        """Inject a type/class into the namespace."""
        
    def describe_namespace(self) -> str:
        """Generate namespace description for system prompt injection."""
        
    async def retrieve(self, name: str) -> Any:
        """Retrieve a variable value from the namespace."""
        
    async def reset(self):
        """Reset the runtime (clear all state)."""
```

**Tool Properties:**
- `name`: `"python"`
- `exclusive`: `True` (modifies namespace state, cannot run concurrently)
- `read_only`: `False`
- `concurrency_safe`: `False`

### 3.2 Configuration

Added to `nanobot/config/schema.py` as a Pydantic model:

```python
class PythonRuntimeConfig(Base):
    """cave-agent Python runtime tool configuration."""
    enable: bool = False
    backend: str = "ipython"         # "ipython" or "ipykernel"
    max_output_chars: int = 10_000
```

Nested under `ToolsConfig`:
```python
class ToolsConfig(Base):
    web: WebToolsConfig = ...
    exec: ExecToolConfig = ...
    python_runtime: PythonRuntimeConfig = Field(default_factory=PythonRuntimeConfig)
    ...
```

**nanobot.yaml 启用示例:**
```yaml
tools:
  python_runtime:
    enable: true
    backend: ipython       # "ipython" (in-process) or "ipykernel" (process-isolated)
    max_output_chars: 10000
```

依赖安装: `pip install 'cave-agent[all]'`

### 3.3 System Prompt Injection

Modified `nanobot/agent/context.py` — `build_system_prompt()` accepts `python_namespace_description` parameter:

```
# Python Runtime (Stateful)
<python_runtime>
Available Python objects (stateful, persistent across calls):

Functions:
  add(a: int, b: int) -> int — Add two numbers
  process_data(df: DataFrame) -> dict — Process a DataFrame

Variables:
  secret (str): A reversed message
  data (DataFrame): Input dataset with columns [name, age, score]

Types:
  AnalysisResult (dataclass): mean (float), count (int), status (str)
</python_runtime>
```

`AgentLoop._python_namespace_description()` generates this from the `PythonRuntimeTool` instance, and passes it through `build_messages()` → `build_system_prompt()`.

### 3.4 Registration in AgentLoop

Modified `nanobot/agent/loop.py`:
- `__init__` accepts `python_runtime_config: PythonRuntimeConfig | None`
- `_register_default_tools()` registers `PythonRuntimeTool` when enabled
- Graceful fallback: if cave-agent not installed, logs warning and skips

```python
if self.python_runtime_config.enable:
    try:
        python_tool = PythonRuntimeTool(
            backend=self.python_runtime_config.backend,
            max_output_chars=self.python_runtime_config.max_output_chars,
        )
        self.tools.register(python_tool)
        self._python_runtime_tool = python_tool
    except ImportError:
        logger.warning("PythonRuntimeTool enabled but cave-agent not installed.")
```

### 3.5 ExecTool vs PythonRuntimeTool 共存策略

两个 tool 都能执行代码，LLM 需要知道何时用哪个：

| 场景 | 用哪个 | 理由 |
|------|--------|------|
| 系统命令 (git, npm, pip) | `exec` | shell 命令，不需要 Python |
| 数据分析/处理 | `python` | 需要变量持久化和 DataFrame 操作 |
| 文件读写 | `read_file`/`write_file` | nanobot 内置工具更合适 |
| 多步 Python 工作流 | `python` | 需要 import/变量跨步持久化 |
| 一次性脚本 | `exec` 或 `python` 均可 | 无状态需求时两者等价 |

**LLM 引导**: `PythonRuntimeTool.description` 已经包含 "Prefer this over exec for data analysis, object manipulation, and multi-step Python workflows"，引导 LLM 正确选择。

## 4. Runtime Backend Selection

| Scenario | Backend | Reason |
|----------|---------|--------|
| Development/Debug | `IPythonRuntime` | Zero overhead, direct debugging |
| Production | `IPyKernelRuntime` | Process isolation, crash-safe |
| Untrusted code | `IPyKernelRuntime` + nanobot bubblewrap | Double isolation |

## 5. Key Challenges

### 5.1 IPyKernel Async Lifecycle

`IPyKernelRuntime` requires kernel startup/shutdown via `await start()`/`await stop()`.

**方案**: 在 `PythonRuntimeTool._ensure_runtime()` 中 lazy 初始化。首次 execute 时 start kernel。需要：
- `AgentLoop` 关闭时调用 `PythonRuntimeTool` 的 cleanup
- 或注册一个 shutdown hook

```python
# 在 PythonRuntimeTool 中:
async def _ensure_runtime(self):
    if self._runtime is not None:
        return self._runtime
    if self._backend == "ipykernel":
        IPyKernelRuntime = _get_ipykernel_runtime()
        self._runtime = IPyKernelRuntime(security_checker=checker)
        await self._runtime._executor.start()
    else:
        self._runtime = _IPythonRuntime(security_checker=checker)

async def cleanup(self):
    """Call during AgentLoop shutdown."""
    if self._runtime and self._backend == "ipykernel":
        await self._runtime._executor.stop()
```

### 5.2 Prompt Budget

Namespace descriptions consume context tokens. Strategy:
- Truncate descriptions that exceed a configurable token budget (e.g., 500 tokens)
- nanobot's existing microcompact will handle old tool results
- Empty namespace = no injection (zero overhead)

### 5.3 Error Recovery — Kernel Crash

If IPython kernel crashes (segfault, OOM in IPyKernelRuntime):

```python
async def execute(self, code: str) -> str:
    runtime = await self._ensure_runtime()
    try:
        result = await runtime.execute(code)
    except Exception as exc:
        if self._backend == "ipykernel":
            # Kernel may have crashed — reset and retry
            logger.warning("Kernel may have crashed, attempting reset: {}", exc)
            await self.reset()
            runtime = await self._ensure_runtime()
            try:
                result = await runtime.execute(code)
            except Exception as retry_exc:
                return self._format_error(retry_exc)
        return self._format_error(exc)
```

`reset()` on `IPyKernelRuntime` restarts the kernel and re-injects all registered primitives via `cave-agent`'s built-in reset logic.

### 5.4 Security

cave-agent's `SecurityChecker` provides AST-level validation:

```python
from cave_agent.security import SecurityChecker, ImportRule, FunctionRule, AttributeRule

rules = [
    ImportRule({"os", "subprocess", "sys"}),
    FunctionRule({"eval", "exec", "open"}),
    AttributeRule({"__globals__", "__builtins__"}),
]
```

Combined with nanobot's existing `_guard_command()` and bubblewrap sandbox = defense-in-depth.

**Phase 2 需要做的**: 在 `PythonRuntimeConfig` 中支持从 YAML 配置 security rules:
```yaml
tools:
  python_runtime:
    enable: true
    security:
      blocked_imports: ["os", "subprocess", "sys"]
      blocked_functions: ["eval", "exec"]
      blocked_attributes: ["__globals__", "__builtins__"]
```

## 6. Implementation Plan

### Phase 1: PoC ✅ (Complete — all 9/9 tests passing)

- [x] Create `PythonRuntimeTool` with IPythonRuntime backend
- [x] Register in `AgentLoop._register_default_tools()`
- [x] Add `PythonRuntimeConfig` to nanobot config schema
- [x] Inject namespace descriptions into system prompt via `ContextBuilder`
- [x] Test: basic stateful execution (variable persists across calls)
- [x] Test: inject Variable/Function and verify code can use them
- [x] Test: complex objects (dict, list) persist and are mutable
- [x] Test: error handling (runtime survives errors)
- [x] Test: reset clears state
- [x] Test: retrieve gets injected variable values
- [x] Test: describe_namespace generates readable prompt text
- [x] Test: tool schema is valid for nanobot ToolRegistry

### Phase 2: Integration

- [ ] **Config loading path**: Wire `PythonRuntimeConfig` from YAML → `AgentLoop.__init__` (currently the config object exists but nanobot's startup code doesn't pass it through)
- [ ] **IPyKernel lifecycle**: Implement `cleanup()` method, register in AgentLoop shutdown
- [ ] **Error recovery**: Add kernel crash detection + auto-restart + re-inject in `execute()`
- [ ] **Security rules config**: Parse YAML security rules → cave-agent SecurityChecker
- [ ] **LLM end-to-end test**: Real LLM call using `python` tool, verify multi-step stateful execution

### Phase 3: Production

- [ ] Context budget management for namespace descriptions (truncate if too long)
- [ ] Nanobot CLI `--python-runtime` flag
- [ ] Integration tests in nanobot's test suite
- [ ] User documentation

## 7. Dependencies

```
# Required
cave-agent>=0.7.0       # includes ipython
ipython                  # pulled in by cave-agent

# Optional (for IPyKernelRuntime process isolation)
ipykernel
dill                     # serialization for cross-process injection

# Install
pip install 'cave-agent[all]'          # includes everything
pip install 'cave-agent[ipykernel]'    # just IPyKernel support
```

## 8. Files Changed

| File | Change | Lines |
|------|--------|-------|
| `nanobot/agent/tools/python_runtime.py` | **NEW** — PythonRuntimeTool | ~350 |
| `nanobot/config/schema.py` | **MODIFIED** — Add PythonRuntimeConfig | +8 |
| `nanobot/agent/loop.py` | **MODIFIED** — Register tool + namespace description | +25 |
| `nanobot/agent/context.py` | **MODIFIED** — Pass description to prompt | +6 |
| `tests/poc_python_runtime.py` | **NEW** — 9 PoC tests | ~180 |
| `docs/proposals/cave-agent-runtime-integration.md` | **NEW** — This document | ~280 |

## 9. References

- cave-agent repo: https://github.com/acodercat/cave-agent
- cave-agent paper: https://arxiv.org/abs/2601.01569
- nanobot repo: https://github.com/HKUDS/nanobot
- Fork: https://github.com/Luck9Star/nanobot
- PoC branch: `poc/cave-agent-runtime`
