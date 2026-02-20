"""
Google Gemini CLI OAuth provider implementation.

Migrated from openclaw/extensions/google-gemini-cli-auth
Provides OAuth-based authentication for Google's Gemini CLI (Code Assist).
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import shutil
import socket
import tempfile
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

# Lazy imports for UI components
def _get_console():
    from rich.console import Console
    return Console()

def _get_prompt():
    from typer import prompt
    return prompt


# Configuration
CLIENT_ID_KEYS = [
    "NANOBOT_GEMINI_OAUTH_CLIENT_ID",
    "GEMINI_CLI_OAUTH_CLIENT_ID",
    "OPENCLAW_GEMINI_OAUTH_CLIENT_ID",
]
CLIENT_SECRET_KEYS = [
    "NANOBOT_GEMINI_OAUTH_CLIENT_SECRET",
    "GEMINI_CLI_OAUTH_CLIENT_SECRET",
    "OPENCLAW_GEMINI_OAUTH_CLIENT_SECRET",
]
REDIRECT_URI = "http://localhost:8085/oauth2callback"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://www.googleapis.com/oauth2/v1/userinfo?alt=json"
CODE_ASSIST_ENDPOINT = "https://cloudcode-pa.googleapis.com"

SCOPES = [
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]

TIER_FREE = "free-tier"
TIER_LEGACY = "legacy-tier"
TIER_STANDARD = "standard-tier"


class GeminiOAuthCredentials:
    """OAuth credentials for Gemini CLI."""

    def __init__(
        self,
        access: str,
        refresh: str,
        expires: int,
        email: str | None = None,
        project_id: str = "",
    ):
        self.access = access
        self.refresh = refresh
        self.expires = expires
        self.email = email
        self.project_id = project_id


def _resolve_env(keys: list[str]) -> str | None:
    """Resolve environment variable from list of candidates."""
    for key in keys:
        value = os.environ.get(key, "").strip()
        if value:
            return value
    return None


_cached_gemini_credentials: dict[str, str] | None = None


def _clear_credentials_cache() -> None:
    """Clear cached Gemini CLI credentials."""
    global _cached_gemini_credentials
    _cached_gemini_credentials = None


def _find_in_path(name: str) -> str | None:
    """Find executable in system PATH."""
    return shutil.which(name)


def _find_file(dir_path: str, name: str, depth: int = 10) -> str | None:
    """Recursively find a file in directory tree."""

    def _search(current: Path, current_depth: int) -> Path | None:
        if current_depth <= 0:
            return None
        try:
            for item in current.iterdir():
                if item.is_file() and item.name == name:
                    return item
                if item.is_dir() and not item.name.startswith("."):
                    result = _search(item, current_depth - 1)
                    if result:
                        return result
        except (OSError, PermissionError):
            pass
        return None

    return str(_search(Path(dir_path), depth)) if _search(Path(dir_path), depth) else None


def extract_gemini_cli_credentials() -> dict[str, str] | None:
    """Extract OAuth credentials from installed Gemini CLI.

    Searches for the oauth2.js file in the Gemini CLI installation
    and extracts the client ID and secret.
    """
    global _cached_gemini_credentials

    if _cached_gemini_credentials:
        return _cached_gemini_credentials

    try:
        gemini_path = _find_in_path("gemini")
        if not gemini_path:
            return None

        gemini_cli_dir = Path(gemini_path).parent.parent

        # Search paths for oauth2.js
        search_paths = [
            gemini_cli_dir
            / "node_modules"
            / "@google"
            / "gemini-cli-core"
            / "dist"
            / "src"
            / "code_assist"
            / "oauth2.js",
            gemini_cli_dir
            / "node_modules"
            / "@google"
            / "gemini-cli-core"
            / "dist"
            / "code_assist"
            / "oauth2.js",
        ]

        content = None
        for path in search_paths:
            if path.exists():
                content = path.read_text()
                break

        if not content:
            found = _find_file(str(gemini_cli_dir), "oauth2.js", 10)
            if found:
                content = Path(found).read_text()

        if not content:
            return None

        # Extract client ID and secret using regex
        import re

        id_match = re.search(r"(\d+-[a-z0-9]+\.apps\.googleusercontent\.com)", content)
        secret_match = re.search(r"(GOCSPX-[A-Za-z0-9_-]+)", content)

        if id_match and secret_match:
            _cached_gemini_credentials = {
                "clientId": id_match.group(1),
                "clientSecret": secret_match.group(1),
            }
            return _cached_gemini_credentials

    except Exception:
        # Gemini CLI not installed or extraction failed
        pass

    return None


def resolve_oauth_client_config() -> dict[str, Any]:
    """Resolve OAuth client configuration.

    Priority:
    1. Environment variables (user override)
    2. Extracted from Gemini CLI installation
    3. Error if neither available
    """
    # Check env vars first
    env_client_id = _resolve_env(CLIENT_ID_KEYS)
    env_client_secret = _resolve_env(CLIENT_SECRET_KEYS)

    if env_client_id:
        return {"clientId": env_client_id, "clientSecret": env_client_secret}

    # Try extraction from Gemini CLI
    extracted = extract_gemini_cli_credentials()
    if extracted:
        return extracted

    # No credentials available
    raise RuntimeError(
        "Gemini CLI not found. Install it first:\n"
        "  brew install gemini-cli\n"
        "  or: npm install -g @google/gemini-cli\n"
        "Or set GEMINI_CLI_OAUTH_CLIENT_ID environment variable."
    )


def generate_pkce() -> dict[str, str]:
    """Generate PKCE verifier and challenge.

    Returns:
        dict with 'verifier' and 'challenge' keys
    """
    verifier = secrets.token_urlsafe(32)
    # Create SHA-256 hash and base64url encode
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()

    return {"verifier": verifier, "challenge": challenge}


def build_auth_url(challenge: str, verifier: str) -> str:
    """Build OAuth authorization URL."""
    config = resolve_oauth_client_config()
    params = {
        "client_id": config["clientId"],
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": " ".join(SCOPES),
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": verifier,
        "access_type": "offline",
        "prompt": "consent",
    }
    return f"{AUTH_URL}?{urllib.parse.urlencode(params)}"


class CallbackHandler(BaseHTTPRequestHandler):
    """HTTP request handler for OAuth callback."""

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress default logging."""

    def do_GET(self) -> None:
        """Handle GET request for OAuth callback."""
        parsed = urllib.parse.urlparse(self.path or "/")

        if parsed.path != "/oauth2callback":
            self.send_error(404, "Not Found")
            return

        params = urllib.parse.parse_qs(parsed.query)

        error = params.get("error", [None])[0]
        code = params.get("code", [None])[0]
        state = params.get("state", [None])[0]

        if error:
            self.send_response(400)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(f"Authentication failed: {error}".encode())
            CallbackHandler.error = error or "OAuth error"
            return

        if not code or not state:
            self.send_response(400)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Missing code or state")
            CallbackHandler.error = "Missing OAuth code or state"
            return

        CallbackHandler.code = code
        CallbackHandler.state = state

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        html = """<!doctype html>
<html><head><meta charset='utf-8'/></head>
<body><h2>Gemini CLI OAuth complete</h2>
<p>You can close this window and return to nanobot.</p></body></html>
"""
        self.wfile.write(html.encode())


