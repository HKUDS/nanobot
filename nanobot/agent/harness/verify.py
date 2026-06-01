"""运行时 Harness 验证命令执行器（由 verify tool 和 Plan 共享）"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

_IS_WINDOWS = sys.platform == "win32"
_DEFAULT_MAX_OUTPUT_CHARS = 10_000  # 验证命令最大输出字符数


@dataclass(slots=True)
class VerifyResult:
    """
    单条 verify 命令执行结果的数据结构。
    - command：命令行字符串
    - cwd：执行目录
    - exit_code：退出码，None 表示未完成
    - stdout：标准输出内容
    - stderr：标准错误内容
    - timed_out：是否超时退出
    - denied：是否被权限策略阻止
    - deny_reason：阻止原因
    """

    command: str
    cwd: str
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    denied: bool = False
    deny_reason: str | None = None

    @property
    def allowed(self) -> bool:
        # 判断本次命令是否被允许
        return not self.denied


def validate_verify_command(
    command: str,
    *,
    allow_commands: list[str],
    allow_arbitrary_commands: bool = False,
    trusted_workspace: bool = False,
) -> str | None:
    """
    检查命令是否被允许运行。
    - 不被允许时返回错误原因字符串
    - 被允许运行时返回 None
    """
    cmd = command.strip()
    if not cmd:
        return "Error: command must not be empty"  # 必须有命令

    if allow_arbitrary_commands:
        # 如果允许任意命令，但需要 trusted_workspace=真
        if not trusted_workspace:
            return (
                "Error: allow_arbitrary_commands requires trusted_workspace "
                "(set agents.defaults.harness.trustedWorkspace)"
            )
        return None

    # 前缀匹配白名单
    normalized = cmd.lower()
    for prefix in allow_commands:
        prefix_norm = prefix.strip().lower()
        if prefix_norm and normalized.startswith(prefix_norm):
            return None

    allowed = ", ".join(repr(item) for item in allow_commands)
    return f"Error: command not in verify allowlist ({allowed})"  # 不在白名单


def format_verify_result(
    result: VerifyResult,
    *,
    max_output_chars: int = _DEFAULT_MAX_OUTPUT_CHARS,
) -> str:
    """
    渲染 VerifyResult 结果为文本，面向大模型读取。
    超出 max_output_chars 长度时进行截断。
    """
    if result.denied:
        return result.deny_reason or "Error: command denied by verify policy"  # 权限拒绝

    parts: list[str] = []
    if result.stdout:
        parts.append(result.stdout.rstrip("\n"))  # 标准输出内容
    if result.stderr.strip():
        # 如果有标准错误输出，则添加进结果，并带上 STDERR 前缀
        parts.append(f"STDERR:\n{result.stderr.rstrip()}")
    if result.timed_out:
        # 超时信息
        parts.append(f"Error: Command timed out after running in {result.cwd!r}")
    elif result.exit_code is not None:
        # 正常/异常退出码
        parts.append(f"Exit code: {result.exit_code}")

    text = "\n".join(parts) if parts else "(no output)"

    # 如果输出过长则进行截断，保留头尾各一半
    if len(text) > max_output_chars:
        half = max_output_chars // 2
        text = (
            text[:half]
            + f"\n\n... ({len(text) - max_output_chars:,} chars truncated) ...\n\n"
            + text[-half:]
        )
    return text


async def run_verify_command(
    command: str,
    cwd: str,
    timeout_s: int,
    *,
    allow_commands: list[str],
    allow_arbitrary_commands: bool = False,
    trusted_workspace: bool = False,
    max_output_chars: int = _DEFAULT_MAX_OUTPUT_CHARS,
    spawn: Callable[..., Awaitable[Any]] | None = None,
) -> VerifyResult:
    """
    在通过权限校验的情况下执行命令。
    - 命令首先经过 validate_verify_command 校验
    - 允许后异步执行，按 timeout_s 超时时间限制
    - 支持 Windows 和类 Unix 平台差异
    - 返回 VerifyResult 结构体
    """
    cmd = command.strip()
    deny_reason = validate_verify_command(
        cmd,
        allow_commands=allow_commands,
        allow_arbitrary_commands=allow_arbitrary_commands,
        trusted_workspace=trusted_workspace,
    )
    if deny_reason is not None:
        # 校验不通过，返回拒绝原因
        return VerifyResult(
            command=cmd,
            cwd=cwd,
            denied=True,
            deny_reason=deny_reason,
        )

    # spawn 用于自定义进程启动函数，默认为 _spawn_shell
    spawn_fn = spawn or _spawn_shell
    try:
        # 启动子进程进行命令执行
        # 这里采用子进程执行命令（而不是直接用 Python 内置方式或在主进程内执行），主要是出于以下考虑：
        # 1. 安全隔离：子进程运行可以有效隔离主进程，减少恶意命令或 bug 对主系统的破坏。
        # 2. 支持多平台：通过子进程能兼容 windows 和类 unix 环境下的 shell 行为和环境变量管理。
        # 3. 可控性强：可以方便地向子进程传递超时、环境变量、目录等参数，且能精准杀死超时的进程。
        # 4. 获取命令完整输出：子进程能直接拿到 stdout/stderr，便于结果结构化返回给 Agent。
        process = await spawn_fn(cmd, cwd, _build_env())
        try:
            # 等待子进程输出，带超时控制
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout_s,
            )
        except asyncio.TimeoutError:
            # 超时则杀掉进程并标记
            await _kill_process(process)
            result = VerifyResult(
                command=cmd,
                cwd=cwd,
                timed_out=True,
                exit_code=None,
            )
            return result
        except asyncio.CancelledError:
            # 协程被取消也要杀掉进程再抛
            await _kill_process(process)
            raise

        # 正常返回执行结果
        return VerifyResult(
            command=cmd,
            cwd=cwd,
            exit_code=process.returncode,
            stdout=_decode(stdout_bytes),
            stderr=_decode(stderr_bytes),
        )
    except Exception as exc:
        # 运行出错综合兜底
        return VerifyResult(
            command=cmd,
            cwd=cwd,
            exit_code=1,
            stderr=f"Error executing verify command: {exc}",
        )


def _decode(data: bytes | None) -> str:
    """
    解码字节为 UTF-8 字符串，出错时用替代字符。
    """
    if not data:
        return ""
    return data.decode("utf-8", errors="replace")


def _build_env() -> dict[str, str]:
    """
    构建执行命令所需的环境变量字典。
    - Windows 和 Nix 系统区别处理
    - 保证 PYTHONUNBUFFERED=1，避免缓冲阻塞
    """
    if _IS_WINDOWS:
        system_root = os.environ.get("SYSTEMROOT", r"C:\Windows")
        return {
            "SYSTEMROOT": system_root,
            "COMSPEC": os.environ.get("COMSPEC", f"{system_root}\\system32\\cmd.exe"),
            "USERPROFILE": os.environ.get("USERPROFILE", ""),
            "PATH": os.environ.get("PATH", f"{system_root}\\system32;{system_root}"),
            "PYTHONUNBUFFERED": "1",
        }
    home = os.environ.get("HOME", "/tmp")
    return {
        "HOME": home,
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "TERM": os.environ.get("TERM", "dumb"),
        "PYTHONUNBUFFERED": "1",
    }


async def _spawn_shell(command: str, cwd: str, env: dict[str, str]) -> asyncio.subprocess.Process:
    """
    启动 shell 子进程执行命令
    - Windows 下用 create_subprocess_shell (交给 cmd 执行)
    - Unix 下优先挑 bash，否则默认 /bin/bash，用 bash -lc "cmd"
    """
    if _IS_WINDOWS:
        return await asyncio.create_subprocess_shell(
            command,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
        )
    # 非 Windows，查找 bash 路径，不存在就用 /bin/bash
    shell = shutil.which("bash") or "/bin/bash"
    return await asyncio.create_subprocess_exec(
        shell,
        "-lc",
        command,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
        env=env,
    )


async def _kill_process(process: asyncio.subprocess.Process) -> None:
    """
    强制杀死异步子进程，并等待结束，最大超时 5 秒
    """
    process.kill()
    try:
        await asyncio.wait_for(process.wait(), timeout=5.0)
    except asyncio.TimeoutError:
        # 超时无视，进程已被 kill
        pass
