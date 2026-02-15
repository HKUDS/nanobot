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
    Handles meta commands like /model, /session, /help, /status.
    
    Uses argparse for robust command parsing with subcommands support.
    CommandHandler does NOT directly operate on sessions.
    Instead, it interacts with SessionManager and ChannelManager.
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

        # /session command
        session_parser = subparsers.add_parser(
            'session', 
            help='💬 Session Management',
            description='Manage conversation sessions'
        )
        session_parser.add_argument(
            'action', 
            nargs='?', 
            default='info', 
            help='info | list | consolidate | <session_id>'
        )
        
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
    
    async def process(self, msg, user_key, provider, model: str, memory_window: int = 50) -> str:
        """
        Process a command and return response.
        
        Args:
            msg: The inbound message
            user_key: The current user
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
        args = cmd_parts[1] if len(cmd_parts) > 1 else ""
        cmd_line = f"{command} {args}".strip()
        logger.info(f"Processing command: /{cmd_line}")
        session = self.sessions.get_or_create(user_key)
        try:
            # Parse command
            parsed_args = self.parser.parse_args(cmd_line.split())
            
            # Dispatch to handler
            if parsed_args.command == 'reset':
                return await self.handle_reset(session)
            elif parsed_args.command == 'session':
                return await self.handle_session(parsed_args, user_key,provider, model, memory_window)
            elif parsed_args.command == 'new':
                return await self.handle_new(user_key)
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
    
    async def handle_new(self,user_key) -> str:
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
        session = self.sessions.create_new_session(user_key)
        return (
            f"🆕 **New Session Created**\n\n"
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
       
    async def handle_session(self, args: argparse.Namespace, user_key: str,provider, model, memory_window) -> str:
        """Handle session commands: info, list, consolidate, or switch to <id>."""
        action = args.action
        
        if action == 'list':
            return self._handle_session_list(user_key)
        elif action == 'info' or action is None:
            return self._handle_session_info(user_key)
        elif action == 'consolidate':
            return await self._handle_session_consolidate(user_key,provider, model, memory_window)
        else:
            # Treat as session ID to switch to
            return self._handle_session_switch(user_key,action)
    
    def _handle_session_list(self,user_key) -> str:
        """List all sessions in markdown format."""
        sessions = self.sessions.list_sessions()
        
        if not sessions:
            return "📋 No sessions found"
        
        # Build markdown list
        lines = ["📋 **Available Sessions:**", ""]
        
        for i, session in enumerate(sessions[:20], 1):  # Show top 20
            logger.debug(session)
            key = session.get('key', 'unknown')
            updated = session.get('updated_at', 'unknown')
            msg_count = session.get("message_count", 0)
            
            # Mark current session
            current_session_id = self.sessions.session_table.get(user_key)
            is_current = "⭐ " if key == current_session_id else ""
            
            lines.append(f"{i}. {is_current}`{key}` - {msg_count} messages (updated: {updated})")
        
        # Add summary if there are more sessions
        if len(sessions) > 20:
            lines.append("")
            lines.append(f"... and {len(sessions) - 20} more sessions")
        
        lines.append("")
        lines.append("💡 Use `/session <session_id>` to switch to a specific session")
        
        return "\n".join(lines)
    
    def _handle_session_info(self, user_key: str) -> str:
        """Show current session info."""
        info = self.sessions.get_session_info(user_key)
        
        
        lines = [
            f"💬 **Session Info**",
            f"\nSession id: `{info['session_id']}`",
            f"\nKey: `{info['user_key']}`",
            f"\nMessages: {info['message_count']}",
            f"\nCreated: {info['created_at']}",
            f"\nUpdated: {info['updated_at']}",
        ]
        return "\n".join(lines)
    
    def _handle_session_switch(self, user_key: str, session_id: str) -> str:
        """Switch to another session."""
        # Note: In current architecture, session switching is handled by channel/client
        # This is more of an informational command
        results = self.sessions.switch_session(user_key, session_id)
        if results is True:
            return (
                f"✅ **Session Switched**\n\n"
                f"Now using session: `{session_id}`"
            )
        else:
            return f"❌ Session `{session_id}` not found. Use `/session list` to see available sessions."
    
    async def _handle_session_consolidate(self, user_key: str,provider, model, memory_window) -> str:
        """Consolidate current session's memory."""
        session = self.sessions.get_or_create(user_key)
        
        if not session.messages:
            return "ℹ️ No messages to consolidate in current session."
        
        message_count = len(session.messages)
        
        try:
            consolidate,response = await self.sessions.consolidate_memory(session,provider, model, archive_all=False,memory_window=memory_window)
            if consolidate:
                self.sessions.save(session)
            return f"{response}"
        except Exception as e:
            logger.error(f"Consolidation failed: {e}")
            return f"❌ Failed to consolidate memory: {str(e)}"
    
   
    
    def handle_help(self) -> str:
        """
        Handle /help command - show available commands.
        
        Returns:
            Help text with all available commands
        """
        lines = ["# 🤖 nanobot Commands", ""]
        # Custom examples for specific commands (no verbose descriptions)
        custom_examples = {
            'session': [
                "/session                  # show current session info",
                "/session list             # list all sessions",
                "/session consolidate      # compress memory",
                "/session <session_id>     # switch to session",
            ],
            'reset': [
                "/reset                    # clear all messages",
            ],
            'new': [
                "/new                      # create new session",
            ],
            'help': [
                "/help                     # show this help",
            ],
        }
        
        # Get all subparsers
        subparsers_actions = [
            action for action in self.parser._actions 
            if isinstance(action, argparse._SubParsersAction)
        ]
        
        if subparsers_actions:
            for subparsers_action in subparsers_actions:
                for choice, subparser in subparsers_action.choices.items():
                    # Get help text from the subparsers_action, not from subparser
                    help_text = subparsers_action.choices[choice].description or choice
                    
                    # Format command with description
                    lines.append(f"### `/{choice}`")
                    lines.append(f"> {help_text}")
                    lines.append("")
                    
                    # Use custom examples if available
                    if choice in custom_examples:
                        lines.append("```")
                        for example in custom_examples[choice]:
                            lines.append(example)
                        lines.append("```")
                        lines.append("")
                    else:
                        # Add argument details for other commands
                        args_help = []
                        for action in subparser._actions:
                            if action.dest not in ['help', 'command']:
                                if action.dest == 'action' and action.help:
                                    args_help.append(action.help)
                                elif action.option_strings:
                                    opt_str = '/'.join(action.option_strings)
                                    args_help.append(f"`{opt_str}` - {action.help}")
                                elif action.help:
                                    dest_display = f"<{action.dest}>"
                                    if action.nargs in ['+', '*']:
                                        dest_display = f"<{action.dest}...>"
                                    args_help.append(f"`{dest_display}` - {action.help}")
                        
                        if args_help:
                            for help_item in args_help:
                                lines.append(help_item)
                            lines.append("")
                        
                        # Add example if available
                        if hasattr(subparser, 'epilog') and subparser.epilog:
                            lines.append(f"**{subparser.epilog}**")
                            lines.append("")
        
        # Add tips
        lines.extend([
            "---",
            "",
            "## 💡 Tips",
            "",
            "- All commands must start with `/`",
            "- Model changes only affect the current session",
            "- Each session can use a different model independently",
        ])
        
        return "\n".join(lines)
    
