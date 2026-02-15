import pytest

from nanobot.agent.tools.shell import ExecTool

BLOCKED_COMMANDS = [
    "mkfs.ext4 /dev/sda",
    "sudo mkfs.ext4 /dev/sda",
    r"cmd /c C:\\Windows\\System32\\format.com c:",
    r"C:\\Windows\\System32\\format.com c:",
    r"cmd.exe /c shutdown /r /t 0",
    r"cmd /c C:\\Windows\\System32\\shutdown.exe /r /t 0",
    r"C:\\Windows\\System32\\shutdown.exe /s /t 0",
    r"\\server\share\mkfs.exe /dev/sda",
    r"\\server\share\shutdown.exe /r /t 0",
    "(mkfs.ext4 /dev/sda)",
    "$(mkfs.ext4 /dev/sda)",
    "bash -lc \"mkfs.ext4 /dev/sda\"",
    "shutdown now",
    "sudo shutdown -h now",
    "$(reboot)",
    "bash -lc \"shutdown now\"",
    "env PATH=/tmp shutdown now",
    "sudo env FOO=1 mkfs.ext4 /dev/sda",
]

ALLOWED_COMMANDS = [
    "curl -s \"wttr.in/London?format=3\"",
    "echo mkfs.ext4 /dev/sda",
    "bash -lc \"echo mkfs.ext4 /dev/sda\"",
    "echo shutdown now",
    "bash -lc \"echo shutdown now\"",
    "env PATH=/tmp echo shutdown now",
    r"cmd /c echo shutdown now",
    r"cmd /c echo C:\\Windows\\System32\\format.com c:",
    r"echo C:\\Windows\\System32\\shutdown.exe /s /t 0",
    r"echo \\server\share\mkfs.exe /dev/sda",
    "FOO=shutdown",
]


@pytest.mark.parametrize("command", BLOCKED_COMMANDS)
def test_guard_blocks_destructive_commands_in_prefixed_and_nested_contexts(command: str) -> None:
    tool = ExecTool()

    result = tool._guard_command(command, cwd=".")

    assert result == "Error: Command blocked by safety guard (dangerous pattern detected)"


@pytest.mark.parametrize("command", ALLOWED_COMMANDS)
def test_guard_allows_non_executing_text_mentions(command: str) -> None:
    tool = ExecTool()

    result = tool._guard_command(command, cwd=".")

    assert result is None
