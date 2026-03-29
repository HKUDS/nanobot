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
from nanobot.channels.registry import register_channel

from pydantic import BaseModel

class VoiceServerConfig(BaseModel):
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
    force_ota: bool = False
    firmware_path: str = "/root/.nanobot/firmware.bin"


class WhisperTranscriber:
    """Inline implementation of Whisper STT provider to avoid missing dependencies."""
    def __init__(self, api_base, model=None, api_key=None):
        self.api_base = api_base
        self.model = model or "whisper-large-v3"
        self.api_key = api_key

    async def transcribe(self, file_path):
        import httpx
        try:
            async with httpx.AsyncClient() as client:
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
                        files=files,
                        timeout=60.0
                    )
                    response.raise_for_status()
                    data = response.json()
                    return data.get("text", "")
        except Exception as e:
            logger.error(f"Whisper transcription error: {e}")
            return ""

# Since opuslib might not be installed in all environments
try:
    import opuslib
except ImportError:
    opuslib = None


@register_channel("voice_server")
class VoiceServerChannel(BaseChannel):
    """
    WebSocket server for voice-enabled devices.

    
    Supports:
    - Audio streaming from device (STT)
    - Audio streaming to device (TTS)
    - JSON control messages
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

        # MCP Proxy states
        self.mcp_server = None
        self.mcp_requests: dict[int, asyncio.Future] = {}
        self._mcp_req_id = 0

        # Initialize transcriber
        self.transcriber = WhisperTranscriber(
            api_base=config.transcription_api_base,
            model=config.transcription_model,
            api_key=config.token
        )

    async def start(self) -> None:
        """Start the WebSocket server."""
        self._running = True
        self._stop_future = asyncio.Future()

        # Start local Unix socket for MCP proxy
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
        
        # Keep running until stop() is called
        try:
            await self._stop_future
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()

    async def stop(self) -> None:
        """Stop the server and close all connections."""
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
        """Send an outbound message to the device."""
        client_id = message.chat_id
        ws = self.clients.get(client_id)
        
        if not ws:
            logger.warning(f"Client {client_id} not connected, cannot send message")
            return

        # If it's voice content, we usually handle it differently (TTS)
        # For now, let's just send JSON if it's text
        try:
            # Check if there is audio in metadata (from TTS tool)
            audio_url = message.metadata.get("audio_url")
            mcp_payload = message.metadata.get("mcp")
            direct_json = message.metadata.get("json")
            
            if direct_json:
                await ws.send(json.dumps(direct_json))
            elif mcp_payload:
                await ws.send(json.dumps({
                    "type": "mcp",
                    "payload": mcp_payload
                }))
            elif audio_url:
                await ws.send(json.dumps({
                    "type": "tts",
                    "state": "start",
                    "url": audio_url,
                    "session_id": message.metadata.get("session_id", "default")
                }))
            else:
                # Binary OPUS stream generator fallback using edge_tts + ffmpeg
                try:
                    import edge_tts
                    import subprocess
                    import asyncio
                    import opuslib
                    
                    state = self.audio_states[client_id]
                    if "encoder" not in state:
                        # Create Opus encoder for 16kHz 1-channel VoIP
                        state["encoder"] = opuslib.Encoder(16000, 1, opuslib.APPLICATION_VOIP)
                    encoder = state["encoder"]
                    
                    safe_id = "".join([c for c in client_id if c.isalnum()])
                    file_path = f"/tmp/tts_{safe_id}.mp3"
                    
                    communicate = edge_tts.Communicate(message.content, "ru-RU-SvetlanaNeural")
                    await communicate.save(file_path)
                    
                    # Send TTS START over WebSocket
                    await ws.send(json.dumps({"type": "tts", "state": "start"}))
                    
                    # Convert MP3 to Raw PCM 16kHz 16-bit Mono using ffmpeg
                    cmd = [
                        'ffmpeg', '-i', file_path, 
                        '-f', 's16le', '-acodec', 'pcm_s16le', 
                        '-ar', '16000', '-ac', '1', 'pipe:1'
                    ]
                    process = await asyncio.create_subprocess_exec(
                        *cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
                    )
                    
                    # 60ms frame of 16kHz 16-bit Mono is 1920 bytes (960 samples)
                    chunk_size = 1920 
                    while True:
                        pcm_chunk = await process.stdout.read(chunk_size)
                        if not pcm_chunk:
                            break
                        if len(pcm_chunk) < chunk_size:
                            pcm_chunk = pcm_chunk.ljust(chunk_size, b'\x00')
                            
                        # Encode into Opus
                        opus_frame = encoder.encode(pcm_chunk, 960)
                        # Send as binary frame
                        await ws.send(opus_frame)
                        # Yield duration of are frame (60ms) to stream in real-time
                        await asyncio.sleep(0.06)
                        
                    await process.wait()
                    
                    # Send TTS STOP over WebSocket with dynamic listening flag
                    listening_flag = "?" in message.content
                    await ws.send(json.dumps({
                        "type": "tts", 
                        "state": "stop",
                        "listening": listening_flag
                    }))
                    logger.info(f"Streamed auto-tts Opus bytes to {client_id} (listening={listening_flag})")
                    
                except Exception as tts_err:
                    logger.error(f"Auto-TTS Opus error for {client_id}: {tts_err}")
                    await ws.send(json.dumps({
                        "type": "text",
                        "content": message.content
                    }))
        except Exception as e:
            logger.error(f"Failed to send to {client_id}: {e}")

    async def _handle_mcp_socket(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """Handler for internal MCP proxy requests via unix socket."""
        try:
            data = await reader.readline()
            if not data:
                return
            
            req = json.loads(data.decode("utf-8"))
            action = req.get("action")
            
            if action == "list_devices":
                # Wait for all devices to return their tools (list_tools takes time we don't have statically)
                # But since MCP tools are dynamic per device, we can just return connected macs
                # and assume they all share similar tools, or we fetch dynamically.
                # Since we don't cache tools, let's just return MACs.
                devices = []
                for mac in list(self.clients.keys()):
                    if mac.startswith("pending_") or mac.startswith("unknown_"):
                        continue
                    devices.append({"mac": mac})
                response = {"status": "ok", "devices": devices, "note": "Use 'call_xiaozhi_tool' with these MACs."}
                writer.write(json.dumps(response).encode("utf-8") + b"\n")
                await writer.drain()
                
            elif action == "call_tool":
                mac = req.get("mac")
                ws = self.clients.get(mac)
                if not ws:
                    response = {"error": f"Device {mac} not connected."}
                    writer.write(json.dumps(response).encode("utf-8") + b"\n")
                    await writer.drain()
                    return
                
                # Send JSON-RPC tools/call to device
                self._mcp_req_id += 1
                req_id = self._mcp_req_id
                fut = asyncio.Future()
                self.mcp_requests[req_id] = fut
                
                mcp_payload = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "method": "tools/call",
                    "params": {
                        "name": req.get("tool_name"),
                        "arguments": req.get("arguments", {})
                    }
                }
                await ws.send(json.dumps({"type": "mcp", "payload": mcp_payload}))
                
                # Wait for response
                try:
                    result = await asyncio.wait_for(fut, timeout=10.0)
                    if "result" in result:
                        response = result["result"]
                    elif "error" in result:
                        response = {"error": result["error"]}
                    else:
                        response = {"error": "Invalid response"}
                except asyncio.TimeoutError:
                    response = {"error": "Timeout waiting for device response"}
                finally:
                    self.mcp_requests.pop(req_id, None)
                    
                writer.write(json.dumps(response).encode("utf-8") + b"\n")
                await writer.drain()
                
        except Exception as e:
            logger.error(f"MCP Proxy handler error: {e}")
            writer.write(json.dumps({"error": str(e)}).encode("utf-8") + b"\n")
        finally:
            writer.close()
            await writer.wait_closed()

    def _init_client_state(self, client_id: str):
        if opuslib is None:
            logger.error("opuslib not installed, voice features will not work!")
            return

        self.audio_states[client_id] = {
            "is_listening": False,
            "pcm_buffer": bytearray(),
            "decoder": opuslib.Decoder(16000, 1),
            "session_id": "default"
        }

    async def _process_request(self, connection, request):
        """
        Interceptors HTTP requests to serve OTA info and other files.
        XiaoZhi devices hit this endpoint before connecting via WebSocket.
        """
        try:
            from websockets.http11 import Response
            from websockets.datastructures import Headers
            
            # Use getattr for robustness across websockets versions
            path = getattr(request, 'path', getattr(request, 'uri', 'unknown'))
            method = getattr(request, 'method', 'GET')
            
            # Get remote address safely
            peer = "unknown"
            if connection:
                if hasattr(connection, 'remote_address'):
                    peer = connection.remote_address[0]
                elif hasattr(connection, 'transport'):
                    peername = connection.transport.get_extra_info('peername')
                    if peername:
                        peer = peername[0]
            
            logger.info(f"HTTP Request: {method} {path} from {peer}")
            
            parsed_url = urlparse(path)
            clean_path = parsed_url.path
            params = parse_qs(parsed_url.query)
            
            # Extract device-id from headers or query params
            device_id = request.headers.get("Device-Id") or params.get("device-id", [None])[0]
            if not device_id:
                device_id = "unknown"

            if clean_path == "/ota":
                # XiaoZhi firmware checks this path for updates and configuration
                import time
                local_ip = self.config.local_ip or "0.0.0.0"
                
                ota_info = {
                    "server_time": {
                        "timestamp": int(time.time() * 1000),
                        "timezone_offset": 180 # UTC+3
                    },
                    "firmware": {
                        "version": "4.1.0",
                        "url": f"http://{local_ip}:{self.config.port}/xiaozhi.bin",
                        "md5": "00000000000000000000000000000000"
                    },
                    "websocket": {
                        "url": f"ws://{local_ip}:{self.config.port}",
                        "token": self.config.token,
                        "version": 3
                    }
                }
                
                logger.info(f"  Serving OTA info for {device_id} to {peer}")
                
                body = json.dumps(ota_info, ensure_ascii=False) + "\n"
                data = body.encode("utf-8")
                
                headers = Headers([
                    ("Content-Type", "application/json"),
                    ("Content-Length", str(len(data))),
                    ("Connection", "close")
                ])
                return Response(200, "OK", headers, data)
                
            if clean_path.startswith("/tts/"):
                file_name = clean_path.split("/")[-1]
                safe_id = file_name.split(".")[0]
                file_path = Path(f"/tmp/tts_{safe_id}.mp3")
                if file_path.exists():
                    logger.info(f"Serving auto-tts file: {file_path}")
                    data = file_path.read_bytes()
                    headers = Headers([
                        ("Content-Type", "audio/mpeg"),
                        ("Content-Length", str(len(data))),
                        ("Connection", "close")
                    ])
                    return Response(200, "OK", headers, data)
                else:
                    logger.error(f"TTS file NOT FOUND: {file_path}")
                    return Response(404, "Not Found", Headers([("Connection", "close")]), b"Not Found")

            if clean_path == "/xiaozhi.bin":
                firmware_path = Path(self.config.firmware_path)
                if firmware_path.exists():
                    logger.info(f"  Serving firmware file: {firmware_path}")
                    data = firmware_path.read_bytes()
                    headers = Headers([
                        ("Content-Type", "application/octet-stream"),
                        ("Content-Length", str(len(data))),
                        ("Connection", "close")
                    ])
                    return Response(200, "OK", headers, data)
                else:
                    logger.error(f"  Firmware file NOT FOUND: {firmware_path}")
                    return Response(404, "Not Found", Headers([("Connection", "close")]), b"Not Found")

            if clean_path == "" or clean_path == "/":
                headers = Headers([
                    ("Content-Type", "text/plain"),
                    ("Connection", "close")
                ])
                return Response(200, "OK", headers, b"XiaoZhi Voice Server (Nanobot)")

            # For everything else, proceed to WebSocket handshake
            return None
            
        except Exception as e:
            logger.exception(f"Error in _process_request: {e}")
            from websockets.http11 import Response
            from websockets.datastructures import Headers
            return Response(500, "Internal Server Error", Headers([("Connection", "close")]), str(e).encode())

    async def _handle_client(self, websocket: Any):
        """Handle individual WebSocket client connection."""
        client_id = "pending_" + str(id(websocket))
        self.clients[client_id] = websocket
        self._init_client_state(client_id)
        logger.info(f"--- ENTERED _handle_client for {client_id} (Total: {len(self.clients)}) ---")
        
        try:
            # Device waits for server to send "type": "hello" first
            await websocket.send(json.dumps({
                "type": "hello",
                "version": 3,
                "transport": "websocket",
                "audio_params": {
                    "format": "opus",
                    "sample_rate": 24000,
                    "channels": 1,
                    "frame_duration": 60
                }
            }))
            logger.info(f"Sent early hello to {client_id}")

            async for message in websocket:
                if isinstance(message, str):
                    # JSON control message
                    try:
                        data = json.loads(message)
                        msg_type = data.get("type")
                        logger.debug(f"Received msg from {client_id}: {data}")
                        
                        if data.get("type") == "hello":
                            # Try to get MAC from JSON, then from headers (Device-Id), then default
                            client_id = data.get("mac")
                            if not client_id:
                                # In websockets 13.0+ ServerConnection has 'request'
                                try:
                                    client_id = websocket.request.headers.get("Device-Id")
                                except AttributeError:
                                    pass
                            
                            if not client_id:
                                client_id = "unknown_mac_" + str(id(websocket))
                                
                            if client_id in self.clients:
                                logger.warning(f"Client {client_id} reconnected. Closing previous connection.")
                                try:
                                    await self.clients[client_id].close()
                                except Exception:
                                    pass
                                    
                            self.clients[client_id] = websocket
                            self._init_client_state(client_id)
                            logger.info(f"Client {client_id} connected (Version: {data.get('version')})")
                            
                            # Optional OTA Trigger
                            if self.config.force_ota:
                                logger.info(f"Triggering OTA upgrade for client: {client_id}")
                                try:
                                    local_ip = self.config.local_ip or "0.0.0.0"
                                    await websocket.send(json.dumps({
                                        "type": "mcp",
                                        "payload": {
                                            "jsonrpc": "2.0",
                                            "id": 999,
                                            "method": "tools/call",
                                            "params": {
                                                "name": "self.upgrade_firmware",
                                                "arguments": {
                                                    "url": f"http://{local_ip}:{self.config.port}/xiaozhi.bin"
                                                }
                                            }
                                        }
                                    }))
                                    logger.info(f"OTA Trigger sent successfully to {client_id}")
                                except Exception as e:
                                    logger.error(f"Failed to send forced OTA trigger to {client_id}: {e}")

                            # Reply with hello
                            await websocket.send(json.dumps({
                                "type": "hello",
                                "version": 3,
                                "transport": "websocket",
                                "audio_params": {
                                    "format": "opus",
                                    "sample_rate": 16000,
                                    "channels": 1,
                                    "frame_duration": 60
                                }
                            }))
                            
                        elif msg_type == "listen":
                            if client_id not in self.audio_states:
                                self._init_client_state(client_id)
                                
                            state = data.get("state")
                            if state == "start":
                                self.audio_states[client_id]["is_listening"] = True
                                self.audio_states[client_id]["pcm_buffer"] = bytearray()
                                self.audio_states[client_id]["silent_frames"] = 0
                                self.audio_states[client_id]["session_id"] = data.get("session_id", "default")
                                logger.info(f"Client {client_id} STARTED listening (session: {self.audio_states[client_id]['session_id']})")
                            elif state == "stop":
                                self.audio_states[client_id]["is_listening"] = False
                                pcm_len = len(self.audio_states[client_id]['pcm_buffer'])
                                logger.info(f"Client {client_id} sent STOP listening. Buffered {pcm_len} bytes ({pcm_len/32000:.2f}s)")
                                
                                if pcm_len == 0:
                                    logger.warning(f"Client {client_id} sent STOP but no audio was buffered. Ignoring.")
                                    return

                                # Process the audio!
                                await self._process_audio_buffer(client_id)
                                
                        elif msg_type == "mcp":
                            payload = data.get("payload", {})
                            logger.info(f"Received MCP packet from {client_id}: {payload}")
                            req_id = payload.get("id")
                            if req_id is not None and req_id in self.mcp_requests:
                                if not self.mcp_requests[req_id].done():
                                    self.mcp_requests[req_id].set_result(payload)
                            else:
                                logger.debug(f"Unhandled MCP packet (no id or unsupported method): {payload}")
                            
                        else:
                            logger.debug(f"JSON from {client_id}: {data}")
                            
                    except json.JSONDecodeError:
                        logger.error(f"Invalid JSON from {client_id}: {message}")
                elif isinstance(message, bytes):
                    # Binary data (OPUS frames from microphone)
                    if client_id in self.audio_states and self.audio_states[client_id]["is_listening"]:
                        try:
                            state = self.audio_states[client_id]
                            # Frame size for 60ms at 16kHz is 960 samples
                            pcm_frame = state["decoder"].decode(message, 960)
                            state["pcm_buffer"].extend(pcm_frame)
                            
                            # VAD/Silence Auto-Stop
                            import audioop
                            rms = audioop.rms(pcm_frame, 2)
                            
                            if "silent_frames" not in state:
                                state["silent_frames"] = 0
                                
                            if rms < 300:  # Threshold for silence, adjust if needed
                                state["silent_frames"] += 1
                            else:
                                state["silent_frames"] = 0
                                
                            # 20 consecutive frames * 60ms = 1.2 seconds of silence
                            # AND ensure we buffered at least 0.5s of audio to avoid instant warm-up crashes
                            if state["silent_frames"] >= 20 and len(state["pcm_buffer"]) >= 16000 * 2 * 0.5:
                                logger.info(f"Silence detected from {client_id} (rms: {rms}). Auto-stopping.")
                                state["is_listening"] = False
                                import asyncio
                                asyncio.create_task(self._process_audio_buffer(client_id))
                            # Auto-stop failsafe fallback after 8 seconds 
                            elif len(state["pcm_buffer"]) >= 16000 * 2 * 8:
                                logger.warning(f"Client {client_id} streamed 8s without stop. Forcing stop.")
                                state["is_listening"] = False
                                # Run processing outside current cycle async
                                import asyncio
                                asyncio.create_task(self._process_audio_buffer(client_id))
                            elif len(state["pcm_buffer"]) % 32000 == 0:
                                logger.info(f"Buffered {len(state['pcm_buffer'])} bytes for {client_id}")
                        except (opuslib.OpusError, AttributeError) as e:
                            logger.error(f"Opus decode error from {client_id}: {e}")
                            
        except Exception as e:
            logger.exception(f"Unexpected error in _handle_client for {client_id}: {e}")
        except websockets.exceptions.ConnectionClosed:
            logger.info(f"Client {client_id} disconnected")
        finally:
            if client_id in self.clients:
                del self.clients[client_id]
            if client_id in self.audio_states:
                del self.audio_states[client_id]

    async def _process_audio_buffer(self, client_id: str):
        state = self.audio_states.get(client_id)
        ws = self.clients.get(client_id)

        async def send_tts_stop():
            if ws and state:
                try:
                    await ws.send(json.dumps({
                        "type": "tts", 
                        "state": "stop", 
                        "listening": False,
                        "session_id": state.get("session_id", "default")
                    }))
                except Exception as e:
                    logger.error(f"Failed to send expected tts.stop to {client_id}: {e}")

        if not state or not state["pcm_buffer"]:
            await send_tts_stop()
            return
            
        pcm_data = bytes(state["pcm_buffer"])
        state["pcm_buffer"].clear()
        
        if len(pcm_data) < 16000 * 2 * 0.5:  # Less than half a second
            logger.warning(f"Audio buffer for {client_id} too short ({len(pcm_data)} bytes), ignoring.")
            await send_tts_stop()
            return

        logger.info(f"Transcribing {len(pcm_data)} bytes for {client_id} using {self.transcriber.__class__.__name__}")
        
        # Save to temp WAV file
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_wav:
            with wave.open(temp_wav.name, 'wb') as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(16000)
                wav_file.writeframes(pcm_data)
                
            temp_wav_path = temp_wav.name
            
        try:
            # Transcribe
            text = await self.transcriber.transcribe(temp_wav_path)
            Path(temp_wav_path).unlink(missing_ok=True)
            
            # Discard Whisper hallucinations for silence
            if text:
                cleaned_text = text.strip().lower().replace(".", "").replace("!", "").replace("?", "").replace("…", "")
                hallucinations = [
                    "продолжение следует", "спасибо за просмотр", 
                    "редактор субтитров", "субтитры", "редактирование",
                    "подписывайтесь на канал", "до новых встреч"
                ]
                if cleaned_text in hallucinations:
                    logger.warning(f"Discarding Whisper hallucination from {client_id}: '{text}'")
                    text = ""
            
            if not text or not text.strip():
                logger.info(f"Transcription empty for {client_id}")
                await send_tts_stop()
                return
                
            logger.info(f"STT: '{text}' from {client_id}")
            
            # Send STT to device display
            if ws and state:
                try:
                    await ws.send(json.dumps({
                        "type": "stt",
                        "text": text
                    }))
                except Exception as e:
                    logger.error(f"Failed to send stt text to display: {e}")
            
            # Send to bus
            msg = InboundMessage(
                channel=self.name,
                sender_id=client_id,
                chat_id=client_id,
                content=text,
                metadata={
                    "is_voice": True,
                    "session_id": state["session_id"]
                }
            )
            await self.bus.publish_inbound(msg)
            
        except Exception as e:
            logger.error(f"Error processing audio for {client_id}: {e}")
            Path(temp_wav_path).unlink(missing_ok=True)
            await send_tts_stop()
