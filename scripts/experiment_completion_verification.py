"""Offline fault-injection experiment for main and child completion gates.

Run: uv run --no-sync python -m scripts.experiment_completion_verification
Optionally pass --output /tmp/completion-experiment.json to preserve raw results.
The baseline disables the new gate in the same checkout. A deterministic review
oracle inspects actual tool receipts; this measures lifecycle enforcement, not
the accuracy, latency, or token cost of a live LLM reviewer.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path
from threading import Thread
from unittest.mock import MagicMock, patch

from loguru import logger

from nanobot.agent.completion import CompletionVerifier
from nanobot.agent.loop import AgentLoop
from nanobot.agent.runner import AgentRunner, AgentRunSpec
from nanobot.agent.subagent import SubagentManager
from nanobot.agent.tools.filesystem import ListDirTool, ReadFileTool, WriteFileTool
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.loader import get_config_path, set_config_path
from nanobot.providers.base import (
    GenerationSettings,
    LLMProvider,
    LLMResponse,
    LLMUsage,
    ToolCallRequest,
)
from nanobot.session.goal_state import GOAL_STATE_KEY
from nanobot.utils.llm_runtime import LLMRuntime

CRITERIA = "result.txt contains answer=42 and has been read back after the write."
SCENARIOS = (
    "success", "false_claim", "repairable_claim", "tool_error", "iteration_limit",
    "provider_error", "refusal", "cancelled", "review_unavailable",
)


async def no_consolidation(_messages, _previous_summary):
    return None


def tool_response(call_id, name, **arguments):
    return LLMResponse(content=None, tool_calls=[ToolCallRequest(call_id, name, arguments)])


class ScriptedTask:
    """Keep the builder independent from the review oracle and ground truth."""

    def __init__(self, scenario, *, goal, gated):
        self.scenario, self.goal, self.gated = scenario, goal, gated
        self.builder_calls = self.review_calls = self.step = 0
        self.reported_tokens = 0
        self.provider = MagicMock(spec=LLMProvider)
        self.provider.provider_name = "offline-completion-experiment"
        self.provider.generation = GenerationSettings()
        self.provider.get_default_model.return_value = "scripted"
        self.provider.estimate_prompt_tokens = lambda *_args: (100, "scripted")
        self.provider.chat_stream_with_retry = self.build
        self.provider.chat_with_retry = self.review

    async def build(self, *, messages, **_kwargs):
        self.builder_calls += 1
        self.reported_tokens += 15
        if self.goal and self.builder_calls == 1:
            arguments = {"objective": "Create and verify result.txt"}
            if self.gated:
                arguments["acceptance_criteria"] = CRITERIA
            response = tool_response("create", "create_goal", **arguments)
        elif self.goal and any(
            message.get("role") == "tool" and any(marker in str(message.get("content")) for marker in (
                "Goal marked complete", "not verified (exhausted)", "not verified (blocked)",
            )) for message in messages
        ):
            response = LLMResponse(content="The task has stopped; use its recorded completion status.")
        else:
            response = self.next_action()
            if self.goal and response.finish_reason == "stop" and not response.has_tool_calls:
                response = tool_response(f"finish-{self.step}", "update_goal", action="complete", recap=response.content)
        response.usage = LLMUsage.reported(input_tokens=10, output_tokens=5)
        return response

    def next_action(self):
        step = self.step
        self.step += 1
        if self.scenario == "cancelled":
            raise asyncio.CancelledError()
        if self.scenario in {"provider_error", "refusal"}:
            return LLMResponse(content="Provider cannot execute this task.", finish_reason="error" if self.scenario == "provider_error" else "refusal")
        if self.scenario == "iteration_limit":
            return tool_response(f"list-{step}", "list_dir", path=".")
        if self.scenario == "tool_error":
            return tool_response("read-missing", "read_file", path="missing.txt") if step == 0 else LLMResponse(content="Done; the missing file was verified.")
        if self.scenario == "false_claim":
            return LLMResponse(content="Done; result.txt is correct.")
        if self.scenario == "repairable_claim":
            if step == 0:
                return LLMResponse(content="Done; result.txt is correct.")
            step -= 1
        if step == 0:
            return tool_response("write", "write_file", path="result.txt", content="answer=42")
        if step == 1:
            return tool_response("read", "read_file", path="result.txt")
        return LLMResponse(content="Wrote result.txt and read back answer=42.")

    async def review(self, *, messages, **_kwargs):
        self.review_calls += 1
        if self.scenario == "review_unavailable":
            raise RuntimeError("Injected reviewer outage")
        self.reported_tokens += 28
        payload = json.loads(messages[1]["content"])
        receipts = [item for item in payload["evidence"] if item["kind"] == "tool_result"]
        readbacks = [item for item in receipts if item["name"] == "read_file" and item.get("status") == "ok" and "answer=42" in item["result"]]
        verified = bool(readbacks)
        return LLMResponse(
            content=json.dumps({
                "status": "verified" if verified else "needs_revision",
                "reason": "Successful readback meets the criteria." if verified else "No successful readback. Write the required file and read it.",
                "evidence_ids": [readbacks[-1]["id"]] if verified else ["candidate"],
            }),
            usage=LLMUsage.reported(input_tokens=20, output_tokens=8),
        )


async def run_case(root, surface, scenario, gated):
    workspace = root / f"{surface}-{scenario}-{int(gated)}"
    workspace.mkdir()
    set_config_path(root / "runtime" / workspace.name / "config.json")
    task = ScriptedTask(scenario, goal=surface == "goal", gated=gated)
    runtime = LLMRuntime.capture(task.provider, "scripted", context_window_tokens=128_000)
    # Both arms receive the same total call ceiling. Reserve review capacity
    # from the treatment's builder allowance and one finalization request for
    # the main goal's iteration-limit path (also counted as a builder call).
    total_budget = 8 if surface == "goal" else 6
    builder_budget = total_budget - (2 if gated else 0) - (1 if surface == "goal" else 0)
    accepted, status, stop_reason, completion = False, "cancelled", "cancelled", None
    try:
        if surface == "goal":
            loop = AgentLoop(bus=MessageBus(), provider=task.provider, workspace=workspace, model="scripted", max_iterations=builder_budget)
            try:
                await loop._process_message(InboundMessage(channel="cli", sender_id="experiment", chat_id="case", content=f"/goal {CRITERIA}"))
                goal = loop.sessions.get_or_create("cli:case").metadata[GOAL_STATE_KEY]
                status, completion = goal["status"], goal.get("completion")
                accepted = status == "completed"
                stop_reason = status
            finally:
                await loop.subagents.close()
        elif surface == "subagent":
            manager = SubagentManager(workspace=workspace, bus=MessageBus(), max_tool_result_chars=16_000, consolidator=MagicMock(), max_iterations=builder_budget)
            try:
                await manager.run_inline(task="Create and verify result.txt", runtime=runtime, acceptance_criteria=CRITERIA if gated else None)
                child = next(iter(manager.statuses_for_session("cli:direct").values()))
                status, stop_reason = child.state, child.stop_reason
                completion = child.completion.as_dict() if child.completion else None
                accepted = status == "done"
            finally:
                await manager.close()
        else:
            tools = ToolRegistry()
            for cls in (WriteFileTool, ReadFileTool, ListDirTool):
                tools.register(cls(workspace=workspace))
            result = await AgentRunner().run(AgentRunSpec(
                initial_messages=[{"role": "user", "content": CRITERIA}], tools=tools,
                runtime=runtime, max_iterations=builder_budget, max_tool_result_chars=16_000,
                consolidate_history=no_consolidation, finalize_on_max_iterations=False,
                completion_verifier=CompletionVerifier(runtime, CRITERIA) if gated else None,
            ))
            status = stop_reason = result.stop_reason
            completion = result.completion.as_dict() if result.completion else None
            accepted = stop_reason == "completed"
    except asyncio.CancelledError:
        pass
    artifact = workspace / "result.txt"
    correct = artifact.exists() and artifact.read_text(encoding="utf-8") == "answer=42"
    calls = task.builder_calls + task.review_calls
    if calls > total_budget:
        raise AssertionError(f"{surface}/{scenario} exceeded total call budget: {calls}>{total_budget}")
    if scenario == "success" or (scenario == "repairable_claim" and gated):
        if not accepted or not correct:
            raise AssertionError(f"{surface}/{scenario} rejected a successful supported path")
    if gated and accepted and not correct:
        raise AssertionError(f"{surface}/{scenario} accepted an incorrect artifact")
    if scenario in {"provider_error", "refusal", "cancelled", "iteration_limit"} and accepted:
        raise AssertionError(f"{surface}/{scenario} incorrectly accepted a stopped task")
    return {
        "surface": surface, "scenario": scenario, "mode": "gated" if gated else "disabled",
        "artifact_correct": correct, "accepted": accepted, "false_accept": accepted and not correct,
        "valid_but_not_accepted": correct and not accepted, "status": status, "stop_reason": stop_reason,
        "completion": completion, "builder_calls": task.builder_calls, "review_calls": task.review_calls,
        "total_calls": calls, "call_budget": total_budget, "synthetic_reported_tokens": task.reported_tokens,
    }


async def experiment():
    previous_config = get_config_path()
    rows = []
    logger.disable("nanobot")
    try:
        with tempfile.TemporaryDirectory(prefix="nanobot-completion-") as directory, patch("nanobot.utils.token_encoding._warmup_thread", Thread()):
            for surface in ("runner", "goal", "subagent"):
                for scenario in SCENARIOS:
                    for gated in (False, True):
                        rows.append(await run_case(Path(directory), surface, scenario, gated))
    finally:
        set_config_path(previous_config)
        logger.enable("nanobot")
    summaries = []
    for surface in ("runner", "goal", "subagent"):
        for mode in ("disabled", "gated"):
            selected = [row for row in rows if row["surface"] == surface and row["mode"] == mode]
            summaries.append({"surface": surface, "mode": mode, **{
                key: sum(row[key] for row in selected)
                for key in ("accepted", "false_accept", "valid_but_not_accepted", "builder_calls", "review_calls", "total_calls")
            }})
    repo = Path(__file__).resolve().parent.parent
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()
    dirty = bool(subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True, check=True).stdout)
    source = hashlib.sha256()
    paths = [*(repo / "nanobot").rglob("*.py"), *(repo / "nanobot" / "templates").rglob("*.md"), Path(__file__).resolve(), repo / "pyproject.toml"]
    for path in sorted(paths):
        source.update(path.relative_to(repo).as_posix().encode() + b"\0" + path.read_bytes() + b"\0")
    return {"git_head": head, "working_tree_dirty": dirty, "source_sha256": source.hexdigest(), "method": "Same-checkout gate-disabled baseline; real file tools; scripted builder and receipt-based review oracle; equal total model-call ceilings. Synthetic usage is not measured model cost.", "summaries": summaries, "cases": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = asyncio.run(experiment())
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")


if __name__ == "__main__":
    main()
