"""Shell execution tool with security hardening."""

import asyncio
import logging
import os
import re
import shlex
import shutil
from pathlib import Path
from typing import Any

from nanobot.agent.tools.base import Tool

# Configure logging for security auditing
logger = logging.getLogger(__name__)


# Allowlist of safe commands that can be executed without shell
ALLOWED_COMMANDS = frozenset({
    # Version control
    'git', 'hg', 'svn',
    # Package managers
    'npm', 'npx', 'yarn', 'pnpm', 'pip', 'pip3', 'pipx', 'poetry', 'pdm',
    'cargo', 'go', 'gem', 'bundle', 'composer', 'maven', 'mvn', 'gradle',
    # Language runtimes
    'python', 'python3', 'node', 'ruby', 'php', 'java', 'javac',
    'rustc', 'gcc', 'g++', 'clang', 'make', 'cmake',
    # File operations (safe)
    'ls', 'cat', 'head', 'tail', 'grep', 'find', 'wc', 'sort', 'uniq',
    'diff', 'file', 'stat', 'du', 'df', 'pwd', 'basename', 'dirname',
    'realpath', 'readlink',
    # Directory operations
    'mkdir', 'cp', 'mv', 'touch', 'chmod', 'chown',
    # Text processing
    'sed', 'awk', 'cut', 'tr', 'xargs', 'tee',
    # Archive operations
    'tar', 'zip', 'unzip', 'gzip', 'gunzip', 'bzip2',
    # Network tools (read-only)
    'curl', 'wget', 'ping', 'host', 'dig', 'nslookup',
    # Process info (safe)
    'ps', 'top', 'htop', 'uptime', 'whoami', 'id', 'groups',
    # Docker (common operations)
    'docker', 'docker-compose', 'podman',
    # Testing tools
    'pytest', 'jest', 'mocha', 'rspec', 'phpunit',
    # Linting/formatting
    'eslint', 'prettier', 'black', 'flake8', 'mypy', 'rubocop',
    # Build tools
    'webpack', 'vite', 'esbuild', 'rollup', 'parcel',
    # Other common tools
    'echo', 'printf', 'date', 'env', 'which', 'whereis', 'type',
    'true', 'false', 'test', 'expr',
})

# Shell metacharacters that indicate potential injection
DANGEROUS_METACHARACTERS = frozenset({
    ';',   # Command separator
    '|',   # Pipe
    '&',   # Background/AND
    '$',   # Variable expansion
    '`',   # Command substitution
    '(',   # Subshell
    ')',   # Subshell
    '{',   # Brace expansion
    '}',   # Brace expansion
    '<',   # Input redirection
    '>',   # Output redirection
    '\n',  # Newline (command separator)
    '\r',  # Carriage return
})

# Patterns that indicate shell-specific features requiring shell=True
SHELL_FEATURE_PATTERNS = [
    r'\$\{',          # Variable expansion ${var}
    r'\$\(',          # Command substitution $(cmd)
    r'`[^`]+`',       # Backtick command substitution
    r'\|\|',          # OR operator
    r'&&',            # AND operator
    r'[<>]{1,2}',     # Redirections
    r'\*|\?|\[',      # Glob patterns (need shell for expansion)
    r'~/',            # Home directory expansion
]


class ShellSecurityError(Exception):
    """Raised when a command fails security validation."""
    pass


