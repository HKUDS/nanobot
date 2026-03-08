"""MQTT channel implementation using aiomqtt."""

from __future__ import annotations

import asyncio
import json
import re
import ssl
from typing import Any

from aiomqtt import Client, MqttError, Will
from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import MQTTConfig


class MQTTChannel(BaseChannel):
    """
    MQTT channel using aiomqtt for async-native MQTT communication.

    Supports:
    - Bidirectional messaging via pub/sub topics
    - TLS/SSL secure connections
    - Username/password authentication
    - QoS levels 0, 1, 2
    - Last Will Testament (LWT)
    - Birth messages
    - JSON and text payload formats
    - Exponential backoff reconnection
    """

    name = "mqtt"

    # Default topic pattern for extracting sender_id
    # Matches: nanobot/{sender_id}/inbox or any single-level wildcard
    DEFAULT_TOPIC_PATTERN = re.compile(r"^nanobot/([^/]+)/inbox$")

    def __init__(self, config: MQTTConfig, bus: MessageBus):
        super().__init__(config, bus)
        self.config: MQTTConfig = config
        self._client: Client | None = None
        self._running = False
        self._reconnect_delay = config.reconnect_min_delay
        self._topic_pattern = self.DEFAULT_TOPIC_PATTERN

    def _build_tls_context(self) -> ssl.SSLContext | None:
        """Build TLS context for secure connections."""
        if not self.config.use_tls:
            return None

        context = ssl.create_default_context()

        if self.config.tls_ca_certs:
            context.load_verify_locations(cafile=self.config.tls_ca_certs)

        if self.config.tls_insecure:
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            logger.warning("MQTT TLS certificate verification disabled")

        return context

    def _build_will(self) -> Will | None:
        """Build Last Will Testament (LWT) message."""
        if not self.config.will.enabled:
            return None

        return Will(
            topic=self.config.will.topic,
            payload=self.config.will.payload,
            qos=self.config.will.qos,
            retain=self.config.will.retain,
        )

    def _parse_topic(self, topic: str) -> tuple[str, str] | None:
        """
        Extract sender_id and chat_id from topic path.

        Returns (sender_id, chat_id) or None if topic doesn't match pattern.
        """
        match = self._topic_pattern.match(topic)
        if match:
            sender_id = match.group(1)
            return sender_id, sender_id
        return None

    def _build_publish_topic(self, chat_id: str) -> str:
        """Build outbound topic from template."""
        return self.config.publish_topic_template.replace("{chat_id}", chat_id)

    def _decode_payload(self, payload: bytes, topic: str) -> tuple[str, dict[str, Any]]:
        """
        Decode MQTT payload to content and metadata.

        Returns (content, metadata) tuple.
        """
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError:
            logger.warning("Failed to decode MQTT payload as UTF-8 from topic: {}", topic)
            return "", {"raw": True, "decode_error": True}

        if self.config.payload_format == "json":
            try:
                data = json.loads(text)
                if isinstance(data, dict):
                    content = data.get("content", "")
                    metadata = data.get("metadata", {})
                    if not isinstance(metadata, dict):
                        metadata = {"raw_metadata": metadata}
                    return content, metadata
                return str(data), {}
            except json.JSONDecodeError:
                # Fall back to plain text
                return text, {"json_parse_error": True}

        # Plain text format
        return text, {}

    def _encode_payload(self, content: str, metadata: dict[str, Any] | None = None) -> bytes:
        """Encode message content to MQTT payload."""
        if self.config.payload_format == "json":
            data = {"content": content}
            if metadata:
                # Filter out internal metadata
                filtered = {k: v for k, v in metadata.items() if not k.startswith("_")}
                if filtered:
                    data["metadata"] = filtered
            return json.dumps(data, ensure_ascii=False).encode("utf-8")

        return content.encode("utf-8")

    async def _publish_birth_message(self, client: Client) -> None:
        """Publish birth message to indicate online status."""
        if not self.config.birth_enabled:
            return

        try:
            await client.publish(
                topic=self.config.birth_topic,
                payload=self.config.birth_payload,
                qos=self.config.birth_qos,
                retain=self.config.birth_retain,
            )
            logger.debug("Published MQTT birth message to {}", self.config.birth_topic)
        except MqttError as e:
            logger.warning("Failed to publish birth message: {}", e)

    async def _handle_mqtt_message(self, topic: str, payload: bytes) -> None:
        """Process an incoming MQTT message."""
        parsed = self._parse_topic(topic)
        if not parsed:
            logger.debug("MQTT message from unmatched topic: {}", topic)
            return

        sender_id, chat_id = parsed
        content, metadata = self._decode_payload(payload, topic)
        metadata["mqtt_topic"] = topic

        if not content:
            logger.debug("Empty MQTT message from {} on topic {}", sender_id, topic)
            return

        logger.debug("MQTT message from {}: {}...", sender_id, content[:50])

        await self._handle_message(
            sender_id=sender_id,
            chat_id=chat_id,
            content=content,
            media=[],
            metadata=metadata,
        )

    async def _message_loop(self, client: Client) -> None:
        """Process incoming MQTT messages."""
        async for message in client.messages:
            if not self._running:
                break

            try:
                await self._handle_mqtt_message(
                    topic=str(message.topic),
                    payload=message.payload,
                )
            except Exception as e:
                logger.error("Error processing MQTT message: {}", e)

    async def _exponential_backoff(self) -> None:
        """Wait with exponential backoff before reconnecting."""
        logger.info("Reconnecting to MQTT in {:.1f} seconds...", self._reconnect_delay)
        await asyncio.sleep(self._reconnect_delay)
        self._reconnect_delay = min(
            self._reconnect_delay * 2,
            self.config.reconnect_max_delay,
        )

    async def start(self) -> None:
        """Start the MQTT client and begin listening for messages."""
        if not self.config.host:
            logger.error("MQTT broker host not configured")
            return

        self._running = True
        logger.info(
            "Starting MQTT channel ({}:{})...",
            self.config.host,
            self.config.port,
        )

        while self._running:
            try:
                await self._run_client()
            except MqttError as e:
                if not self._running:
                    break
                logger.error("MQTT connection error: {}", e)
                await self._exponential_backoff()
            except Exception as e:
                if not self._running:
                    break
                logger.error("Unexpected MQTT error: {}", e)
                await self._exponential_backoff()

    async def _run_client(self) -> None:
        """Run the MQTT client connection loop."""
        tls_context = self._build_tls_context()
        will = self._build_will()

        client_kwargs: dict[str, Any] = {
            "hostname": self.config.host,
            "port": self.config.port,
            "identifier": self.config.client_id or None,
            "keepalive": self.config.keepalive,
            "clean_session": self.config.clean_session,
        }

        if self.config.username:
            client_kwargs["username"] = self.config.username
        if self.config.password:
            client_kwargs["password"] = self.config.password
        if tls_context:
            client_kwargs["tls_context"] = tls_context
        if will:
            client_kwargs["will"] = will

        async with Client(**client_kwargs) as client:
            self._client = client
            self._reconnect_delay = self.config.reconnect_min_delay

            logger.info("MQTT connected to {}:{}", self.config.host, self.config.port)

            # Subscribe to configured topics
            for topic_config in self.config.subscribe_topics:
                await client.subscribe(topic_config.topic, qos=topic_config.qos)
                logger.debug("MQTT subscribed to: {} (QoS {})", topic_config.topic, topic_config.qos)

            # Publish birth message
            await self._publish_birth_message(client)

            # Process messages
            await self._message_loop(client)

    async def stop(self) -> None:
        """Stop the MQTT client."""
        logger.info("Stopping MQTT channel...")
        self._running = False
        self._client = None

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message through MQTT."""
        if not self._client:
            logger.warning("MQTT client not connected, cannot send message")
            return

        topic = self._build_publish_topic(msg.chat_id)
        payload = self._encode_payload(msg.content, msg.metadata)

        try:
            await self._client.publish(
                topic=topic,
                payload=payload,
                qos=self.config.publish_qos,
                retain=self.config.retain_outbound,
            )
            logger.debug("MQTT published to {}: {}...", topic, msg.content[:50] if msg.content else "[empty]")
        except MqttError as e:
            logger.error("Failed to publish MQTT message to {}: {}", topic, e)
