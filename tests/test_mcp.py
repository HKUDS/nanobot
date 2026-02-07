
import asyncio
import os
import sys

# Add project root to path
sys.path.append(os.getcwd())

from nanobot.agent.tools.mcp import MCPManager
from nanobot.config.schema import MCPToolConfig

async def test_mcp_load():
    print("Initializing MCP Manager...")
    manager = MCPManager()
    
    # Config matching the one in config.json for 'math'
    config = {
        # "stdio_time": MCPToolConfig(
        #     command="/home/sheng/uv_project/mcphub_p/.venv/bin/python",
        #     args=["/home/sheng/uv_project/mcphub_p/mcp_server/python/stdio_time/server.py"],
        #     transport="stdio"
        # ),
        "http_email": MCPToolConfig(
            url="http://172.20.77.183:3000/mcp/python_stdio_email",
            transport="http"
        )
    }
    
    try:
        print("Loading tools...")
        tools = await manager.load_tools(config)
        print(f"Loaded {len(tools)} tools")
        
        for tool in tools:
            print(f"Tool: {tool.name}")
            print(f"Description: {tool.description}")
            print(f"Parameters: {tool.parameters}")
            
            # Try to execute if it's a simple tool (optional)
            # The 'math' server seems to be 'stdio_time', so maybe it has 'get_time' or similar?
            if "time" in tool.name.lower():
                 print("Executing tool...")
                 result = await tool.execute()
                 print(f"Result: {result}")
                 
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("Cleaning up...")
        await manager.cleanup()

if __name__ == "__main__":
    asyncio.run(test_mcp_load())
