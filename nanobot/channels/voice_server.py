import re, httpx
"""Voice server channel for ESP32/XiaoZhi devices."""

import asyncio
import json
import logging
import os
import tempfile
import wave
from pathlib import Path
import http
from typing import Any, Dict

import websockets
from loguru import logger
from urllib.parse import urlparse, parse_qs
import collections
import audioop

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel

from pydantic import BaseModel, ConfigDict

class VoiceServerConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    enabled: bool = False
    port: int = 18790
    host: str = "0.0.0.0"
    local_ip: str | None = None
    mic_gain: float = 6.0
    token: str | None = None
    transcription_api_base: str = ""
    transcription_model: str = ""
    rms_threshold: float = 30.0
    allowFrom: list[str] | None = None
    firmware_path: str = "/root/.nanobot/firmware.bin"
    show_debug_on_display: bool = True
    speaker_id_url: str = "http://192.168.22.111:8001/identify"
    enroll_url: str = "http://192.168.22.111:8001/enroll"


class WhisperTranscriber:
    """Inline implementation of Whisper STT provider to avoid missing dependencies."""
    def __init__(self, api_base, model=None, api_key=None):
        self.api_base = api_base
        self.model = model or "whisper-large-v3"
        self.api_key = api_key
        self._client = None
    
    async def get_client(self):
        import httpx
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=60.0)
        return self._client

    async def transcribe(self, file_path):
        import httpx
        max_retries = 3
        retry_delay = 1.0
        
        client = await self.get_client()
        for attempt in range(max_retries):
            try:
                with open(file_path, "rb") as f:
                        files = {
                            "file": (Path(file_path).name, f),
                            "model": (None, self.model),
                            "language": (None, "ru"),
                        }
                        headers = {}
                        if self.api_key:
                            headers["Authorization"] = f"Bearer {self.api_key}"
                        
                        response = await client.post(
                            self.api_base,
                            headers=headers,
                            files=files
                        )
                        
                        if response.status_code in [500, 503, 404] and attempt < max_retries - 1:
                            logger.info(f"STT server warming up (attempt {attempt+1}/{max_retries})...")
                            await asyncio.sleep(retry_delay)
                            continue
                            
                        response.raise_for_status()
                        data = response.json()
                        return data.get("text", "")
            except Exception as e:
                if "closed" in str(e).lower() or "connection" in str(e).lower():
                    self._client = None
                
                if attempt < max_retries - 1:
                    logger.debug(f"Transcription retry {attempt+1} due to: {e}")
                    await asyncio.sleep(retry_delay)
                else:
                    logger.error(f"Whisper transcription error: {e}")
                    return ""
        return ""

try:
    import opuslib
except ImportError:
    opuslib = None


