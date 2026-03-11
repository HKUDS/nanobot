"""
Graph Email Channel

Microsoft Graph API based email channel for nanobot.

Features:
- OAuth2 authentication with 90-day token cache
- Email polling with configurable interval
- Automatic deduplication of processed emails
- Agent tools for sending/moving/mark emails

Usage:
    1. First-time login: cd /root/.nanobot/workspace/skills/graph-email && python login.py login
    2. Start nanobot: nanobot start

Note:
    Login is handled by standalone login.py script (requires user interaction).
    This channel only loads cached tokens and auto-refreshes them.

Configuration (~/.nanobot/config.json):
{
  "channels": {
    "graph_email": {
      "enabled": true,
      "accounts": [
        {
          "id": "default",
          "email": "your-email@outlook.com",
          "client_id": "your-client-id",
          "tenant_id": "consumers"
        }
      ],
      "poll_interval_seconds": 300
    }
  }
}
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional, Set

import httpx
from loguru import logger

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import GraphEmailConfig
from nanobot.agent.tools.base import Tool


# ============================================================================
# OAuth2 Authentication (Device Code Flow)
# ============================================================================

@dataclass
class TokenData:
    """OAuth2 token data."""
    access_token: str
    refresh_token: str
    access_expires_at: float  # Access token expiration (~1 hour)
    refresh_expires_at: float  # Refresh token expiration (90 days)
    token_type: str = "Bearer"
    
    @property
    def is_expired(self) -> bool:
        """Check if access token is expired (with 5-minute buffer)."""
        return time.time() >= (self.access_expires_at - 300)
    
    @property
    def is_refresh_expired(self) -> bool:
        """Check if refresh token is expired."""
        return time.time() >= self.refresh_expires_at
    
    @property
    def access_expires_in(self) -> int:
        """Seconds until access token expiration."""
        return max(0, int(self.access_expires_at - time.time()))


class GraphAuthProvider:
    """
    OAuth2 authentication provider for Microsoft Graph.
    
    Responsibilities:
    - Load cached token from disk
    - Auto-refresh expired access tokens
    - Save refreshed tokens to disk
    
    Note: Initial login is handled by login.py script (user interaction required).
    Token is cached for 90 days.
    """
    
    GRAPH_ENDPOINT = "https://graph.microsoft.com"
    AUTHORITY = "https://login.microsoftonline.com"
    SCOPES = ["Mail.Read", "Mail.ReadWrite", "Mail.Send", "offline_access"]
    
    def __init__(self, client_id: str, tenant_id: str, email: str):
        self.client_id = client_id
        self.tenant_id = tenant_id
        self.email = email
        self._token: Optional[TokenData] = None
        self._token_file: Optional[Path] = None
    
    def _get_token_cache_path(self, account_id: str) -> Path:
        """Get token cache file path."""
        cache_dir = Path.home() / ".nanobot" / "workspace" / "skills" / "graph-email" / "data"
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir / "token_cache.bin"
    
    def _load_token(self, account_id: str) -> Optional[TokenData]:
        """Load token from cache."""
        self._token_file = self._get_token_cache_path(account_id)
        
        if not self._token_file.exists():
            return None
        
        try:
            data = json.loads(self._token_file.read_text())
            token = TokenData(
                access_token=data["access_token"],
                refresh_token=data["refresh_token"],
                access_expires_at=data.get("access_expires_at", data.get("expires_at", 0)),
                refresh_expires_at=data.get("refresh_expires_at", data.get("expires_at", 0)),
                token_type=data.get("token_type", "Bearer")
            )
            self._token = token
            return token
        except Exception as e:
            logger.warning(f"Failed to load token cache: {e}")
            return None
    
    def _save_token(self, token: TokenData) -> None:
        """Save token to cache."""
        if not self._token_file:
            return
        
        data = {
            "access_token": token.access_token,
            "refresh_token": token.refresh_token,
            "access_expires_at": token.access_expires_at,
            "refresh_expires_at": token.refresh_expires_at,
            "token_type": token.token_type,
            "email": self.email,
            "saved_at": datetime.now().isoformat()
        }
        self._token_file.write_text(json.dumps(data, indent=2))
        logger.info(f"Token saved to {self._token_file}")
    
    def is_authenticated(self) -> bool:
        """Check if currently authenticated."""
        return self._token is not None and not self._token.is_expired
    
    def get_access_token(self) -> Optional[str]:
        """
        Get valid access token, refreshing if needed.
        
        Returns:
            Access token string or None if not authenticated
        """
        if not self._token:
            return None
        
        if self._token.is_expired:
            logger.info("Token expired, attempting refresh...")
            if not self._refresh_token():
                return None
        
        return self._token.access_token
    
    def _refresh_token(self) -> bool:
        """Refresh access token using refresh token."""
        if not self._token or not self._token.refresh_token:
            return False
        
        try:
            token_url = f"{self.AUTHORITY}/{self.tenant_id}/oauth2/v2.0/token"
            
            response = httpx.post(
                token_url,
                data={
                    "client_id": self.client_id,
                    "refresh_token": self._token.refresh_token,
                    "grant_type": "refresh_token",
                    "scope": " ".join(self.SCOPES),
                },
                timeout=30
            )
            
            if response.status_code != 200:
                logger.error(f"Token refresh failed: {response.text}")
                return False
            
            token_data = response.json()
            self._token = TokenData(
                access_token=token_data["access_token"],
                refresh_token=token_data.get("refresh_token", self._token.refresh_token),
                access_expires_at=time.time() + token_data["expires_in"],
                refresh_expires_at=self._token.refresh_expires_at,  # Keep original refresh expiration
                token_type=token_data["token_type"]
            )
            
            self._save_token(self._token)
            logger.info("Token refreshed successfully")
            return True
            
        except Exception as e:
            logger.error(f"Token refresh error: {e}")
            return False


# ============================================================================
# Graph API Client
# ============================================================================

class GraphMailClient:
    """
    Microsoft Graph API client for email operations.
    
    Provides methods for:
    - Sending emails
    - Reading emails
    - Moving emails between folders
    - Marking emails as read
    """
    
    GRAPH_ENDPOINT = "https://graph.microsoft.com/v1.0"
    
    def __init__(self, auth: GraphAuthProvider):
        self.auth = auth
        self._client = httpx.Client(timeout=30)
    
    def _get_headers(self) -> dict[str, str]:
        """Get authenticated request headers."""
        token = self.auth.get_access_token()
        if not token:
            raise Exception("Not authenticated")
        
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
    
    def send_email(self, to: str, subject: str, content: str, is_html: bool = False) -> bool:
        """
        Send an email.
        
        Args:
            to: Recipient email address
            subject: Email subject
            content: Email body
            is_html: Whether content is HTML
            
        Returns:
            True if sent successfully
        """
        try:
            url = f"{self.GRAPH_ENDPOINT}/me/sendMail"
            
            payload = {
                "message": {
                    "subject": subject,
                    "body": {
                        "contentType": "HTML" if is_html else "Text",
                        "content": content
                    },
                    "toRecipients": [{"emailAddress": {"address": to}}]
                }
            }
            
            response = self._client.post(url, headers=self._get_headers(), json=payload)
            
            if response.status_code == 202:
                logger.info(f"Email sent to {to}: {subject}")
                return True
            else:
                logger.error(f"Failed to send email: {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Send email error: {e}")
            return False
    
    def get_messages(self, folder: str = "inbox", limit: int = 50, unread_only: bool = True) -> list[dict[str, Any]]:
        """
        Get messages from a folder.
        
        Args:
            folder: Folder name (inbox, junk, archive, etc.)
            limit: Maximum number of messages
            unread_only: Only return unread messages (default: True)
            
        Returns:
            List of message dictionaries
        """
        try:
            url = f"{self.GRAPH_ENDPOINT}/me/mailFolders/{folder}/messages"
            params = {
                "$top": limit,
                "$select": "id,subject,from,receivedDateTime,bodyPreview,isRead",
                "$orderby": "receivedDateTime desc"
            }
            
            # Only fetch unread messages
            if unread_only:
                params["$filter"] = "isRead eq false"
            
            response = self._client.get(url, headers=self._get_headers(), params=params)
            
            if response.status_code == 200:
                data = response.json()
                messages = data.get("value", [])
                logger.debug(f"Got {len(messages)} messages from {folder} (unread_only={unread_only})")
                return messages
            else:
                logger.error(f"Failed to get messages: {response.text}")
                return []
                
        except Exception as e:
            logger.error(f"Get messages error: {e}")
            return []
    
    def move_message(self, message_id: str, folder: str) -> bool:
        """
        Move a message to a different folder.
        
        Args:
            message_id: Message ID
            folder: Destination folder
            
        Returns:
            True if moved successfully
        """
        try:
            url = f"{self.GRAPH_ENDPOINT}/me/messages/{message_id}/move"
            
            response = self._client.post(
                url,
                headers=self._get_headers(),
                json={"destinationId": folder}
            )
            
            if response.status_code == 201:
                logger.info(f"Message {message_id} moved to {folder}")
                return True
            else:
                logger.error(f"Failed to move message: {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Move message error: {e}")
            return False
    
    def mark_as_read(self, message_id: str) -> bool:
        """
        Mark a message as read.
        
        Args:
            message_id: Message ID
            
        Returns:
            True if marked successfully
        """
        try:
            url = f"{self.GRAPH_ENDPOINT}/me/messages/{message_id}"
            
            response = self._client.patch(
                url,
                headers=self._get_headers(),
                json={"isRead": True}
            )
            
            if response.status_code == 200:
                logger.debug(f"Message {message_id} marked as read")
                return True
            else:
                logger.error(f"Failed to mark as read: {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Mark as read error: {e}")
            return False
    
    def get_message_detail(self, message_id: str) -> Optional[dict[str, Any]]:
        """
        Get full message details.
        
        Args:
            message_id: Message ID
            
        Returns:
            Message details or None
        """
        try:
            url = f"{self.GRAPH_ENDPOINT}/me/messages/{message_id}"
            params = {"$select": "id,subject,from,toRecipients,receivedDateTime,body,isRead"}
            
            response = self._client.get(url, headers=self._get_headers(), params=params)
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Failed to get message detail: {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"Get message detail error: {e}")
            return None


# ============================================================================
# Email Listener (Polling & Deduplication)
# ============================================================================

@dataclass
class EmailMessage:
    """Normalized email message."""
    id: str
    subject: str
    from_email: str
    from_name: str
    to_emails: list[str]
    received_at: str
    body: str
    is_read: bool
    account_id: str = "default"


class FolderListener:
    """
    Poll email folders and forward new messages to Agent.
    
    Features:
    - Configurable polling interval
    - Persistent deduplication (JSON file)
    - Automatic forwarding to MessageBus
    - API rate limiting protection
    """
    
    def __init__(self, client: GraphMailClient, config: GraphEmailConfig, bus: MessageBus):
        self.client = client
        self.config = config
        self.bus = bus
        self._running = False
        self._processed_ids: Set[str] = set()
        self._poll_interval = config.poll_interval_seconds
        self._processed_file: Optional[Path] = None
        self._api_call_count = 0
        self._api_call_reset_time = time.time() + 3600  # Reset every hour
    
    def _get_processed_file_path(self, account_id: str) -> Path:
        """Get processed IDs file path."""
        cache_dir = Path.home() / ".nanobot" / "workspace" / "skills" / "graph-email" / "data"
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir / f"processed_ids_{account_id}.json"
    
    def _load_processed_ids(self, account_id: str) -> Set[str]:
        """Load processed IDs from JSON file."""
        self._processed_file = self._get_processed_file_path(account_id)
        
        if not self._processed_file.exists():
            return set()
        
        try:
            data = json.loads(self._processed_file.read_text())
            ids = set(data.get("ids", []))
            logger.info(f"Loaded {len(ids)} processed email IDs")
            return ids
        except Exception as e:
            logger.warning(f"Failed to load processed IDs: {e}")
            return set()
    
    def _save_processed_ids(self, max_age_days: int = 30) -> None:
        """
        Save processed IDs to JSON file.
        
        Args:
            max_age_days: Keep only IDs from last N days (default: 30)
        """
        if not self._processed_file:
            return
        
        # Clean up old IDs (keep only last N days)
        # Note: We can't determine email age from ID alone, so we keep all IDs
        # but limit the total count to prevent unbounded growth
        max_ids = 10000  # Reasonable limit
        if len(self._processed_ids) > max_ids:
            # Convert to list and keep only newest (we can't sort by date, so just truncate)
            ids_list = list(self._processed_ids)
            self._processed_ids = set(ids_list[-max_ids:])
            logger.info(f"Cleaned up old processed IDs, kept {len(self._processed_ids)} newest")
        
        data = {
            "ids": list(self._processed_ids),
            "last_updated": datetime.now().isoformat(),
            "count": len(self._processed_ids)
        }
        self._processed_file.write_text(json.dumps(data, indent=2))
    
    def _normalize_message(self, raw: dict[str, Any], account_id: str) -> EmailMessage:
        """Normalize raw Graph API message to EmailMessage."""
        from_data = raw.get("from", {}) or {}
        from_email = from_data.get("emailAddress", {}).get("address", "unknown")
        from_name = from_data.get("emailAddress", {}).get("name", "Unknown")
        
        to_recipients = raw.get("toRecipients", [])
        to_emails = [r.get("emailAddress", {}).get("address", "") for r in to_recipients]
        
        body = raw.get("body", {}) or {}
        body_content = body.get("content", raw.get("bodyPreview", ""))
        
        return EmailMessage(
            id=raw["id"],
            subject=raw.get("subject", "(no subject)"),
            from_email=from_email,
            from_name=from_name,
            to_emails=to_emails,
            received_at=raw.get("receivedDateTime", ""),
            body=body_content,
            is_read=raw.get("isRead", False),
            account_id=account_id
        )
    
    def _format_email_content(self, email: EmailMessage) -> str:
        """Format email for Agent consumption."""
        return f"""📧 New Email

