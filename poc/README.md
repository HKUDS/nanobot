# Security Audit POC Environment

This directory contains a Docker-based proof-of-concept environment to verify and demonstrate the vulnerabilities identified in the [SECURITY_AUDIT.md](../SECURITY_AUDIT.md).

## Quick Start

```bash
# Run all POC tests
./run_poc.sh

# Build only (no tests)
./run_poc.sh --build-only

# Include vulnerable dependency tests
./run_poc.sh --vulnerable

# Clean and run fresh
./run_poc.sh --clean
```

## Vulnerabilities Demonstrated

### 1. Shell Command Injection (MEDIUM)

**File:** `nanobot/agent/tools/shell.py`

The shell tool uses `create_subprocess_shell()` which is vulnerable to command injection. While a regex pattern blocks some dangerous commands (`rm -rf /`, fork bombs, etc.), many bypasses exist:

| Bypass Technique | Example |
|-----------------|---------|
| Command substitution | `echo $(cat /etc/passwd)` |
| Backtick substitution | `` echo `id` `` |
| Base64 encoding | `echo BASE64 | base64 -d \| bash` |
| Alternative interpreters | `python3 -c 'import os; ...'` |
| Environment exfiltration | `env \| grep -i key` |

**Impact:**
- Read sensitive files
- Execute arbitrary code
- Network reconnaissance
- Potential container escape

### 2. Path Traversal (MEDIUM)

**File:** `nanobot/agent/tools/filesystem.py`

The `_validate_path()` function supports restricting file access to a base directory, but this parameter is **never passed** by any tool:

```python
# The function signature:
def _validate_path(path: str, base_dir: Path | None = None)

# But all tools call it without base_dir:
valid, file_path = _validate_path(path)  # No restriction!
```

**Impact:**
- Read any file the process can access (`/etc/passwd`, SSH keys, AWS credentials)
- Write to any writable location (`/tmp`, home directories)
- List any directory for reconnaissance

### 3. LiteLLM Remote Code Execution (CRITICAL)

**CVE:** CVE-2024-XXXX (Multiple related CVEs)  
**Affected Versions:** litellm <= 1.28.11 and < 1.40.16

Multiple vectors for Remote Code Execution through unsafe `eval()` usage:

| Vector | Location | Description |
|--------|----------|-------------|
| Template Injection | `litellm/utils.py` | User input passed to eval() |
| Proxy Config | `proxy/ui_sso.py` | Configuration values evaluated |
| SSTI | Various | Unsandboxed Jinja2 templates |
| Callback Handlers | Callbacks module | Dynamic code execution |

**Impact:**
- Arbitrary code execution on the server
- Access to all environment variables (API keys, secrets)
- Full file system access
- Reverse shell capability
- Lateral movement in network

### 4. Vulnerable Dependencies (CRITICAL - if using old versions)

**litellm < 1.40.16:**
- Remote Code Execution via `eval()`
- Server-Side Request Forgery (SSRF)
- API Key Leakage

**ws < 8.17.1:**
- Denial of Service via header flooding

## Directory Structure

```
poc/
├── docker-compose.yml      # Container orchestration
├── Dockerfile.nanobot      # Python app container
├── Dockerfile.bridge       # Node.js bridge container
├── run_poc.sh              # Test harness script
├── config/
│   └── config.json         # Test configuration (not used by exploit scripts)
├── exploits/
│   ├── shell_injection.py  # Shell bypass tests - uses real ExecTool
│   ├── path_traversal.py   # File access tests - uses real ReadFileTool/WriteFileTool
│   └── litellm_rce.py      # LiteLLM RCE tests - scans real litellm source code
├── sensitive/              # Test files to demonstrate path traversal
└── results/                # Test output
```

## Running Individual Tests

### Shell Injection POC

```bash
# In container
docker compose run --rm nanobot python /app/poc/exploits/shell_injection.py

# Locally (if dependencies installed)
python poc/exploits/shell_injection.py
```

### Path Traversal POC

```bash
# In container
docker compose run --rm nanobot python /app/poc/exploits/path_traversal.py

# Locally
python poc/exploits/path_traversal.py
```

### LiteLLM RCE POC

```bash
# In container (current version)
docker compose run --rm nanobot python /app/poc/exploits/litellm_rce.py

# With vulnerable version
docker compose --profile vulnerable run --rm nanobot-vulnerable python /app/poc/exploits/litellm_rce.py

# Locally
python poc/exploits/litellm_rce.py
```

### Interactive Testing

```bash
# Get a shell in the container
docker compose run --rm nanobot bash

# Test individual commands
python -c "
import asyncio
from nanobot.agent.tools.shell import ExecTool
tool = ExecTool()
print(asyncio.run(tool.execute(command='cat /etc/passwd')))
"
```

## Expected Results

### Shell Injection

Most tests should show **⚠️ EXECUTED** status, demonstrating that commands bypass the pattern filter:

```
[TEST 1] Command Substitution - Reading /etc/passwd
  Status: ⚠️ EXECUTED
  Risk: Read sensitive system file via command substitution
  Output: root:x:0:0:root:/root:/bin/bash\ndaemon:x:1:1:...
```

### Path Traversal

File operations outside the workspace should succeed (or fail only due to OS permissions, not code restrictions):

```
[TEST 1] Read /etc/passwd
  Status: ⚠️ SUCCESS (VULNERABLE)
  Risk: System user enumeration
  Content: root:x:0:0:root:/root:/bin/bash...
```

## Cleanup

```bash
# Stop and remove containers
docker compose down -v

# Remove results
rm -rf results/*

# Full cleanup
./run_poc.sh --clean
```

## Recommended Mitigations

### For Shell Injection

1. **Replace `create_subprocess_shell` with `create_subprocess_exec`:**
   ```python
   # Instead of:
   process = await asyncio.create_subprocess_shell(command, ...)
   
   # Use:
   args = shlex.split(command)
   process = await asyncio.create_subprocess_exec(*args, ...)
   ```

2. **Implement command whitelisting:**
   ```python
   ALLOWED_COMMANDS = {'ls', 'cat', 'grep', 'find', 'echo'}
   command_name = shlex.split(command)[0]
   if command_name not in ALLOWED_COMMANDS:
       raise SecurityError(f"Command not allowed: {command_name}")
   ```

3. **Use container isolation with seccomp profiles**

### For Path Traversal

1. **Always pass base_dir to _validate_path:**
   ```python
   WORKSPACE_DIR = Path("/app/workspace")
   
   async def execute(self, path: str) -> str:
       valid, file_path = _validate_path(path, base_dir=WORKSPACE_DIR)
   ```

2. **Prevent symlink traversal:**
   ```python
   resolved = Path(path).resolve()
   if not resolved.is_relative_to(base_dir):
       raise SecurityError("Path traversal detected")
   ```

## Contributing

When adding new POC tests:

1. Add test method in appropriate exploit file
2. Include expected risk description
3. Document bypass technique
4. Update this README
