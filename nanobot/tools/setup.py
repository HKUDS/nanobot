"""Default tool registration for the agent loop.

Extracted from ``AgentLoop._register_default_tools`` (LAN-213) so that tool
construction is a pure, standalone function with explicit dependencies — no
``self`` access required.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from nanobot.agent.scratchpad import Scratchpad
from nanobot.tools.builtin.cron import CronTool
from nanobot.tools.builtin.delegate import DelegateParallelTool, DelegateTool
from nanobot.tools.builtin.email import CheckEmailTool
from nanobot.tools.builtin.excel import (
    DescribeDataTool,
    ExcelFindTool,
    ExcelGetRowsTool,
    QueryDataTool,
    ReadSpreadsheetTool,
)
from nanobot.tools.builtin.feedback import FeedbackTool
from nanobot.tools.builtin.filesystem import EditFileTool, ListDirTool, ReadFileTool, WriteFileTool
from nanobot.tools.builtin.message import MessageTool
from nanobot.tools.builtin.mission import (
    MissionCancelTool,
    MissionListTool,
    MissionStartTool,
    MissionStatusTool,
)
from nanobot.tools.builtin.powerpoint import AnalyzePptxTool, PptxGetSlideTool, ReadPptxTool
from nanobot.tools.builtin.scratchpad import ScratchpadReadTool, ScratchpadWriteTool
from nanobot.tools.builtin.shell import ExecTool
from nanobot.tools.builtin.web import WebFetchTool, WebSearchTool
from nanobot.tools.result_cache import CacheGetSliceTool, ToolResultCache

if TYPE_CHECKING:
    from nanobot.agent.mission import MissionManager
    from nanobot.agent.skills import SkillsLoader
    from nanobot.config.schema import AgentRoleConfig, ExecToolConfig
    from nanobot.cron.service import CronService
    from nanobot.tools.capability import CapabilityRegistry


def register_default_tools(  # noqa: PLR0913
    *,
    capabilities: CapabilityRegistry,
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
    the ``capabilities`` registry that is mutated in place.
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
            capabilities.register_tool(tool)

    spreadsheet_tool = ReadSpreadsheetTool(
        workspace=workspace,
        allowed_dir=allowed_dir,
        cache=result_cache,
    )
    if _should_register(spreadsheet_tool.name):
        capabilities.register_tool(spreadsheet_tool)

    # PowerPoint tools
    pptx_read = ReadPptxTool(
        workspace=workspace,
        allowed_dir=allowed_dir,
        cache=result_cache,
    )
    if _should_register(pptx_read.name):
        capabilities.register_tool(pptx_read)

    _pptx_kw: dict[str, Any] = {
        "workspace": workspace,
        "allowed_dir": allowed_dir,
        "cache": result_cache,
    }
    if vision_model is not None:
        _pptx_kw["vision_model"] = vision_model
    pptx_analyze = AnalyzePptxTool(**_pptx_kw)
    if _should_register(pptx_analyze.name):
        capabilities.register_tool(pptx_analyze)

    exec_tool = ExecTool(
        working_dir=str(workspace),
        timeout=exec_config.timeout,
        restrict_to_workspace=restrict_to_workspace,
        shell_mode=shell_mode,
    )
    if _should_register(exec_tool.name):
        capabilities.register_tool(exec_tool)

    for extra_tool in (
        WebSearchTool(api_key=brave_api_key),
        WebFetchTool(),
        MessageTool(send_callback=publish_outbound),
        FeedbackTool(events_file=workspace / "memory" / "events.jsonl"),
    ):
        if _should_register(extra_tool.name):
            capabilities.register_tool(extra_tool)

    # Email checking tool (callback set later by gateway via set_email_fetch)
    email_tool = CheckEmailTool()
    if _should_register(email_tool.name):
        capabilities.register_tool(email_tool)

    if cron_service:
        cron_tool = CronTool(cron_service)
        if _should_register(cron_tool.name):
            capabilities.register_tool(cron_tool)

    # Delegation tools
    if delegation_enabled:
        delegate_tool = DelegateTool()
        if _should_register(delegate_tool.name):
            capabilities.register_tool(delegate_tool)
        delegate_parallel_tool = DelegateParallelTool()
        if _should_register(delegate_parallel_tool.name):
            capabilities.register_tool(delegate_parallel_tool)
        mission_tool = MissionStartTool(manager=missions)
        if _should_register(mission_tool.name):
            capabilities.register_tool(mission_tool)
        mission_status = MissionStatusTool(manager=missions)
        if _should_register(mission_status.name):
            capabilities.register_tool(mission_status)
        mission_list = MissionListTool(manager=missions)
        if _should_register(mission_list.name):
            capabilities.register_tool(mission_list)
        mission_cancel = MissionCancelTool(manager=missions)
        if _should_register(mission_cancel.name):
            capabilities.register_tool(mission_cancel)

    # Scratchpad tools (scratchpad instance swapped per session in _ensure_scratchpad)
    placeholder_pad = Scratchpad(workspace / "sessions" / "_placeholder")
    for st in (
        ScratchpadWriteTool(placeholder_pad),
        ScratchpadReadTool(placeholder_pad),
    ):
        if _should_register(st.name):
            capabilities.register_tool(st)

    # Skill-provided custom tools (Step 14)
    if skills_enabled:
        for skill_tool in skills_loader.discover_tools():
            capabilities.register_tool(skill_tool)

    # Cache retrieval tools
    cache_slice = CacheGetSliceTool(cache=result_cache)
    if _should_register(cache_slice.name):
        capabilities.register_tool(cache_slice)

    excel_rows = ExcelGetRowsTool(cache=result_cache)
    if _should_register(excel_rows.name):
        capabilities.register_tool(excel_rows)

    excel_find = ExcelFindTool(cache=result_cache)
    if _should_register(excel_find.name):
        capabilities.register_tool(excel_find)

    pptx_get_slide = PptxGetSlideTool(cache=result_cache)
    if _should_register(pptx_get_slide.name):
        capabilities.register_tool(pptx_get_slide)

    query_tool = QueryDataTool(cache=result_cache)
    if _should_register(query_tool.name):
        capabilities.register_tool(query_tool)

    describe_tool = DescribeDataTool(cache=result_cache)
    if _should_register(describe_tool.name):
        capabilities.register_tool(describe_tool)
