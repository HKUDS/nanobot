# Discord Role Mentions Feature - Pull Request

## Overview
This pull request implements configurable role mention support for the Discord channel with granular control over ping behavior and author type restrictions.

## Branch
- **Branch Name**: `feature/discord-role-mentions`
- **Base Branch**: `main`

## Changes

### 1. Configuration Schema (`nanobot/config/schema.py`)
Added new configuration options to `DiscordConfig`:

```python
respond_to_role_mentions: bool = False
    # Enable the bot to respond when its role is mentioned
    
bot_role_ids: list[str] = Field(default_factory=list)
    # List of role IDs that should trigger bot responses
    # Example: ["1234567890", "9876543210"]
    
respond_to_bot_id_ping: bool = True
    # Respond when bot is explicitly pinged by ID (default: enabled)
    
respond_to_non_bot_ping: bool = True
    # Respond to pings from non-bot users (default: enabled)
    
respond_to_self_bot_ping: bool = False
    # Respond when pinged by other bots (default: disabled to prevent loops)
```

### 2. Discord Channel Implementation (`nanobot/channels/discord.py`)
Enhanced the `_is_ping_for_bot` method to support:

- **Role Mention Detection**: Bot responds when a configured role is mentioned via `@role_name` or `<@&ROLE_ID>` format
- **Author Type Restrictions**: Control which types of users can ping the bot:
  - Non-bot users (normal Discord users)
  - Bot users (other bots)
  - Self-bot users (the bot's own messages, for self-reply scenarios)
- **Hierarchical Ping Detection**:
  1. `@everyone` always triggers (unchanged)
  2. Role mentions (if `respond_to_role_mentions` is True)
  3. Explicit bot ID pings (if `respond_to_bot_id_ping` is True)
  4. Author type validation applied to all

## Configuration Examples

### Example 1: Basic Role Mentions
```json
{
  "channels": {
    "discord": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "respond_to_role_mentions": true,
      "bot_role_ids": ["1234567890"]
    }
  }
}
```

### Example 2: Respond Only to Non-Bot Users
```json
{
  "channels": {
    "discord": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "respond_to_non_bot_ping": true,
      "respond_to_self_bot_ping": false,
      "respond_to_role_mentions": true,
      "bot_role_ids": ["1234567890", "9876543210"]
    }
  }
}
```

### Example 3: Accept Bot-to-Bot Interactions
```json
{
  "channels": {
    "discord": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "respond_to_self_bot_ping": true,
      "respond_to_role_mentions": true,
      "bot_role_ids": ["1234567890"]
    }
  }
}
```

## Behavior

### Ping Detection Logic
The bot responds to a ping if ALL of the following conditions are met:

1. **Author Type Check**: Sender passes author type restrictions
   - If sender is a bot and `respond_to_self_bot_ping` is False → Ignore
   - If sender is not a bot and `respond_to_non_bot_ping` is False → Ignore

2. **Ping Check**: Message contains one of:
   - `@everyone` (always triggers if author passes)
   - Role mention via `@role_name` or `<@&ROLE_ID>` (if `respond_to_role_mentions` is True AND role is in `bot_role_ids`)
   - Bot ID ping via `@bot_name` or `<@BOT_ID>` (if `respond_to_bot_id_ping` is True)

### Example Scenarios

| Scenario | Author | Ping Type | respond_to_role_mentions | bot_role_ids | respond_to_self_bot_ping | respond_to_non_bot_ping | Result |
|----------|--------|-----------|--------------------------|--------------|--------------------------|-------------------------|--------|
| User pings bot role | Human | @myrole | true | ["123"] | - | true | ✅ Respond |
| Bot pings bot role | Bot | @myrole | true | ["123"] | false | - | ❌ Ignore |
| Bot pings bot role | Bot | @myrole | true | ["123"] | true | - | ✅ Respond |
| User pings bot ID | Human | @bot | true | ["123"] | - | true | ✅ Respond |
| User pings bot ID | Human | @bot | true | ["123"] | - | false | ❌ Ignore |
| Bot pings bot ID | Bot | @bot | true | ["123"] | false | - | ❌ Ignore |

## Default Behavior
With default configuration:
- `respond_to_role_mentions`: false (disabled)
- `bot_role_ids`: [] (empty)
- `respond_to_bot_id_ping`: true (enabled)
- `respond_to_non_bot_ping`: true (enabled)
- `respond_to_self_bot_ping`: false (disabled)

**Result**: Bot responds only to non-bot users who explicitly ping the bot ID, preventing bot-to-bot loops while maintaining normal user interaction.

## Benefits

1. **Prevention of Bot Loops**: Default settings prevent bots from endlessly pinging each other
2. **Flexible Ping Control**: Users can customize exactly which types of mentions trigger responses
3. **Role-Based Automation**: Enables role-based command structures (e.g., ping @support role)
4. **Per-Type Restrictions**: Independent control over non-bot and bot user interactions
5. **Backward Compatible**: Default behavior preserves existing functionality

## Testing

The changes have been tested for:
- ✅ Role mention detection (text and mention format)
- ✅ Bot ID mention detection
- ✅ Author type filtering
- ✅ Configuration parsing with defaults
- ✅ Mention content parsing (`<@USER_ID>`, `<@&ROLE_ID>`, `<@!USER_ID>`)

## Related Issues
- Discord channel enhancement for better control over bot behavior
- Prevention of bot-to-bot interaction loops
- Role-based automation support

## PR Link
https://github.com/Duo-Keyboard-Koalition/nanobot/pull/new/feature/discord-role-mentions

---

**Created**: March 5, 2026
**Feature Branch**: `feature/discord-role-mentions`
**Base Branch**: `main`

 nee