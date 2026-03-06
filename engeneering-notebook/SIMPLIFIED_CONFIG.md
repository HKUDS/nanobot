# Discord Role Mentions - Simplified Configuration

## ✅ Configuration Simplified to Single Option: `allowBots`

Based on your requirements, the Discord role mentions feature has been streamlined to a **single, intuitive configuration option**.

---

## 🎯 Configuration Design

### The Simple Rule:
- **Humans**: ✅ Always can ping this bot (no configuration needed)
- **Other Bots**: ⚙️ Can ping only if `allowBots` is explicitly enabled

When `allowBots=True`, bots have the **same level of agency as humans**.

---

## 📋 Discord Configuration Schema

### DiscordConfig Class
```python
class DiscordConfig(Base):
    # ... existing fields ...
    
    # Role mentions (optional, separate from bot pinging)
    respond_to_role_mentions: bool = False  # Enable role pinging
    bot_role_ids: list[str] = []            # Which roles trigger bot
    
    # Bot pinging control (your new single option)
    allow_bots: bool = False                # Allow other bots to ping
```

---

## 🔧 Configuration Examples

### Example 1: Default (Humans Only)
```json
{
  "channels": {
    "discord": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN"
      // allowBots defaults to false - only humans can ping
    }
  }
}
```

### Example 2: Allow Bot-to-Bot Communication
```json
{
  "channels": {
    "discord": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "allowBots": true  // Other bots can ping this bot
    }
  }
}
```

### Example 3: With Role Mentions
```json
{
  "channels": {
    "discord": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "allowBots": true,
      "respond_to_role_mentions": true,
      "bot_role_ids": ["coder_role_id", "validator_role_id"]
    }
  }
}
```

---

## 🎯 Implementation Logic

### `_is_ping_for_bot()` Method Flow

```
Message received
    ↓
Is author a bot?
    ├─ YES: Is allowBots enabled?
    │   ├─ NO  → Don't respond (return False)
    │   └─ YES → Continue (bots have same agency as humans)
    │
    └─ NO (human): Always continue (humans always can ping)
    
    ↓
Check ping type:
    ├─ @everyone → Respond ✅
    ├─ @bot_id   → Respond ✅
    └─ @role     → Respond if respond_to_role_mentions enabled
```

---

## ✨ Benefits

✅ **Simple**: One boolean flag for bot pinging  
✅ **Intuitive**: Clear that humans always work, bots optional  
✅ **Safe Default**: `allowBots=False` prevents unintended bot loops  
✅ **Flexible**: Enable when you need bot-to-bot coordination  
✅ **Clean**: No complex multi-flag configuration  

---

## 🤖 Use Cases

### Single Bot (Default)
```json
{"allowBots": false}
```
- Responds to humans
- Ignores other bots
- Perfect for user-facing bots

### Bot Swarm Coordination
```json
{"allowBots": true}
```
- Coordinator bot can mention specialist bots
- Specialist bots can coordinate with each other
- Full bot-to-bot agency enabled

### Hybrid Mode (Recommended)
```json
{
  "allowBots": true,
  "respond_to_role_mentions": true,
  "bot_role_ids": ["coordinator_role_id"]
}
```
- Humans can ping directly
- Coordinator bot can ping via role mention
- Other bots can ping directly (if allowBots=true)

---

## 📊 Configuration Comparison

| Option | Before | After |
|--------|--------|-------|
| Config options | 5 | 1 |
| Complexity | High | Low |
| Human pinging | Configurable | Always enabled |
| Bot pinging | Complex logic | Single flag |
| Role mentions | Mixed in | Separate |
| Default safety | Moderate | High |

---

## 🔐 Security & Defaults

### Default Configuration (`allowBots: false`)
- ✅ Humans can ping bot
- ❌ Other bots cannot ping bot
- ✅ Prevents bot-to-bot loops
- ✅ Safe by default

### When Enabled (`allowBots: true`)
- ✅ Humans can ping bot
- ✅ Other bots can ping bot (same agency)
- ⚠️ Enables bot-to-bot communication
- ⚠️ Requires careful coordination

---

## 🎯 For Your Auto Coder Bot Swarm

### Coordinator Bot Configuration
```json
{
  "channels": {
    "discord": {
      "enabled": true,
      "token": "COORDINATOR_BOT_TOKEN",
      "allowBots": true,
      "respond_to_role_mentions": true,
      "bot_role_ids": ["coder_bots", "validator_bots"]
    }
  }
}
```

### Specialist Bot Configuration
```json
{
  "channels": {
    "discord": {
      "enabled": true,
      "token": "CODER_BOT_TOKEN",
      "allowBots": true,
      "respond_to_role_mentions": true,
      "bot_role_ids": ["task_queue"]
    }
  }
}
```

### Result
- Coordinator can mention specialist bots
- Specialist bots can coordinate with each other
- All bots can respond to humans
- Full agency enabled for bot-to-bot orchestration

---

## ✅ Files Modified

### `nanobot/config/schema.py` (Lines 60-75)
- Removed 4 old configuration options
- Added single `allow_bots: bool = False`
- Kept `respond_to_role_mentions` and `bot_role_ids` for role-based triggering

### `nanobot/channels/discord.py` (Lines 299-351)
- Simplified `_is_ping_for_bot()` method
- Clear logic: Bot author check first, then ping detection
- Comments explain behavior clearly

---

## 🚀 Migration from Previous Config

If you had:
```json
{
  "respond_to_bot_id_ping": true,
  "respond_to_non_bot_ping": true,
  "respond_to_self_bot_ping": false
}
```

It maps to:
```json
{
  "allowBots": false  // Bots cannot ping
}
```

If you had:
```json
{
  "respond_to_bot_id_ping": true,
  "respond_to_non_bot_ping": true,
  "respond_to_self_bot_ping": true
}
```

It maps to:
```json
{
  "allowBots": true   // Bots can ping (same agency as humans)
}
```

---

## 📝 Code Example

### How It Works
```python
def _is_ping_for_bot(self, payload: dict[str, Any]) -> bool:
    author = payload.get("author") or {}
    is_bot_author = bool(author.get("bot"))

    # KEY LOGIC: If bot author and allowBots is False, don't respond
    if is_bot_author and not self.config.allow_bots:
        return False
    
    # Humans always proceed, bots proceed if allowBots is True
    # ... rest of ping detection logic ...
```

---

## 🎯 Summary

**What**: Single `allowBots` configuration option  
**Default**: `False` (safe, humans only)  
**When Enabled**: Bots have same agency as humans  
**Role Mentions**: Separate control via `respond_to_role_mentions`  
**Best For**: Auto coder bot swarms, multi-bot coordination  

---

**Status**: ✅ Implemented and pushed to feature/discord-role-mentions  
**Simplification**: Reduced from 5 options to 1 core option  
**Clarity**: Much more intuitive configuration

