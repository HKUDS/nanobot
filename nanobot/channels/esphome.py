"""ESPHome Voice channel implementation.

Connects to ESPHome voice satellites via the Native API (aioesphomeapi)
and orchestrates the STT -> agent -> TTS pipeline using local models
(faster-whisper for STT, piper-tts for TTS) with silero VAD for
server-side voice activity detection.
"""

from __future__ import annotations

import asyncio
import io
import tempfile
import time
import uuid
import wave
from pathlib import Path
from typing import Any, Literal

from loguru import logger
from pydantic import Field

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import Base

# ESPHome satellites send/expect 16kHz 16-bit mono PCM
_SAT_RATE = 16000
_SAT_WIDTH = 2
_SAT_CHANNELS = 1

# VAD constants
_VAD_FRAME_SAMPLES = 512  # silero expects multiples of 512 samples
_VAD_FRAME_BYTES = _VAD_FRAME_SAMPLES * _SAT_WIDTH
_SPEECH_THRESHOLD = 0.5  # probability above which we consider speech
_SILENCE_TIMEOUT = 0.8  # seconds of silence after speech to trigger end

# Auto-cleanup TTS audio entries after this many seconds
_TTS_STORE_TTL = 30.0


# ---------------------------------------------------------------------------
# Config models
# ---------------------------------------------------------------------------

class ESPHomeSatelliteTarget(Base):
    """Connection target for an ESPHome voice satellite."""

    name: str = "default"
    host: str = "localhost"
    port: int = 6053
    password: str = ""
    encryption_key: str = ""  # Noise PSK for encrypted connections


class STTConfig(Base):
    """Speech-to-text configuration."""

    provider: Literal["local", "groq"] = "local"
    model: str = "distil-small.en"
    device: Literal["cpu", "cuda"] = "cpu"
    language: str | None = None


class TTSConfig(Base):
    """Text-to-speech configuration."""

    model: str = "en_US-lessac-medium"
    data_dir: str = "~/.local/share/piper-tts"
    speaker_id: int | None = None


class ESPHomeConfig(Base):
    """ESPHome voice channel configuration."""

    enabled: bool = False
    host: str = "0.0.0.0"  # IP address satellites can reach this server on
    tts_port: int = 18791  # HTTP port for serving TTS audio to satellites
    satellites: list[ESPHomeSatelliteTarget] = Field(default_factory=list)
    stt: STTConfig = Field(default_factory=STTConfig)
    tts: TTSConfig = Field(default_factory=TTSConfig)
    response_timeout: float = 30.0
    allow_from: list[str] = Field(default_factory=lambda: ["*"])
    reconnect_interval: float = 5.0
    silence_timeout_seconds: float = _SILENCE_TIMEOUT
    speech_threshold: float = _SPEECH_THRESHOLD


# ---------------------------------------------------------------------------
# Channel
# ---------------------------------------------------------------------------

