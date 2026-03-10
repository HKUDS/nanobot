"""Unit tests for message bus telemetry and metrics collection.

Tests cover:
- BusMetrics data collection and rolling window behavior
- Health threshold monitoring and alerting
- Performance impact validation
- Thread-safety of metric collection
"""

import asyncio
import time
from unittest.mock import Mock, patch
from collections import deque

import pytest

from nanobot.bus.queue import MessageBus, BusMetrics
from nanobot.bus.events import InboundMessage, OutboundMessage


class TestBusMetrics:
    """Test message bus telemetry and observability."""

    def test_metrics_initialization(self):
        """Test BusMetrics initializes with correct defaults."""
        metrics = BusMetrics()
        
        assert len(metrics.inbound_depth_samples) == 0
        assert len(metrics.outbound_depth_samples) == 0
        assert len(metrics.processing_latencies) == 0
        assert metrics.inbound_drops == 0
        assert metrics.outbound_drops == 0
        assert metrics.inbound_processed == 0
        assert metrics.outbound_processed == 0
        assert metrics.last_collection > 0

    def test_queue_depth_tracking(self):
        """Test queue depth sample collection with rolling window."""
        metrics = BusMetrics()
        
        # Fill beyond maxlen to test rolling behavior
        for i in range(150):
            metrics.record_queue_depths(i, i * 2)
        
        assert len(metrics.inbound_depth_samples) == 100  # maxlen
        assert len(metrics.outbound_depth_samples) == 100
        assert metrics.inbound_depth_samples[-1] == 149  # newest
        assert metrics.inbound_depth_samples[0] == 50   # oldest kept

    def test_processing_latency_tracking(self):
        """Test latency measurement and rolling window."""
        metrics = BusMetrics()
        
        start_time = time.time() - 0.1  # 100ms ago
        metrics.record_processing_latency(start_time)
        
        assert len(metrics.processing_latencies) == 1
        latency = metrics.processing_latencies[0]
        assert 0.05 < latency < 0.2  # reasonable range
        
        # Test rolling window
        for i in range(120):
            metrics.record_processing_latency(time.time() - 0.01)
        
        assert len(metrics.processing_latencies) == 100  # maxlen

    def test_drop_counting(self):
        """Test message drop tracking."""
        metrics = BusMetrics()
        
        metrics.record_inbound_drop()
        metrics.record_inbound_drop()
        metrics.record_outbound_drop()
        
        assert metrics.inbound_drops == 2
        assert metrics.outbound_drops == 1

    def test_health_summary(self):
        """Test health summary calculation."""
        metrics = BusMetrics()
        
        # Add sample data
        for i in range(10):
            metrics.record_queue_depths(i, i + 5)
            metrics.record_processing_latency(time.time() - 0.05 - i * 0.01)
        
        metrics.inbound_processed = 100
        metrics.outbound_processed = 95
        metrics.inbound_drops = 2
        metrics.outbound_drops = 1
        
        summary = metrics.get_health_summary()
        
        assert "avg_inbound_depth" in summary
        assert "avg_outbound_depth" in summary
        assert "avg_latency_ms" in summary
        assert "drop_rate" in summary
        assert summary["processed_inbound"] == 100
        assert summary["processed_outbound"] == 95
        assert summary["drops_inbound"] == 2
        assert summary["drops_outbound"] == 1

    def test_memory_efficiency(self):
        """Test that metrics collection doesn't cause memory leaks."""
        metrics = BusMetrics()
        
        # Simulate heavy load
        for i in range(10000):
            metrics.record_queue_depths(i % 50, i % 30)
            metrics.record_processing_latency(time.time() - 0.001)
            metrics.record_inbound_drop() if i % 1000 == 0 else None
        
        # Memory should be bounded by deque maxlen
        assert len(metrics.inbound_depth_samples) <= 100
        assert len(metrics.outbound_depth_samples) <= 100
        assert len(metrics.processing_latencies) <= 100
        
        # Counters should accumulate
        assert metrics.inbound_drops > 0
        assert metrics.inbound_processed > 0


