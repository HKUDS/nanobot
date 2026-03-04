"""File system tools: read, write, edit."""

import difflib
import re
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.agent.tools.base import Tool


def _resolve_path(
    path: str, workspace: Path | None = None, allowed_dir: Path | None = None
) -> Path:
    """Resolve path against workspace (if relative) and enforce directory restriction."""
    p = Path(path).expanduser()
    if not p.is_absolute() and workspace:
        p = workspace / p
    resolved = p.resolve()
    if allowed_dir:
        try:
            resolved.relative_to(allowed_dir.resolve())
        except ValueError:
            raise PermissionError(f"Path {path} is outside allowed directory {allowed_dir}")
    return resolved


class ReadFileTool(Tool):
    """Tool to read file contents."""

    def __init__(
        self,
        workspace: Path | None = None,
        allowed_dir: Path | None = None,
        redact_sensitive: bool = True,
    ):
        self._workspace = workspace
        self._allowed_dir = allowed_dir
        self._redact_sensitive = redact_sensitive

    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return "Read the contents of a file at the given path."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "The file path to read"}},
            "required": ["path"],
        }

    SENSITIVE_PATTERNS = [
        r"\.json$",
        r"\.jsonc$",
        r"\.yaml$",
        r"\.yml$",
        r"\.toml$",
        r"\.ini$",
        r"\.properties$",
        r"\.conf$",
        r"credentials",
        r"secrets",
        r"settings",
        r"\.env\.",
    ]

    def _should_redact(self, file_path: Path) -> bool:
        """判断文件是否需要脱敏"""
        if not self._redact_sensitive:
            return False
        path_str = str(file_path)
        return any(
            re.search(pattern, path_str, re.IGNORECASE) for pattern in self.SENSITIVE_PATTERNS
        )

    def _redact(self, content: str) -> str:
        """脱敏处理"""
        redacted = content

        # JSON 格式: "api_key": "xxx" (支持下划线)
        redacted = re.sub(
            r'(?i)"(api[_-]?key|apikey|api[_-]?secret)"\s*:\s*"[^"]+"',
            r'"\1": "***REDACTED***"',
            redacted,
        )
        # 密码字段: password, *password*, passwd, pwd
        redacted = re.sub(
            r'(?i)"(\w*password\w*|passwd|pwd)"\s*:\s*"[^"]+"',
            r'"\1": "***REDACTED***"',
            redacted,
        )
        # 私钥/密钥字段: secret_key, aws_secret, private_key
        redacted = re.sub(
            r'(?i)"(\w*secret\w*|\w*private\w*key\w*)"\s*:\s*"[^"]+"',
            r'"\1": "***REDACTED***"',
            redacted,
        )
        redacted = re.sub(
            r'(?i)"(token|access[_-]?token|auth[_-]?token)"\s*:\s*"[^"]+"',
            r'"\1": "***REDACTED***"',
            redacted,
        )

        # 配置文件格式: api_key=xxx
        redacted = re.sub(
            r"(?i)(api[_-]?key|apikey|password|passwd|secret|token)\s*=\s*[^\s]+",
            r"\1=***REDACTED***",
            redacted,
        )

        # Bearer Token
        redacted = re.sub(r"Bearer\s+[A-Za-z0-9_.=]+", r"Bearer ***REDACTED***", redacted)

        # AWS Keys (Access Key)
        redacted = re.sub(r"(AKIA|ABIA|ACCA|ASIA)[0-9A-Z]{16}", r"***AWS_KEY_REDACTED***", redacted)

        # sk- 开头的 Key (包括 sk-, sk-proj-, sk-admin- 等)
        redacted = re.sub(r"sk-[A-Za-z0-9-]{20,}", r"sk-***REDACTED***", redacted)

        # GitHub Token (ghp_, gho_, ghs_, ghr_)
        redacted = re.sub(r"gh[pogrs][A-Za-z0-9_]{20,}", r"gh***REDACTED***", redacted)

        # 连接字符串: postgres://user:pass@host -> postgres://***REDACTED***@host
        redacted = re.sub(r"://[^:]+:[^@]+@", r"://***REDACTED***@", redacted)

        return redacted

    async def execute(self, path: str, **kwargs: Any) -> str:
        try:
            file_path = _resolve_path(path, self._workspace, self._allowed_dir)
            if not file_path.exists():
                return f"Error: File not found: {path}"
            if not file_path.is_file():
                return f"Error: Not a file: {path}"

            content = file_path.read_text(encoding="utf-8")

            # 脱敏处理
            if self._should_redact(file_path):
                original_len = len(content)
                content = self._redact(content)
                if len(content) != original_len:
                    logger.info("Sensitive data redacted in file: {}", path)

            return content
        except PermissionError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error reading file: {str(e)}"


