import json
import os
import time
from datetime import datetime
from typing import Any, Dict, Optional
from pathlib import Path
import asyncio
from uuid import uuid4

import httpx

from loguru import logger

from nanobot.config.loader import get_credentials_dir
from nanobot.utils.helpers import ensure_dir

from nanobot.providers.openai_compat_provider import OpenAICompatProvider
from nanobot.providers.registry import ProviderSpec

# Constants
GITHUB_COPILOT_API_BASE = "https://api.githubcopilot.com"
GITHUB_CLIENT_ID = "Iv1.b507a08c87ecfe98"
GITHUB_DEVICE_CODE_URL = "https://github.com/login/device/code"
GITHUB_ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_API_KEY_URL = "https://api.github.com/copilot_internal/v2/token"

def get_copilot_default_headers(api_key: str | None = None) -> dict:
    """
    Get default headers for GitHub Copilot Responses API.

    Based on copilot-api's header configuration.
    """
    COPILOT_VERSION = "0.26.7"
    EDITOR_PLUGIN_VERSION = f"copilot-chat/{COPILOT_VERSION}"
    USER_AGENT = f"GitHubCopilotChat/{COPILOT_VERSION}"
    API_VERSION = "2025-04-01"
    
    output =  {
        "content-type": "application/json",
        "copilot-integration-id": "vscode-chat",
        "editor-version": "vscode/1.95.0",  # Fixed version for stability
        "editor-plugin-version": EDITOR_PLUGIN_VERSION,
        "user-agent": USER_AGENT,
        "openai-intent": "conversation-panel",
        "x-github-api-version": API_VERSION,
        "x-request-id": str(uuid4()),
        "x-vscode-user-agent-library-version": "electron-fetch",
    }
    if api_key:
        output["authorization"] = f"Bearer {api_key}"
    return output


class GithubCopilotProvider(OpenAICompatProvider):
    """
    Provider for GitHub Copilot, using OpenAI-compatible API calls where possible.

    Handles authentication and API key management specific to GitHub Copilot.
    """

    def __init__(
        self,
        default_model: str = "gpt-4o",
        extra_headers: dict[str, str] | None = None,
        spec: ProviderSpec | None = None,
    ):

        api_base = GITHUB_COPILOT_API_BASE
        self._authenticator = GithubCopilotAuthenticator(authorize_login=False)
        api_key = self._authenticator.get_api_key_async
        extra_headers = {**get_copilot_default_headers(), **(extra_headers or {})}

        super().__init__(
            api_key=api_key,
            api_base=api_base,
            default_model=default_model,
            extra_headers=extra_headers,
            spec=spec,
        )


