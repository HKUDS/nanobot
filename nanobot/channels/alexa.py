"""Amazon Alexa channel implementation.

Runs an HTTPS-capable HTTP server that receives Alexa Custom Skill requests,
verifies the request signature, forwards the user's speech to the agent,
and returns the agent's response as spoken text.
"""

from __future__ import annotations

import asyncio
import base64
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from aiohttp import ClientSession, web
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.padding import PKCS1v15
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import AlexaConfig

# Alexa enforces an 8-second response timeout; leave headroom.
_RESPONSE_TIMEOUT = 7.5

# Cache fetched certificates to avoid repeated downloads.
_cert_cache: dict[str, tuple[x509.Certificate, float]] = {}
_CERT_TTL = 3600  # 1 hour


def _validate_cert_url(url: str) -> bool:
    """Ensure the certificate URL matches Amazon's requirements."""
    parsed = urlparse(url)
    return (
        parsed.scheme == "https"
        and parsed.hostname is not None
        and parsed.hostname.lower() == "s3.amazonaws.com"
        and parsed.path.startswith("/echo.api/")
        and (parsed.port is None or parsed.port == 443)
    )


async def _fetch_certificate(url: str) -> x509.Certificate:
    """Fetch and cache the Alexa signing certificate."""
    now = time.monotonic()
    cached = _cert_cache.get(url)
    if cached and (now - cached[1]) < _CERT_TTL:
        return cached[0]

    async with ClientSession() as session:
        async with session.get(url) as resp:
            resp.raise_for_status()
            pem_data = await resp.read()

    cert = x509.load_pem_x509_certificate(pem_data)
    _cert_cache[url] = (cert, now)
    return cert


def _verify_certificate(cert: x509.Certificate) -> bool:
    """Check the certificate is valid and issued by Amazon."""
    now = datetime.now(timezone.utc)
    if now < cert.not_valid_before_utc or now > cert.not_valid_after_utc:
        return False

    # Subject Alternative Name must include echo-api.amazon.com
    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        dns_names = san.value.get_values_for_type(x509.DNSName)
        if "echo-api.amazon.com" not in dns_names:
            return False
    except x509.ExtensionNotFound:
        return False

    return True


def _verify_signature(cert: x509.Certificate, signature_b64: str, body: bytes) -> bool:
    """Verify the request body against the Alexa signature."""
    public_key = cert.public_key()
    if not isinstance(public_key, RSAPublicKey):
        return False
    signature = base64.b64decode(signature_b64)
    try:
        public_key.verify(signature, body, PKCS1v15(), hashes.SHA256())
        return True
    except Exception:
        return False


def _build_response(speech: str, end_session: bool = True) -> dict:
    """Build an Alexa JSON response with plain-text output speech."""
    return {
        "version": "1.0",
        "response": {
            "outputSpeech": {
                "type": "PlainText",
                "text": speech,
            },
            "shouldEndSession": end_session,
        },
    }


