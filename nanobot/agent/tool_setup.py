"""Default tool registration for the agent loop.

Extracted from ``AgentLoop._register_default_tools`` (LAN-213) so that tool
construction is a pure, standalone function with explicit dependencies — no
``self`` access required.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from nanobot.agent.scratchpad import Scratchpad
from nanobot.agent.tools.cron import CronTool
from nanobot.agent.tools.delegate import DelegateParallelTool, DelegateTool
from nanobot.agent.tools.email import CheckEmailTool
from nanobot.agent.tools.excel import (
    DescribeDataTool,
    ExcelFindTool,
    ExcelGetRowsTool,
    QueryDataTool,
    ReadSpreadsheetTool,
)
from nanobot.agent.tools.feedback import FeedbackTool
from nanobot.agent.tools.filesystem import EditFileTool, ListDirTool, ReadFileTool, WriteFileTool
from nanobot.agent.tools.message import MessageTool
from nanobot.agent.tools.mission import (
    MissionCancelTool,
    MissionListTool,
    MissionStartTool,
    MissionStatusTool,
)
from nanobot.agent.tools.powerpoint import AnalyzePptxTool, PptxGetSlideTool, ReadPptxTool
from nanobot.agent.tools.result_cache import CacheGetSliceTool, ToolResultCache
from nanobot.agent.tools.scratchpad import ScratchpadReadTool, ScratchpadWriteTool
from nanobot.agent.tools.shell import ExecTool
from nanobot.agent.tools.web import WebFetchTool, WebSearchTool

if TYPE_CHECKING:
    from nanobot.agent.mission import MissionManager
    from nanobot.agent.skills import SkillsLoader
    from nanobot.agent.tool_executor import ToolExecutor
    from nanobot.config.schema import AgentRoleConfig, ExecToolConfig
    from nanobot.cron.service import CronService


def register_default_tools(  # noqa: PLR0913
    *,
    tools: ToolExecutor,
    role_config: AgentRoleConfig | None,
    workspace: Path,
    restrict_to_workspace: bool,
    shell_mode: str,
    vision_model: str | None,
    exec_config: ExecToolConfig,
    brave_api_key: str | None,
    publish_outbound: Callable[..., Awaitable[Any]],
    cron_service: CronService | None,
    delegation_enabled: bool,
    missions: MissionManager,
    result_cache: ToolResultCache,
    skills_enabled: bool,
    skills_loader: SkillsLoader,
) -> None:
    """Register the default set of tools, filtered by role config.

    This is a pure construction function — no async, no persistent state beyond
    the ``tools`` registry that is mutated in place.
    """
    allowed = (
        set(role_config.allowed_tools)
        if role_config and role_config.allowed_tools is not None
        else None
    )
    denied = set(role_config.denied_tools) if role_config and role_config.denied_tools else set()
    allowed_dir = workspace if restrict_to_workspace else None

    def _should_register(name: str) -> bool:
        if allowed is not None and name not in allowed:
            return False
        return name not in denied

    for cls in (ReadFileTool, WriteFileTool, EditFileTool, ListDirTool):
        tool = cls(workspace=workspace, allowed_dir=allowed_dir)
        if _should_register(tool.name):
            tools.register(tool)

    spreadsheet_tool = ReadSpreadsheetTool(
        workspace=workspace,
        allowed_dir=allowed_dir,
        cache=result_cache,
    )
    if _should_register(spreadsheet_tool.name):
        tools.register(spreadsheet_tool)

    # PowerPoint tools
    pptx_read = ReadPptxTool(
        workspace=workspace,
        allowed_dir=allowed_dir,
        cache=result_cache,
    )
    if _should_register(pptx_read.name):
        tools.register(pptx_read)

    _pptx_kw: dict[str, Any] = {
        "workspace": workspace,
        "allowed_dir": allowed_dir,
        "cache": result_cache,
    }
    if vision_model is not None:
        _pptx_kw["vision_model"] = vision_model
    pptx_analyze = AnalyzePptxTool(**_pptx_kw)
    if _should_register(pptx_analyze.name):
        tools.register(pptx_analyze)

    exec_tool = ExecTool(
        working_dir=str(workspace),
        timeout=exec_config.timeout,
        restrict_to_workspace=restrict_to_workspace,
        shell_mode=shell_mode,
    )
    if _should_register(exec_tool.name):
        tools.register(exec_tool)

    for extra_tool in (
        WebSearchTool(api_key=brave_api_key),
        WebFetchTool(),
        MessageTool(send_callback=publish_outbound),
        FeedbackTool(events_file=workspace / "memory" / "events.jsonl"),
    ):
        if _should_register(extra_tool.name):
            tools.register(extra_tool)

    # Email checking tool (callback set later by gateway via set_email_fetch)
    email_tool = CheckEmailTool()
    if _should_register(email_tool.name):
        tools.register(email_tool)

    if cron_service:
        cron_tool = CronTool(cron_service)
        if _should_register(cron_tool.name):
            tools.register(cron_tool)

    # Delegation tools
    if delegation_enabled:
        delegate_tool = DelegateTool()
        if _should_register(delegate_tool.name):
            tools.register(delegate_tool)
        delegate_parallel_tool = DelegateParallelTool()
        if _should_register(delegate_parallel_tool.name):
            tools.register(delegate_parallel_tool)
        mission_tool = MissionStartTool(manager=missions)
        if _should_register(mission_tool.name):
            tools.register(mission_tool)
        mission_status = MissionStatusTool(manager=missions)
        if _should_register(mission_status.name):
            tools.register(mission_status)
        mission_list = MissionListTool(manager=missions)
        if _should_register(mission_list.name):
            tools.register(mission_list)
        mission_cancel = MissionCancelTool(manager=missions)
        if _should_register(mission_cancel.name):
            tools.register(mission_cancel)

    # Scratchpad tools (scratchpad instance swapped per session in _ensure_scratchpad)
    placeholder_pad = Scratchpad(workspace / "sessions" / "_placeholder")
    for st in (
        ScratchpadWriteTool(placeholder_pad),
        ScratchpadReadTool(placeholder_pad),
    ):
        if _should_register(st.name):
            tools.register(st)

    # Skill-provided custom tools (Step 14)
    if skills_enabled:
        for skill_tool in skills_loader.discover_tools():
            tools.register(skill_tool)

    # Cache retrieval tools
    cache_slice = CacheGetSliceTool(cache=result_cache)
    if _should_register(cache_slice.name):
        tools.register(cache_slice)

    excel_rows = ExcelGetRowsTool(cache=result_cache)
    if _should_register(excel_rows.name):
        tools.register(excel_rows)

    excel_find = ExcelFindTool(cache=result_cache)
    if _should_register(excel_find.name):
        tools.register(excel_find)

    pptx_get_slide = PptxGetSlideTool(cache=result_cache)
    if _should_register(pptx_get_slide.name):
        tools.register(pptx_get_slide)

    query_tool = QueryDataTool(cache=result_cache)
    if _should_register(query_tool.name):
        tools.register(query_tool)

    describe_tool = DescribeDataTool(cache=result_cache)
    if _should_register(describe_tool.name):
        tools.register(describe_tool)
