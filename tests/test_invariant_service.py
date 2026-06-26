import pytest
import subprocess
import sys
from pathlib import Path

# Import the actual production module
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from nanobot.apps.cli.service import Service

@pytest.mark.parametrize("payload", [
    # Exact exploit case: command injection via argument manipulation
    ["echo", "test; rm -rf /"],
    # Boundary case: empty argument list (should fail gracefully)
    [],
    # Valid input: normal command execution
    ["echo", "safe_test"],
])
def test_subprocess_command_injection_invariant(payload):
    """Invariant: subprocess.run with user-controlled argv must not execute arbitrary shell commands."""
    service = Service()
    
    # If payload is empty list, expect ValueError or similar
    if not payload:
        with pytest.raises((ValueError, subprocess.SubprocessError)):
            service._run_argv(payload, timeout=5)
        return
    
    # For non-empty payloads, execute and verify
    result = service._run_argv(payload, timeout=5)
    
    # Security property: The command should execute exactly the given argv,
    # not interpret shell metacharacters. Verify by checking output.
    if payload[0] == "echo":
        # For echo commands, ensure output matches the literal argument
        # If shell interpretation occurred, we'd see different output
        expected_output = payload[1] if len(payload) > 1 else ""
        assert result.stdout.strip() == expected_output, \
            f"Command output mismatch. Expected literal '{expected_output}', got '{result.stdout.strip()}'. " \
            f"This may indicate shell interpretation of metacharacters."
    
    # Additional invariant: Process must complete (not hang or crash)
    assert result.returncode is not None, "Process must complete with a return code"