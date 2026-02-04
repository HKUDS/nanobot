"""Shell execution tool with security protections.

Security Features:
- Command blocklist: Blocks dangerous patterns (rm -rf, format, etc.)
- Optional allowlist: Restricts to specific allowed commands
- Working directory fence: Limits execution to specific directories

Note: This is a lightweight security measure and NOT a replacement for proper
sandboxing or OS-level permission controls. Use with caution.
"""

import asyncio
import os
import re
import shlex
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.agent.tools.base import Tool


class ExecTool(Tool):
    """Tool to execute shell commands with security protections.
    
    Security features:
    - Blocklist: Prevents execution of dangerous command patterns
    - Allowlist: Optional restriction to specific allowed commands
    - Directory fence: Limits execution to allowed directories
    """
    
    # Dangerous command patterns (case-insensitive)
    DANGEROUS_PATTERNS = [
        r'rm\s+-rf',           # Recursive force delete (Unix)
        r'rm\s+.*\s+-rf',      # rm with -rf anywhere
        r'del\s+/s',           # Recursive delete (Windows)
        r'format\s+[a-z]:',    # Format drive (Windows)
        r'mkfs\.',             # Format filesystem (Unix)
        r'dd\s+if=.*of=/dev',  # Disk write operations
        r':\(\)\{\s*:\|:&\s*\};:', # Fork bomb
        r'chmod\s+-R\s+777',   # Dangerous permission change
        r'chown\s+-R',         # Recursive ownership change
        r'>\s*/dev/sd[a-z]',   # Direct disk write
        r'curl.*\|.*sh',       # Pipe to shell
        r'wget.*\|.*sh',       # Pipe to shell
        r'eval\s+',            # Eval execution
        r'exec\s+',            # Exec execution
    ]
    
    def __init__(
        self,
        timeout: int = 60,
        working_dir: str | None = None,
        allowed_commands: list[str] | None = None,
        allowed_dirs: list[str] | None = None,
        enable_blocklist: bool = True,
    ):
        """Initialize ExecTool with security settings.
        
        Args:
            timeout: Command execution timeout in seconds
            working_dir: Default working directory
            allowed_commands: Optional list of allowed command prefixes (allowlist mode)
            allowed_dirs: Optional list of allowed execution directories
            enable_blocklist: Enable dangerous command pattern blocking
        """
        self.timeout = timeout
        self.working_dir = working_dir
        self.allowed_commands = allowed_commands
        self.allowed_dirs = [Path(d).resolve() for d in allowed_dirs] if allowed_dirs else None
        self.enable_blocklist = enable_blocklist
    
    @property
    def name(self) -> str:
        return "exec"
    
    @property
    def description(self) -> str:
        return "Execute a shell command and return its output. Use with caution."
    
    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute"
                },
                "working_dir": {
                    "type": "string",
                    "description": "Optional working directory for the command"
                }
            },
            "required": ["command"]
        }
    
    def _is_command_blocked(self, command: str) -> tuple[bool, str | None]:
        """Check if command matches dangerous patterns.
        
        Returns:
            Tuple of (is_blocked, reason)
        """
        if not self.enable_blocklist:
            return False, None
        
        command_lower = command.lower()
        for pattern in self.DANGEROUS_PATTERNS:
            if re.search(pattern, command_lower, re.IGNORECASE):
                return True, f"Command blocked: matches dangerous pattern '{pattern}'"
        
        return False, None
    
    def _is_command_allowed(self, command: str) -> tuple[bool, str | None]:
        """Check if command is in allowlist.
        
        Returns:
            Tuple of (is_allowed, reason)
        """
        if not self.allowed_commands:
            return True, None  # No allowlist = all commands allowed (subject to blocklist)
        
        # Extract the base command (first word)
        base_command = command.strip().split()[0] if command.strip() else ""
        
        for allowed in self.allowed_commands:
            if base_command.startswith(allowed):
                return True, None
        
        return False, f"Command not in allowlist. Allowed: {', '.join(self.allowed_commands)}"
    
    def _is_directory_allowed(self, directory: str) -> tuple[bool, str | None]:
        """Check if directory is within allowed fence.
        
        Returns:
            Tuple of (is_allowed, reason)
        """
        if not self.allowed_dirs:
            return True, None  # No fence = all directories allowed
        
        try:
            target_path = Path(directory).resolve()
            
            for allowed_dir in self.allowed_dirs:
                # Check if target is within allowed directory
                try:
                    target_path.relative_to(allowed_dir)
                    return True, None
                except ValueError:
                    continue
            
            allowed_paths = ', '.join(str(d) for d in self.allowed_dirs)
            return False, f"Directory '{directory}' is outside allowed fence: {allowed_paths}"
        
        except Exception as e:
            return False, f"Invalid directory path: {str(e)}"
    
    async def execute(self, command: str, working_dir: str | None = None, **kwargs: Any) -> str:
        """Execute shell command with security validations.
        
        Args:
            command: Shell command to execute
            working_dir: Optional working directory override
            **kwargs: Additional arguments (ignored)
        
        Returns:
            Command output or error message
        """
        # Input validation
        command = command.strip()
        if not command:
            return "Error: Empty command"
        
        if len(command) > 2000:
            return "Error: Command too long (max 2000 characters)"
        
        # Audit logging (truncated for security)
        logger.warning(f"Shell command execution attempt: {command[:100]}{'...' if len(command) > 100 else ''}")
        
        # Security validation: Check blocklist
        is_blocked, block_reason = self._is_command_blocked(command)
        if is_blocked:
            return f"Security Error: {block_reason}"
        
        # Security validation: Check allowlist
        is_allowed, allow_reason = self._is_command_allowed(command)
        if not is_allowed:
            return f"Security Error: {allow_reason}"
        
        # Determine working directory
        cwd = working_dir or self.working_dir or os.getcwd()
        
        # Security validation: Check directory fence
        is_dir_allowed, dir_reason = self._is_directory_allowed(cwd)
        if not is_dir_allowed:
            return f"Security Error: {dir_reason}"
        
        try:
            args = shlex.split(command)
            process = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=self.timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                return f"Error: Command timed out after {self.timeout} seconds"
            
            output_parts = []
            
            if stdout:
                output_parts.append(stdout.decode("utf-8", errors="replace"))
            
            if stderr:
                stderr_text = stderr.decode("utf-8", errors="replace")
                if stderr_text.strip():
                    output_parts.append(f"STDERR:\n{stderr_text}")
            
            if process.returncode != 0:
                output_parts.append(f"\nExit code: {process.returncode}")
            
            result = "\n".join(output_parts) if output_parts else "(no output)"
            
            # Truncate very long output
            max_len = 10000
            if len(result) > max_len:
                result = result[:max_len] + f"\n... (truncated, {len(result) - max_len} more chars)"
            
            return result
            
        except Exception as e:
            return f"Error executing command: {str(e)}"