class GithubCopilotAuthenticator:
    """Handles authentication for GitHub Copilot, including device code flow and API key management. Strongly inspired by LiteLLM. """

    def __init__(self, authorize_login: bool = True) -> None:
        """Initialize the GitHub Copilot authenticator with configurable token paths."""

        self.authorize_login = authorize_login
        # Token storage paths
        self.token_dir = ensure_dir(Path(os.getenv(
            "GITHUB_COPILOT_TOKEN_DIR",
            str(get_credentials_dir() / "github_copilot"),
        )).expanduser())

        self.access_token_file = self.token_dir / os.getenv(
            "GITHUB_COPILOT_ACCESS_TOKEN_FILE", "access-token"
        )
        self.api_key_file = self.token_dir / os.getenv("GITHUB_COPILOT_API_KEY_FILE", "api-key.json")
        
        self.http_client = httpx.Client(
            timeout=httpx.Timeout(600.0, connect=5.0),
            follow_redirects=True,
        )

    def close(self) -> None:
        """
        Close the underlying HTTP client to release network resources.
        """
        http_client = getattr(self, "http_client", None)
        if http_client is not None:
            http_client.close()

    def __del__(self) -> None:
        """
        Ensure the HTTP client is closed when the authenticator is garbage-collected.
        """
        try:
            self.close()
        except Exception:
            # Suppress all exceptions during garbage collection.
            pass
    def get_access_token(self) -> str:
        """
        Login to Copilot with retry 3 times.

        Returns:
            str: The GitHub access token.

        Raises:
            GetAccessTokenError: If unable to obtain an access token after retries.
        """
        try:
            with open(self.access_token_file, "r") as f:
                access_token = f.read().strip()
                if access_token:
                    return access_token
        except IOError:
            logger.warning(
                "No existing access token found or error reading file"
            )
        
        if not self.authorize_login:
            raise GetAccessTokenError(
                message="GithubCopilotProvider: No access token available. Try logging in by running `nanobot provider login github-copilot` ",
                status_code=401,
            )

        for attempt in range(3):
            logger.debug(f"Access token acquisition attempt {attempt + 1}/3")
            try:
                access_token = self._login()
                try:
                    with open(self.access_token_file, "w") as f:
                        f.write(access_token)
                except IOError:
                    logger.error("Error saving access token to file")
                return access_token
            except (GetDeviceCodeError, GetAccessTokenError, RefreshAPIKeyError) as e:
                logger.warning(f"Failed attempt {attempt + 1}: {str(e)}")
                continue

        raise GetAccessTokenError(
            message="GithubCopilotProvider: Failed to get access token after 3 attempts",
            status_code=401,
        )

    async def get_api_key_async(self) -> str:
        """
        Async wrapper for get_api_key to allow async calls.
        Returns:
            str: The GitHub Copilot API key.
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.get_api_key)

    def get_api_key(self) -> str:
        """
        Get the API key, refreshing if necessary.

        Returns:
            str: The GitHub Copilot API key.

        Raises:
            GetAPIKeyError: If unable to obtain an API key.
        """
        try:
            with open(self.api_key_file, "r") as f:
                api_key_info = json.load(f)
                if api_key_info.get("expires_at", 0) > datetime.now().timestamp():
                    return api_key_info.get("token")
                else:
                    logger.warning("API key expired, refreshing")
                    raise APIKeyExpiredError(
                        message="GithubCopilotProvider: API key expired",
                        status_code=401,
                    )
        except IOError:
            logger.warning("No API key file found or error opening file")
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Error reading API key from file: {str(e)}")
        except APIKeyExpiredError:
            pass  # Already logged in the try block

        try:
            api_key_info = self._refresh_api_key()
            with open(self.api_key_file, "w") as f:
                json.dump(api_key_info, f)
            token = api_key_info.get("token")
            if token:
                return token
            else:
                raise GetAPIKeyError(
                    message="GithubCopilotProvider: API key response missing token",
                    status_code=401,
                )
        except IOError as e:
            logger.error(f"Error saving API key to file: {str(e)}")
            raise GetAPIKeyError(
                message=f"Failed to save API key: {str(e)}",
                status_code=500,
            )
        except RefreshAPIKeyError as e:
            raise GetAPIKeyError(
                message=f"Failed to refresh API key: {str(e)}",
                status_code=401,
            )

    def get_api_base(self) -> Optional[str]:
        """
        Get the API endpoint from the api-key.json file.

        Returns:
            Optional[str]: The GitHub Copilot API endpoint, or None if not found.
        """
        try:
            with open(self.api_key_file, "r") as f:
                api_key_info = json.load(f)
                endpoints = api_key_info.get("endpoints", {})
                api_endpoint = endpoints.get("api")
                return api_endpoint
        except (IOError, json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Error reading API endpoint from file: {str(e)}")
            return None

    def _refresh_api_key(self) -> Dict[str, Any]:
        """
        Refresh the API key using the access token.

        Returns:
            Dict[str, Any]: The API key information including token and expiration.

        Raises:
            RefreshAPIKeyError: If unable to refresh the API key.
        """
        access_token = self.get_access_token()
        headers = self._get_github_headers(access_token)

        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = self.http_client.get(GITHUB_API_KEY_URL, headers=headers)
                response.raise_for_status()

                response_json = response.json()

                if "token" in response_json:
                    return response_json
                else:
                    logger.warning(
                        f"API key response missing token: {response_json}"
                    )
            except httpx.HTTPStatusError as e:
                logger.error(
                    f"HTTP error refreshing API key (attempt {attempt+1}/{max_retries}): {str(e)}"
                )
            except Exception as e:
                logger.error(f"Unexpected error refreshing API key: {str(e)}")

        raise RefreshAPIKeyError(
            message="GithubCopilotProvider: Failed to refresh API key after maximum retries",
            status_code=401,
        )


    def _get_github_headers(self, access_token: Optional[str] = None) -> Dict[str, str]:
        """
        Generate standard GitHub headers for API requests.

        Args:
            access_token: Optional access token to include in the headers.

        Returns:
            Dict[str, str]: Headers for GitHub API requests.
        """
        headers = {
            "accept": "application/json",
            "editor-version": "vscode/1.85.1",
            "editor-plugin-version": "copilot/1.155.0",
            "user-agent": "GithubCopilot/1.155.0",
            "accept-encoding": "gzip,deflate,br",
        }

        if access_token:
            headers["authorization"] = f"token {access_token}"

        if "content-type" not in headers:
            headers["content-type"] = "application/json"

        return headers

    def _get_device_code(self) -> Dict[str, str]:
        """
        Get a device code for GitHub authentication.

        Returns:
            Dict[str, str]: Device code information.

        Raises:
            GetDeviceCodeError: If unable to get a device code.
        """
        try:
            resp = self.http_client.post(
                GITHUB_DEVICE_CODE_URL,
                headers=self._get_github_headers(),
                json={"client_id": GITHUB_CLIENT_ID, "scope": "read:user"},
            )
            resp.raise_for_status()
            resp_json = resp.json()

            required_fields = ["device_code", "user_code", "verification_uri"]
            if not all(field in resp_json for field in required_fields):
                logger.error(f"Response missing required fields: {resp_json}")
                raise GetDeviceCodeError(
                    message="GithubCopilotProvider: Response missing required fields",
                    status_code=400,
                )

            return resp_json
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error getting device code: {str(e)}")
            raise GetDeviceCodeError(
                message=f"Failed to get device code: {str(e)}",
                status_code=400,
            )
        except json.JSONDecodeError as e:
            logger.error(f"Error decoding JSON response: {str(e)}")
            raise GetDeviceCodeError(
                message=f"Failed to decode device code response: {str(e)}",
                status_code=400,
            )
        except Exception as e:
            logger.error(f"Unexpected error getting device code: {str(e)}")
            raise GetDeviceCodeError(
                message=f"Failed to get device code: {str(e)}",
                status_code=400,
            )

    def _poll_for_access_token(self, device_code: str) -> str:
        """
        Poll for an access token after user authentication.

        Args:
            device_code: The device code to use for polling.

        Returns:
            str: The access token.

        Raises:
            GetAccessTokenError: If unable to get an access token.
        """
        max_attempts = 12  # 1 minute (12 * 5 seconds)

        for attempt in range(max_attempts):
            try:
                resp = self.http_client.post(
                    GITHUB_ACCESS_TOKEN_URL,
                    headers=self._get_github_headers(),
                    json={
                        "client_id": GITHUB_CLIENT_ID,
                        "device_code": device_code,
                        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    },
                )
                resp.raise_for_status()
                resp_json = resp.json()

                if "access_token" in resp_json:
                    logger.info("Authentication successful!")
                    return resp_json["access_token"]
                elif (
                    "error" in resp_json
                    and resp_json.get("error") == "authorization_pending"
                ):
                    # logger.debug(
                    #     f"Authorization pending (attempt {attempt+1}/{max_attempts})"
                    # )
                    pass 
                else:
                    logger.warning(f"Unexpected response: {resp_json}")
            except httpx.HTTPStatusError as e:
                logger.error(f"HTTP error polling for access token: {str(e)}")
                raise GetAccessTokenError(
                    message=f"Failed to get access token: {str(e)}",
                    status_code=400,
                )
            except json.JSONDecodeError as e:
                logger.error(f"Error decoding JSON response: {str(e)}")
                raise GetAccessTokenError(
                    message=f"Failed to decode access token response: {str(e)}",
                    status_code=400,
                )
            except Exception as e:
                logger.error(
                    f"Unexpected error polling for access token: {str(e)}"
                )
                raise GetAccessTokenError(
                    message=f"Failed to get access token: {str(e)}",
                    status_code=400,
                )

            time.sleep(5)

        raise GetAccessTokenError(
            message="GithubCopilotProvider: Timed out waiting for user to authorize the device",
            status_code=400,
        )

    def _login(self) -> str:
        """
        Login to GitHub Copilot using device code flow.

        Returns:
            str: The GitHub access token.

        Raises:
            GetDeviceCodeError: If unable to get a device code.
            GetAccessTokenError: If unable to get an access token.
        """
        device_code_info = self._get_device_code()

        device_code = device_code_info["device_code"]
        user_code = device_code_info["user_code"]
        verification_uri = device_code_info["verification_uri"]

        print(f"Please visit {verification_uri} and enter code {user_code} to authenticate.",flush=True,)

        return self._poll_for_access_token(device_code)


class GithubCopilotError(Exception):
    def __init__(
        self,
        status_code,
        message,
    ):
        self.status_code = status_code
        self.message: str = message
        super().__init__(
            self.message
        )


class GetDeviceCodeError(GithubCopilotError):
    pass


class GetAccessTokenError(GithubCopilotError):
    pass


class APIKeyExpiredError(GithubCopilotError):
    pass


class RefreshAPIKeyError(GithubCopilotError):
    pass


class GetAPIKeyError(GithubCopilotError):
    pass