From: {email.from_name} <{email.from_email}>
To: {', '.join(email.to_emails)}
Subject: {email.subject}
Received: {email.received_at}

---

{email.body[:2000]}  # Limit body length
"""
    
    async def check_once(self) -> int:
        """
        Check for new emails once.
        
        Returns:
            Number of new emails found
        """
        if not self.config.accounts:
            return 0
        
        # Check API rate limit
        if time.time() > self._api_call_reset_time:
            self._api_call_count = 0
            self._api_call_reset_time = time.time() + 3600
        
        # Warn if approaching rate limit (10,000 calls/hour)
        if self._api_call_count > 9000:
            logger.warning(f"Approaching API rate limit: {self._api_call_count}/10000 calls this hour")
        
        total_new = 0
        
        for account in self.config.accounts:
            if not account.enabled:
                continue
            
            # Load processed IDs for this account (ONCE per check)
            self._processed_ids = self._load_processed_ids(account.id)
            initial_count = len(self._processed_ids)
            
            # Get messages from configured folders
            for folder in self.config.folders:
                try:
                    self._api_call_count += 1
                    messages = self.client.get_messages(folder=folder, limit=self.config.max_messages_per_check)
                    
                    for raw in messages:
                        if raw["id"] in self._processed_ids:
                            continue  # Already processed, skip
                        
                        # New message!
                        email = self._normalize_message(raw, account.id)
                        self._processed_ids.add(email.id)
                        total_new += 1
                        
                        logger.info(f"New email from {email.from_email}: {email.subject}")
                        
                        # Forward to Agent via MessageBus
                        await self.bus.publish_inbound(InboundMessage(
                            channel="graph_email",
                            sender_id=email.from_email,
                            chat_id=f"email:{account.id}",
                            content=self._format_email_content(email),
                            metadata={
                                "email_id": email.id,
                                "from_email": email.from_email,
                                "from_name": email.from_name,
                                "subject": email.subject,
                                "received_at": email.received_at,
                                "account_id": account.id
                            }
                        ))
                    
                except Exception as e:
                    logger.error(f"Error checking folder {folder}: {e}")
            
            # Save processed IDs AFTER all folders (not after each folder)
            if len(self._processed_ids) > initial_count:
                self._save_processed_ids()
                logger.info(f"Saved {len(self._processed_ids) - initial_count} new email IDs for account {account.id}")
        
        if total_new > 0:
            logger.info(f"Check complete: {total_new} new emails found (API calls: {self._api_call_count})")
        
        return total_new
    
    async def start_polling(self) -> None:
        """Start continuous polling loop."""
        self._running = True
        logger.info(f"Starting email polling (interval: {self._poll_interval}s)")
        
        check_count = 0
        while self._running:
            try:
                new_count = await self.check_once()
                check_count += 1
                
                # Log periodic status
                if check_count % 10 == 0:
                    logger.info(f"Polling status: {check_count} checks, {len(self._processed_ids)} processed IDs")
                
            except Exception as e:
                logger.error(f"Poll error: {e}")
            
            await asyncio.sleep(self._poll_interval)
    
    def stop(self) -> None:
        """Stop polling."""
        self._running = False


# ============================================================================
# Agent Tools
# ============================================================================

class SendEmailTool(Tool):
    """Send an email via Graph API."""
    
    def __init__(self, client: GraphMailClient):
        self.client = client
    
    @property
    def name(self) -> str:
        return "send_email"
    
    @property
    def description(self) -> str:
        return "Send an email via Microsoft Graph API. Use this to reply to emails or send new messages."
    
    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient email address"},
                "subject": {"type": "string", "description": "Email subject"},
                "body": {"type": "string", "description": "Email body content"},
                "is_html": {"type": "boolean", "description": "Whether body is HTML (default: false)"}
            },
            "required": ["to", "subject", "body"]
        }
    
    async def execute(self, to: str, subject: str, body: str, is_html: bool = False, **kwargs) -> str:
        try:
            success = self.client.send_email(to=to, subject=subject, content=body, is_html=is_html)
            return f"✅ Email sent to {to}: {subject}" if success else f"❌ Failed to send email to {to}"
        except Exception as e:
            return f"Error sending email: {str(e)}"


class MoveEmailTool(Tool):
    """Move an email to a different folder."""
    
    def __init__(self, client: GraphMailClient):
        self.client = client
    
    @property
    def name(self) -> str:
        return "move_email"
    
    @property
    def description(self) -> str:
        return "Move an email to a different folder (e.g., 'inbox', 'junk', 'archive')."
    
    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "email_id": {"type": "string", "description": "Email ID to move"},
                "folder": {"type": "string", "description": "Destination folder"}
            },
            "required": ["email_id", "folder"]
        }
    
    async def execute(self, email_id: str, folder: str, **kwargs) -> str:
        try:
            success = self.client.move_message(message_id=email_id, folder=folder)
            return f"✅ Email moved to '{folder}'" if success else f"❌ Failed to move email"
        except Exception as e:
            return f"Error moving email: {str(e)}"


class MarkAsReadTool(Tool):
    """Mark an email as read."""
    
    def __init__(self, client: GraphMailClient):
        self.client = client
    
    @property
    def name(self) -> str:
        return "mark_as_read"
    
    @property
    def description(self) -> str:
        return "Mark an email as read. Use this after processing an email."
    
    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "email_id": {"type": "string", "description": "Email ID to mark as read"}
            },
            "required": ["email_id"]
        }
    
    async def execute(self, email_id: str, **kwargs) -> str:
        try:
            success = self.client.mark_as_read(message_id=email_id)
            return f"✅ Email marked as read" if success else f"❌ Failed to mark email as read"
        except Exception as e:
            return f"Error marking email as read: {str(e)}"


class SetPollIntervalTool(Tool):
    """Adjust the email polling interval."""
    
    def __init__(self, listener: FolderListener):
        self.listener = listener
    
    @property
    def name(self) -> str:
        return "set_email_poll_interval"
    
    @property
    def description(self) -> str:
        return "Adjust the email polling interval in seconds (30-3600). Updates both runtime and config file."
    
    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "interval_seconds": {"type": "integer", "description": "Polling interval in seconds"}
            },
            "required": ["interval_seconds"]
        }
    
    async def execute(self, interval_seconds: int, **kwargs) -> str:
        try:
            if interval_seconds < 30:
                return "Error: Interval must be at least 30 seconds"
            if interval_seconds > 3600:
                return "Error: Interval must be at most 3600 seconds"
            
            old = self.listener._poll_interval
            self.listener._poll_interval = interval_seconds
            
            # Also update config file for persistence
            from pathlib import Path
            import json
            config_file = Path.home() / ".nanobot" / "config.json"
            
            if config_file.exists():
                config = json.loads(config_file.read_text())
                if "channels" in config and "graph_email" in config["channels"]:
                    config["channels"]["graph_email"]["poll_interval_seconds"] = interval_seconds
                    config_file.write_text(json.dumps(config, indent=2, ensure_ascii=False))
                    logger.info(f"Config updated: poll_interval_seconds = {interval_seconds}")
            
            return f"✅ Poll interval changed from {old}s to {interval_seconds}s (saved to config)"
        except Exception as e:
            logger.error(f"Error adjusting poll interval: {e}")
            return f"Error adjusting poll interval: {str(e)}"


# ============================================================================
# Graph Email Channel
# ============================================================================

class GraphEmailChannel(BaseChannel):
    """
    Graph Email Channel for nanobot.
    
    Simplified architecture:
    - Channel handles I/O only (polling, sending, auth)
    - Agent handles all intelligence (analysis, decisions)
    """
    
    name = "graph_email"
    
    def __init__(self, config: GraphEmailConfig, bus: MessageBus):
        super().__init__(config, bus)
        self.config: GraphEmailConfig = config
        self.bus = bus
        self._listener: Optional[FolderListener] = None
        self._poll_task: Optional[asyncio.Task] = None
        self._tools: list[Tool] = []
    
    @property
    def listener(self) -> Optional[FolderListener]:
        """Get the folder listener."""
        return self._listener
    
    def is_authenticated(self) -> bool:
        """Check if currently authenticated."""
        if not self.config.accounts:
            return False
        
        # Check first enabled account
        for account in self.config.accounts:
            if account.enabled:
                auth = GraphAuthProvider(account.client_id, account.tenant_id, account.email)
                cache_file = Path.home() / ".nanobot" / "workspace" / "skills" / "graph-email" / "data" / "token_cache.bin"
                return cache_file.exists()
        
        return False
    
    def register_tools(self, registry) -> None:
        """Register email tools with Agent's ToolRegistry."""
        if not self._listener:
            logger.warning("Cannot register tools: listener not initialized")
            return
        
        # Create tools
        client = self._listener.client
        self._tools = [
            SendEmailTool(client),
            MoveEmailTool(client),
            MarkAsReadTool(client),
            SetPollIntervalTool(self._listener),
        ]
        
        # Register with registry
        for tool in self._tools:
            registry.register(tool)
        
        logger.info(f"Registered {len(self._tools)} Graph Email tools")
    
    async def start(self) -> None:
        """Start the email channel."""
        if not self.config.enabled:
            logger.info("Graph Email channel is disabled")
            return
        
        if not self.config.accounts:
            logger.error("No email accounts configured")
            return
        
        self._running = True
        
        # Get first enabled account
        account = None
        for acc in self.config.accounts:
            if acc.enabled:
                account = acc
                break
        
        if not account:
            account = self.config.accounts[0]
        
        logger.info(f"Starting Graph Email channel for {account.email}")
        
        # Initialize auth and client
        auth = GraphAuthProvider(account.client_id, account.tenant_id, account.email)
        
        # Load cached token
        if not auth._load_token(account.id):
            logger.error("No cached token found. Please run login first:")
            logger.error("  python -m nanobot.channels.graph_email.login login")
            return
        
        if not auth.is_authenticated():
            logger.error("Token expired. Please re-login:")
            logger.error("  python -m nanobot.channels.graph_email.login login")
            return
        
        # Create client and listener
        client = GraphMailClient(auth)
        self._listener = FolderListener(client, self.config, self.bus)
        
        # Start polling in background
        self._poll_task = asyncio.create_task(self._listener.start_polling())
        logger.info("Graph Email channel started")
    
    async def stop(self) -> None:
        """Stop the email channel."""
        self._running = False
        
        if self._listener:
            self._listener.stop()
        
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        
        logger.info("Graph Email channel stopped")
    
    async def send(self, msg: OutboundMessage) -> None:
        """Send a message (not used for email channel)."""
        # Email channel only receives, sending is done via tools
        pass
