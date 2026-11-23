from nanobot.agent.tools import mcp


async def discover_into(servers, registry, *, network=None, oauth_handlers=None):
    """Expose one server's discovery result to registry-based assertions."""
    (name, config), = servers.items()
    connection = await mcp.connect_mcp_server(
        name, config, network=network, oauth_handler=(oauth_handlers or {}).get(name),
    )
    if connection is None:
        return {}
    for tool in connection.tools:
        registry.register(tool)
    return {name: connection}
