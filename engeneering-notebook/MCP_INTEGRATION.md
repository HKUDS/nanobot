# Discord Role Mentions - MCP Integration Guide

## Overview
This document outlines how the Discord role mentions feature integrates with the Model Context Protocol (MCP) for your auto coder bot swarm, enabling configurable Discord mention handling through MCP tools.

## Integration Architecture

### Current State
- Discord channel with role mention support (`feature/discord-role-mentions`)
- Configurable via `config.json` per bot instance
- Author type restrictions to prevent bot loops

### MCP Enhancement Opportunity
The Discord mention detection logic can be exposed as an MCP tool for:
1. Dynamic configuration of mention behavior
2. Runtime role mention updates
3. Cross-bot coordination
4. Swarm-wide mention policies

## MCP Tool: Discord Mention Configuration

### Tool Definition
```python
# Proposed MCP tool for discord_mention_config

tool_name: "discord_mention_config"
tool_description: "Configure Discord mention behavior and role detection for bot swarms"

parameters:
  - name: "action"
    type: "string"
    enum: ["get", "set", "add_role", "remove_role", "enable_role_mentions", "disable_role_mentions"]
    description: "Configuration action to perform"
    
  - name: "respond_to_role_mentions"
    type: "boolean"
    description: "Enable/disable role mention responses"
    
  - name: "bot_role_ids"
    type: "array[string]"
    description: "List of Discord role IDs to respond to"
    
  - name: "respond_to_bot_id_ping"
    type: "boolean"
    description: "Respond to explicit bot ID pings"
    
  - name: "respond_to_non_bot_ping"
    type: "boolean"
    description: "Respond to pings from non-bot users"
    
  - name: "respond_to_self_bot_ping"
    type: "boolean"
    description: "Respond to pings from other bots (for swarm coordination)"
```

### Tool Implementation Example

```python
# nanobot/agent/tools/discord_mention_config.py

from typing import Any, Literal
from nanobot.agent.tools.base import BaseTool
from nanobot.channels.discord import DiscordChannel

class DiscordMentionConfigTool(BaseTool):
    """MCP tool for configuring Discord mention behavior."""
    
    name = "discord_mention_config"
    description = "Configure Discord mention detection and role responses"
    
    def execute(
        self,
        action: Literal["get", "set", "add_role", "remove_role"],
        respond_to_role_mentions: bool | None = None,
        bot_role_ids: list[str] | None = None,
        respond_to_bot_id_ping: bool | None = None,
        respond_to_non_bot_ping: bool | None = None,
        respond_to_self_bot_ping: bool | None = None,
    ) -> dict[str, Any]:
        """
        Configure Discord mention behavior.
        
        Args:
            action: Configuration action (get, set, add_role, remove_role)
            respond_to_role_mentions: Enable role mentions
            bot_role_ids: List of role IDs to respond to
            respond_to_bot_id_ping: Respond to bot ID pings
            respond_to_non_bot_ping: Respond to non-bot pings
            respond_to_self_bot_ping: Respond to bot-to-bot pings
            
        Returns:
            Current configuration state and action result
        """
        discord_channel = self._get_discord_channel()
        
        if action == "get":
            return {
                "status": "success",
                "config": {
                    "respond_to_role_mentions": discord_channel.config.respond_to_role_mentions,
                    "bot_role_ids": discord_channel.config.bot_role_ids,
                    "respond_to_bot_id_ping": discord_channel.config.respond_to_bot_id_ping,
                    "respond_to_non_bot_ping": discord_channel.config.respond_to_non_bot_ping,
                    "respond_to_self_bot_ping": discord_channel.config.respond_to_self_bot_ping,
                }
            }
            
        elif action == "set":
            if respond_to_role_mentions is not None:
                discord_channel.config.respond_to_role_mentions = respond_to_role_mentions
            if bot_role_ids is not None:
                discord_channel.config.bot_role_ids = bot_role_ids
            if respond_to_bot_id_ping is not None:
                discord_channel.config.respond_to_bot_id_ping = respond_to_bot_id_ping
            if respond_to_non_bot_ping is not None:
                discord_channel.config.respond_to_non_bot_ping = respond_to_non_bot_ping
            if respond_to_self_bot_ping is not None:
                discord_channel.config.respond_to_self_bot_ping = respond_to_self_bot_ping
                
            return {
                "status": "success",
                "message": "Discord mention configuration updated",
                "config": self._get_config_dict(discord_channel)
            }
            
        elif action == "add_role":
            if bot_role_ids and bot_role_ids[0] not in discord_channel.config.bot_role_ids:
                discord_channel.config.bot_role_ids.append(bot_role_ids[0])
                
            return {
                "status": "success",
                "message": f"Role {bot_role_ids[0]} added to mention responses",
                "bot_role_ids": discord_channel.config.bot_role_ids
            }
            
        elif action == "remove_role":
            if bot_role_ids and bot_role_ids[0] in discord_channel.config.bot_role_ids:
                discord_channel.config.bot_role_ids.remove(bot_role_ids[0])
                
            return {
                "status": "success",
                "message": f"Role {bot_role_ids[0]} removed from mention responses",
                "bot_role_ids": discord_channel.config.bot_role_ids
            }
            
        return {"status": "error", "message": f"Unknown action: {action}"}
    
    def _get_discord_channel(self) -> DiscordChannel:
        """Get the Discord channel instance."""
        from nanobot.channels.manager import ChannelManager
        manager = ChannelManager.get_instance()
        return manager.get_channel("discord")
    
    def _get_config_dict(self, channel: DiscordChannel) -> dict[str, Any]:
        """Get configuration as dictionary."""
        return {
            "respond_to_role_mentions": channel.config.respond_to_role_mentions,
            "bot_role_ids": channel.config.bot_role_ids,
            "respond_to_bot_id_ping": channel.config.respond_to_bot_id_ping,
            "respond_to_non_bot_ping": channel.config.respond_to_non_bot_ping,
            "respond_to_self_bot_ping": channel.config.respond_to_self_bot_ping,
        }
```

