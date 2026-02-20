"""Command handler for meta commands."""

import argparse
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from nanobot.session.manager import SessionManager


class CommandArgumentParser(argparse.ArgumentParser):
    """Custom ArgumentParser that doesn't exit on error."""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, add_help=False, **kwargs)
        self.error_message = None
    
    def error(self, message):
        """Override error to capture message instead of exiting."""
        self.error_message = message
        raise argparse.ArgumentError(None, message)
    
    def format_help(self):
        """Format help message."""
        return super().format_help()


class CommandHandler:
    """
    Handles meta commands: /new, /reset, /help.
    
    Uses argparse for robust command parsing with subcommands support.
    """
    
    def __init__(self, sessions: "SessionManager"):
        """
        Initialize the command handler.
        
        Args:
            sessions: The SessionManager instance to interact with
        """
        self.sessions = sessions
        self._setup_parsers()
    
    def _setup_parsers(self):
        """Setup argparse parsers for all commands."""
        # Main parser
        self.parser = CommandArgumentParser(
            prog='/',
            description='nanobot commands'
        )
        subparsers = self.parser.add_subparsers(dest='command', help='Available commands')
        
        # /reset command
        subparsers.add_parser(
            'reset', 
            help='🔄 Reset Session',
            description='Clear all messages in current session (preserves configuration)'
        )
        
        # /new command
        subparsers.add_parser(
            'new', 
            help='🆕 Create New Session',
            description='Create a new conversation session'
        )
        
        # /help command
        subparsers.add_parser(
            'help', 
            help='❓ Help',
            description='Show available commands and usage'
        )
    
    async def process(self, msg, session, provider, model: str, memory_window: int = 50) -> str:
        """
        Process a command and return response.
        
        Args:
            msg: The inbound message
            session: The current session
            provider: LLM provider for memory consolidation
            model: Model name for consolidation
            memory_window: Memory window size for consolidation
        
        Returns:
            Response string to send back to user
        """
        # Build command line
        cmd_content = msg.content.strip()[1:]  # Remove leading '/'
        cmd_parts = cmd_content.split(maxsplit=1)
        command = cmd_parts[0]
        cmd_line = f"{command}".strip()
        logger.info(f"Processing command: /{cmd_line}")
        try:
            # Parse command
            parsed_args = self.parser.parse_args(cmd_line.split())
            
            # Dispatch to handler
            if parsed_args.command == 'reset':
                return await self.handle_reset(session)
            elif parsed_args.command == 'new':
                return await self.handle_new(session, provider, model, memory_window)
            elif parsed_args.command == 'help':
                return self.handle_help()
            else:
                return self.handle_help()
                
        except (argparse.ArgumentError, SystemExit) as e:
            # Parse error - show help for that command
            if hasattr(self.parser, 'error_message') and self.parser.error_message:
                return f"❌ Error: {self.parser.error_message}\n\n{self.handle_help()}"
            return f"❌ Invalid command syntax\n\n{self.handle_help()}"
        except Exception as e:
            logger.error(f"Command processing error: {e}")
            return f"❌ Error processing command: {str(e)}\n\nType /help for usage"
    
    async def handle_new(self, session, provider, model: str, memory_window: int = 50) -> str:
        """
        Handle /new command - create a new session.
        
        Args:
            session: The current session
            provider: LLM provider for memory consolidation
            model: Model name for consolidation
            memory_window: Memory window size for consolidation
        
        Returns:
            Response message
        """
        await self.sessions.create_new_session(
            session=session,
            provider=provider,
            model=model,
            memory_window=memory_window
        )
        return (
            f"🆕 **New Session Created**\n\n"
            f"🐈 Memory from previous session has been consolidated.\n"
            f"Session key: `{session.key}`"
        )
    
    async def handle_reset(self, session) -> str:
        """
        Handle /reset command - reset current session.
        
        Args:
            session: The current session
        
        Returns:
            Response message
        """
        # Clear session messages
        session.clear()
        self.sessions.save(session)
        
        return "✅ Session reset! All messages cleared. Configuration preserved."
    
    def handle_help(self) -> str:
        """
        Handle /help command - show available commands.
        
        Returns:
            Help text with all available commands
        """
        lines = [
            "🤖 **Available Commands**",
            "",
            "**New Session**",
            "• `/new` - Create a new conversation session",
            "",
            "**Reset Session**",
            "• `/reset` - Clear all messages in current session",
            "",
            "**Help**",
            "• `/help` - Show this help message",
        ]
        
        return "\n".join(lines)
    