class ExecTool(Tool):
    """
    Tool to execute shell commands with security hardening.

    Security features:
    - Uses subprocess_exec instead of subprocess_shell where possible
    - Validates commands against an allowlist
    - Blocks dangerous shell metacharacters
    - Provides explicit shell escape hatch with logging
    - Implements timeout protection
    - Restricts path traversal when configured
    """

    def __init__(
        self,
        timeout: int = 60,
        working_dir: str | None = None,
        deny_patterns: list[str] | None = None,
        allow_patterns: list[str] | None = None,
        restrict_to_workspace: bool = False,
        allowed_commands: set[str] | None = None,
        allow_shell_fallback: bool = False,
        log_commands: bool = True,
    ):
        """
        Initialize the ExecTool with security settings.

        Args:
            timeout: Maximum execution time in seconds
            working_dir: Default working directory for commands
            deny_patterns: Regex patterns to block (dangerous commands)
            allow_patterns: If set, only allow commands matching these patterns
            restrict_to_workspace: If True, block access outside working_dir
            allowed_commands: Override default command allowlist
            allow_shell_fallback: Allow falling back to shell for complex commands
            log_commands: Log all executed commands for auditing
        """
        self.timeout = timeout
        self.working_dir = working_dir
        self.deny_patterns = deny_patterns or [
            r"\brm\s+-[rf]{1,2}\b",          # rm -r, rm -rf, rm -fr
            r"\brm\s+.*-[rf]{1,2}\b",        # rm with flags anywhere
            r"\bdel\s+/[fq]\b",              # del /f, del /q
            r"\brmdir\s+/s\b",               # rmdir /s
            r"\b(format|mkfs|diskpart)\b",   # disk operations
            r"\bdd\s+if=",                   # dd
            r">\s*/dev/sd",                  # write to disk
            r"\b(shutdown|reboot|poweroff|init\s+[06])\b",  # system power
            r":\(\)\s*\{.*\};\s*:",          # fork bomb
            r"\bsudo\b",                     # privilege escalation
            r"\bsu\s+-?\s*\w*\b",            # switch user
            r"\bchmod\s+.*777\b",            # overly permissive
            r"\b(curl|wget).*\|\s*(ba)?sh",  # remote code execution
            r"\beval\b",                     # eval execution
            r"\bexec\b",                     # exec replacement
            r"/etc/(passwd|shadow|sudoers)", # sensitive files
            r"~/.ssh",                       # SSH keys
            r"\.env\b",                      # environment files
        ]
        self.allow_patterns = allow_patterns or []
        self.restrict_to_workspace = restrict_to_workspace
        self.allowed_commands = allowed_commands or ALLOWED_COMMANDS
        self.allow_shell_fallback = allow_shell_fallback
        self.log_commands = log_commands

    @property
    def name(self) -> str:
        return "exec"

    @property
    def description(self) -> str:
        return "Execute a shell command and return its output. Commands are validated for security."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The command to execute (will be validated for security)"
                },
                "working_dir": {
                    "type": "string",
                    "description": "Optional working directory for the command"
                },
                "allow_shell": {
                    "type": "boolean",
                    "description": "Explicitly allow shell execution for complex commands (requires allow_shell_fallback=True)"
                }
            },
            "required": ["command"]
        }

    def _contains_shell_features(self, command: str) -> bool:
        """Check if command contains shell-specific features that need shell=True."""
        for pattern in SHELL_FEATURE_PATTERNS:
            if re.search(pattern, command):
                return True
        return False

    def _contains_dangerous_metacharacters(self, command: str) -> set[str]:
        """Return set of dangerous metacharacters found in command."""
        found = set()
        for char in command:
            if char in DANGEROUS_METACHARACTERS:
                found.add(char)
        return found

    def _validate_command_in_path(self, cmd: str) -> bool:
        """Check if command exists in PATH."""
        return shutil.which(cmd) is not None

    def _parse_command(self, command: str) -> tuple[str, list[str]]:
        """
        Parse command string into executable and arguments.

        Returns:
            Tuple of (executable_name, full_args_list)

        Raises:
            ShellSecurityError: If parsing fails or command is invalid
        """
        try:
            args = shlex.split(command)
        except ValueError as e:
            raise ShellSecurityError(f"Failed to parse command: {e}")

        if not args:
            raise ShellSecurityError("Empty command")

        # Extract the base command name (without path)
        executable = args[0]
        base_cmd = os.path.basename(executable)

        return base_cmd, args

    def _validate_command_allowlist(self, base_cmd: str) -> None:
        """Validate command against allowlist."""
        if base_cmd not in self.allowed_commands:
            raise ShellSecurityError(
                f"Command '{base_cmd}' is not in the allowed commands list. "
                f"Allowed commands include: {', '.join(sorted(list(self.allowed_commands)[:20]))}..."
            )

    async def execute(
        self,
        command: str,
        working_dir: str | None = None,
        allow_shell: bool = False,
        **kwargs: Any
    ) -> str:
        """
        Execute a command securely.

        Args:
            command: The command to execute
            working_dir: Optional working directory
            allow_shell: Explicitly allow shell execution (requires allow_shell_fallback)

        Returns:
            Command output or error message
        """
        cwd = working_dir or self.working_dir or os.getcwd()

        # Log the command attempt
        if self.log_commands:
            logger.info(f"Command execution requested: {command!r} in {cwd}")

        # Run security guards
        guard_error = self._guard_command(command, cwd)
        if guard_error:
            logger.warning(f"Command blocked by guard: {command!r} - {guard_error}")
            return guard_error

        # Determine execution mode
        use_shell = False
        needs_shell = self._contains_shell_features(command)

        if needs_shell:
            if allow_shell and self.allow_shell_fallback:
                use_shell = True
                logger.warning(f"Shell execution explicitly allowed for: {command!r}")
            else:
                # Check for dangerous metacharacters
                dangerous = self._contains_dangerous_metacharacters(command)
                if dangerous:
                    return (
                        f"Error: Command contains shell metacharacters {dangerous} which "
                        f"could enable injection attacks. Use simple commands without "
                        f"shell features like pipes, redirects, or variable expansion."
                    )
                # If it's just glob patterns, we might still be able to handle it
                if allow_shell and not self.allow_shell_fallback:
                    return (
                        "Error: Shell execution requested but allow_shell_fallback is disabled. "
                        "Please use simple commands or enable allow_shell_fallback in configuration."
                    )

        try:
            if use_shell:
                # Shell execution with extra logging
                result = await self._execute_shell(command, cwd)
            else:
                # Secure exec-based execution
                result = await self._execute_exec(command, cwd)

            if self.log_commands:
                logger.info(f"Command completed: {command!r}")

            return result

        except ShellSecurityError as e:
            logger.warning(f"Security error: {command!r} - {e}")
            return f"Error: {e}"
        except Exception as e:
            logger.error(f"Execution error: {command!r} - {e}")
            return f"Error executing command: {str(e)}"

    async def _execute_exec(self, command: str, cwd: str) -> str:
        """Execute command using subprocess_exec (secure)."""
        try:
            base_cmd, args = self._parse_command(command)
        except ShellSecurityError as e:
            return f"Error: {e}"

        # Validate against allowlist
        try:
            self._validate_command_allowlist(base_cmd)
        except ShellSecurityError as e:
            return f"Error: {e}"

        # Verify command exists in PATH
        if not self._validate_command_in_path(args[0]):
            return f"Error: Command '{args[0]}' not found in PATH"

        # Execute using exec (no shell)
        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )

        return await self._handle_process(process, command)

    async def _execute_shell(self, command: str, cwd: str) -> str:
        """Execute command using shell (less secure, requires explicit opt-in)."""
        # Additional validation for shell commands
        base_cmd, _ = self._parse_command(command)
        self._validate_command_allowlist(base_cmd)

        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )

        return await self._handle_process(process, command)

    async def _handle_process(self, process: asyncio.subprocess.Process, command: str) -> str:
        """Handle process output and timeout."""
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=self.timeout
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()  # Ensure process is cleaned up
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

    def _guard_command(self, command: str, cwd: str) -> str | None:
        """
        Security guard for potentially destructive commands.

        Returns error message if command should be blocked, None otherwise.
        """
        cmd = command.strip()
        lower = cmd.lower()

        # Check deny patterns
        for pattern in self.deny_patterns:
            if re.search(pattern, lower, re.IGNORECASE):
                return "Error: Command blocked by safety guard (dangerous pattern detected)"

        # Check allow patterns (if configured)
        if self.allow_patterns:
            if not any(re.search(p, lower) for p in self.allow_patterns):
                return "Error: Command blocked by safety guard (not in allowlist)"

        # Path restriction checks
        if self.restrict_to_workspace:
            # Check for path traversal
            if "..\\" in cmd or "../" in cmd:
                return "Error: Command blocked by safety guard (path traversal detected)"

            cwd_path = Path(cwd).resolve()

            # Extract and validate paths
            win_paths = re.findall(r"[A-Za-z]:\\[^\s\\\"']+", cmd)
            posix_paths = re.findall(r"/[^\s\"']+", cmd)

            for raw in win_paths + posix_paths:
                try:
                    p = Path(raw).resolve()
                except Exception:
                    continue
                if cwd_path not in p.parents and p != cwd_path:
                    return "Error: Command blocked by safety guard (path outside working dir)"

        return None
