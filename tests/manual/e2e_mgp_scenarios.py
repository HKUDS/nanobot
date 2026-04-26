"""End-to-end MGP integration scenarios.

Drives a real ``mgp-gateway`` (in-memory adapter) over real HTTP and exercises
the full sidecar -> gateway -> adapter stack. The LLM provider is mocked so
the run is deterministic and free; the goal is to validate **wiring**, not
LLM behavior.

Run from the repo root:

    uv run --extra dev --extra mgp python tests/manual/e2e_mgp_scenarios.py

The script returns exit code 0 if all scenarios pass, 1 otherwise. It is
deliberately not a pytest test: spinning up the gateway subprocess for every
test session would be too slow for the regular CI loop.
"""

from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
import time
import urllib.request
from contextlib import closing
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from nanobot.agent.loop import AgentLoop  # noqa: E402
from nanobot.agent.mgp import build_sidecar  # noqa: E402
from nanobot.agent.tools.mgp_recall import MGPRecallTool  # noqa: E402
from nanobot.bus.queue import MessageBus  # noqa: E402
from nanobot.config.schema import MGPConfig  # noqa: E402
from nanobot.providers.base import GenerationSettings, LLMResponse  # noqa: E402

# ---------------------------------------------------------------------------
# Tiny pretty-print helpers
# ---------------------------------------------------------------------------

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"
INFO = "\033[36m••\033[0m"


def _free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---------------------------------------------------------------------------
# Gateway lifecycle
# ---------------------------------------------------------------------------


def _start_gateway(port: int) -> subprocess.Popen[bytes]:
    env = {**os.environ, "MGP_ADAPTER": "memory"}
    proc = subprocess.Popen(
        [sys.executable, "-m", "gateway", "--host", "127.0.0.1", "--port", str(port)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=0.5):
                return proc
        except Exception:
            time.sleep(0.2)
    proc.terminate()
    raise RuntimeError(f"mgp-gateway did not become healthy on :{port}")


# ---------------------------------------------------------------------------
# Loop builder
# ---------------------------------------------------------------------------


def _make_loop(*, gateway_url: str, default_user_id: str | None, tmp_path: Path) -> AgentLoop:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings(max_tokens=0)
    provider.estimate_prompt_tokens.return_value = (0, "test-counter")
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(content="ok", tool_calls=[]))
    provider.chat_stream_with_retry = AsyncMock(
        return_value=LLMResponse(content="ok", tool_calls=[])
    )

    cfg = MGPConfig(
        enabled=True,
        gateway_url=gateway_url,
        default_user_id=default_user_id,
        # keep both commit channels on so we can exercise them
        enable_consolidator_commit=True,
        enable_dream_commit=True,
    )
    return AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        mgp_config=cfg,
    )


async def _drain_background_tasks() -> None:
    """Let asyncio.create_task fan-outs run to completion."""
    pending = [
        t for t in asyncio.all_tasks() if not t.done() and t is not asyncio.current_task()
    ]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------


async def _call_recall(loop: AgentLoop, **kwargs: Any) -> str:
    tool: MGPRecallTool = loop.tools.get("recall_memory")  # type: ignore[assignment]
    return await tool.execute(**kwargs)


async def scenario_1_recall_when_empty(loop: AgentLoop) -> tuple[bool, str]:
    loop._set_tool_context(channel="cli", chat_id="alice", message_id="m1")
    text = await _call_recall(loop, query="anything")
    ok = "no memories found" in text.lower()
    return ok, f"recall returned: {text!r}"


async def scenario_2_consolidator_commit(loop: AgentLoop) -> tuple[bool, str]:
    loop.provider.chat_with_retry = AsyncMock(
        return_value=LLMResponse(content="- User has a cat named Luna", tool_calls=[])
    )
    session = loop.sessions.get_or_create("cli:alice")
    session.messages = [{"role": "user", "content": "I love cats", "timestamp": "2026-01-01T00:00:00"}]
    summary = await loop.consolidator.archive(session.messages, session=session)
    await _drain_background_tasks()
    ok = summary == "- User has a cat named Luna"
    return ok, f"archive returned: {summary!r}"