class VoiceServerChannel(BaseChannel):
    """
    WebSocket server for voice-enabled devices.
    """
    name = "voice_server"

    def __init__(self, config: Any, bus: MessageBus):
        if isinstance(config, dict):
            config = VoiceServerConfig(**config)
        super().__init__(config, bus)
        self.config = config
        self._running = False
        self._stop_future: asyncio.Future | None = None
        self.server = None
        self.clients: dict[str, Any] = {}
        self.audio_states: dict[str, dict[str, Any]] = {}

        self.mcp_server = None
        self.mcp_requests: dict[int, asyncio.Future] = {}
        self._mcp_req_id = 0

        self.transcriber = WhisperTranscriber(
            api_base=config.transcription_api_base,
            model=config.transcription_model,
            api_key=config.token
        )

    async def start(self) -> None:
        self._running = True
        self._stop_future = asyncio.Future()

        sock_path = "/tmp/xiaozhi_proxy.sock"
        if os.path.exists(sock_path):
            os.remove(sock_path)
        self.mcp_server = await asyncio.start_unix_server(self._handle_mcp_socket, sock_path)
        os.chmod(sock_path, 0o777)
        logger.info(f"Local MCP proxy socket listening on {sock_path}")

        self.server = await websockets.serve(
            self._handle_client,
            self.config.host,
            self.config.port,
            process_request=self._process_request
        )
        logger.info(f"Voice server listening on {self.config.host}:{self.config.port}")
        
        try:
            await self._stop_future
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()

    async def stop(self) -> None:
        self._running = False
        if self._stop_future and not self._stop_future.done():
            self._stop_future.set_result(True)

        if self.server:
            self.server.close()
            await self.server.wait_closed()
            self.server = None

        if self.mcp_server:
            self.mcp_server.close()
            await self.mcp_server.wait_closed()
            self.mcp_server = None
            if os.path.exists("/tmp/xiaozhi_proxy.sock"):
                os.remove("/tmp/xiaozhi_proxy.sock")
        
        for ws in self.clients.values():
            await ws.close()
        self.clients.clear()

    async def send(self, message: OutboundMessage) -> None:
        emotion = None
        if hasattr(message, 'content') and message.content:
            # Extract emotion from brackets [emotion] or JSON blocks {"emotion": "..."}
            match = re.search(r'\[(.*?)\]', message.content)
            if match:
                emotion = match.group(1).lower()
            else:
                # Try to find JSON block with emotion
                json_match = re.search(r'\{.*"emotion":\s*"([^"]+)".*\}', message.content, re.DOTALL)
                if json_match:
                    emotion = json_match.group(1).lower()

            if emotion:
                # Mapping puzzled and confused to thinking for device compatibility
                if emotion in ["puzzled", "confused"]:
                    emotion = "thinking"
                logger.info(f"Detected emotion: {emotion} in message to {message.chat_id}")

            # Strip emojis
            message.content = re.sub(r'[\U00010000-\U0010ffff]', '', message.content)
            # Strip text inside brackets and asterisks (emotions/actions)
            message.content = re.sub(r'\[.*?\]', '', message.content)
            message.content = re.sub(r'\*.*?\*', '', message.content)
            # Final cleanup of non-verbal characters but keep basic punctuation
            message.content = re.sub(r'[^\w\s\.,!\?\-:]', '', message.content)
            # Remove redundant spaces and strip
            message.content = re.sub(r'\s+', ' ', message.content).strip()

        client_id = message.chat_id
        ws = self.clients.get(client_id)
        
        if not ws:
            logger.warning(f"Client {client_id} not connected, cannot send message")
            return

        try:
            # Send emotion update if detected
            if emotion:
                await ws.send(json.dumps({"type": "llm", "emotion": emotion}))

            audio_url = message.metadata.get("audio_url")
            mcp_payload = message.metadata.get("mcp")
            direct_json = message.metadata.get("json")
            
            if direct_json:
                await ws.send(json.dumps(direct_json))
            elif mcp_payload:
                await ws.send(json.dumps({"type": "mcp", "payload": mcp_payload}))
            elif audio_url:
                await ws.send(json.dumps({
                    "type": "tts",
                    "state": "start",
                    "url": audio_url,
                    "session_id": message.metadata.get("session_id", "default")
                }))
            else:
                try:
                    import edge_tts
                    import subprocess
                    import asyncio
                    import opuslib
                    
                    state = self.audio_states.get(client_id)
                    if not state: return

                    if "encoder" not in state:
                        state["encoder"] = opuslib.Encoder(16000, 1, opuslib.APPLICATION_VOIP)
                    encoder = state["encoder"]
                    
                    safe_id = "".join([c for c in client_id if c.isalnum()])
                    file_path = f"/tmp/tts_{safe_id}.mp3"
                    
                    communicate = edge_tts.Communicate(message.content, "ru-RU-SvetlanaNeural")
                    await communicate.save(file_path)
                    
                    await ws.send(json.dumps({"type": "tts", "state": "start"}))
                    
                    cmd = ['ffmpeg', '-i', file_path, '-f', 's16le', '-acodec', 'pcm_s16le', '-ar', '16000', '-ac', '1', 'pipe:1']
                    process = await asyncio.create_subprocess_exec(*cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                    
                    chunk_size = 1920 
                    while True:
                        pcm_chunk = await process.stdout.read(chunk_size)
                        if not pcm_chunk: break
                        if len(pcm_chunk) < chunk_size:
                            pcm_chunk = pcm_chunk.ljust(chunk_size, b'\x00')
                        opus_frame = encoder.encode(pcm_chunk, 960)
                        await ws.send(opus_frame)
                        await asyncio.sleep(0.06)
                        
                    await process.wait()
                    
                    listening_flag = "?" in message.content
                    await ws.send(json.dumps({
                        "type": "tts", 
                        "state": "stop",
                        "listening": listening_flag,
                        "session_id": message.metadata.get("session_id", "default")
                    }))
                    logger.info(f"Streamed auto-tts Opus bytes to {client_id} (listening={listening_flag})")
                    
                except Exception as tts_err:
                    logger.error(f"Auto-TTS Opus error for {client_id}: {tts_err}")
                    await ws.send(json.dumps({"type": "text", "content": message.content}))
        except Exception as e:
            logger.error(f"Failed to send to {client_id}: {e}")

    async def _handle_mcp_socket(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            data = await reader.readline()
            if not data: return
            
            req = json.loads(data.decode("utf-8"))
            action = req.get("action")
            
            if action == "list_devices":
                devices = [{"mac": mac} for mac in self.clients.keys() if not (mac.startswith("pending_") or mac.startswith("unknown_"))]
                response = {"status": "ok", "devices": devices}
                writer.write(json.dumps(response).encode("utf-8") + b"\n")
                await writer.drain()
                
            elif action == "call_tool":
                mac = req.get("mac")
                ws = self.clients.get(mac)
                if not ws:
                    writer.write(json.dumps({"error": "Device not connected"}).encode("utf-8") + b"\n")
                    await writer.drain()
                    return
                
                self._mcp_req_id += 1
                req_id = self._mcp_req_id
                fut = asyncio.Future()
                self.mcp_requests[req_id] = fut
                
                mcp_payload = {
                    "jsonrpc": "2.0", "id": req_id, "method": "tools/call",
                    "params": {"name": req.get("tool_name"), "arguments": req.get("arguments", {})}
                }
                await ws.send(json.dumps({"type": "mcp", "payload": mcp_payload}))
                
                try:
                    result = await asyncio.wait_for(fut, timeout=10.0)
                    response = result.get("result") or {"error": result.get("error", "Invalid response")}
                except asyncio.TimeoutError:
                    response = {"error": "Timeout"}
                finally:
                    self.mcp_requests.pop(req_id, None)
                    
                writer.write(json.dumps(response).encode("utf-8") + b"\n")
                await writer.drain()
                
        except Exception as e:
            logger.error(f"MCP Proxy error: {e}")
        finally:
            writer.close()
            await writer.wait_closed()

    def _init_client_state(self, client_id: str):
        if opuslib is None: return
        self.audio_states[client_id] = {
            "is_listening": False,
            "pcm_buffer": bytearray(),
            "decoder": opuslib.Decoder(16000, 1),
            "session_id": "default",
            "silent_frames": 0
        }

    async def _process_request(self, connection, request):
        try:
            from websockets.http11 import Response
            from websockets.datastructures import Headers
            path = getattr(request, 'path', getattr(request, 'uri', 'unknown'))
            parsed_url = urlparse(path)
            clean_path = parsed_url.path
            
            if clean_path == "/ota":
                import time
                local_ip = self.config.local_ip or "0.0.0.0"
                ota_info = {
                    "server_time": {"timestamp": int(time.time() * 1000), "timezone_offset": 180},
                    "firmware": {"version": "4.1.0", "url": f"http://{local_ip}:{self.config.port}/xiaozhi.bin", "md5": "0"},
                    "websocket": {"url": f"ws://{local_ip}:{self.config.port}", "token": self.config.token, "version": 3}
                }
                data = json.dumps(ota_info).encode("utf-8")
                return Response(200, "OK", Headers([("Content-Type", "application/json"), ("Content-Length", str(len(data)))]), data)
                
            if clean_path.startswith("/tts/"):
                file_path = Path(f"/tmp/tts_{clean_path.split('/')[-1].split('.')[0]}.mp3")
                if file_path.exists():
                    data = file_path.read_bytes()
                    return Response(200, "OK", Headers([("Content-Type", "audio/mpeg"), ("Content-Length", str(len(data)))]), data)

            if clean_path == "/xiaozhi.bin":
                f_path = Path(self.config.firmware_path)
                if f_path.exists():
                    data = f_path.read_bytes()
                    return Response(200, "OK", Headers([("Content-Type", "application/octet-stream"), ("Content-Length", str(len(data)))]), data)

            return None
        except Exception as e:
            logger.exception(f"HTTP Error: {e}")
            return None

    async def _handle_client(self, websocket: Any):
        client_id = "pending_" + str(id(websocket))
        self.clients[client_id] = websocket
        self._init_client_state(client_id)
        
        try:
            await websocket.send(json.dumps({
                "type": "hello", "version": 3, "transport": "websocket",
                "audio_params": {"format": "opus", "sample_rate": 24000, "channels": 1, "frame_duration": 60}
            }))

            async for message in websocket:
                if isinstance(message, str):
                    try:
                        data = json.loads(message)
                        msg_type = data.get("type")
                        
                        if msg_type == "hello":
                            client_id = data.get("mac") or "unknown_" + str(id(websocket))
                            if client_id in self.clients and self.clients[client_id] != websocket:
                                await self.clients[client_id].close()
                            self.clients[client_id] = websocket
                            self._init_client_state(client_id)
                            logger.info(f"Client {client_id} connected")
                            await websocket.send(json.dumps({
                                "type": "hello", "version": 3, "transport": "websocket",
                                "audio_params": {"format": "opus", "sample_rate": 16000, "channels": 1, "frame_duration": 60}
                            }))
                            
                        elif msg_type == "listen":
                            if client_id not in self.audio_states: self._init_client_state(client_id)
                            state = data.get("state")
                            if state == "start":
                                self.audio_states[client_id].update({"is_listening": True, "pcm_buffer": bytearray(), "silent_frames": 0, "session_id": data.get("session_id", "default")})
                                logger.info(f"Client {client_id} STARTED listening")
                            elif state == "stop":
                                self.audio_states[client_id]["is_listening"] = False
                                await self._process_audio_buffer(client_id)
                                
                        elif msg_type == "mcp":
                            payload = data.get("payload", {})
                            req_id = payload.get("id")
                            if req_id in self.mcp_requests: self.mcp_requests[req_id].set_result(payload)
                            
                    except json.JSONDecodeError: pass

                elif isinstance(message, bytes):
                    if client_id in self.audio_states and self.audio_states[client_id]["is_listening"]:
                        state = self.audio_states[client_id]
                        try:
                            pcm_frame = state["decoder"].decode(message, 960)
                            state["pcm_buffer"].extend(pcm_frame)
                            
                            rms = audioop.rms(pcm_frame, 2)
                            is_enrolling = state.get("pending_enrollment")
                            
                            # VAD Logic: Check silence threshold from config
                            if rms < self.config.rms_threshold:
                                state["silent_frames"] += 1
                            else:
                                state["silent_frames"] = 0
                                
                            # Auto-stop after 80 silent frames (4.8s) if not enrolling
                            if not is_enrolling and state["silent_frames"] >= 80 and len(state["pcm_buffer"]) >= 16000 * 2 * 0.5:
                                logger.info(f"Silence detected ({rms:.1f}). Auto-stopping.")
                                state["is_listening"] = False
                                asyncio.create_task(self._process_audio_buffer(client_id))
                                continue

                            # Enrollment sample duration (5.5s)
                            if is_enrolling and len(state["pcm_buffer"]) >= 16000 * 2 * 5.5:
                                state["is_listening"] = False
                                asyncio.create_task(self._process_audio_buffer(client_id))
                                continue

                            # Max record time (30s failsafe)
                            if len(state["pcm_buffer"]) >= 16000 * 2 * 30:
                                state["is_listening"] = False
                                asyncio.create_task(self._process_audio_buffer(client_id))
                                continue

                        except Exception as e:
                            logger.error(f"Binary frame error: {e}")
                            
        except Exception: pass
        finally:
            self.clients.pop(client_id, None)
            self.audio_states.pop(client_id, None)

    async def _process_audio_buffer(self, client_id: str):
        state = self.audio_states.get(client_id)
        ws = self.clients.get(client_id)
        if not state or not state["pcm_buffer"]: return

        async def send_tts_stop():
            if ws: await ws.send(json.dumps({"type": "tts", "state": "stop", "listening": False, "session_id": state.get("session_id", "default")}))

        pcm_data = bytes(state["pcm_buffer"])
        state["pcm_buffer"].clear()
        
        if len(pcm_data) < 16000 * 2 * 0.3: # Min 300ms
            await send_tts_stop()
            return

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_wav:
            with wave.open(temp_wav.name, 'wb') as wav_file:
                wav_file.setnchannels(1); wav_file.setsampwidth(2); wav_file.setframerate(16000); wav_file.writeframes(pcm_data)
            temp_wav_path = temp_wav.name
            
        try:
            # Multi-threaded identification and transcription
            if not hasattr(self, "_speaker_client"): self._speaker_client = httpx.AsyncClient(timeout=10.0)
            
            async def _identify_speaker(wav_path):
                try:
                    with open(wav_path, "rb") as f:
                        resp = await self._speaker_client.post(self.config.speaker_id_url, files={"file": f})
                        if resp.status_code == 200:
                            data = resp.json()
                            identified = data.get("identified", "Unknown")
                            logger.info(f"Speaker ID: identified='{identified}' score={score:.2f}")
                            if "results" in data:
                                top_n = sorted(data["results"], key=lambda x: x["score"], reverse=True)[:3]
                                scores_str = ", ".join([f"{r['user_id']}:{r['score']:.2f}" for r in top_n])
                                logger.debug(f"Top scores: {scores_str}")
                            return identified
                        else:
                            logger.warn(f"Speaker ID error: code={resp.status_code} body={resp.text[:100]}")
                            return "Unknown"
                except Exception as e:
                    logger.error(f"Speaker ID request failed: {e}")
                    return "Unknown"

            text_task = asyncio.create_task(self.transcriber.transcribe(temp_wav_path))
            speaker_task = asyncio.create_task(_identify_speaker(temp_wav_path))
            
            text = await text_task
            try: speaker = await asyncio.wait_for(speaker_task, timeout=5.0)
            except: speaker = "Unknown"
            
            if not text or not text.strip():
                await send_tts_stop(); return
            
            # Hallucination filter
            hallucinations = ["продолжение следует", "спасибо за просмотр", "редактор субтитров", "подписывайтесь на канал"]
            if any(h in text.lower() for h in hallucinations):
                await send_tts_stop(); return

            # Enrollment checks
            enroll_pattern = r"(?:запомни|запиши|сохрани|регистр)[\s,]+(?:меня[\s,]+)?(?:как)[\s,]+([а-яё\s,a-z0-9]+)"
            enroll_match = re.search(enroll_pattern, text.lower(), re.IGNORECASE)
            # English fallback
            en_enroll_match = re.search(r"remember\s+me\s+as\s+([a-z0-9\s]+)", text.lower(), re.IGNORECASE)
            
            enroll_name = None
            if enroll_match: enroll_name = enroll_match.group(1).strip().capitalize()
            elif en_enroll_match: enroll_name = en_enroll_match.group(1).strip().capitalize()

            if enroll_name:
                try:
                    with open(temp_wav_path, 'rb') as f:
                        async with httpx.AsyncClient() as client:
                            await client.post(self.config.enroll_url, files={'file': f}, data={'user_id': enroll_name}, timeout=10.0)
                            await self.send(OutboundMessage(channel=self.name, chat_id=client_id, content=f'Запомнила тебя как {enroll_name}!' if not en_enroll_match else f'Remembered you as {enroll_name}!'))
                except: pass
                return

            # Normal command logic
            prompt_prefix = f"(This is {speaker} speaking): " if speaker != "Unknown" else ""
            inbound_text = f"{prompt_prefix}{text}"
            logger.info(f"Inbound from {client_id} ({speaker}): {text}")
            
            # Update device display
            if ws and self.config.show_debug_on_display:
                display_text = f"[{speaker}]: {text}" if speaker != "Unknown" else text
                await ws.send(json.dumps({"type": "stt", "text": display_text}))
            
            await self.bus.publish_inbound(InboundMessage(channel=self.name, sender_id=client_id, chat_id=client_id, content=inbound_text, metadata={"is_voice": True, "session_id": state["session_id"]}))
        except Exception as e:
            logger.error(f"Process error: {e}")
            await send_tts_stop()
        finally:
            Path(temp_wav_path).unlink(missing_ok=True)
