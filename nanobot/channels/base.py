"""Base channel interface for chat platforms."""

from abc import ABC, abstractmethod
from typing import Any

from loguru import logger

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.utils.errors import (
    ChannelError,
    ChannelConnectionError,
    ChannelAuthError,
    ChannelSendError,
    ChannelReceiveError,
    ErrorInfo,
    RetryPolicy,
    CircuitBreaker,
    log_error,
    format_error_for_user,
)


class BaseChannel(ABC):
    """
    Abstract base class for chat channel implementations.
    
    Each channel (Telegram, Discord, etc.) should implement this interface
    to integrate with the nanobot message bus.
    
    Error Handling:
    - Channels should raise ChannelError subclasses for known error conditions
    - Connection errors should use ChannelConnectionError (triggers retry)
    - Auth errors should use ChannelAuthError (no retry)
    - Send/receive errors should use ChannelSendError/ChannelReceiveError
    - Use _safe_send() wrapper for automatic error handling
    """
    
    name: str = "base"
    
    # Default retry policy for channel operations
    DEFAULT_RETRY_POLICY = RetryPolicy(
        max_retries=3,
        base_delay=2.0,
        max_delay=30.0,
        retryable_exceptions=(
            ChannelConnectionError,
            ChannelSendError,
            ChannelReceiveError,
            ConnectionError,
            TimeoutError,
        ),
    )
    
    def __init__(self, config: Any, bus: MessageBus):
        """
        Initialize the channel.
        
        Args:
            config: Channel-specific configuration.
            bus: The message bus for communication.
        """
        self.config = config
        self.bus = bus
        self._running = False
        self._retry_policy = self.DEFAULT_RETRY_POLICY
        self._circuit_breaker = CircuitBreaker(
            name=f"channel_{self.name}",
            failure_threshold=5,
            success_threshold=2,
            timeout=30.0,
        )
    
    @abstractmethod
    async def start(self) -> None:
        """
        Start the channel and begin listening for messages.
        
        This should be a long-running async task that:
        1. Connects to the chat platform
        2. Listens for incoming messages
        3. Forwards messages to the bus via _handle_message()
        
        Raises:
            ChannelConnectionError: If connection fails.
            ChannelAuthError: If authentication fails.
        """
        pass
    
    @abstractmethod
    async def stop(self) -> None:
        """Stop the channel and clean up resources."""
        pass
    
    @abstractmethod
    async def send(self, msg: OutboundMessage) -> None:
        """
        Send a message through this channel.
        
        Args:
            msg: The message to send.
        
        Raises:
            ChannelSendError: If sending fails.
            ChannelConnectionError: If connection is lost.
        """
        pass
    
    def is_allowed(self, sender_id: str) -> bool:
        """
        Check if a sender is allowed to use this bot.
        
        Args:
            sender_id: The sender's identifier.
        
        Returns:
            True if allowed, False otherwise.
        """
        allow_list = getattr(self.config, "allow_from", [])
        
        # If no allow list, allow everyone
        if not allow_list:
            return True
        
        sender_str = str(sender_id)
        if sender_str in allow_list:
            return True
        if "|" in sender_str:
            for part in sender_str.split("|"):
                if part and part in allow_list:
                    return True
        return False
    
    async def _handle_message(
        self,
        sender_id: str,
        chat_id: str,
        content: str,
        media: list[str] | None = None,
        metadata: dict[str, Any] | None = None
    ) -> None:
        """
        Handle an incoming message from the chat platform.
        
        This method checks permissions and forwards to the bus.
        
        Args:
            sender_id: The sender's identifier.
            chat_id: The chat/channel identifier.
            content: Message text content.
            media: Optional list of media URLs.
            metadata: Optional channel-specific metadata.
        """
        if not self.is_allowed(sender_id):
            logger.warning(
                f"Access denied for sender {sender_id} on channel {self.name}. "
                f"Add them to allowFrom list in config to grant access."
            )
            return
        
        msg = InboundMessage(
            channel=self.name,
            sender_id=str(sender_id),
            chat_id=str(chat_id),
            content=content,
            media=media or [],
            metadata=metadata or {}
        )
        
        try:
            await self.bus.publish_inbound(msg)
        except Exception as e:
            log_error(e, f"Failed to publish inbound message", extra_context={
                "channel": self.name,
                "sender_id": sender_id,
                "chat_id": chat_id,
            })
    
    @property
    def is_running(self) -> bool:
        """Check if the channel is running."""
        return self._running
    
    async def _safe_send(self, msg: OutboundMessage) -> bool:
        """
        Send a message with automatic error handling and retry logic.
        
        This method wraps the send() method with:
        - Circuit breaker protection
        - Automatic retry for transient errors
        - Structured error logging
        
        Args:
            msg: The message to send.
        
        Returns:
            True if sent successfully, False otherwise.
        """
        import asyncio
        
        try:
            # Check circuit breaker
            if self._circuit_breaker.is_open:
                logger.warning(
                    f"Circuit breaker open for {self.name}, skipping send to {msg.chat_id}"
                )
                return False
            
            # Attempt send with retry
            last_error: Exception | None = None
            for attempt in range(1, self._retry_policy.max_retries + 1):
                try:
                    await self.send(msg)
                    self._circuit_breaker.record_success()
                    return True
                except Exception as e:
                    last_error = e
                    
                    if not self._retry_policy.should_retry(e, attempt):
                        self._circuit_breaker.record_failure()
                        raise
                    
                    delay = self._retry_policy.get_delay(attempt, e)
                    logger.warning(
                        f"Send retry {attempt}/{self._retry_policy.max_retries} "
                        f"for {self.name}:{msg.chat_id} after {delay:.2f}s: {e}"
                    )
                    await asyncio.sleep(delay)
            
            # Exhausted retries
            if last_error:
                self._circuit_breaker.record_failure()
                raise last_error
            return False
            
        except ChannelAuthError as e:
            # Auth errors are permanent, log and don't retry
            log_error(e, f"Auth error sending to {self.name}", extra_context={
                "chat_id": msg.chat_id,
            })
            return False
        except ChannelError as e:
            # Other channel errors
            log_error(e, f"Failed to send to {self.name}", extra_context={
                "chat_id": msg.chat_id,
            })
            return False
        except Exception as e:
            # Unexpected errors
            log_error(e, f"Unexpected error sending to {self.name}", extra_context={
                "chat_id": msg.chat_id,
            })
            return False
    
    def _classify_send_error(self, error: Exception) -> ChannelError:
        """
        Classify a send error into appropriate ChannelError subclass.
        
        Override this in subclasses to add channel-specific error classification.
        
        Args:
            error: The original exception.
        
        Returns:
            Appropriate ChannelError subclass.
        """
        error_str = str(error).lower()
        
        # Auth errors
        if any(s in error_str for s in ["unauthorized", "forbidden", "401", "403", "auth"]):
            return ChannelAuthError(
                f"Authentication failed for {self.name}",
                context={"original_error": str(error)}
            )
        
        # Connection errors
        if any(s in error_str for s in ["connection", "timeout", "network", "unreachable"]):
            return ChannelConnectionError(
                f"Connection failed for {self.name}",
                context={"original_error": str(error)}
            )
        
        # Generic send error
        return ChannelSendError(
            f"Failed to send message via {self.name}",
            context={"original_error": str(error)}
        )
