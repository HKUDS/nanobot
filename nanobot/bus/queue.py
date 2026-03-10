"""Async message queue for decoupled channel-agent communication."""

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

from loguru import logger

from nanobot.bus.events import InboundMessage, OutboundMessage


@dataclass
class BusMetrics:
    """Message bus telemetry and observability metrics."""
    
    # Queue depth tracking
    inbound_depth_samples: deque = field(default_factory=lambda: deque(maxlen=100))
    outbound_depth_samples: deque = field(default_factory=lambda: deque(maxlen=100))
    
    processing_latencies: deque = field(default_factory=lambda: deque(maxlen=100))
    
    # Event drop counters
    inbound_drops: int = 0
    outbound_drops: int = 0
    
    inbound_processed: int = 0
    outbound_processed: int = 0
    
    # Last metric collection time
    last_collection: float = field(default_factory=time.time)
    
    def record_queue_depths(self, inbound_size: int, outbound_size: int) -> None:
        """Record current queue depths for monitoring."""
        self.inbound_depth_samples.append(inbound_size)
        self.outbound_depth_samples.append(outbound_size)
    
    def record_processing_latency(self, start_time: float) -> None:
        """Record message processing latency."""
        latency = time.time() - start_time
        self.processing_latencies.append(latency)
    
    def record_inbound_drop(self) -> None:
        """Record dropped inbound message."""
        self.inbound_drops += 1
    
    def record_outbound_drop(self) -> None:
        """Record dropped outbound message."""
        self.outbound_drops += 1
    
    def record_inbound_processed(self) -> None:
        """Record successful inbound message processing."""
        self.inbound_processed += 1
    
    def record_outbound_processed(self) -> None:
        """Record successful outbound message processing."""
        self.outbound_processed += 1
    
    @property
    def avg_inbound_depth(self) -> float:
        """Average inbound queue depth over recent samples."""
        return sum(self.inbound_depth_samples) / len(self.inbound_depth_samples) if self.inbound_depth_samples else 0.0
    
    @property
    def avg_outbound_depth(self) -> float:
        """Average outbound queue depth over recent samples."""
        return sum(self.outbound_depth_samples) / len(self.outbound_depth_samples) if self.outbound_depth_samples else 0.0
    
    @property
    def avg_processing_latency(self) -> float:
        """Average processing latency in seconds over recent samples."""
        return sum(self.processing_latencies) / len(self.processing_latencies) if self.processing_latencies else 0.0
    
    @property
    def max_processing_latency(self) -> float:
        """Maximum processing latency in seconds over recent samples."""
        return max(self.processing_latencies) if self.processing_latencies else 0.0
    
    def get_health_summary(self) -> dict:
        """Get comprehensive health metrics summary."""
        return {
            "queue_health": {
                "avg_inbound_depth": self.avg_inbound_depth,
                "avg_outbound_depth": self.avg_outbound_depth,
            },
            "performance": {
                "avg_processing_latency_ms": self.avg_processing_latency * 1000,
                "max_processing_latency_ms": self.max_processing_latency * 1000,
            },
            "reliability": {
                "inbound_drops": self.inbound_drops,
                "outbound_drops": self.outbound_drops,
                "inbound_processed": self.inbound_processed,
                "outbound_processed": self.outbound_processed,
                "drop_rate": self._calculate_drop_rate(),
            }
        }
    
    def _calculate_drop_rate(self) -> float:
        """Calculate overall drop rate percentage."""
        total_attempts = self.inbound_processed + self.outbound_processed + self.inbound_drops + self.outbound_drops
        total_drops = self.inbound_drops + self.outbound_drops
        return (total_drops / total_attempts * 100) if total_attempts > 0 else 0.0


