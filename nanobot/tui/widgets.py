"""Custom widgets for the nanobot TUI."""

from textual.widgets import Static, Input
from textual.containers import ScrollableContainer
from textual.message import Message
from textual.reactive import reactive
from datetime import datetime
from typing import Optional
from rich.text import Text


class ChatView(ScrollableContainer):
    """Scrollable chat message display."""
    
    # Store messages for potential export
    messages: reactive[list] = reactive(list)
    
    def __init__(self, id: Optional[str] = None):
        super().__init__(id=id)
        self._message_widgets = []
    
    def add_message(
        self,
        sender: str,
        content: str,
        channel: Optional[str] = None,
        chat_id: Optional[str] = None,
        timestamp: Optional[datetime] = None,
    ) -> None:
        """Add a new message to the chat."""
        ts = timestamp or datetime.now()
        time_str = ts.strftime("%H:%M:%S")
        
        # Format message with Rich
        msg_text = Text()
        msg_text.append(f"[{time_str}] ", style="dim")
        msg_text.append(f"<{sender}> ", style="bold cyan")
        if channel:
            msg_text.append(f"({channel}", style="dim yellow")
            if chat_id:
                msg_text.append(f":{chat_id}", style="dim")
            msg_text.append(") ", style="dim yellow")
        msg_text.append(content)
        
        # Create message widget
        msg_widget = Static(msg_text, classes="message")
        self._message_widgets.append(msg_widget)
        self.mount(msg_widget)
        self.scroll_end(animate=False)
        
        # Store message
        self.messages.append({
            "sender": sender,
            "content": content,
            "channel": channel,
            "chat_id": chat_id,
            "timestamp": ts.isoformat(),
        })
    
    def clear(self) -> None:
        """Clear all messages."""
        for widget in self._message_widgets:
            widget.remove()
        self._message_widgets.clear()
        self.messages = []


class MessageInput(Static):
    """Message input widget with send functionality."""
    
    DEFAULT_CSS = """
    MessageInput {
        layout: horizontal;
        height: 3;
        padding: 1;
    }
    
    MessageInput Input {
        width: 1fr;
    }
    """
    
    class Submitted(Message):
        """Message sent when user submits input."""
        def __init__(self, content: str) -> None:
            super().__init__()
            self.content = content
    
    def compose(self):
        from textual.widgets import Input
        yield Input(placeholder="Type a message...", id="msg-input")
    
    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle input submission."""
        if event.value.strip():
            self.post_message(self.Submitted(event.value))
            event.input.value = ""


class Sidebar(Static):
    """Sidebar showing available chats/channels."""
    
    DEFAULT_CSS = """
    Sidebar {
        width: 25;
        dock: left;
        background: $surface;
        border-right: solid $primary;
    }
    
    .chat-item {
        padding: 1;
    }
    
    .chat-item:hover {
        background: $primary-darken-2;
    }
    
    .chat-item.active {
        background: $primary;
    }
    """
    
    chats: reactive[list] = reactive(list)
    
    def __init__(self, id: Optional[str] = None):
        super().__init__(id=id)
        self._chat_widgets = []
    
    def add_chat(self, name: str, channel: str, chat_id: str, unread: int = 0) -> None:
        """Add a chat to the sidebar."""
        display = f"{'●' if unread else '○'} {name}"
        if unread:
            display += f" ({unread})"
        
        widget = Static(display, classes="chat-item")
        self._chat_widgets.append(widget)
        self.mount(widget)
        
        self.chats.append({
            "name": name,
            "channel": channel,
            "chat_id": chat_id,
            "unread": unread,
        })
    
    def update_unread(self, chat_id: str, count: int) -> None:
        """Update unread count for a chat."""
        for i, chat in enumerate(self.chats):
            if chat["chat_id"] == chat_id:
                chat["unread"] = count
                # Update widget display
                display = f"{'●' if count else '○'} {chat['name']}"
                if count:
                    display += f" ({count})"
                self._chat_widgets[i].update(display)
                break


class StatusBar(Static):
    """Status bar showing connection info."""
    
    DEFAULT_CSS = """
    StatusBar {
        height: 1;
        background: $primary;
        color: $text;
        padding: 0 1;
    }
    """
    
    connected: reactive[bool] = reactive(False)
    gateway_url: reactive[str] = reactive("")
    
    def watch_connected(self, connected: bool) -> None:
        """Update display when connection state changes."""
        self._update_display()
    
    def watch_gateway_url(self, url: str) -> None:
        """Update display when gateway URL changes."""
        self._update_display()
    
    def _update_display(self) -> None:
        """Update the status bar display."""
        status = "🟢 Connected" if self.connected else "🔴 Disconnected"
        url = f" | {self.gateway_url}" if self.gateway_url else ""
        self.update(f"{status}{url}")
