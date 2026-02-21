"""Main TUI application for nanobot gateway."""

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Header, Footer, Static
from textual.reactive import reactive
from textual.message import Message
from datetime import datetime
import asyncio
from typing import Optional

from .widgets import ChatView, MessageInput, Sidebar, StatusBar


class NanobotTUI(App):
    """Terminal UI for nanobot gateway messaging."""
    
    CSS = """
    Screen {
        layout: grid;
        grid-size: 1 3;
        grid-rows: 1fr auto auto;
    }
    
    .main-container {
        layout: horizontal;
    }
    
    Sidebar {
        width: 25;
        dock: left;
    }
    
    ChatView {
        width: 1fr;
    }
    
    StatusBar {
        height: 1;
    }
    
    MessageInput {
        height: 3;
    }
    """
    
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("n", "new_chat", "New Chat"),
        ("r", "refresh", "Refresh"),
    ]
    
    # Reactive state
    current_chat: reactive[str] = reactive("")
    connected: reactive[bool] = reactive(False)
    
    def __init__(self, gateway_url: str = "ws://localhost:8765"):
        super().__init__()
        self.gateway_url = gateway_url
        self._ws = None
        self._receive_task: Optional[asyncio.Task] = None
    
    def compose(self) -> ComposeResult:
        """Create the UI layout."""
        yield Header()
        with Container(classes="main-container"):
            yield Sidebar(id="sidebar")
            yield ChatView(id="chat")
        yield MessageInput(id="input")
        yield StatusBar(id="status")
        yield Footer()
    
    async def on_mount(self) -> None:
        """Connect to gateway when app starts."""
        self.title = "nanobot TUI"
        self.sub_title = f"Gateway: {self.gateway_url}"
        await self.connect_gateway()
    
    async def connect_gateway(self) -> None:
        """Connect to the nanobot gateway."""
        try:
            import websockets
            self._ws = await websockets.connect(self.gateway_url)
            self.connected = True
            self._receive_task = asyncio.create_task(self._receive_messages())
            self.notify("Connected to gateway")
        except Exception as e:
            self.connected = False
            self.notify(f"Connection failed: {e}", severity="error")
    
    async def _receive_messages(self) -> None:
        """Receive messages from gateway."""
        if not self._ws:
            return
        try:
            async for message in self._ws:
                self.handle_gateway_message(message)
        except Exception as e:
            self.connected = False
            self.notify(f"Connection lost: {e}", severity="error")
    
    def handle_gateway_message(self, raw_message: str) -> None:
        """Process incoming gateway message."""
        import json
        try:
            data = json.loads(raw_message)
            msg_type = data.get("type", "message")
            
            if msg_type == "status":
                # Connection status update
                self.notify(f"Connected ({data.get('clients', 1)} clients)")
                return
            
            if msg_type == "error":
                self.notify(f"Error: {data.get('message', 'Unknown error')}", severity="error")
                return
            
            # Regular message
            chat = self.query_one("#chat", ChatView)
            chat.add_message(
                sender=data.get("sender", "unknown"),
                content=data.get("content", raw_message),
                channel=data.get("channel"),
                chat_id=data.get("chat_id"),
            )
        except json.JSONDecodeError:
            chat = self.query_one("#chat", ChatView)
            chat.add_message(sender="gateway", content=raw_message)
    
    async def send_message(self, content: str, channel: str = "telegram", chat_id: str = "") -> None:
        """Send a message through the gateway."""
        if not self._ws or not self.connected:
            self.notify("Not connected to gateway", severity="error")
            return
        
        import json
        message = {
            "type": "message",
            "content": content,
            "channel": channel,
            "chat_id": chat_id,
        }
        await self._ws.send(json.dumps(message))
        
        # Show in chat
        chat = self.query_one("#chat", ChatView)
        chat.add_message(sender="you", content=content)
    
    def on_message_input_submitted(self, event: MessageInput.Submitted) -> None:
        """Handle message submission."""
        asyncio.create_task(self.send_message(event.content))
    
    def action_refresh(self) -> None:
        """Refresh connection."""
        asyncio.create_task(self.connect_gateway())
    
    def action_new_chat(self) -> None:
        """Start a new chat."""
        chat = self.query_one("#chat", ChatView)
        chat.clear()
    
    async def on_unmount(self) -> None:
        """Cleanup on exit."""
        if self._receive_task:
            self._receive_task.cancel()
        if self._ws:
            await self._ws.close()


def run_tui(gateway_url: str = "ws://localhost:8765"):
    """Entry point for running the TUI."""
    app = NanobotTUI(gateway_url=gateway_url)
    app.run()


if __name__ == "__main__":
    import sys
    url = sys.argv[1] if len(sys.argv) > 1 else "ws://localhost:8765"
    run_tui(url)
