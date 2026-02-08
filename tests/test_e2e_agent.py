import asyncio
import os

import pytest
from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.providers.lazyllm_provider import LazyLLMProvider


SOURCE = "doubao"
API_KEY = os.getenv("NANOBOT_TEST_DOUBAO_API_KEY", "")
MODEL = "doubao-seed-1-8-251228"
MODEL_WITH_SOURCE = f"{SOURCE}/{MODEL}"


def test_agent_loop_minimal_e2e(tmp_path):
    if not API_KEY:
        pytest.skip("Set NANOBOT_TEST_DOUBAO_API_KEY to run real network E2E.")
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    target_file = workspace / "note.txt"
    target_file.write_text("hello-e2e", encoding="utf-8")

    provider = LazyLLMProvider(
        api_key=API_KEY,
        default_model=MODEL_WITH_SOURCE,
        type="LLM",
    )
    bus = MessageBus()
    agent = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=workspace,
        model=MODEL_WITH_SOURCE,
        max_iterations=4,
        brave_api_key=None,
    )

    output = asyncio.run(
        agent.process_direct(
            f"请调用 read_file 工具读取文件 {target_file}，并只回复文件原文，不要添加任何其他内容。",
            session_key=f"cli:e2e-{tmp_path.name}",
        )
    )
    print(f"\nE2E output:\n{output}\n")
    assert output
    assert "Error calling LLM" not in output