## Bot Swarm Use Cases

### Use Case 1: Dynamic Role Assignment
```python
# Auto coder bot identifies new team roles and adds them dynamically

@agent_skill
async def update_discord_roles(self, new_role_ids: list[str]) -> str:
    """Update bot's responsive Discord roles."""
    result = await self.tools.call("discord_mention_config", {
        "action": "set",
        "bot_role_ids": new_role_ids,
        "respond_to_role_mentions": True
    })
    return f"Updated roles: {result['bot_role_ids']}"
```

### Use Case 2: Swarm Coordination
```python
# Coordinator bot enables bot-to-bot mentions for swarm tasks

@agent_skill
async def enable_swarm_coordination(self) -> str:
    """Enable bot-to-bot communication for coordinated tasks."""
    result = await self.tools.call("discord_mention_config", {
        "action": "set",
        "respond_to_self_bot_ping": True,
        "respond_to_bot_id_ping": True
    })
    return "Swarm coordination enabled"
```

### Use Case 3: Role-Based Command Routing
```python
# Route commands to specialized bots based on mention roles

@agent_skill
async def route_to_specialist(self, role_name: str, task: str) -> str:
    """Route task to specialist bot via role mention."""
    # Get role ID for specialist
    role_id = await self.get_discord_role_id(role_name)
    
    # Add role to mention config if not present
    config = await self.tools.call("discord_mention_config", {"action": "get"})
    if role_id not in config['config']['bot_role_ids']:
        await self.tools.call("discord_mention_config", {
            "action": "add_role",
            "bot_role_ids": [role_id]
        })
    
    # Mention the role in Discord
    await self.discord_mention_role(role_id, task)
    return f"Routed to {role_name}: {task}"
```

### Use Case 4: Selective Human-Only Mode
```python
# Restrict bot to only respond to human users (no bot-to-bot)

@agent_skill
async def restrict_to_humans(self) -> str:
    """Set bot to only respond to human pings."""
    result = await self.tools.call("discord_mention_config", {
        "action": "set",
        "respond_to_non_bot_ping": True,
        "respond_to_self_bot_ping": False,
        "respond_to_bot_id_ping": True
    })
    return "Bot now responds only to human users"
```

## Configuration Templates

### Template 1: Autonomous Coder Bot
```json
{
  "channels": {
    "discord": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "respond_to_role_mentions": true,
      "bot_role_ids": ["coder_role_id", "dev_team_role_id"],
      "respond_to_bot_id_ping": true,
      "respond_to_non_bot_ping": true,
      "respond_to_self_bot_ping": true,
      "comment": "Autonomous coder accepts all mentions for swarm coordination"
    }
  }
}
```