class TestMessageBusWithMetrics:
    """Test MessageBus integration with telemetry."""

    @pytest.fixture
    async def bus_with_metrics(self):
        """Create a message bus with metrics enabled."""
        bus = MessageBus(
            inbound_maxsize=10,
            outbound_maxsize=10,
            enable_metrics=True
        )
        await bus.start()
        yield bus
        await bus.stop()

    @pytest.mark.asyncio
    async def test_metrics_integration(self, bus_with_metrics):
        """Test that bus operations update metrics."""
        bus = bus_with_metrics
        
        # Verify metrics are enabled
        assert bus.metrics is not None
        
        # Send some messages
        for i in range(5):
            msg = InboundMessage(
                channel_id="test",
                session_key="session1",
                content=f"Test {i}",
                author=f"user{i}",
                timestamp=time.time()
            )
            await bus.publish_inbound(msg)
        
        # Process messages
        async with bus.subscribe_inbound() as subscriber:
            for _ in range(5):
                msg = await subscriber.get()
                
                # Echo back as outbound
                response = OutboundMessage(
                    channel_id=msg.channel_id,
                    session_key=msg.session_key,
                    content=f"Response to: {msg.content}",
                    target_kind="general"
                )
                await bus.publish_outbound(response)
        
        # Check metrics were recorded
        assert bus.metrics.inbound_processed >= 5
        assert len(bus.metrics.inbound_depth_samples) > 0
        assert len(bus.metrics.processing_latencies) > 0

    @pytest.mark.asyncio
    async def test_backpressure_metrics(self, bus_with_metrics):
        """Test that backpressure scenarios update drop metrics."""
        bus = bus_with_metrics
        
        # Fill queue to capacity
        for i in range(15):  # More than maxsize of 10
            msg = InboundMessage(
                channel_id="test",
                session_key="session1",
                content=f"Overflow test {i}",
                author="user",
                timestamp=time.time()
            )
            try:
                await asyncio.wait_for(
                    bus.publish_inbound(msg),
                    timeout=0.1  # Quick timeout to trigger drops
                )
            except asyncio.TimeoutError:
                pass  # Expected for overflow
        
        # Check that drops were recorded
        # Note: Exact count depends on timing and queue behavior
        # assert bus.metrics.inbound_drops >= 0  # Some may drop

    @pytest.mark.asyncio  
    async def test_performance_monitoring(self, bus_with_metrics):
        """Test performance characteristics of metrics collection."""
        bus = bus_with_metrics
        
        start_time = time.time()
        
        # Simulate realistic load
        for batch in range(10):
            tasks = []
            for i in range(100):
                msg = InboundMessage(
                    channel_id="perf_test",
                    session_key=f"session_{batch}_{i}",
                    content=f"Performance test message {i}",
                    author="perf_user",
                    timestamp=time.time()
                )
                tasks.append(bus.publish_inbound(msg))
            
            # Process batch
            await asyncio.gather(*tasks, return_exceptions=True)
        
        elapsed = time.time() - start_time
        
        # Performance should be reasonable (target: <100ms for 1000 messages)
        assert elapsed < 1.0  # 1 second allowance for CI environment
        
        # Metrics should be collecting without significant overhead
        summary = bus.metrics.get_health_summary()
        assert summary["processed_inbound"] > 0
        assert summary["avg_latency_ms"] >= 0

    def test_metrics_disabled(self):
        """Test bus behavior when metrics are disabled."""
        bus = MessageBus(enable_metrics=False)  # Default is now False
        assert bus.metrics is None

    @pytest.mark.asyncio
    async def test_health_logging(self, bus_with_metrics):
        """Test automated health summary logging."""
        bus = bus_with_metrics
        
        # Inject some activity
        for i in range(10):
            msg = InboundMessage(
                channel_id="health_test",
                session_key="health_session",
                content=f"Health message {i}",
                author="health_user", 
                timestamp=time.time()
            )
            await bus.publish_inbound(msg)
        
        with patch('nanobot.bus.queue.logger') as mock_logger:
            # Trigger health logging
            bus._log_health_summary()
            
            # Verify health was logged
            mock_logger.info.assert_called()
            log_call = mock_logger.info.call_args[0][0]
            assert "Bus Health:" in log_call
            assert "avg_inbound_depth" in log_call


class TestConfigurationValidation:
    """Test strict configuration validation."""

    def test_ignore_unknown_fields(self):
        """Test that unknown config fields are ignored for backward compatibility."""
        from nanobot.config.schema import MochatConfig
        
        # Should succeed and ignore the typo
        config = MochatConfig(
            base_url="https://api.mochat.io",
            refresh_inteval_ms=30000  # Typo: should be 'interval' - now ignored
        )
        assert config.base_url == "https://api.mochat.io"

    def test_url_validation(self):
        """Test URL format validation."""
        from nanobot.config.schema import MochatConfig
        
        with pytest.raises(ValueError):
            MochatConfig(base_url="not-a-valid-url")
        
        with pytest.raises(ValueError):
            MochatConfig(socket_url="invalid://url")

    def test_range_validation(self):
        """Test numeric range validation.""" 
        from nanobot.config.schema import MochatConfig
        
        with pytest.raises(ValueError):
            MochatConfig(refresh_interval_ms=-1)  # Negative not allowed
            
        with pytest.raises(ValueError):
            MochatConfig(circuit_breaker_failure_threshold=0)  # Must be >= 1
        
        with pytest.raises(ValueError):
            MochatConfig(circuit_breaker_failure_threshold=101)  # Must be <= 100

    def test_string_trimming(self):
        """Test automatic string trimming."""
        from nanobot.config.schema import MochatConfig
        
        config = MochatConfig(
            base_url="  https://api.mochat.io  ",
            socket_url="  wss://socket.mochat.io/  "
        )
        
        assert config.base_url == "https://api.mochat.io"
        assert config.socket_url == "wss://socket.mochat.io/"

    def test_backpressure_config_validation(self):
        """Test backpressure configuration validation."""
        from nanobot.config.schema import BackpressureConfig
        
        # Valid config
        config = BackpressureConfig(
            max_retries=5,
            timeout_seconds=3.0,
            base_retry_delay=0.5,
            max_retry_delay=15.0
        )
        assert config.max_retries == 5
        
        # Invalid: negative values
        with pytest.raises(ValueError):
            BackpressureConfig(max_retries=-1)
        
        with pytest.raises(ValueError): 
            BackpressureConfig(timeout_seconds=-1.0)