class WriteFileTool(Tool):
    """Tool to write content to a file."""

    def __init__(self, workspace: Path | None = None, allowed_dir: Path | None = None):
        self._workspace = workspace
        self._allowed_dir = allowed_dir

    @property
    def name(self) -> str:
        return "write_file"

    @property
    def description(self) -> str:
        return "Write content to a file at the given path. Creates parent directories if needed."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "The file path to write to"},
                "content": {"type": "string", "description": "The content to write"},
            },
            "required": ["path", "content"],
        }

    async def execute(self, path: str, content: str, **kwargs: Any) -> str:
        try:
            file_path = _resolve_path(path, self._workspace, self._allowed_dir)
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
            return f"Successfully wrote {len(content)} bytes to {file_path}"
        except PermissionError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error writing file: {str(e)}"


class EditFileTool(Tool):
    """Tool to edit a file by replacing text."""

    def __init__(self, workspace: Path | None = None, allowed_dir: Path | None = None):
        self._workspace = workspace
        self._allowed_dir = allowed_dir

    @property
    def name(self) -> str:
        return "edit_file"

    @property
    def description(self) -> str:
        return "Edit a file by replacing old_text with new_text. The old_text must exist exactly in the file."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "The file path to edit"},
                "old_text": {"type": "string", "description": "The exact text to find and replace"},
                "new_text": {"type": "string", "description": "The text to replace with"},
            },
            "required": ["path", "old_text", "new_text"],
        }

    async def execute(self, path: str, old_text: str, new_text: str, **kwargs: Any) -> str:
        try:
            file_path = _resolve_path(path, self._workspace, self._allowed_dir)
            if not file_path.exists():
                return f"Error: File not found: {path}"

            content = file_path.read_text(encoding="utf-8")

            if old_text not in content:
                return self._not_found_message(old_text, content, path)

            # Count occurrences
            count = content.count(old_text)
            if count > 1:
                return f"Warning: old_text appears {count} times. Please provide more context to make it unique."

            new_content = content.replace(old_text, new_text, 1)
            file_path.write_text(new_content, encoding="utf-8")

            return f"Successfully edited {file_path}"
        except PermissionError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error editing file: {str(e)}"

    @staticmethod
    def _not_found_message(old_text: str, content: str, path: str) -> str:
        """Build a helpful error when old_text is not found."""
        lines = content.splitlines(keepends=True)
        old_lines = old_text.splitlines(keepends=True)
        window = len(old_lines)

        best_ratio, best_start = 0.0, 0
        for i in range(max(1, len(lines) - window + 1)):
            ratio = difflib.SequenceMatcher(None, old_lines, lines[i : i + window]).ratio()
            if ratio > best_ratio:
                best_ratio, best_start = ratio, i

        if best_ratio > 0.5:
            diff = "\n".join(
                difflib.unified_diff(
                    old_lines,
                    lines[best_start : best_start + window],
                    fromfile="old_text (provided)",
                    tofile=f"{path} (actual, line {best_start + 1})",
                    lineterm="",
                )
            )
            return f"Error: old_text not found in {path}.\nBest match ({best_ratio:.0%} similar) at line {best_start + 1}:\n{diff}"
        return (
            f"Error: old_text not found in {path}. No similar text found. Verify the file content."
        )


class ListDirTool(Tool):
    """Tool to list directory contents."""

    def __init__(self, workspace: Path | None = None, allowed_dir: Path | None = None):
        self._workspace = workspace
        self._allowed_dir = allowed_dir

    @property
    def name(self) -> str:
        return "list_dir"

    @property
    def description(self) -> str:
        return "List the contents of a directory."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "The directory path to list"}},
            "required": ["path"],
        }

    async def execute(self, path: str, **kwargs: Any) -> str:
        try:
            dir_path = _resolve_path(path, self._workspace, self._allowed_dir)
            if not dir_path.exists():
                return f"Error: Directory not found: {path}"
            if not dir_path.is_dir():
                return f"Error: Not a directory: {path}"

            items = []
            for item in sorted(dir_path.iterdir()):
                prefix = "📁 " if item.is_dir() else "📄 "
                items.append(f"{prefix}{item.name}")

            if not items:
                return f"Directory {path} is empty"

            return "\n".join(items)
        except PermissionError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error listing directory: {str(e)}"