CallbackHandler.code: str | None = None
CallbackHandler.state: str | None = None
CallbackHandler.error: str | None = None


def wait_for_local_callback(
    expected_state: str, timeout_ms: int = 300000
) -> dict[str, str]:
    """Wait for OAuth callback on localhost.

    Args:
        expected_state: Expected state parameter from auth URL
        timeout_ms: Timeout in milliseconds (default 5 minutes)

    Returns:
        dict with 'code' and 'state' keys

    Raises:
        RuntimeError: If callback fails or times out
    """
    port = 8085

    # Find available port
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("localhost", 0))
        port = sock.getsockname()[1]
    finally:
        sock.close()

    server = HTTPServer(("localhost", port), CallbackHandler)

    # Reset class variables
    CallbackHandler.code = None
    CallbackHandler.state = None
    CallbackHandler.error = None

    import threading

    def run_server() -> None:
        try:
            server.handle_request()
        except Exception:
            pass

    thread = threading.Thread(target=run_server, daemon=True)
    thread.start()

    _get_console().print(
        f"[dim]Waiting for OAuth callback on http://localhost:{port}/oauth2callback...[/dim]"
    )

    start_time = time.time()
    timeout_sec = timeout_ms / 1000

    while time.time() - start_time < timeout_sec:
        if CallbackHandler.code:
            server.shutdown()
            if CallbackHandler.state != expected_state:
                raise RuntimeError("OAuth state mismatch")
            return {"code": CallbackHandler.code, "state": CallbackHandler.state}
        if CallbackHandler.error:
            server.shutdown()
            raise RuntimeError(f"OAuth error: {CallbackHandler.error}")
        time.sleep(0.1)

    server.shutdown()
    raise RuntimeError("OAuth callback timeout")