### Template 2: Human-Supervised Bot
```json
{
  "channels": {
    "discord": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "respond_to_role_mentions": true,
      "bot_role_ids": ["support_role_id"],
      "respond_to_bot_id_ping": true,
      "respond_to_non_bot_ping": true,
      "respond_to_self_bot_ping": false,
      "comment": "Supervised bot only accepts human commands, no bot interference"
    }
  }
}
```

### Template 3: Coordinator Bot
```json
{
  "channels": {
    "discord": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "respond_to_role_mentions": true,
      "bot_role_ids": ["coordinator_role_id", "task_dispatcher_role_id"],
      "respond_to_bot_id_ping": true,
      "respond_to_non_bot_ping": true,
      "respond_to_self_bot_ping": true,
      "comment": "Coordinator enables full bot-to-bot communication for orchestration"
    }
  }
}
```

## Integration Roadmap

### Phase 1: Merge Feature Branch
- [ ] Merge `feature/discord-role-mentions` to `main`
- [ ] Create stable release with role mention support
- [ ] Update documentation in main repo

### Phase 2: MCP Tool Implementation
- [ ] Create `discord_mention_config` MCP tool
- [ ] Add to MCP registry
- [ ] Document tool schema
- [ ] Add integration tests

### Phase 3: Swarm Coordination
- [ ] Implement bot-to-bot coordination patterns
- [ ] Create swarm skill set for role-based routing
- [ ] Add coordinator bot template
- [ ] Publish examples

### Phase 4: Auto Coder Integration
- [ ] Integrate with auto coder bot framework
- [ ] Add dynamic role detection
- [ ] Enable runtime configuration via MCP
- [ ] Create specialized coder templates

## MCP Tool Registration

### Register in Tool Registry
```python
# nanobot/agent/tools/registry.py

from nanobot.agent.tools.discord_mention_config import DiscordMentionConfigTool

# Add to registry
TOOLS_REGISTRY = {
    # ... existing tools ...
    "discord_mention_config": DiscordMentionConfigTool,
}
```

### MCP Schema
```json
{
  "tools": [
    {
      "name": "discord_mention_config",
      "description": "Configure Discord mention detection and role responses for bot swarms",
      "inputSchema": {
        "type": "object",
        "properties": {
          "action": {
            "type": "string",
            "enum": ["get", "set", "add_role", "remove_role"],
            "description": "Configuration action"
          },
          "respond_to_role_mentions": {
            "type": "boolean",
            "description": "Enable role mention responses"
          },
          "bot_role_ids": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Discord role IDs to respond to"
          },
          "respond_to_bot_id_ping": {
            "type": "boolean",
            "description": "Respond to bot ID pings"
          },
          "respond_to_non_bot_ping": {
            "type": "boolean",
            "description": "Respond to non-bot user pings"
          },
          "respond_to_self_bot_ping": {
            "type": "boolean",
            "description": "Respond to bot-to-bot pings"
          }
        },
        "required": ["action"]
      }
    }
  ]
}
```

## Deployment to Open Source

### For Main Repository
This feature is designed to be:
1. **Modular** - Works independently or with MCP
2. **Optional** - Existing configs work unchanged
3. **Safe** - Default settings prevent unwanted loops
4. **Extensible** - Ready for MCP integration
5. **Well-documented** - Clear configuration examples

### Key Advantages for Community
- ✅ Role-based bot automation
- ✅ Prevent bot-to-bot loops by default
- ✅ Fine-grained control over mention behavior
- ✅ Foundation for swarm coordination
- ✅ Backward compatible

## Documentation for Merge Request

Include in PR description:

> This feature enables advanced Discord mention handling with role-based responses and author type restrictions. It's designed as a foundation for bot swarms and multi-bot coordination scenarios, with optional MCP tool integration for runtime configuration.
>
> The feature includes:
> - Configurable role mention support
> - Author type filtering (human, bot, self-bot)
> - Prevention of bot-to-bot loops (secure by default)
> - MCP tool ready (can be implemented as needed)
> - Full backward compatibility

---

**Purpose**: Discord role mentions feature for nanobot with MCP integration for auto coder bot swarm
**Status**: Ready for merge to main open source repository
**MCP Ready**: Yes - tool implementation provided
**Target**: Auto coder bot swarm coordination

