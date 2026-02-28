"""Agent loop: the core processing engine."""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import weakref
from contextlib import AsyncExitStack
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from loguru import logger

from nanobot.agent.context import ContextBuilder
from nanobot.agent.memory import MemoryStore
from nanobot.agent.subagent import SubagentManager
from nanobot.agent.tools.cron import CronTool
from nanobot.agent.tools.filesystem import EditFileTool, ListDirTool, ReadFileTool, WriteFileTool
from nanobot.agent.tools.message import MessageTool
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.shell import ExecTool
from nanobot.agent.tools.spawn import SpawnTool
from nanobot.agent.tools.web import WebFetchTool, WebSearchTool
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMProvider
from nanobot.session.manager import Session, SessionManager

if TYPE_CHECKING:
    from nanobot.config.schema import ChannelsConfig, ExecToolConfig
    from nanobot.cron.service import CronService


class AgentLoop:
    """
    The agent loop is the core processing engine.

    It:
    1. Receives messages from the bus
    2. Builds context with history, memory, skills
    3. Calls the LLM
    4. Executes tool calls
    5. Sends responses back
    """

    _TOOL_RESULT_MAX_CHARS = 500
    _MOBILE_SHORTCUT_TIMEOUT_S = 120
    _APP_ID_RE = re.compile(r"(?<![A-Za-z0-9_])[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+(?![A-Za-z0-9_])")

    def __init__(
        self,
        bus: MessageBus,
        provider: LLMProvider,
        workspace: Path,
        model: str | None = None,
        max_iterations: int = 40,
        temperature: float = 0.1,
        max_tokens: int = 4096,
        memory_window: int = 100,
        brave_api_key: str | None = None,
        exec_config: ExecToolConfig | None = None,
        cron_service: CronService | None = None,
        restrict_to_workspace: bool = False,
        session_manager: SessionManager | None = None,
        mcp_servers: dict | None = None,
        channels_config: ChannelsConfig | None = None,
    ):
        from nanobot.config.schema import ExecToolConfig
        self.bus = bus
        self.channels_config = channels_config
        self.provider = provider
        self.workspace = workspace
        self.model = model or provider.get_default_model()
        self.max_iterations = max_iterations
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.memory_window = memory_window
        self.brave_api_key = brave_api_key
        self.exec_config = exec_config or ExecToolConfig()
        self.cron_service = cron_service
        self.restrict_to_workspace = restrict_to_workspace

        self.context = ContextBuilder(workspace)
        self.sessions = session_manager or SessionManager(workspace)
        self.tools = ToolRegistry()
        self.subagents = SubagentManager(
            provider=provider,
            workspace=workspace,
            bus=bus,
            model=self.model,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            brave_api_key=brave_api_key,
            exec_config=self.exec_config,
            restrict_to_workspace=restrict_to_workspace,
        )

        self._running = False
        self._mcp_servers = mcp_servers or {}
        self._mcp_stack: AsyncExitStack | None = None
        self._mcp_connected = False
        self._mcp_connecting = False
        self._consolidating: set[str] = set()  # Session keys with consolidation in progress
        self._consolidation_tasks: set[asyncio.Task] = set()  # Strong refs to in-flight tasks
        self._consolidation_locks: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()
        self._active_tasks: dict[str, list[asyncio.Task]] = {}  # session_key -> tasks
        self._processing_lock = asyncio.Lock()
        self._register_default_tools()

    def _register_default_tools(self) -> None:
        """Register the default set of tools."""
        allowed_dir = self.workspace if self.restrict_to_workspace else None
        for cls in (ReadFileTool, WriteFileTool, EditFileTool, ListDirTool):
            self.tools.register(cls(workspace=self.workspace, allowed_dir=allowed_dir))
        self.tools.register(ExecTool(
            working_dir=str(self.workspace),
            timeout=self.exec_config.timeout,
            restrict_to_workspace=self.restrict_to_workspace,
            path_append=self.exec_config.path_append,
        ))
        self.tools.register(WebSearchTool(api_key=self.brave_api_key))
        self.tools.register(WebFetchTool())
        self.tools.register(MessageTool(send_callback=self.bus.publish_outbound))
        self.tools.register(SpawnTool(manager=self.subagents))
        if self.cron_service:
            self.tools.register(CronTool(self.cron_service))

    async def _connect_mcp(self) -> None:
        """Connect to configured MCP servers (one-time, lazy)."""
        if self._mcp_connected or self._mcp_connecting or not self._mcp_servers:
            return
        self._mcp_connecting = True
        from nanobot.agent.tools.mcp import connect_mcp_servers
        try:
            self._mcp_stack = AsyncExitStack()
            await self._mcp_stack.__aenter__()
            await connect_mcp_servers(self._mcp_servers, self.tools, self._mcp_stack)
            self._mcp_connected = True
        except Exception as e:
            logger.error("Failed to connect MCP servers (will retry next message): {}", e)
            if self._mcp_stack:
                try:
                    await self._mcp_stack.aclose()
                except Exception:
                    pass
                self._mcp_stack = None
        finally:
            self._mcp_connecting = False

    def _set_tool_context(self, channel: str, chat_id: str, message_id: str | None = None) -> None:
        """Update context for all tools that need routing info."""
        for name in ("message", "spawn", "cron"):
            if tool := self.tools.get(name):
                if hasattr(tool, "set_context"):
                    tool.set_context(channel, chat_id, *([message_id] if name == "message" else []))

    @staticmethod
    def _strip_think(text: str | None) -> str | None:
        """Remove <think>…</think> blocks that some models embed in content."""
        if not text:
            return None
        return re.sub(r"<think>[\s\S]*?</think>", "", text).strip() or None

    @staticmethod
    def _tool_hint(tool_calls: list) -> str:
        """Format tool calls as concise hint, e.g. 'web_search("query")'."""
        def _fmt(tc):
            args = (tc.arguments[0] if isinstance(tc.arguments, list) else tc.arguments) or {}
            val = next(iter(args.values()), None) if isinstance(args, dict) else None
            if not isinstance(val, str):
                return tc.name
            return f'{tc.name}("{val[:40]}…")' if len(val) > 40 else f'{tc.name}("{val}")'
        return ", ".join(_fmt(tc) for tc in tool_calls)

    @classmethod
    def _extract_mobile_transfer_app_id(cls, content: str) -> str | None:
        """Detect 'open app and go to transfer page' intent from plain text."""
        text = (content or "").strip()
        if not text:
            return None
        lowered = text.lower()
        has_open = any(k in text for k in ("打开", "启动")) or any(k in lowered for k in ("open", "launch", "start"))
        has_transfer = any(k in text for k in ("转账", "转帳")) or any(k in lowered for k in ("transfer", "send"))
        if not (has_open and has_transfer):
            return None
        matched = cls._APP_ID_RE.search(text)
        return matched.group(0) if matched else None

    @staticmethod
    def _extract_selected_token_symbol(content: str) -> str | None:
        """Extract token symbol from user command, e.g. '选择ETH' / 'select ETH'."""
        text = (content or "").strip()
        if not text:
            return None
        lowered = text.lower()
        if "地址" in text or "address" in lowered:
            return None
        patterns = [
            r"(?:选择|选中|切换到)\s*([A-Za-z][A-Za-z0-9._-]{1,15})",
            r"(?:select|choose|pick)\s+([A-Za-z][A-Za-z0-9._-]{1,15})",
        ]
        for pattern in patterns:
            m = re.search(pattern, text, flags=re.IGNORECASE)
            if not m:
                continue
            symbol = re.sub(r"[^A-Za-z0-9_]", "", m.group(1).upper())
            if symbol:
                return symbol
        return None

    @staticmethod
    def _extract_address_network(content: str) -> str | None:
        """
        Extract address-network selection from text:
        e.g. '选择Ethereum地址' / 'select ethereum address'
        """
        text = (content or "").strip()
        if not text:
            return None
        patterns = [
            r"(?:选择|选中|切换到)\s*([A-Za-z][A-Za-z0-9._-]{1,20})\s*地址",
            r"(?:select|choose|pick)\s+([A-Za-z][A-Za-z0-9._-]{1,20})\s+address",
        ]
        for pattern in patterns:
            m = re.search(pattern, text, flags=re.IGNORECASE)
            if not m:
                continue
            token = re.sub(r"[^A-Za-z0-9._-]", "", m.group(1)).strip()
            if token:
                return token
        return None

    @staticmethod
    def _extract_input_payload(content: str) -> str | None:
        """Extract input payload from text, e.g. '输入0x11111' / 'input 0x11111'."""
        text = (content or "").strip()
        if not text:
            return None
        patterns = [
            r"(?:输入|填入|粘贴)\s*([^\s，,。；;]+)",
            r"(?:input|type|enter)\s+([^\s，,。；;]+)",
        ]
        for pattern in patterns:
            m = re.search(pattern, text, flags=re.IGNORECASE)
            if not m:
                continue
            payload = m.group(1).strip()
            if payload:
                return payload
        return None

    @staticmethod
    def _yaml_quote(value: str) -> str:
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f"\"{escaped}\""

    @staticmethod
    def _split_instruction_segments(content: str) -> list[str]:
        """Split natural-language command into ordered segments."""
        text = (content or "").strip()
        if not text:
            return []
        return [seg.strip() for seg in re.split(r"[，,。；;、\n]+", text) if seg.strip()]

    @classmethod
    def _build_mobile_flow_from_instruction(cls, app_id: str, instruction: str) -> tuple[list[str], str]:
        """
        Build Maestro flow lines from instruction semantics instead of fixed script.

        Supported action segments:
        - enter transfer page
        - select token symbol (e.g. ETH/USDT)
        """
        segments = cls._split_instruction_segments(instruction)
        transfer_opened = False
        screenshot_idx = 0
        action_desc: list[str] = []

        flow_lines = [
            f"appId: {app_id}",
            "---",
            "- launchApp",
        ]
        action_desc.append("打开应用")

        def _append_open_transfer() -> None:
            nonlocal transfer_opened
            if transfer_opened:
                return
            flow_lines.extend(
                [
                    "- assertVisible:",
                    '    id: "FunctionBar.转账"',
                    "- tapOn:",
                    '    id: "FunctionBar.转账"',
                    "- assertVisible:",
                    '    id: "modal-header-close-button"',
                ]
            )
            transfer_opened = True
            action_desc.append("进入转账页面")

        for seg in segments:
            lowered = seg.lower()
            if ("转账" in seg) or ("transfer" in lowered):
                _append_open_transfer()

            if selected_token := cls._extract_selected_token_symbol(seg):
                _append_open_transfer()
                token_id = f"TokenSelectModal.TokenSymbol.{selected_token}"
                flow_lines.extend(
                    [
                        "- assertVisible:",
                        f'    id: "{token_id}"',
                        "- tapOn:",
                        f'    id: "{token_id}"',
                    ]
                )
                action_desc.append(f"选择{selected_token}")

            if addr_network := cls._extract_address_network(seg):
                flow_lines.extend(
                    [
                        "- tapOn:",
                        f"    text: {cls._yaml_quote(addr_network)}",
                    ]
                )
                action_desc.append(f"选择{addr_network}地址")

            if payload := cls._extract_input_payload(seg):
                flow_lines.append(f"- inputText: {cls._yaml_quote(payload)}")
                action_desc.append(f"输入{payload}")

            if any(k in seg for k in ("截图", "截屏", "屏幕截图")) or any(k in lowered for k in ("screenshot", "screen shot", "snapshot")):
                screenshot_idx += 1
                flow_lines.append(f"- takeScreenshot: shot-{screenshot_idx:02d}")
                action_desc.append("截图")

            if ("返回" in seg) or ("回退" in seg) or ("back" in lowered):
                flow_lines.append("- back")
                action_desc.append("返回")

        flow_lines.append("")
        if len(action_desc) <= 1:
            target_desc = action_desc[0]
        else:
            target_desc = "，".join(action_desc[1:])
        return flow_lines, target_desc

    @staticmethod
    def _classify_mobile_failure(stdout_text: str, stderr_text: str) -> str:
        """Classify failure reason into user-facing categories."""
        combined = f"{stdout_text}\n{stderr_text}"
        text = combined.lower()
        if "not enough devices connected" in text or "0 devices connected" in text:
            return "未检测到可用设备"
        if re.search(r"launch app .*?\.\.\. failed", text) or "unable to launch app" in text:
            return "应用启动失败"
        if m := re.search(r"assert that (.+?)\.\.\. failed", combined, flags=re.IGNORECASE):
            detail = m.group(1).strip()
            return f"页面断言失败（{detail}）"
        if m := re.search(r"tap on (.+?)\.\.\. failed", combined, flags=re.IGNORECASE):
            detail = m.group(1).strip()
            return f"点击失败（{detail}）"
        if m := re.search(r"input text (.+?)\.\.\. failed", combined, flags=re.IGNORECASE):
            detail = m.group(1).strip()
            return f"输入失败（{detail}）"
        if "assert" in text and "failed" in text:
            return "页面断言失败"
        if "timeout" in text or "timed out" in text:
            return "执行超时"
        return "Maestro执行失败"

    @staticmethod
    def _summarize_mobile_result(final_content: str) -> str:
        """Build a short completion notification for remote channels."""
        content = (final_content or "").strip()
        run_id_match = re.search(r"runId:\s*([^\n]+)", content)
        run_id = run_id_match.group(1).strip() if run_id_match else ""
        reason_match = re.search(r"reason:\s*([^\n]+)", content)
        reason = reason_match.group(1).strip() if reason_match else ""
        success = content.startswith("已完成移动自动化测试")
        if success:
            base = "移动自动化任务已结束：成功。"
            return f"{base}\nrunId: {run_id}" if run_id else base
        base = f"移动自动化任务已结束：失败。{reason}" if reason else "移动自动化任务已结束：失败。"
        return f"{base}\nrunId: {run_id}" if run_id else base

    async def _run_mobile_transfer_shortcut(
        self,
        app_id: str,
        *,
        instruction: str,
        expose_paths: bool = True,
        timeout_s: int | None = None,
        on_progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> str:
        """
        Generate and run Maestro flow from explicit user command:
        launch app -> open transfer -> optional token selection.
        """
        if shutil.which("maestro") is None:
            return (
                "检测到移动测试指令，但未找到 maestro CLI。"
                "请先安装 maestro（curl -fsSL \"https://get.maestro.mobile.dev\" | bash）。"
            )

        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        app_slug = re.sub(r"[^a-z0-9]+", "-", app_id.lower()).strip("-") or "app"
        run_id = f"intent-{stamp}-{app_slug[:24]}"

        flow_dir = self.workspace / "mobile" / "flows" / "generated"
        run_dir = self.workspace / "reports" / "mobile" / "runs" / run_id
        artifact_dir = self.workspace / "reports" / "mobile" / "artifacts" / run_id / "transfer"
        maestro_home = self.workspace / ".maestro-home"
        flow_dir.mkdir(parents=True, exist_ok=True)
        run_dir.mkdir(parents=True, exist_ok=True)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        maestro_home.mkdir(parents=True, exist_ok=True)

        flow_lines, target_desc = self._build_mobile_flow_from_instruction(app_id, instruction)

        flow_file = flow_dir / f"{run_id}.yaml"
        log_file = run_dir / "transfer.log"
        flow_file.write_text("\n".join(flow_lines), encoding="utf-8")
        timeout = timeout_s or self._MOBILE_SHORTCUT_TIMEOUT_S
        if on_progress:
            await on_progress(f"已生成脚本，准备执行：{target_desc}（timeout={timeout}s）")

        cmd = ["maestro", "test", str(flow_file), "--test-output-dir", str(artifact_dir)]
        env = dict(os.environ)
        env["HOME"] = str(maestro_home)
        existing_opts = env.get("MAESTRO_OPTS", "").strip()
        user_home_opt = f"-Duser.home={maestro_home}"
        env["MAESTRO_OPTS"] = f"{existing_opts} {user_home_opt}".strip()
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(self.workspace),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            log_file.write_text(
                f"$ {' '.join(cmd)}\n\n[timeout] execution exceeded {timeout}s\n",
                encoding="utf-8",
            )
            if on_progress:
                await on_progress(f"执行超时：{timeout}s")
            if not expose_paths:
                return (
                    f"移动自动化执行超时（{timeout}s）。\n"
                    f"app: {app_id}\n"
                    f"runId: {run_id}\n"
                    "详情日志已保存到本地服务器（已脱敏，不返回本地目录路径）。"
                )
            return (
                f"移动自动化执行超时（{timeout}s）。\n"
                f"flow: {flow_file}\nlog: {log_file}\nartifact: {artifact_dir}"
            )

        stdout_text = (stdout_bytes or b"").decode("utf-8", errors="replace")
        stderr_text = (stderr_bytes or b"").decode("utf-8", errors="replace")
        log_file.write_text(
            f"$ {' '.join(cmd)}\n\nSTDOUT:\n{stdout_text}\n\nSTDERR:\n{stderr_text}\n",
            encoding="utf-8",
        )

        if proc.returncode == 0:
            if on_progress:
                await on_progress("执行完成：通过")
            if not expose_paths:
                return (
                    "已完成移动自动化测试。\n"
                    f"app: {app_id}\n"
                    f"target: {target_desc}\n"
                    f"runId: {run_id}\n"
                    "执行证据已保存到本地服务器（已脱敏，不返回本地目录路径）。"
                )
            return (
                "已完成移动自动化测试。\n"
                f"app: {app_id}\n"
                f"target: {target_desc}\n"
                f"flow: {flow_file}\n"
                f"log: {log_file}\n"
                f"artifact: {artifact_dir}"
            )

        reason = self._classify_mobile_failure(stdout_text, stderr_text)
        if on_progress:
            await on_progress(f"执行失败：{reason}")
        tail = "\n".join((stdout_text + "\n" + stderr_text).strip().splitlines()[-20:])
        if not expose_paths:
            return (
                "移动自动化测试执行失败。\n"
                f"app: {app_id}\n"
                f"reason: {reason}\n"
                f"runId: {run_id}\n"
                "详情日志已保存到本地服务器（已脱敏，不返回本地目录路径）。"
            )
        return (
            "移动自动化测试执行失败。\n"
            f"app: {app_id}\n"
            f"reason: {reason}\n"
            f"flow: {flow_file}\n"
            f"log: {log_file}\n"
            f"artifact: {artifact_dir}\n"
            "最后输出:\n"
            f"{tail}"
        )

    async def _run_agent_loop(
        self,
        initial_messages: list[dict],
        on_progress: Callable[..., Awaitable[None]] | None = None,
    ) -> tuple[str | None, list[str], list[dict]]:
        """Run the agent iteration loop. Returns (final_content, tools_used, messages)."""
        messages = initial_messages
        iteration = 0
        final_content = None
        tools_used: list[str] = []

        while iteration < self.max_iterations:
            iteration += 1

            response = await self.provider.chat(
                messages=messages,
                tools=self.tools.get_definitions(),
                model=self.model,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )

            if response.has_tool_calls:
                if on_progress:
                    clean = self._strip_think(response.content)
                    if clean:
                        await on_progress(clean)
                    await on_progress(self._tool_hint(response.tool_calls), tool_hint=True)

                tool_call_dicts = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments, ensure_ascii=False)
                        }
                    }
                    for tc in response.tool_calls
                ]
                messages = self.context.add_assistant_message(
                    messages, response.content, tool_call_dicts,
                    reasoning_content=response.reasoning_content,
                )

                for tool_call in response.tool_calls:
                    tools_used.append(tool_call.name)
                    args_str = json.dumps(tool_call.arguments, ensure_ascii=False)
                    logger.info("Tool call: {}({})", tool_call.name, args_str[:200])
                    result = await self.tools.execute(tool_call.name, tool_call.arguments)
                    messages = self.context.add_tool_result(
                        messages, tool_call.id, tool_call.name, result
                    )
            else:
                clean = self._strip_think(response.content)
                # Don't persist error responses to session history — they can
                # poison the context and cause permanent 400 loops (#1303).
                if response.finish_reason == "error":
                    logger.error("LLM returned error: {}", (clean or "")[:200])
                    final_content = clean or "Sorry, I encountered an error calling the AI model."
                    break
                messages = self.context.add_assistant_message(
                    messages, clean, reasoning_content=response.reasoning_content,
                )
                final_content = clean
                break

        if final_content is None and iteration >= self.max_iterations:
            logger.warning("Max iterations ({}) reached", self.max_iterations)
            final_content = (
                f"I reached the maximum number of tool call iterations ({self.max_iterations}) "
                "without completing the task. You can try breaking the task into smaller steps."
            )

        return final_content, tools_used, messages

    async def run(self) -> None:
        """Run the agent loop, dispatching messages as tasks to stay responsive to /stop."""
        self._running = True
        logger.info("Agent loop started")

        while self._running:
            try:
                msg = await asyncio.wait_for(self.bus.consume_inbound(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            if msg.content.strip().lower() == "/stop":
                await self._handle_stop(msg)
            else:
                task = asyncio.create_task(self._dispatch(msg))
                self._active_tasks.setdefault(msg.session_key, []).append(task)
                task.add_done_callback(lambda t, k=msg.session_key: self._active_tasks.get(k, []) and self._active_tasks[k].remove(t) if t in self._active_tasks.get(k, []) else None)

    async def _handle_stop(self, msg: InboundMessage) -> None:
        """Cancel all active tasks and subagents for the session."""
        tasks = self._active_tasks.pop(msg.session_key, [])
        cancelled = sum(1 for t in tasks if not t.done() and t.cancel())
        for t in tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        sub_cancelled = await self.subagents.cancel_by_session(msg.session_key)
        total = cancelled + sub_cancelled
        content = f"⏹ Stopped {total} task(s)." if total else "No active task to stop."
        await self.bus.publish_outbound(OutboundMessage(
            channel=msg.channel, chat_id=msg.chat_id, content=content,
        ))

    async def _dispatch(self, msg: InboundMessage) -> None:
        """Process a message under the global lock."""
        async with self._processing_lock:
            try:
                response = await self._process_message(msg)
                if response is not None:
                    await self.bus.publish_outbound(response)
                elif msg.channel == "cli":
                    await self.bus.publish_outbound(OutboundMessage(
                        channel=msg.channel, chat_id=msg.chat_id,
                        content="", metadata=msg.metadata or {},
                    ))
            except asyncio.CancelledError:
                logger.info("Task cancelled for session {}", msg.session_key)
                raise
            except Exception:
                logger.exception("Error processing message for session {}", msg.session_key)
                await self.bus.publish_outbound(OutboundMessage(
                    channel=msg.channel, chat_id=msg.chat_id,
                    content="Sorry, I encountered an error.",
                ))

    async def close_mcp(self) -> None:
        """Close MCP connections."""
        if self._mcp_stack:
            try:
                await self._mcp_stack.aclose()
            except (RuntimeError, BaseExceptionGroup):
                pass  # MCP SDK cancel scope cleanup is noisy but harmless
            self._mcp_stack = None

    def stop(self) -> None:
        """Stop the agent loop."""
        self._running = False
        logger.info("Agent loop stopping")

    async def _process_message(
        self,
        msg: InboundMessage,
        session_key: str | None = None,
        on_progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> OutboundMessage | None:
        """Process a single inbound message and return the response."""
        # System messages: parse origin from chat_id ("channel:chat_id")
        if msg.channel == "system":
            await self._connect_mcp()
            channel, chat_id = (msg.chat_id.split(":", 1) if ":" in msg.chat_id
                                else ("cli", msg.chat_id))
            logger.info("Processing system message from {}", msg.sender_id)
            key = f"{channel}:{chat_id}"
            session = self.sessions.get_or_create(key)
            self._set_tool_context(channel, chat_id, msg.metadata.get("message_id"))
            history = session.get_history(max_messages=self.memory_window)
            messages = self.context.build_messages(
                history=history,
                current_message=msg.content, channel=channel, chat_id=chat_id,
            )
            final_content, _, all_msgs = await self._run_agent_loop(messages)
            self._save_turn(session, all_msgs, 1 + len(history))
            self.sessions.save(session)
            return OutboundMessage(channel=channel, chat_id=chat_id,
                                  content=final_content or "Background task completed.")

        preview = msg.content[:80] + "..." if len(msg.content) > 80 else msg.content
        logger.info("Processing message from {}:{}: {}", msg.channel, msg.sender_id, preview)

        key = session_key or msg.session_key
        session = self.sessions.get_or_create(key)

        # Slash commands
        cmd = msg.content.strip().lower()
        if cmd == "/new":
            lock = self._consolidation_locks.setdefault(session.key, asyncio.Lock())
            self._consolidating.add(session.key)
            try:
                async with lock:
                    snapshot = session.messages[session.last_consolidated:]
                    if snapshot:
                        temp = Session(key=session.key)
                        temp.messages = list(snapshot)
                        if not await self._consolidate_memory(temp, archive_all=True):
                            return OutboundMessage(
                                channel=msg.channel, chat_id=msg.chat_id,
                                content="Memory archival failed, session not cleared. Please try again.",
                            )
            except Exception:
                logger.exception("/new archival failed for {}", session.key)
                return OutboundMessage(
                    channel=msg.channel, chat_id=msg.chat_id,
                    content="Memory archival failed, session not cleared. Please try again.",
                )
            finally:
                self._consolidating.discard(session.key)

            session.clear()
            self.sessions.save(session)
            self.sessions.invalidate(session.key)
            return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id,
                                  content="New session started.")
        if cmd == "/help":
            return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id,
                                  content="🐈 nanobot commands:\n/new — Start a new conversation\n/stop — Stop the current task\n/help — Show available commands")

        async def _shortcut_progress(content: str, *, final: bool = False) -> None:
            if on_progress:
                await on_progress(content)
                return
            meta = dict(msg.metadata or {})
            if not final:
                meta["_progress"] = True
            await self.bus.publish_outbound(
                OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content=content, metadata=meta)
            )

        if app_id := self._extract_mobile_transfer_app_id(msg.content):
            await _shortcut_progress(f"Detected mobile transfer intent for {app_id}; running Maestro flow.")
            expose_paths = msg.channel in {"cli", "system"}
            final_content = await self._run_mobile_transfer_shortcut(
                app_id,
                instruction=msg.content,
                expose_paths=expose_paths,
                timeout_s=self._MOBILE_SHORTCUT_TIMEOUT_S,
                on_progress=_shortcut_progress,
            )
            now = datetime.now().isoformat()
            completion_notice = self._summarize_mobile_result(final_content)
            await _shortcut_progress(completion_notice, final=True)
            session.messages.append({"role": "user", "content": msg.content, "timestamp": now})
            session.messages.append({"role": "assistant", "content": final_content, "timestamp": now})
            self.sessions.save(session)
            if msg.channel not in {"cli", "system"}:
                return None
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=final_content,
                metadata=msg.metadata or {},
            )

        unconsolidated = len(session.messages) - session.last_consolidated
        if (unconsolidated >= self.memory_window and session.key not in self._consolidating):
            self._consolidating.add(session.key)
            lock = self._consolidation_locks.setdefault(session.key, asyncio.Lock())

            async def _consolidate_and_unlock():
                try:
                    async with lock:
                        await self._consolidate_memory(session)
                finally:
                    self._consolidating.discard(session.key)
                    _task = asyncio.current_task()
                    if _task is not None:
                        self._consolidation_tasks.discard(_task)

            _task = asyncio.create_task(_consolidate_and_unlock())
            self._consolidation_tasks.add(_task)

        self._set_tool_context(msg.channel, msg.chat_id, msg.metadata.get("message_id"))
        if message_tool := self.tools.get("message"):
            if isinstance(message_tool, MessageTool):
                message_tool.start_turn()

        await self._connect_mcp()

        history = session.get_history(max_messages=self.memory_window)
        initial_messages = self.context.build_messages(
            history=history,
            current_message=msg.content,
            media=msg.media if msg.media else None,
            channel=msg.channel, chat_id=msg.chat_id,
        )

        async def _bus_progress(content: str, *, tool_hint: bool = False) -> None:
            meta = dict(msg.metadata or {})
            meta["_progress"] = True
            meta["_tool_hint"] = tool_hint
            await self.bus.publish_outbound(OutboundMessage(
                channel=msg.channel, chat_id=msg.chat_id, content=content, metadata=meta,
            ))

        final_content, _, all_msgs = await self._run_agent_loop(
            initial_messages, on_progress=on_progress or _bus_progress,
        )

        if final_content is None:
            final_content = "I've completed processing but have no response to give."

        self._save_turn(session, all_msgs, 1 + len(history))
        self.sessions.save(session)

        if (mt := self.tools.get("message")) and isinstance(mt, MessageTool) and mt._sent_in_turn:
            return None

        preview = final_content[:120] + "..." if len(final_content) > 120 else final_content
        logger.info("Response to {}:{}: {}", msg.channel, msg.sender_id, preview)
        return OutboundMessage(
            channel=msg.channel, chat_id=msg.chat_id, content=final_content,
            metadata=msg.metadata or {},
        )

    def _save_turn(self, session: Session, messages: list[dict], skip: int) -> None:
        """Save new-turn messages into session, truncating large tool results."""
        from datetime import datetime
        for m in messages[skip:]:
            entry = {k: v for k, v in m.items() if k != "reasoning_content"}
            role, content = entry.get("role"), entry.get("content")
            if role == "assistant" and not content and not entry.get("tool_calls"):
                continue  # skip empty assistant messages — they poison session context
            if role == "tool" and isinstance(content, str) and len(content) > self._TOOL_RESULT_MAX_CHARS:
                entry["content"] = content[:self._TOOL_RESULT_MAX_CHARS] + "\n... (truncated)"
            elif role == "user":
                if isinstance(content, str) and content.startswith(ContextBuilder._RUNTIME_CONTEXT_TAG):
                    continue
                if isinstance(content, list):
                    entry["content"] = [
                        {"type": "text", "text": "[image]"} if (
                            c.get("type") == "image_url"
                            and c.get("image_url", {}).get("url", "").startswith("data:image/")
                        ) else c for c in content
                    ]
            entry.setdefault("timestamp", datetime.now().isoformat())
            session.messages.append(entry)
        session.updated_at = datetime.now()

    async def _consolidate_memory(self, session, archive_all: bool = False) -> bool:
        """Delegate to MemoryStore.consolidate(). Returns True on success."""
        return await MemoryStore(self.workspace).consolidate(
            session, self.provider, self.model,
            archive_all=archive_all, memory_window=self.memory_window,
        )

    async def process_direct(
        self,
        content: str,
        session_key: str = "cli:direct",
        channel: str = "cli",
        chat_id: str = "direct",
        on_progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> str:
        """Process a message directly (for CLI or cron usage)."""
        msg = InboundMessage(channel=channel, sender_id="user", chat_id=chat_id, content=content)
        response = await self._process_message(msg, session_key=session_key, on_progress=on_progress)
        return response.content if response else ""