class MessageBus:
    """
    Async message bus that decouples chat channels from the agent core.

    Channels push messages to the inbound queue, and the agent processes
    them and pushes responses to the outbound queue.
    
    Implements backpressure protection via bounded queues to prevent
    memory exhaustion during high-volume message bursts.
    
    Includes comprehensive telemetry for observability in production.
    """

    def __init__(
        self, 
        inbound_maxsize: int = 1000, 
        outbound_maxsize: int = 1000,
        enable_metrics: bool = False  # Disabled by default for backward compatibility
    ):
        """
        Initialize message bus with bounded queues and optional telemetry.
        
        Args:
            inbound_maxsize: Maximum inbound queue size (0 = unlimited)
            outbound_maxsize: Maximum outbound queue size (0 = unlimited)
            enable_metrics: Enable detailed telemetry collection
        """
        self.inbound: asyncio.Queue[InboundMessage] = asyncio.Queue(maxsize=inbound_maxsize)
        self.outbound: asyncio.Queue[OutboundMessage] = asyncio.Queue(maxsize=outbound_maxsize)
        
        # Track queue limits for monitoring
        self._inbound_maxsize = inbound_maxsize
        self._outbound_maxsize = outbound_maxsize
        
        # Telemetry and observability
        self._enable_metrics = enable_metrics
        self.metrics = BusMetrics() if enable_metrics else None
        self._last_metrics_log = time.time()
        self._metrics_log_interval = 300.0  # Log metrics every 5 minutes

    async def publish_inbound(self, msg: InboundMessage, timeout: Optional[float] = None) -> bool:
        """
        Publish a message from a channel to the agent with backpressure protection and telemetry.
        
        Args:
            msg: The inbound message to publish
            timeout: Optional timeout in seconds (default: no timeout)
            
        Returns:
            True if message was published, False if queue is full and timeout occurred
            
        Raises:
            asyncio.TimeoutError: If timeout specified and queue remains full
        """
        start_time = time.time() if self._enable_metrics else None
        
        try:
            if timeout is not None:
                await asyncio.wait_for(self.inbound.put(msg), timeout=timeout)
            else:
                await self.inbound.put(msg)
            
            # Record successful processing
            if self._enable_metrics and self.metrics:
                self.metrics.record_inbound_processed()
                if start_time:
                    self.metrics.record_processing_latency(start_time)
                self._update_queue_metrics()
            
            return True
            
        except asyncio.TimeoutError:
            if self._enable_metrics and self.metrics:
                self.metrics.record_inbound_drop()
            
            logger.warning(
                "Inbound queue full ({}/{}), message from {} dropped", 
                self.inbound.qsize(), 
                self._inbound_maxsize,
                msg.sender_id
            )
            return False
            
        except Exception as e:
            if self._enable_metrics and self.metrics:
                self.metrics.record_inbound_drop()
                
            logger.error("Unexpected error publishing inbound message: {}", e)
            return False

    async def consume_inbound(self) -> InboundMessage:
        """Consume the next inbound message (blocks until available)."""
        msg = await self.inbound.get()
        
        # Update metrics after consumption
        if self._enable_metrics and self.metrics:
            self._update_queue_metrics()
            self._periodic_metrics_log()
            
        return msg

    async def publish_outbound(self, msg: OutboundMessage, timeout: Optional[float] = None) -> bool:
        """
        Publish a response from the agent to channels with backpressure protection and telemetry.
        
        Args:
            msg: The outbound message to publish
            timeout: Optional timeout in seconds (default: no timeout)
            
        Returns:
            True if message was published, False if queue is full and timeout occurred
            
        Raises:
            asyncio.TimeoutError: If timeout specified and queue remains full
        """
        start_time = time.time() if self._enable_metrics else None
        
        try:
            if timeout is not None:
                await asyncio.wait_for(self.outbound.put(msg), timeout=timeout)
            else:
                await self.outbound.put(msg)
            
            # Record successful processing
            if self._enable_metrics and self.metrics:
                self.metrics.record_outbound_processed()
                if start_time:
                    self.metrics.record_processing_latency(start_time)
                self._update_queue_metrics()
                
            return True
            
        except asyncio.TimeoutError:
            if self._enable_metrics and self.metrics:
                self.metrics.record_outbound_drop()
                
            logger.warning(
                "Outbound queue full ({}/{}), message to {} dropped", 
                self.outbound.qsize(), 
                self._outbound_maxsize,
                msg.chat_id
            )
            return False

    async def consume_outbound(self) -> OutboundMessage:
        """Consume the next outbound message (blocks until available)."""
        return await self.outbound.get()

    @property
    def inbound_size(self) -> int:
        """Number of pending inbound messages."""
        return self.inbound.qsize()

    @property
    def outbound_size(self) -> int:
        """Number of pending outbound messages."""
        return self.outbound.qsize()
        
    @property
    def inbound_capacity(self) -> tuple[int, int]:
        """Current inbound queue size and maximum capacity."""
        return (self.inbound.qsize(), self._inbound_maxsize)
        
    @property
    def outbound_capacity(self) -> tuple[int, int]:
        """Current outbound queue size and maximum capacity."""
        return (self.outbound.qsize(), self._outbound_maxsize)
        
    def is_inbound_full(self) -> bool:
        """Check if inbound queue is at capacity."""
        return self._inbound_maxsize > 0 and self.inbound.qsize() >= self._inbound_maxsize
        
    def is_outbound_full(self) -> bool:
        """Check if outbound queue is at capacity."""
        return self._outbound_maxsize > 0 and self.outbound.qsize() >= self._outbound_maxsize
    
    def _update_queue_metrics(self) -> None:
        """Update internal queue metrics for monitoring."""
        if self._enable_metrics and self.metrics:
            self.metrics.record_queue_depths(self.inbound.qsize(), self.outbound.qsize())
    
    def _periodic_metrics_log(self) -> None:
        """Periodically log comprehensive metrics for monitoring."""
        if not self._enable_metrics or not self.metrics:
            return
            
        now = time.time()
        if now - self._last_metrics_log >= self._metrics_log_interval:
            health_summary = self.metrics.get_health_summary()
            
            # Log key metrics for monitoring systems to pick up
            logger.info(
                "Bus Health: avg_inbound_depth={:.1f}, avg_outbound_depth={:.1f}, "
                "avg_latency_ms={:.1f}, drop_rate={:.2f}%, "
                "processed=(in:{}, out:{}), dropped=(in:{}, out:{})",
                health_summary["queue_health"]["avg_inbound_depth"],
                health_summary["queue_health"]["avg_outbound_depth"],
                health_summary["performance"]["avg_processing_latency_ms"],
                health_summary["reliability"]["drop_rate"],
                health_summary["reliability"]["inbound_processed"],
                health_summary["reliability"]["outbound_processed"],
                health_summary["reliability"]["inbound_drops"],
                health_summary["reliability"]["outbound_drops"]
            )
            
            self._last_metrics_log = now
    
    def get_metrics_summary(self) -> dict:
        """Get current bus health metrics for external monitoring."""
        if not self._enable_metrics or not self.metrics:
            return {}
        return self.metrics.get_health_summary()