class ESPHomeChannel(BaseChannel):
    """ESPHome Voice channel.

    Connects to ESPHome voice satellites, runs local STT (faster-whisper)
    and TTS (piper), and routes transcripts through the nanobot agent.
    Uses silero VAD for server-side voice activity detection.
    """

    name = "esphome"
    display_name = "ESPHome Voice"

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return ESPHomeConfig().model_dump(by_alias=True)

    def __init__(self, config: Any, bus: MessageBus):
        if isinstance(config, dict):
            config = ESPHomeConfig.model_validate(config)
        super().__init__(config, bus)
        self.config: ESPHomeConfig = config
        self._satellite_tasks: list[asyncio.Task] = []
        self._pending: dict[str, asyncio.Future[str]] = {}
        # Lazy-loaded models (shared across satellites, loaded once)
        self._whisper_model: Any = None
        self._piper_voice: Any = None
        self._vad_model: Any = None
        # TTS audio serving — satellites fetch TTS via URL
        self._tts_audio_store: dict[str, bytes] = {}  # id -> wav bytes
        self._http_runner: Any = None
        self._http_port = config.tts_port

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def _start_tts_server(self) -> None:
        """Start a minimal HTTP server to serve TTS audio files to satellites."""
        from aiohttp import web

        async def _handle_tts(request: web.Request) -> web.Response:
            audio_id = request.match_info["audio_id"]
            wav_data = self._tts_audio_store.pop(audio_id, None)
            if wav_data is None:
                return web.Response(status=404)
            return web.Response(body=wav_data, content_type="audio/wav")

        app = web.Application()
        app.router.add_get("/tts/{audio_id}.wav", _handle_tts)
        self._http_runner = web.AppRunner(app)
        await self._http_runner.setup()
        site = web.TCPSite(self._http_runner, "0.0.0.0", self._http_port)
        await site.start()
        logger.info("ESPHome: TTS audio server listening on port {}", self._http_port)

    async def start(self) -> None:
        try:
            import aioesphomeapi  # noqa: F401
        except ImportError:
            logger.error(
                "ESPHome channel requires 'aioesphomeapi'. "
                "Install with: uv pip install aioesphomeapi"
            )
            return

        if not self.config.satellites:
            logger.warning("ESPHome: no satellites configured")
            return

        # Pre-load models in a thread so we don't block the event loop
        try:
            await asyncio.get_running_loop().run_in_executor(None, self._load_models)
        except Exception:
            logger.exception("ESPHome: failed to load models, channel will not start")
            return

        # Start TTS audio HTTP server
        await self._start_tts_server()

        self._running = True
        logger.info(
            "ESPHome voice channel started with {} satellite(s) "
            "(STT: {} / {}, TTS: piper / {})",
            len(self.config.satellites),
            self.config.stt.provider,
            self.config.stt.model,
            self.config.tts.model,
        )

        for target in self.config.satellites:
            task = asyncio.create_task(
                self._satellite_loop(target), name=f"esphome-{target.name}"
            )
            self._satellite_tasks.append(task)

        while self._running:
            await asyncio.sleep(1)

    async def stop(self) -> None:
        self._running = False
        for fut in self._pending.values():
            if not fut.done():
                fut.cancel()
        self._pending.clear()
        for task in self._satellite_tasks:
            task.cancel()
        for task in self._satellite_tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._satellite_tasks.clear()
        if self._http_runner:
            await self._http_runner.cleanup()
            self._http_runner = None
        self._tts_audio_store.clear()
        logger.info("ESPHome channel stopped")

    async def send(self, msg: OutboundMessage) -> None:
        """Resolve the pending future so the pipeline can return the response."""
        if msg.metadata.get("_progress"):
            return
        sat_name = msg.metadata.get("esphome_satellite") or msg.chat_id
        fut = self._pending.get(sat_name)
        if fut and not fut.done():
            fut.set_result(msg.content)
        else:
            logger.warning("ESPHome: no pending request for satellite '{}'", sat_name)

    # ------------------------------------------------------------------
    # Model loading
    # ------------------------------------------------------------------

    def _load_models(self) -> None:
        """Load STT, TTS, and VAD models (called once, in a thread)."""
        # VAD (silero, bundled with faster-whisper)
        from faster_whisper.vad import get_vad_model

        logger.info("Loading silero VAD model...")
        self._vad_model = get_vad_model()
        logger.info("Silero VAD model loaded")

        # STT
        if self.config.stt.provider == "local":
            from faster_whisper import WhisperModel

            logger.info("Loading faster-whisper model '{}'...", self.config.stt.model)
            self._whisper_model = WhisperModel(
                self.config.stt.model,
                device=self.config.stt.device,
                compute_type="int8" if self.config.stt.device == "cpu" else "float16",
            )
            logger.info("faster-whisper model loaded")

        # TTS
        from piper import PiperVoice

        data_dir = Path(self.config.tts.data_dir).expanduser()
        data_dir.mkdir(parents=True, exist_ok=True)
        model_path = data_dir / f"{self.config.tts.model}.onnx"

        if not model_path.exists():
            alt = Path("~/.local/share/wyoming-piper").expanduser() / f"{self.config.tts.model}.onnx"
            if alt.exists():
                model_path = alt
            else:
                self._download_piper_voice(self.config.tts.model, data_dir)

        logger.info("Loading piper voice '{}'...", model_path.name)
        self._piper_voice = PiperVoice.load(str(model_path))
        logger.info("Piper voice loaded (sample_rate={})", self._piper_voice.config.sample_rate)

    @staticmethod
    def _download_piper_voice(model_name: str, dest_dir: Path) -> None:
        """Download a piper voice model from HuggingFace."""
        import urllib.request

        # Model name format: en_GB-cori-medium -> en/en_GB/cori/medium/
        parts = model_name.split("-")
        if len(parts) != 3:
            raise ValueError(
                f"Cannot auto-download piper model '{model_name}': "
                f"expected format 'lang_COUNTRY-name-quality' (e.g. en_GB-cori-medium)"
            )
        lang_country, voice_name, quality = parts
        lang = lang_country.split("_")[0]
        base = (
            f"https://huggingface.co/rhasspy/piper-voices/resolve/main"
            f"/{lang}/{lang_country}/{voice_name}/{quality}/{model_name}"
        )

        for ext in (".onnx", ".onnx.json"):
            url = f"{base}{ext}"
            dest = dest_dir / f"{model_name}{ext}"
            logger.info("Downloading piper model: {} -> {}", url, dest)
            urllib.request.urlretrieve(url, dest)

        logger.info("Piper model '{}' downloaded to {}", model_name, dest_dir)

    # ------------------------------------------------------------------
    # Satellite connection loop
    # ------------------------------------------------------------------

    async def _satellite_loop(self, target: ESPHomeSatelliteTarget) -> None:
        """Maintain a persistent connection to a single ESPHome satellite."""
        from aioesphomeapi import APIClient, VoiceAssistantEventType

        while self._running:
            client: APIClient | None = None
            pipeline_task: asyncio.Task | None = None
            vad_timeout_task: asyncio.Task | None = None
            try:
                logger.info(
                    "ESPHome: connecting to '{}' at {}:{}",
                    target.name, target.host, target.port,
                )
                client = APIClient(
                    address=target.host,
                    port=target.port,
                    password=target.password or "",
                    client_info="nanobot",
                    noise_psk=target.encryption_key or None,
                )

                disconnect_event = asyncio.Event()

                async def _on_disconnect(expected: bool) -> None:
                    disconnect_event.set()

                await client.connect(on_stop=_on_disconnect)
                logger.info("ESPHome: connected to '{}'", target.name)

                # Per-satellite state
                audio_buffer = bytearray()
                vad_buffer = bytearray()
                pipeline_active = False
                speech_detected = False
                last_speech_time = 0.0

                async def _vad_silence_monitor() -> None:
                    """Monitor for silence timeout after speech is detected."""
                    nonlocal pipeline_active
                    while pipeline_active and speech_detected:
                        await asyncio.sleep(0.1)
                        if (
                            speech_detected
                            and pipeline_active
                            and (time.monotonic() - last_speech_time)
                            > self.config.silence_timeout_seconds
                        ):
                            logger.info(
                                "ESPHome: VAD silence timeout on '{}' "
                                "({:.1f}s), ending audio",
                                target.name,
                                self.config.silence_timeout_seconds,
                            )
                            client.send_voice_assistant_event(
                                VoiceAssistantEventType.VOICE_ASSISTANT_STT_VAD_END,
                                None,
                            )
                            await handle_stop(False)
                            return

                async def handle_start(
                    conversation_id: str,
                    flags: int,
                    audio_settings: Any,
                    wake_word_phrase: str | None,
                ) -> int:
                    nonlocal pipeline_active, speech_detected, last_speech_time
                    nonlocal vad_timeout_task
                    audio_buffer.clear()
                    vad_buffer.clear()
                    pipeline_active = True
                    speech_detected = False
                    last_speech_time = 0.0
                    logger.info(
                        "ESPHome: pipeline started on '{}' (wake: {}, flags={})",
                        target.name, wake_word_phrase or "none", flags,
                    )
                    client.send_voice_assistant_event(
                        VoiceAssistantEventType.VOICE_ASSISTANT_RUN_START, None
                    )
                    return 0  # API audio mode

                async def handle_stop(abort: bool) -> None:
                    nonlocal pipeline_active, pipeline_task, vad_timeout_task
                    nonlocal speech_detected
                    if not pipeline_active:
                        return
                    pipeline_active = False
                    speech_detected = False
                    if vad_timeout_task and not vad_timeout_task.done():
                        vad_timeout_task.cancel()
                        vad_timeout_task = None
                    if abort:
                        logger.info("ESPHome: pipeline aborted on '{}'", target.name)
                        if pipeline_task and not pipeline_task.done():
                            pipeline_task.cancel()
                        client.send_voice_assistant_event(
                            VoiceAssistantEventType.VOICE_ASSISTANT_RUN_END, None
                        )
                        return
                    audio = bytes(audio_buffer)
                    audio_buffer.clear()
                    vad_buffer.clear()
                    logger.info(
                        "ESPHome: received {:.1f}s of audio from '{}'",
                        len(audio) / (_SAT_RATE * _SAT_WIDTH), target.name,
                    )
                    pipeline_task = asyncio.create_task(
                        self._run_pipeline(target, client, audio)
                    )

                async def handle_audio(data: bytes) -> None:
                    nonlocal speech_detected, last_speech_time, vad_timeout_task
                    if not pipeline_active:
                        return
                    audio_buffer.extend(data)
                    vad_buffer.extend(data)

                    # Run VAD on complete frames
                    while len(vad_buffer) >= _VAD_FRAME_BYTES:
                        frame = bytes(vad_buffer[:_VAD_FRAME_BYTES])
                        del vad_buffer[:_VAD_FRAME_BYTES]

                        prob = self._run_vad(frame)
                        if prob >= self.config.speech_threshold:
                            if not speech_detected:
                                speech_detected = True
                                logger.info(
                                    "ESPHome: speech detected on '{}' (prob={:.2f})",
                                    target.name, prob,
                                )
                                client.send_voice_assistant_event(
                                    VoiceAssistantEventType.VOICE_ASSISTANT_STT_VAD_START,
                                    None,
                                )
                                vad_timeout_task = asyncio.create_task(
                                    _vad_silence_monitor()
                                )
                            last_speech_time = time.monotonic()

                client.subscribe_voice_assistant(
                    handle_start=handle_start,
                    handle_stop=handle_stop,
                    handle_audio=handle_audio,
                )
                logger.info("ESPHome: subscribed to voice assistant on '{}'", target.name)

                # Stay alive until disconnected or stopped
                while self._running and not disconnect_event.is_set():
                    await asyncio.sleep(1)

            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "ESPHome: error in satellite loop for '{}'", target.name
                )
            finally:
                # Clean up in-flight tasks and stale pending futures
                if vad_timeout_task and not vad_timeout_task.done():
                    vad_timeout_task.cancel()
                if pipeline_task and not pipeline_task.done():
                    pipeline_task.cancel()
                old_fut = self._pending.pop(target.name, None)
                if old_fut and not old_fut.done():
                    old_fut.cancel()
                if client:
                    try:
                        await client.disconnect()
                    except Exception:
                        pass

            if self._running:
                logger.info(
                    "ESPHome: reconnecting to '{}' in {}s",
                    target.name, self.config.reconnect_interval,
                )
                await asyncio.sleep(self.config.reconnect_interval)

    def _run_vad(self, frame_pcm: bytes) -> float:
        """Run silero VAD on a single 512-sample frame. Returns speech probability."""
        import numpy as np

        samples = np.frombuffer(frame_pcm, dtype=np.int16).astype(np.float32) / 32768.0
        probs = self._vad_model(samples, num_samples=_VAD_FRAME_SAMPLES)
        return float(probs.flat[0])

    # ------------------------------------------------------------------
    # Voice pipeline: STT -> agent -> TTS -> satellite
    # ------------------------------------------------------------------

    async def _run_pipeline(
        self,
        target: ESPHomeSatelliteTarget,
        client: Any,
        audio: bytes,
    ) -> None:
        """Run the full voice pipeline for one utterance."""
        from aioesphomeapi import VoiceAssistantEventType

        try:
            # 1. STT
            client.send_voice_assistant_event(
                VoiceAssistantEventType.VOICE_ASSISTANT_STT_START, None
            )
            transcript = await self._do_stt(audio)

            if not transcript.strip():
                logger.debug("ESPHome: empty transcript from '{}', ignoring", target.name)
                client.send_voice_assistant_event(
                    VoiceAssistantEventType.VOICE_ASSISTANT_RUN_END, None
                )
                return

            client.send_voice_assistant_event(
                VoiceAssistantEventType.VOICE_ASSISTANT_STT_END,
                {"text": transcript},
            )
            logger.info("ESPHome: '{}' said: {}", target.name, transcript)

            # Map voice commands to slash commands
            normalised = transcript.strip().lower().rstrip(".")
            voice_command = None
            if normalised in ("new conversation", "start over", "reset"):
                voice_command = "/new"
            elif normalised in ("stop", "cancel", "nevermind", "never mind"):
                voice_command = "/stop"

            if voice_command:
                await self._handle_message(
                    sender_id=target.name,
                    chat_id=target.name,
                    content=voice_command,
                    metadata={"esphome_satellite": target.name},
                )
                confirmation = "Done." if voice_command == "/stop" else "New conversation started."
                tts_audio, tts_rate = await self._do_tts(confirmation)
                if tts_audio:
                    audio_id = uuid.uuid4().hex[:12]
                    wav_buf = io.BytesIO()
                    with wave.open(wav_buf, "wb") as wf:
                        wf.setnchannels(_SAT_CHANNELS)
                        wf.setsampwidth(_SAT_WIDTH)
                        wf.setframerate(tts_rate)
                        wf.writeframes(tts_audio)
                    self._tts_audio_store[audio_id] = wav_buf.getvalue()
                    asyncio.get_running_loop().call_later(
                        _TTS_STORE_TTL, self._tts_audio_store.pop, audio_id, None
                    )
                    tts_url = f"http://{self.config.host}:{self._http_port}/tts/{audio_id}.wav"
                    client.send_voice_assistant_event(
                        VoiceAssistantEventType.VOICE_ASSISTANT_TTS_END,
                        {"url": tts_url},
                    )
                client.send_voice_assistant_event(
                    VoiceAssistantEventType.VOICE_ASSISTANT_RUN_END, None
                )
                return

            # 2. Agent
            client.send_voice_assistant_event(
                VoiceAssistantEventType.VOICE_ASSISTANT_INTENT_START, None
            )

            loop = asyncio.get_running_loop()
            fut: asyncio.Future[str] = loop.create_future()
            self._pending[target.name] = fut

            try:
                await self._handle_message(
                    sender_id=target.name,
                    chat_id=target.name,
                    content=transcript,
                    metadata={"esphome_satellite": target.name},
                )
                response_text = await asyncio.wait_for(
                    fut, timeout=self.config.response_timeout
                )
            except asyncio.TimeoutError:
                logger.warning("ESPHome: agent response timed out for '{}'", target.name)
                response_text = "Sorry, I took too long to respond."
            finally:
                self._pending.pop(target.name, None)

            client.send_voice_assistant_event(
                VoiceAssistantEventType.VOICE_ASSISTANT_INTENT_END,
                {"conversation_id": target.name},
            )
            logger.info("ESPHome: responding to '{}': {}", target.name, response_text)

            # 3. TTS
            if not response_text.strip():
                client.send_voice_assistant_event(
                    VoiceAssistantEventType.VOICE_ASSISTANT_TTS_END, None
                )
                client.send_voice_assistant_event(
                    VoiceAssistantEventType.VOICE_ASSISTANT_RUN_END, None
                )
                return

            client.send_voice_assistant_event(
                VoiceAssistantEventType.VOICE_ASSISTANT_TTS_START,
                {"text": response_text},
            )

            tts_audio, tts_rate = await self._do_tts(response_text)

            tts_url = ""
            if tts_audio:
                audio_id = uuid.uuid4().hex[:12]
                wav_buf = io.BytesIO()
                with wave.open(wav_buf, "wb") as wf:
                    wf.setnchannels(_SAT_CHANNELS)
                    wf.setsampwidth(_SAT_WIDTH)
                    wf.setframerate(tts_rate)
                    wf.writeframes(tts_audio)
                self._tts_audio_store[audio_id] = wav_buf.getvalue()

                # Auto-cleanup if satellite never fetches the audio
                asyncio.get_running_loop().call_later(
                    _TTS_STORE_TTL, self._tts_audio_store.pop, audio_id, None
                )

                tts_url = f"http://{self.config.host}:{self._http_port}/tts/{audio_id}.wav"
                logger.debug("ESPHome: TTS audio URL: {}", tts_url)

            client.send_voice_assistant_event(
                VoiceAssistantEventType.VOICE_ASSISTANT_TTS_END,
                {"url": tts_url} if tts_url else None,
            )

            # Done
            client.send_voice_assistant_event(
                VoiceAssistantEventType.VOICE_ASSISTANT_RUN_END, None
            )

        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("ESPHome: pipeline error for '{}'", target.name)
            try:
                client.send_voice_assistant_event(
                    VoiceAssistantEventType.VOICE_ASSISTANT_ERROR,
                    {"code": "pipeline_error", "message": "Pipeline failed"},
                )
                client.send_voice_assistant_event(
                    VoiceAssistantEventType.VOICE_ASSISTANT_RUN_END, None
                )
            except Exception:
                pass

    # ------------------------------------------------------------------
    # STT
    # ------------------------------------------------------------------

    async def _do_stt(self, audio_pcm: bytes) -> str:
        """Transcribe 16kHz 16-bit mono PCM audio to text."""
        if self.config.stt.provider == "groq":
            return await self._do_stt_groq(audio_pcm)
        return await self._do_stt_local(audio_pcm)

    async def _do_stt_local(self, audio_pcm: bytes) -> str:
        """Transcribe using local faster-whisper model."""
        import numpy as np

        def _transcribe() -> str:
            samples = np.frombuffer(audio_pcm, dtype=np.int16).astype(np.float32) / 32768.0
            segments, _info = self._whisper_model.transcribe(
                samples,
                language=self.config.stt.language,
                beam_size=5,
                vad_filter=True,
            )
            return " ".join(seg.text.strip() for seg in segments)

        return await asyncio.get_running_loop().run_in_executor(None, _transcribe)

    async def _do_stt_groq(self, audio_pcm: bytes) -> str:
        """Transcribe using Groq cloud Whisper API."""
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            tmp_path = f.name
            with wave.open(f, "wb") as wav:
                wav.setnchannels(_SAT_CHANNELS)
                wav.setsampwidth(_SAT_WIDTH)
                wav.setframerate(_SAT_RATE)
                wav.writeframes(audio_pcm)

        try:
            return await self.transcribe_audio(tmp_path) or ""
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # TTS
    # ------------------------------------------------------------------

    async def _do_tts(self, text: str) -> tuple[bytes, int]:
        """Synthesize text to (pcm_audio_bytes, sample_rate)."""

        def _synthesize() -> tuple[bytes, int]:
            from piper.config import SynthesisConfig

            syn_config = SynthesisConfig()
            if self.config.tts.speaker_id is not None:
                syn_config.speaker_id = self.config.tts.speaker_id

            audio = bytearray()
            rate = 0
            for chunk in self._piper_voice.synthesize(text, syn_config):
                audio.extend(chunk.audio_int16_bytes)
                rate = chunk.sample_rate
            return bytes(audio), rate

        return await asyncio.get_running_loop().run_in_executor(None, _synthesize)
