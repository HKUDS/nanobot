import json
import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("XiaoZhi Hub")

# URL нашего шлюза (через Docker DNS)
GATEWAY_URL = "http://voice_gateway:18792"

@mcp.tool()
async def list_xiaozhi_devices() -> str:
    """List all connected XiaoZhi/ESP32 devices and their current states."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{GATEWAY_URL}/api/devices")
            return json.dumps(resp.json(), indent=2, ensure_ascii=False)
    except Exception as e:
        return f'{{"error": "Cannot connect to Voice Gateway: {e}"}}'

@mcp.tool()
async def get_voice_context(session_id: str) -> str:
    """Get the latest voice transcription for a specific session."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{GATEWAY_URL}/api/devices")
            devices = resp.json()
            for d in devices:
                if d["session_id"] == session_id:
                    return json.dumps({"last_query": d["last_text"], "status": d["status"]}, indent=2, ensure_ascii=False)
        return json.dumps({"error": "Session not found"}, ensure_ascii=False)
    except Exception as e:
        return f'{{"error": "{e}"}}'

@mcp.tool()
async def call_xiaozhi_tool(session_id: str, tool_name: str, arguments: str) -> str:
    """Call a tool (e.g. self.audio_speaker.set_volume) on a specific connected XiaoZhi device."""
    try:
        args_dict = json.loads(arguments) if arguments else {}
    except ValueError:
        return '{"error": "arguments must be a valid JSON string"}'
        
    payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": args_dict
        },
        "id": 1 # ID будет перезаписан шлюзом
    }
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(f"{GATEWAY_URL}/mcp/{session_id}", json=payload)
            return json.dumps(resp.json(), indent=2, ensure_ascii=False)
    except Exception as e:
        return f'{{"error": "{e}"}}'

@mcp.tool()
async def send_tts_alert(session_id: str, text: str) -> str:
    """Send a TTS voice alert to a connected XiaoZhi/ESP32 device. Use session_id="latest" for the most recently connected device."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{GATEWAY_URL}/api/tts",
                json={"session_id": session_id, "text": text},
            )
            return json.dumps(resp.json(), indent=2, ensure_ascii=False)
    except Exception as e:
        return f'{{"error": "TTS delivery failed: {e}"}}'


if __name__ == "__main__":
    mcp.run(transport='stdio')
