"""Shell execution tool with hardened security."""

import asyncio
import os
import re
import shlex
from pathlib import Path
from typing import Any, Optional, Set, Tuple

from nanobot.agent.tools.base import Tool


class ExecTool(Tool):
    """Tool to execute shell commands with comprehensive security guards."""

    # Dangerous commands that should never be allowed
    DANGEROUS_COMMANDS: Set[str] = {
        'rm', 'del', 'rmdir', 'format', 'mkfs', 'diskpart', 'dd',
        'shutdown', 'reboot', 'poweroff', 'halt', 'sysctl',
        'chmod', 'chown', 'chgrp', 'setfacl', 'setfattr',
        'mount', 'umount', 'fdisk', 'parted', 'cfdisk',
        'nc', 'netcat', 'ncat', 'socat', 'telnet',
        'ssh', 'scp', 'sftp',
        'python', 'python2', 'python3', 'py', 'pypy', 'pypy3',
        'perl', 'ruby', 'lua', 'php', 'node', 'nodejs',
        'java', 'javac', 'groovy', 'scala',
        'go', 'rust', 'rustc', 'cargo',
        'gcc', 'g++', 'clang', 'clang++', 'make', 'cmake',
        'docker', 'podman', 'containerd', 'kubectl',
        'systemctl', 'service', 'init', 'telinit',
        'crontab', 'at', 'batch', 'anacron',
        'sudo', 'su', 'doas', 'pkexec', 'gksu', 'kdesu',
        'passwd', 'useradd', 'userdel', 'usermod',
        'groupadd', 'groupdel', 'groupmod',
        'visudo', 'vipw', 'vigr',
        'insmod', 'rmmod', 'modprobe', 'lsmod',
        'iptables', 'ip6tables', 'nft', 'firewall-cmd', 'ufw',
        'tcpdump', 'wireshark', 'tshark',
        'nmap', 'masscan', 'zmap',
        'eval', 'exec', 'source', '.',
        'find', 'xargs', 'parallel',
    }

    # Commands that are generally safe
    SAFE_COMMANDS: Set[str] = {
        'ls', 'dir', 'vdir', 'pwd', 'cd',
        'cat', 'tac', 'head', 'tail', 'less', 'more', 'nl',
        'cp', 'mv', 'ln', 'mkdir', 'touch',
        'echo', 'printf', 'yes', 'true', 'false',
        'date', 'cal', 'ncal', 'time', 'timedatectl',
        'hostname', 'hostnamectl', 'uname', 'arch', 'nproc',
        'whoami', 'who', 'w', 'users', 'groups', 'id',
        'ps', 'top', 'htop', 'uptime', 'free', 'vmstat', 'iostat', 'sar',
        'df', 'du', 'stat', 'wc', 'sort', 'uniq', 'cut', 'paste',
        'diff', 'cmp', 'comm', 'patch',
        'file', 'which', 'whereis', 'locate', 'updatedb', 'type', 'compgen',
        'man', 'info', 'apropos', 'whatis',
        'history', 'fc',
        'alias', 'unalias', 'set', 'unset', 'export', 'env', 'printenv',
        'read', 'sleep', 'wait', 'kill', 'killall', 'pkill', 'pgrep', 'nice', 'renice',
        'bg', 'fg', 'jobs', 'disown', 'nohup',
        'trap', 'exit', 'logout', 'return', 'break', 'continue',
        'test', '[',
        'seq', 'shuf', 'rand',
        'column', 'fold', 'fmt', 'pr',
        'tr', 'rev', 'cksum', 'sum', 'md5sum', 'sha1sum', 'sha224sum', 'sha256sum', 'sha384sum', 'sha512sum',
        'realpath', 'readlink', 'dirname', 'basename',
        'mktemp', 'mkfifo', 'mknod',
        'ip', 'ifconfig', 'route', 'netstat', 'ss', 'ping', 'ping6', 'traceroute', 'tracepath',
        'dig', 'nslookup', 'host', 'getent',
        'grep', 'egrep', 'fgrep', 'zgrep',
        'tar', 'gzip', 'gunzip', 'zcat', 'bzip2', 'bunzip2', 'xz', 'unxz',
        'zip', 'unzip', '7z', 'rar', 'unrar',
        'awk', 'gawk', 'mawk', 'nawk',
        'sed', 'gsed',
        'curl', 'wget',  # These need special handling
        'base64', 'xxd', 'od', 'hexdump',  # Only safe when not piping to shell
    }

    def __init__(
        self,
        timeout: int = 60,
        working_dir: str | None = None,
        deny_patterns: list[str] | None = None,
        allow_patterns: list[str] | None = None,
        restrict_to_workspace: bool = False,
        path_append: str = "",
        enable_enhanced_security: bool = True,
    ):
        self.timeout = timeout
        self.working_dir = working_dir
        self.enable_enhanced_security = enable_enhanced_security
        
        self.deny_patterns = deny_patterns or self._get_default_deny_patterns()
        self.allow_patterns = allow_patterns or []
        self.restrict_to_workspace = restrict_to_workspace
        self.path_append = path_append

    def _get_default_deny_patterns(self) -> list[str]:
        """Return comprehensive default deny patterns."""
        return [
            # Original patterns
            r"\brm\s+-[rf]{1,2}\b",                    # rm -rf
            r"\bdel\s+/[fq]\b",                        # del /f /q
            r"\brmdir\s+/s\b",                         # rmdir /s
            r"(?:^|[;&|]\s*)format\b",                  # format
            r"\b(mkfs|diskpart)\b",                     # disk operations
            r"\bdd\s+if=",                              # dd
            r">\s*/dev/sd",                              # write to disk
            r"\b(shutdown|reboot|poweroff|halt)\b",     # system power
            r":\(\)\s*\{.*\};\s*:",                     # fork bomb
            
            # NEW: Encoding/decoding bypasses
            r"\b(base64|xxd|od|hexdump)\s+.*\|\s*(bash|sh|zsh|ksh)",
            r"\b(echo|printf)\s+['\"]?[A-Za-z0-9+/=]+['\"]?\s*\|\s*(base64|xxd)\s*-d\s*\|\s*(bash|sh)",
            
            # NEW: Command substitution
            r"\$\([^)]*\)",                            # $(command)
            r"`[^`]+`",                                 # `command`
            
            # NEW: Variable expansion
            r"\$\{[^}]*:-[^}]*\}",                     # ${VAR:-command}
            r"\$\{[^}]*:\+[^}]*\}",                   # ${VAR:+command}
            
            # NEW: eval/exec
            r"\b(eval|exec)\s+['\"]?",
            r"\b(bash|sh|zsh|ksh|csh)\s+-c\s",
            
            # NEW: Interpreter invocation
            r"\b(python|python2|python3|py|pypy)\s+(-c|-m)\s",
            r"\b(perl|ruby|lua|php|node)\s+(-e|-m)\s",
            
            # NEW: Remote code execution
            r"\b(curl|wget|fetch|lynx)\s+.*\|\s*(bash|sh|zsh)",
            r"\b(curl|wget)\s+.*-o\s*-.*\|",
            
            # NEW: find/xargs dangerous patterns
            r"\bfind\s+.*-exec\s+.*;",
            r"\bfind\s+.*-delete\b",
            r"\bxargs\s+.*-(rm|del|rmdir|chmod|chown)",
            
            # NEW: Process substitution
            r"<\([^)]+\)",
            r">\([^)]+\)",
            
            # NEW: Variable assignment followed by dangerous usage
            r"^\s*\w+\s*=.*;\s*\$\w+",                 # VAR=value; $VAR
            r"^\s*\w+\s*=.*;\s*\$\{\w+\}",             # VAR=value; ${VAR}
        ]

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
    
    async def execute(self, command: str, working_dir: str | None = None, **kwargs: Any) -> str:
        cwd = working_dir or self.working_dir or os.getcwd()
        
        guard_error = self._guard_command_enhanced(command, cwd)
        if guard_error:
            return guard_error
        
        env = os.environ.copy()
        if self.path_append:
            env["PATH"] = env.get("PATH", "") + os.pathsep + self.path_append

        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env,
                preexec_fn=os.setsid if hasattr(os, 'setsid') else None,
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=self.timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                try:
                    await asyncio.wait_for(process.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    pass
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
            
            max_len = 10000
            if len(result) > max_len:
                result = result[:max_len] + f"\n... (truncated, {len(result) - max_len} more chars)"
            
            return result
            
        except Exception as e:
            return f"Error executing command: {str(e)}"

    def _guard_command_enhanced(self, command: str, cwd: str) -> str | None:
        """Enhanced command safety guard with multiple layers."""
        cmd = command.strip()
        if not cmd:
            return "Error: Empty command"
        
        lower = cmd.lower()
        
        # Layer 1: Pattern-based blocking
        for pattern in self.deny_patterns:
            if re.search(pattern, lower):
                return f"Error: Command blocked (dangerous pattern detected)"
        
        # Layer 2: Allowlist check
        if self.allow_patterns:
            if not any(re.search(p, lower) for p in self.allow_patterns):
                return "Error: Command blocked (not in allowlist)"
        
        # Layer 3: Enhanced security checks
        if self.enable_enhanced_security:
            enhanced_check = self._enhanced_security_check(cmd, lower)
            if enhanced_check:
                return enhanced_check
        
        # Layer 4: Path traversal check
        if self.restrict_to_workspace:
            path_check = self._check_path_traversal(cmd, cwd)
            if path_check:
                return path_check
        
        return None

    def _enhanced_security_check(self, cmd: str, lower: str) -> str | None:
        """Additional security checks beyond regex patterns."""
        
        # Check for variable assignment followed by execution (bypass attempt)
        if re.search(r'^\s*\w+\s*=.*;\s*\$\w+', cmd) or re.search(r'^\s*\w+\s*=.*;\s*\$\{\w+\}', cmd):
            # Check if the variable might contain a dangerous command
            if any(d in lower for d in ['rm ', 'rm-', 'del ', 'del/', 'shutdown', 'reboot']):
                return "Error: Command blocked (variable assignment with potential dangerous command)"
        
        try:
            parts = shlex.split(cmd, posix=True)
        except ValueError:
            if "'" in cmd or '"' in cmd:
                return "Error: Command blocked (unbalanced quotes detected)"
            return "Error: Command blocked (invalid syntax)"
        
        if not parts:
            return "Error: Empty command after parsing"
        
        base_cmd = parts[0].split('/')[-1].lower()
        
        # Check for dangerous commands with context
        if base_cmd in self.DANGEROUS_COMMANDS:
            # Allow rm without -rf flags (single file deletion is generally safe)
            if base_cmd == 'rm':
                # Check if it's just deleting files without recursive/force flags
                has_dangerous_flags = any('-r' in p or '-f' in p for p in parts[1:] if p.startswith('-'))
                if not has_dangerous_flags:
                    # Still check for dangerous paths
                    dangerous_paths = ['/', '/etc', '/home', '/root', '/usr', '/var', '/bin', '/sbin']
                    for part in parts[1:]:
                        if not part.startswith('-') and any(part.startswith(dp) for dp in dangerous_paths):
                            return "Error: Command blocked (rm on system directory)"
                    return None  # Allow safe rm
            
            # Allow curl/wget with safe usage
            if base_cmd in ('curl', 'wget'):
                if '|' in cmd and any(s in lower for s in ['bash', 'sh', 'zsh']):
                    return "Error: Command blocked (curl/wget piping to shell)"
                return None  # Allow safe curl/wget
            
            # Allow find/xargs with safe usage
            if base_cmd in ('find', 'xargs'):
                # Check if piping to or executing dangerous commands
                if any(d in lower for d in ['-exec', '-delete', 'rm ', 'del ', 'chmod', 'chown']):
                    # More detailed check
                    if re.search(r'-exec\s+rm\s+-rf', lower) or '-delete' in lower:
                        return "Error: Command blocked (find with dangerous operation)"
                return None
            
            # Allow base64/xxd when not piping to shell
            if base_cmd in ('base64', 'xxd', 'od', 'hexdump'):
                if '|' in cmd and any(s in lower for s in ['bash', 'sh', 'zsh', 'ksh']):
                    return "Error: Command blocked (decode piping to shell)"
                return None
            
            return f"Error: Command blocked ('{base_cmd}' is restricted)"
        
        # Check for pipe to dangerous commands
        if '|' in cmd:
            pipe_parts = cmd.split('|')
            for pipe_cmd in pipe_parts[1:]:
                pipe_stripped = pipe_cmd.strip()
                if pipe_stripped:
                    try:
                        pipe_parts_parsed = shlex.split(pipe_stripped, posix=True)
                        if pipe_parts_parsed:
                            pipe_base = pipe_parts_parsed[0].split('/')[-1].lower()
                            if pipe_base in self.DANGEROUS_COMMANDS:
                                # Allow safe piped commands
                                if pipe_base in ('rm', 'curl', 'wget', 'base64', 'find', 'xargs'):
                                    # Additional context check
                                    if pipe_base == 'rm' and '-rf' not in pipe_cmd.lower():
                                        continue  # Allow rm without -rf
                                    if pipe_base in ('curl', 'wget', 'base64') and not any(s in pipe_cmd.lower() for s in ['bash', 'sh']):
                                        continue  # Allow if not piping to shell
                                return f"Error: Command blocked (piping to restricted command '{pipe_base}')"
                    except ValueError:
                        return "Error: Command blocked (invalid pipe syntax)"
        
        # Check for background execution
        if cmd.endswith('&'):
            bg_cmd = cmd[:-1].strip()
            bg_check = self._enhanced_security_check(bg_cmd, bg_cmd.lower())
            if bg_check:
                return bg_check.replace("Command blocked", "Background command blocked")
        
        # Check for command sequences
        for sep in [';', '&&', '||']:
            if sep in cmd:
                sub_cmds = re.split(r'\s*' + re.escape(sep) + r'\s*', cmd)
                for sub_cmd in sub_cmds:
                    if sub_cmd.strip():
                        sub_check = self._enhanced_security_check(sub_cmd, sub_cmd.lower())
                        if sub_check:
                            return f"Error: Command sequence blocked ({sep} separator)"
        
        return None

    def _check_path_traversal(self, command: str, cwd: str) -> str | None:
        """Check for path traversal attempts."""
        if "..\\" in command or "../" in command:
            return "Error: Command blocked (path traversal detected)"

        cwd_path = Path(cwd).resolve()

        for raw in self._extract_absolute_paths(command):
            try:
                p = Path(raw.strip()).resolve()
            except Exception:
                continue
            if p.is_absolute() and cwd_path not in p.parents and p != cwd_path:
                return "Error: Command blocked (path outside working dir)"

        return None

    @staticmethod
    def _extract_absolute_paths(command: str) -> list[str]:
        """Extract absolute paths from command."""
        win_paths = re.findall(r"[A-Za-z]:\\[^\\s\"'|><;]+", command)
        posix_paths = re.findall(r"(?:^|[\s|>])(/[^\\s\"'>]+)", command)
        return win_paths + posix_paths


# Export for compatibility
ShellTool = ExecTool
