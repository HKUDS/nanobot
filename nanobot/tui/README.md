# Nanobot TUI

Terminal User Interface for the nanobot gateway messaging system.

## Features

- 🔄 Real-time message display via WebSocket
- 💬 Multi-channel support (Telegram, Discord, etc.)
- 📋 Chat sidebar with unread indicators
- 📊 Status bar with connection info
- ⌨️ Keyboard-friendly navigation

## Installation

```bash
cd /home/kreijstal/git/nanobot
pip install -e ".[tui]"
```

Or install dependencies manually:
```bash
pip install textual rich websockets
```

## Usage

```bash
# Run with default gateway
nanobot tui

# Connect to specific gateway
nanobot tui ws://localhost:8765

# Or run directly
python -m nanobot.tui ws://localhost:8765
```

## Key Bindings

| Key | Action |
|-----|--------|
| `q` | Quit |
| `n` | New chat (clear current) |
| `r` | Refresh connection |
| `Enter` | Send message |

## Architecture

```
tui/
├── __init__.py    # Package exports
├── app.py         # Main TUI application (NanobotTUI)
├── widgets.py     # Custom widgets
│   ├── ChatView      - Scrollable message list
│   ├── MessageInput  - Input field for messages
│   ├── Sidebar       - Chat/channel list
│   └── StatusBar     - Connection status
└── README.md      # This file
```

## Gateway Protocol

The TUI communicates with the gateway via WebSocket using JSON messages:

### Outgoing (TUI → Gateway)
```json
{
  "content": "Hello!",
  "channel": "telegram",
  "chat_id": "123456789"
}
```

### Incoming (Gateway → TUI)
```json
{
  "sender": "user",
  "content": "Hi there!",
  "channel": "telegram",
  "chat_id": "123456789"
}
```

## Development

Run in development mode:
```bash
textual run --dev nanobot/tui/app.py:NanobotTUI
```

## Dependencies

- **textual** - Modern async TUI framework
- **rich** - Rich text rendering
- **websockets** - WebSocket client