def parse_callback_input(input_str: str, expected_state: str) -> dict[str, Any]:
    """Parse callback URL or code from user input.

    Args:
        input_str: User input (URL or code)
        expected_state: Expected state parameter

    Returns:
        dict with 'code' and 'state' keys, or {'error': str}
    """
    trimmed = input_str.strip()
    if not trimmed:
        return {"error": "No input provided"}

    try:
        parsed = urllib.parse.urlparse(trimmed)
        params = urllib.parse.parse_qs(parsed.query)
        code = params.get("code", [None])[0]
        state = params.get("state", [None])[0] or expected_state

        if not code:
            return {"error": "Missing 'code' parameter in URL"}
        if not state:
            return {"error": "Missing 'state' parameter. Paste the full URL."}

        return {"code": code, "state": state}

    except Exception:
        if not expected_state:
            return {"error": "Paste the full redirect URL, not just the code."}
        return {"code": trimmed, "state": expected_state}


def exchange_code_for_tokens(code: str, verifier: str) -> GeminiOAuthCredentials:
    """Exchange authorization code for access and refresh tokens.

    Args:
        code: Authorization code from OAuth callback
        verifier: PKCE verifier

    Returns:
        GeminiOAuthCredentials instance

    Raises:
        RuntimeError: If token exchange fails
    """
    config = resolve_oauth_client_config()

    data = {
        "client_id": config["clientId"],
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT_URI,
        "code_verifier": verifier,
    }

    if config.get("clientSecret"):
        data["client_secret"] = config["clientSecret"]

    try:
        req = Request(
            TOKEN_URL,
            data=urllib.parse.urlencode(data).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urlopen(req, timeout=30) as response:
            response_data = json.loads(response.read().decode())

        if not response_data.get("refresh_token"):
            raise RuntimeError("No refresh token received. Please try again.")

        email = get_user_email(response_data["access_token"])
        project_id = discover_project(response_data["access_token"])
        expires_at = int(time.time() * 1000) + response_data["expires_in"] * 1000 - 300000

        return GeminiOAuthCredentials(
            access=response_data["access_token"],
            refresh=response_data["refresh_token"],
            expires=expires_at,
            email=email,
            project_id=project_id,
        )

    except Exception as e:
        raise RuntimeError(f"Token exchange failed: {e}")


def get_user_email(access_token: str) -> str | None:
    """Get user email from access token.

    Args:
        access_token: OAuth access token

    Returns:
        User email if available, None otherwise
    """
    try:
        req = Request(
            USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        with urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())
            return data.get("email")
    except Exception:
        return None


def is_vpcsc_affected(payload: Any) -> bool:
    """Check if error is due to VPC-SC policy violation.

    Args:
        payload: Error payload from API response

    Returns:
        True if VPC-SC violation detected
    """
    if not payload or not isinstance(payload, dict):
        return False

    error = payload.get("error")
    if not error or not isinstance(error, dict):
        return False

    details = error.get("details", [])
    if not isinstance(details, list):
        return False

    return any(
        isinstance(item, dict) and item.get("reason") == "SECURITY_POLICY_VIOLATED"
        for item in details
    )


def get_default_tier(
    allowed_tiers: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Get default tier from allowed tiers list.

    Args:
        allowed_tiers: List of tier dictionaries

    Returns:
        Dictionary with 'id' key
    """
    if not allowed_tiers:
        return {"id": TIER_LEGACY}

    for tier in allowed_tiers:
        if tier.get("isDefault"):
            return tier

    return {"id": TIER_LEGACY}


def poll_operation(
    operation_name: str, headers: dict[str, str]
) -> dict[str, Any]:
    """Poll long-running operation until completion.

    Args:
        operation_name: Operation name to poll
        headers: HTTP headers for request

    Returns:
        Operation result dict

    Raises:
        RuntimeError: If polling times out
    """
    for _attempt in range(24):
        time.sleep(5)
        try:
            req = Request(
                f"{CODE_ASSIST_ENDPOINT}/v1internal/{operation_name}",
                headers=headers,
            )
            with urlopen(req, timeout=30) as response:
                data = json.loads(response.read().decode())
                if data.get("done"):
                    return data
        except Exception:
            continue

    raise RuntimeError("Operation polling timeout")


def discover_project(access_token: str) -> str:
    """Discover or provision Google Cloud project for Gemini CLI.

    Args:
        access_token: OAuth access token

    Returns:
        Google Cloud project ID

    Raises:
        RuntimeError: If project discovery fails
    """
    env_project = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get(
        "GOOGLE_CLOUD_PROJECT_ID"
    )

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "User-Agent": "google-api-nodejs-client/9.15.1",
        "X-Goog-Api-Client": "gl-node/nanobot",
    }

    load_body = {
        "cloudaicompanionProject": env_project,
        "metadata": {
            "ideType": "IDE_UNSPECIFIED",
            "platform": "PLATFORM_UNSPECIFIED",
            "pluginType": "GEMINI",
            "duetProject": env_project,
        },
    }

    data: dict[str, Any] = {}

    try:
        req = Request(
            f"{CODE_ASSIST_ENDPOINT}/v1internal:loadCodeAssist",
            data=json.dumps(load_body).encode(),
            headers=headers,
            method="POST",
        )
        with urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode())

    except Exception as e:
        # Try to parse error response
        error_payload = None
        try:
            error_response = json.loads(e.read().decode() if hasattr(e, "read") else str(e))
            error_payload = error_response
        except Exception:
            pass

        if is_vpcsc_affected(error_payload):
            data = {"currentTier": {"id": TIER_STANDARD}}
        else:
            raise RuntimeError(f"loadCodeAssist failed: {e}")

    # Check if project already exists
    current_tier = data.get("currentTier", {})
    if current_tier:
        project = data.get("cloudaicompanionProject")
        if isinstance(project, str) and project:
            return project
        if isinstance(project, dict) and project.get("id"):
            return project["id"]
        if env_project:
            return env_project
        raise RuntimeError(
            "This account requires GOOGLE_CLOUD_PROJECT or GOOGLE_CLOUD_PROJECT_ID to be set."
        )

    # Need to onboard user - select tier and provision
    allowed_tiers = data.get("allowedTiers", [])
    tier = get_default_tier(allowed_tiers)
    tier_id = tier.get("id") or TIER_FREE

    if tier_id != TIER_FREE and not env_project:
        raise RuntimeError(
            "This account requires GOOGLE_CLOUD_PROJECT or GOOGLE_CLOUD_PROJECT_ID to be set."
        )

    onboard_body: dict[str, Any] = {
        "tierId": tier_id,
        "metadata": {
            "ideType": "IDE_UNSPECIFIED",
            "platform": "PLATFORM_UNSPECIFIED",
            "pluginType": "GEMINI",
        },
    }

    if tier_id != TIER_FREE and env_project:
        onboard_body["cloudaicompanionProject"] = env_project
        onboard_body["metadata"]["duetProject"] = env_project

    try:
        req = Request(
            f"{CODE_ASSIST_ENDPOINT}/v1internal:onboardUser",
            data=json.dumps(onboard_body).encode(),
            headers=headers,
            method="POST",
        )
        with urlopen(req, timeout=30) as response:
            lro = json.loads(response.read().decode())

        if not lro.get("done") and lro.get("name"):
            lro = poll_operation(lro["name"], headers)

        project_id = lro.get("response", {}).get("cloudaicompanionProject", {}).get("id")
        if project_id:
            return project_id
        if env_project:
            return env_project

        raise RuntimeError(
            "Could not discover or provision a Google Cloud project. "
            "Set GOOGLE_CLOUD_PROJECT or GOOGLE_CLOUD_PROJECT_ID."
        )

    except Exception as e:
        raise RuntimeError(f"Project discovery failed: {e}")
