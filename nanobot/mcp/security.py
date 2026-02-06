"""Security utilities for MCP validation."""

import re
from pathlib import Path
from urllib.parse import urlparse


# Whitelist of safe commands for stdio transport
SAFE_COMMANDS = frozenset({
    "python", "python3", "py",
    "node", "nodejs",
    "deno", "bun",
    "ruby", "rb",
})

# Dangerous characters in tool names
DANGEROUS_CHARS = re.compile(r'[<>&|;$\\]')

# Internal IP patterns for SSRF protection
INTERNAL_IP_PATTERNS = [
    re.compile(r'^127\.'),           # 127.0.0.0/8
    re.compile(r'^10\.'),            # 10.0.0.0/8
    re.compile(r'^172\.(1[6-9]|2[0-9]|3[0-1])\.'),  # 172.16.0.0/12
    re.compile(r'^192\.168\.'),     # 192.168.0.0/16
    re.compile(r'^169\.254\.'),     # 169.254.0.0/16 (link-local)
    re.compile(r'^0\.'),             # 0.0.0.0/8
    re.compile(r'^::1$'),            # IPv6 loopback
    re.compile(r'^fc00:'),           # IPv6 unique local
    re.compile(r'^fe80:'),           # IPv6 link-local
]


def validate_command(command: str, args: list[str]) -> tuple[bool, str]:
    """
    Validate stdio command against whitelist.
    
    Returns:
        (is_valid, error_message)
    """
    # Check if command is in whitelist
    cmd_base = Path(command).name
    if cmd_base not in SAFE_COMMANDS:
        return False, f"Command '{command}' not in whitelist. Allowed: {', '.join(SAFE_COMMANDS)}"
    
    # Check for shell injection in args
    dangerous_patterns = [';', '|', '&', '$', '`', '$(', '${', '<(', '>(']
    for i, arg in enumerate(args):
        for pattern in dangerous_patterns:
            if pattern in arg:
                return False, f"Dangerous pattern '{pattern}' found in arg[{i}]"
    
    return True, ""


def sanitize_tool_name(name: str) -> str:
    """
    Sanitize tool name by removing dangerous characters.
    
    Args:
        name: Raw tool name
        
    Returns:
        Sanitized name safe for registration
    """
    # Remove dangerous characters
    sanitized = DANGEROUS_CHARS.sub('_', name)
    
    # Replace multiple underscores with single
    sanitized = re.sub(r'_+', '_', sanitized)
    
    # Remove leading/trailing underscores
    sanitized = sanitized.strip('_')
    
    return sanitized or "unnamed_tool"


def validate_sse_url(url: str) -> tuple[bool, str]:
    """
    Validate SSE URL to prevent SSRF.
    
    Returns:
        (is_valid, error_message)
    """
    try:
        parsed = urlparse(url)
        
        # Must be http or https
        if parsed.scheme not in ('http', 'https'):
            return False, f"URL scheme must be http or https, got: {parsed.scheme}"
        
        # Must have a hostname
        if not parsed.hostname:
            return False, "URL must have a hostname"
        
        hostname = parsed.hostname.lower()
        
        # Check for internal IPs
        for pattern in INTERNAL_IP_PATTERNS:
            if pattern.match(hostname):
                return False, f"URL points to internal address: {hostname}"
        
        # Check for localhost variants
        if hostname in ('localhost', 'localhost.localdomain', 'ip6-localhost', 'ip6-loopback'):
            return False, f"URL points to localhost: {hostname}"
        
        return True, ""
        
    except Exception as e:
        return False, f"Invalid URL: {e}"


def validate_script_path(script_path: str) -> tuple[bool, str]:
    """
    Validate script path to prevent path traversal.
    
    Returns:
        (is_valid, error_message)
    """
    # Check for path traversal
    if '..' in script_path:
        return False, "Path traversal detected (contains '..')"
    
    if '~' in script_path:
        return False, "Home directory expansion not allowed (contains '~')"
    
    # Resolve to absolute path
    try:
        path = Path(script_path).resolve()
    except Exception as e:
        return False, f"Invalid path: {e}"
    
    # Check if path is within allowed directories
    # Allow: workspace, home/.nanobot/, absolute paths that exist
    home = Path.home()
    allowed_roots = [
        home / ".nanobot",
        Path("/usr/local/lib"),
        Path("/usr/lib"),
    ]
    
    # Also allow if it's an absolute existing file
    if path.is_absolute() and path.exists():
        return True, ""
    
    # Check against allowed roots
    for root in allowed_roots:
        try:
            path.relative_to(root)
            return True, ""
        except ValueError:
            continue
    
    return False, f"Script path '{script_path}' not in allowed directories"