async def scenario_3_dream_phase1_commit(loop: AgentLoop) -> tuple[bool, str]:
    analysis = (
        "[USER] prefers replies in 中文\n"
        "[MEMORY] runs nanobot on macOS\n"
        "[SOUL] friendly, terse"
    )
    loop.dream.on_phase1_analysis(analysis)
    await _drain_background_tasks()
    last = loop.mgp_sidecar.last_commits
    return bool(last), f"recorded {len(last)} commit outcome(s); last written={last[-1].written if last else None}"


async def scenario_4_recall_finds_prior_commit(loop: AgentLoop) -> tuple[bool, str]:
    """Closes the loop: write -> wait for adapter -> search returns the bullet."""
    loop._set_tool_context(channel="cli", chat_id="alice", message_id="m4")
    text = await _call_recall(loop, query="cat", scope="user", limit=5)
    ok = "luna" in text.lower() or "cat" in text.lower()
    return ok, f"recall returned: {text!r}"


async def scenario_5_subject_chat_id_wins(loop: AgentLoop) -> tuple[bool, str]:
    """Telegram-style chat with a real chat_id should write under that id."""
    runtime = loop.mgp_sidecar.build_runtime(
        channel="telegram", chat_id="user_999", session_key="telegram:user_999"
    )
    return runtime.user_id == "user_999", f"derived user_id={runtime.user_id!r}"


async def scenario_6_dream_subject_falls_back_to_default(loop: AgentLoop) -> tuple[bool, str]:
    """Dream uses chat_id='dream' (synthetic) — must hit default_user_id."""
    runtime = loop.mgp_sidecar.build_runtime(
        channel="system", chat_id="dream", session_key="system:dream"
    )
    return runtime.user_id == "alice", f"derived user_id={runtime.user_id!r}"


async def scenario_7_fail_open_when_gateway_down(tmp_path: Path) -> tuple[bool, str]:
    """Point the sidecar at a black-hole port: recall_memory must degrade, not crash."""
    bad_loop = _make_loop(
        gateway_url="http://127.0.0.1:1",  # nothing listens here
        default_user_id="alice",
        tmp_path=tmp_path / "fail_open",
    )
    bad_loop._set_tool_context(channel="cli", chat_id="alice", message_id="m7")
    try:
        text = await _call_recall(bad_loop, query="ping")
    except Exception as e:
        return False, f"raised {type(e).__name__}: {e}"
    ok = "degraded" in text.lower() or "no memories" in text.lower()
    return ok, f"got: {text!r}"


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


async def _run_all(tmp_path: Path, gateway_url: str) -> int:
    loop = _make_loop(gateway_url=gateway_url, default_user_id="alice", tmp_path=tmp_path)

    scenarios = [
        ("1. recall returns 'no memories' when MGP is empty", scenario_1_recall_when_empty(loop)),
        ("2. Consolidator archive commits bullet to MGP",      scenario_2_consolidator_commit(loop)),
        ("3. Dream Phase-1 hook commits tagged analysis",      scenario_3_dream_phase1_commit(loop)),
        ("4. Recall finds the prior commit (write→search)",    scenario_4_recall_finds_prior_commit(loop)),
        ("5. Subject derivation: real chat_id wins",           scenario_5_subject_chat_id_wins(loop)),
        ("6. Subject derivation: Dream → default_user_id",     scenario_6_dream_subject_falls_back_to_default(loop)),
        ("7. Fail-open when gateway is unreachable",           scenario_7_fail_open_when_gateway_down(tmp_path)),
    ]

    failures = 0
    for label, coro in scenarios:
        try:
            ok, detail = await coro
        except Exception as e:
            ok, detail = False, f"raised {type(e).__name__}: {e}"
        marker = PASS if ok else FAIL
        print(f"  {marker}  {label}")
        print(f"        {detail}")
        if not ok:
            failures += 1
    return failures


def main() -> int:
    import tempfile

    port = _free_port()
    gateway_url = f"http://127.0.0.1:{port}"
    print(f"{INFO} starting mgp-gateway (memory adapter) on :{port}")
    proc = _start_gateway(port)
    try:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            print(f"{INFO} workspace: {tmp_path}")
            print(f"{INFO} running 7 scenarios")
            print()
            failures = asyncio.run(_run_all(tmp_path, gateway_url))
        print()
        if failures == 0:
            print(f"{PASS}  all 7 scenarios passed")
            return 0
        print(f"{FAIL}  {failures}/7 scenario(s) failed")
        return 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    sys.exit(main())
