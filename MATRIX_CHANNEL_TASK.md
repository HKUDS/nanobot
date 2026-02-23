# Task: Matrix Channel Integration for nanobot

## Goal
Implement a Matrix protocol channel for nanobot (https://github.com/HKUDS/nanobot),
analogous to the existing Telegram/Discord/Slack channels.
The bot should connect to a self-hosted Matrix homeserver (Tuwunel/Conduwuit-compatible)
and support both direct messages and room-based communication.

## Reference Architecture
Study these existing channel implementations FIRST before writing any code:
- nanobot/channels/telegram.py  (polling-based reference)
- nanobot/channels/slack.py     (WebSocket/async reference, closest match)
- nanobot/channels/discord.py   (bot token + room policy reference)
- nanobot/config/schema.py      (how channels register their config)
- nanobot/bus/                  (message bus interface to implement)

## Dependencies to Add
Add to pyproject.toml / setup.py:
  matrix-nio[e2e]>=0.21.0

## Files to Create/Modify

### 1. CREATE: nanobot/channels/matrix.py

Implement a MatrixChannel class that:
- Uses `matrix-nio` AsyncClient for async Matrix communication
- Connects to a configurable homeserver URL (e.g. https://matrix.example.com)
- Authenticates via access_token (preferred) OR password login
- Runs a sync_forever() loop in an async task
- Handles RoomMessageText events
- Implements allowFrom filtering by Matrix user ID (@user:server)
- Implements roomPolicy (same pattern as Slack's groupPolicy):
    - "mention": only respond when @mentioned in rooms (default)
    - "open": respond to all room messages
    - "dm": only respond to direct messages
- Sends replies via room_send() with msgtype m.text
- Handles long messages by splitting (same as Discord implementation)
- Auto-joins rooms when invited (m.room.member invite event)
- Implements optional E2EE support (matrix-nio[e2e])
- Stores sync token persistently to avoid replaying old messages on restart
  (use ~/.nanobot/matrix_sync_token file)

### 2. MODIFY: nanobot/config/schema.py

Add MatrixConfig class:
```python
class MatrixConfig(BaseModel):
    enabled: bool = False
    homeserver: str = ""          # e.g. "https://matrix.example.com"
    user_id: str = ""             # e.g. "@nanobot:example.com"
    access_token: str = ""        # preferred auth method
    password: str = ""            # fallback auth method
    device_id: str = ""           # optional, for E2EE
    allowFrom: list[str] = []     # e.g. ["@alice:example.com"]
    roomPolicy: str = "mention"   # "mention" | "open" | "dm"
    allowRooms: list[str] = []    # room IDs to whitelist (empty = all)
    e2ee: bool = False            # enable end-to-end encryption

