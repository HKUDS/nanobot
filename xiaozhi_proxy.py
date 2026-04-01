import asyncio
import json
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("XiaoZhi Hub")

async def send_to_voice_server(request: dict) -> dict:
    try:
        reader, writer = await asyncio.open_unix_connection("/tmp/xiaozhi_proxy.sock")
        writer.write(json.dumps(request).encode("utf-8") + b"\n")
        await writer.drain()
        
        response_data = await reader.readline()
        writer.close()
        await writer.wait_closed()
        
        if not response_data:
            return {"error": "No response from VoiceServerChannel"}
        return json.loads(response_data.decode("utf-8"))
    except Exception as e:
        return {"error": f"Socket error: {str(e)}"}

@mcp.tool()
async def list_xiaozhi_devices() -> str:
    """List all connected XiaoZhi/ESP32 devices and their available tools."""
    res = await send_to_voice_server({"action": "list_devices"})
    return json.dumps(res, indent=2, ensure_ascii=False)

@mcp.tool()
async def call_xiaozhi_tool(mac: str, tool_name: str, arguments: str) -> str:
    """
    Call a tool on a specific connected XiaoZhi device.
    
    mac: MAC address or ID of the device.
    tool_name: The name of the tool to call.
    arguments: A JSON string containing the arguments.
    """
    try:
        args_dict = json.loads(arguments) if arguments else {}
    except ValueError:
        return "Error: arguments must be a valid JSON string."
        
    res = await send_to_voice_server({
        "action": "call_tool",
        "mac": mac,
        "tool_name": tool_name,
        "arguments": args_dict
    })
    return json.dumps(res, indent=2, ensure_ascii=False)

if __name__ == "__main__":
    mcp.run(transport='stdio')
