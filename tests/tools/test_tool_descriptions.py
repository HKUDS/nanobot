import sys

from nanobot.agent.tools.apply_patch import ApplyPatchTool
from nanobot.agent.tools.exec_session import ExecSessionTool, ListExecSessionsTool
from nanobot.agent.tools.filesystem import EditFileTool, ReadFileTool, WriteFileTool
from nanobot.agent.tools.search import FindFilesTool, GrepTool
from nanobot.agent.tools.shell import ExecTool


def test_coding_tool_descriptions_steer_editing_priority() -> None:
    apply_patch = ApplyPatchTool().description.lower()
    edit_file = EditFileTool().description.lower()
    write_file = WriteFileTool().description.lower()

    assert "default tool for code edits" in apply_patch
    assert "multi-file" in apply_patch
    assert "dry_run=true" in apply_patch
    assert "edit_file only for small exact replacements" in apply_patch

    assert "small, exact replacement" in edit_file
    assert "copied from read_file" in edit_file
    assert "prefer apply_patch" in edit_file

    assert "replace an entire file" in write_file
    assert "prefer apply_patch" in write_file


def test_coding_tool_descriptions_steer_discovery() -> None:
    read_file = ReadFileTool().description.lower()
    find_files = FindFilesTool().description.lower()
    grep = GrepTool().description.lower()

    assert "text, images, pdfs, and office documents" in read_file
    assert "line-numbered" in read_file
    assert "targeted ranges" in read_file
    assert len(read_file) < 160

    assert "workspace paths" in find_files
    assert "relative paths" in find_files
    assert len(find_files) < 140

    assert "pdf, docx, xlsx, and pptx" in grep
    assert "five context lines" in grep
    assert "source locators" in grep
    assert len(grep) < 150

    read_pages = ReadFileTool().parameters["properties"]["pages"]["description"].lower()
    grep_pages = GrepTool().parameters["properties"]["pages"]["description"].lower()
    assert "page number or range" in read_pages
    assert "page number or range" in grep_pages


def test_exec_tool_descriptions_are_concise() -> None:
    assert ExecTool().description == "Execute a shell command."
    assert ExecSessionTool().description == "Manage a session returned by exec."
    assert ListExecSessionsTool().description == "List active exec sessions."

    exec_parameters = ExecTool().parameters["properties"]
    assert "omit to wait for exit" in exec_parameters["yield_time_ms"]["description"]

    session_parameters = ExecSessionTool().parameters["properties"]
    assert set(session_parameters) == {
        "session_id",
        "input",
        "close_stdin",
        "terminate",
        "wait_for",
        "until_exit",
        "timeout_ms",
    }
    assert session_parameters["until_exit"]["description"] == "Wait for the process to exit."
    assert "wait_for" in session_parameters["timeout_ms"]["description"]
    assert "until_exit" in session_parameters["timeout_ms"]["description"]


def test_exec_shell_parameter_guidance_matches_platform() -> None:
    shell_parameter = ExecTool().parameters["properties"]["shell"]["description"].lower()
    if sys.platform == "win32":
        assert "omit for powershell" in shell_parameter
        assert "powershell" in shell_parameter
        assert "cmd" in shell_parameter
        assert "bash" not in shell_parameter
    else:
        assert "omit for bash" in shell_parameter
        assert "zsh" in shell_parameter
        assert "powershell" not in shell_parameter
        assert "cmd" not in shell_parameter