class AlexaChannel(BaseChannel):
    """Alexa Custom Skill channel.

    Starts an aiohttp server that:
    1. Validates the Alexa request signature (when ``verify_signatures`` is true).
    2. Publishes the user's utterance to the message bus.
    3. Waits (up to ~7.5 s) for the agent's reply and speaks it back.
    """

    name = "alexa"

    def __init__(self, config: AlexaConfig, bus: MessageBus):
        super().__init__(config, bus)
        self.config: AlexaConfig = config
        self._runner: web.AppRunner | None = None
        # Map request_id -> Future[str] for synchronous response flow
        self._pending: dict[str, asyncio.Future[str]] = {}

    async def start(self) -> None:
        app = web.Application()
        app.router.add_post(self.config.endpoint_path, self._handle_request)
        app.router.add_get("/health", self._health)

        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self.config.host, self.config.port)
        await site.start()
        self._running = True
        logger.info(
            "Alexa channel listening on {}:{}{} (signature verification: {})",
            self.config.host,
            self.config.port,
            self.config.endpoint_path,
            self.config.verify_signatures,
        )

        # Keep running
        while self._running:
            await asyncio.sleep(1)

    async def stop(self) -> None:
        self._running = False
        # Cancel any pending response futures
        for fut in self._pending.values():
            if not fut.done():
                fut.cancel()
        self._pending.clear()
        if self._runner:
            await self._runner.cleanup()
            self._runner = None

    async def send(self, msg: OutboundMessage) -> None:
        """Resolve the pending future so the HTTP handler can return the response."""
        # Ignore progress messages — only deliver the final response
        if msg.metadata.get("_progress"):
            return

        request_id = msg.metadata.get("alexa_request_id")
        if not request_id:
            # Fallback: use chat_id which we set to the request_id
            request_id = msg.chat_id

        fut = self._pending.get(request_id)
        if fut and not fut.done():
            fut.set_result(msg.content)
        else:
            logger.warning("Alexa: no pending request for {}", request_id)

    # ------------------------------------------------------------------
    # HTTP handlers
    # ------------------------------------------------------------------

    async def _handle_request(self, request: web.Request) -> web.Response:
        body = await request.read()

        # --- Signature verification ---
        if self.config.verify_signatures:
            cert_url = request.headers.get("SignatureCertChainUrl", "")
            signature = request.headers.get("Signature-256", "")

            if not cert_url or not signature:
                return web.json_response(
                    _build_response("Request verification failed."), status=401
                )

            if not _validate_cert_url(cert_url):
                logger.warning("Alexa: invalid certificate URL: {}", cert_url)
                return web.json_response(
                    _build_response("Request verification failed."), status=401
                )

            try:
                cert = await _fetch_certificate(cert_url)
            except Exception:
                logger.exception("Alexa: failed to fetch certificate")
                return web.json_response(
                    _build_response("Request verification failed."), status=401
                )

            if not _verify_certificate(cert):
                logger.warning("Alexa: certificate validation failed")
                return web.json_response(
                    _build_response("Request verification failed."), status=401
                )

            if not _verify_signature(cert, signature, body):
                logger.warning("Alexa: signature verification failed")
                return web.json_response(
                    _build_response("Request verification failed."), status=401
                )

        # --- Parse the Alexa request ---
        try:
            data = await request.json()
        except Exception:
            return web.json_response(
                _build_response("Invalid request."), status=400
            )

        # Timestamp validation (reject requests older than 150 seconds)
        if self.config.verify_signatures:
            try:
                ts_str = data.get("request", {}).get("timestamp", "")
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                if abs((datetime.now(timezone.utc) - ts).total_seconds()) > 150:
                    return web.json_response(
                        _build_response("Request too old."), status=400
                    )
            except Exception:
                return web.json_response(
                    _build_response("Invalid timestamp."), status=400
                )

        req_type = data.get("request", {}).get("type", "")
        request_id = data.get("request", {}).get("requestId", "")

        # Handle LaunchRequest
        if req_type == "LaunchRequest":
            return web.json_response(
                _build_response(
                    self.config.launch_message,
                    end_session=False,
                )
            )

        # Handle SessionEndedRequest
        if req_type == "SessionEndedRequest":
            return web.json_response(_build_response("Goodbye."))

        # Handle IntentRequest
        if req_type == "IntentRequest":
            intent = data["request"].get("intent", {})
            intent_name = intent.get("name", "")

            # Built-in intents
            if intent_name in ("AMAZON.StopIntent", "AMAZON.CancelIntent"):
                return web.json_response(_build_response("Goodbye."))
            if intent_name == "AMAZON.HelpIntent":
                return web.json_response(
                    _build_response(
                        "Just tell me what you need and I'll do my best to help.",
                        end_session=False,
                    )
                )
            if intent_name == "AMAZON.FallbackIntent":
                return web.json_response(
                    _build_response(
                        "I didn't catch that. Could you say it again?",
                        end_session=False,
                    )
                )

            # Extract the user's utterance from the catch-all slot
            slots = intent.get("slots", {})
            utterance = ""
            for slot in slots.values():
                if slot.get("value"):
                    utterance = slot["value"]
                    break

            if not utterance:
                return web.json_response(
                    _build_response(
                        "I didn't catch that. Could you say it again?",
                        end_session=False,
                    )
                )

            # Determine sender identity
            user_id = (
                data.get("session", {})
                .get("user", {})
                .get("userId", "alexa_user")
            )

            # Create a future for the response
            loop = asyncio.get_running_loop()
            fut: asyncio.Future[str] = loop.create_future()
            self._pending[request_id] = fut

            try:
                # Forward to message bus
                await self._handle_message(
                    sender_id=user_id,
                    chat_id=request_id,
                    content=utterance,
                    metadata={"alexa_request_id": request_id},
                )

                # Wait for the agent response
                response_text = await asyncio.wait_for(fut, timeout=_RESPONSE_TIMEOUT)
                return web.json_response(
                    _build_response(response_text, end_session=False)
                )
            except asyncio.TimeoutError:
                logger.warning("Alexa: agent response timed out for {}", request_id)
                return web.json_response(
                    _build_response(
                        "I'm still thinking about that. Please try again in a moment.",
                        end_session=False,
                    )
                )
            finally:
                self._pending.pop(request_id, None)

        # Unknown request type
        return web.json_response(
            _build_response("I don't know how to handle that request.")
        )

    async def _health(self, request: web.Request) -> web.Response:
        return web.json_response({"status": "ok"})
