"""Command handler for meta commands."""

import argparse
import sys
from io import StringIO
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from nanobot.session.manager import SessionManager
    from nanobot.channels.manager import ChannelManager


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
            channels: The ChannelManager instance (optional, for session switching)
        """
        self.sessions = sessions
        # self.channels = channels
        self._setup_parsers()
    
    def _setup_parsers(self):
        """Setup argparse parsers for all commands."""
        # Main parser
        self.parser = CommandArgumentParser(
            prog='/',
            description='nanobot commands'
        )
        subparsers = self.parser.add_subparsers(dest='command', help='Available commands')
        #
        
        # /model command
        model_parser = subparsers.add_parser(
            'model', 
            help='📦 Model Management',
            description='Show or switch AI model'
        )
        model_parser.add_argument(
            'action', 
            nargs='?', 
            help='list | <model_name>'
        )
        
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
        reset_parser = subparsers.add_parser(
            'reset', 
            help='🔄 Reset Session',
            description='Clear all messages in current session'
        )
        
        # /new command
        subparsers.add_parser(
            'new', 
            help='🆕 Create New Session',
            description='Create a new conversation session'
        )
        
        # /revoke command
        revoke_parser = subparsers.add_parser(
            'revoke',
            help='🚫 Revoke Permissions',
            description='Revoke granted permissions'
        )
        revoke_parser.add_argument(
            'permissions',
            nargs='+',
            help='Permissions to revoke'
        )
        revoke_parser.add_argument(
            '--mode',
            choices=['persistent', 'all'],
            default='all',
            help='persistent or all (default: all)'
        )
        
        # /permissions command
        subparsers.add_parser(
            'permissions',
            help='🔑 View Permissions',
            description='View granted permissions and pending requests'
        )
        
        # /help command
        subparsers.add_parser(
            'help', 
            help='❓ Help',
            description='Show available commands and usage'
        )
    
    async def process(self, msg, session_key) -> str:
        """
        Process a command and return response.
        
        Args:
            command: Command name (without '/')
            args: Command arguments
        
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
        user_key = session_key
        try:
            # Parse command
            parsed_args = self.parser.parse_args(cmd_line.split())
            
            # Dispatch to handler
            if parsed_args.command == 'model':
                return await self.handle_model(parsed_args, user_key)
            elif parsed_args.command == 'session':
                return await self.handle_session(parsed_args, user_key)
            elif parsed_args.command == 'reset':
                return await self.handle_reset(parsed_args, user_key)
            elif parsed_args.command == 'new':
                return await self.handle_new(user_key)
            elif parsed_args.command == 'revoke':
                return await self.handle_revoke(parsed_args, user_key)
            elif parsed_args.command == 'permissions':
                return await self.handle_permissions(user_key)
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
    
    async def handle_model(self, args: argparse.Namespace, user_key: str) -> str:
        if args.action is None:
            # Show current model
            model = self.sessions.get_session_model(user_key)
            session = self.sessions.get_or_create(user_key)
            is_custom = session.config.model is not None
            
            if is_custom:
                return f"📦 Current model: {model} (session-specific)"
            else:
                return f"📦 Current model: {model} (using agent default)"
        elif args.action == 'list':
            # List available models
            models = self.sessions.models
            if not models:
                return "📋 No models available"
            if user_key.startswith("tui:"):
                options = []
                for model in models:
                    options.append({
                        "label": model,
                        "value": model
                    })
                return {
                    "type": "select",
                    "message": "📋 Select a model:",
                    "action": "model",
                    "options": options
                }

            model_list = "\n".join(f"  • {model}" for model in models)
            return f"📋 **Available Models:**\n{model_list}"
        else:
            # Switch model
            model = args.action
            self.sessions.set_session_model(user_key, model)
            return f"✅ Model switched to: {model}\n💡 This change only affects the current session"
    
    async def handle_session(self, args: argparse.Namespace, user_key: str) -> str:
        """Handle session commands: info, list, consolidate, or switch to <id>."""
        action = args.action
        
        if action == 'list':
            return self._handle_session_list(user_key)
        elif action == 'info' or action is None:
            return self._handle_session_info(user_key)
        elif action == 'consolidate':
            return await self._handle_session_consolidate(user_key)
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
            print(session)
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
        
        model_display = info["model"]
        if info["is_custom_model"]:
            model_display += " (session-specific)"
        else:
            model_display += " (using agent default)"
        
        lines = [
            f"💬 **Session Info**",
            f"\nSession id: `{info['session_id']}`",
            f"\nKey: `{info['user_key']}`",
            f"\nMessages: {info['message_count']}",
            f"\nCreated: {info['created_at']}",
            f"\nUpdated: {info['updated_at']}",
            f"\n",
            f"\n**Configuration:**",
            f"\nModel: {model_display}",
        ]
        
        # Add permissions info
        permissions = info.get("permissions", {})
        persistent_perms = permissions.get("persistent", [])
        one_time_perms = permissions.get("one_time", {})
        
        if persistent_perms or one_time_perms:
            lines.append("")
            lines.append("**Granted Permissions:**")
            
            if persistent_perms:
                perms_str = ", ".join(f"`{p}`" for p in sorted(persistent_perms))
                lines.append(f"Persistent: {perms_str}")
            else:
                lines.append("Persistent: none")
            
            if one_time_perms:
                lines.append(f"One-time: {len(one_time_perms)} command(s)")
            else:
                lines.append("One-time: none")
        
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
    
    async def _handle_session_consolidate(self, user_key: str) -> str:
        """Consolidate current session's memory."""
        session = self.sessions.get_or_create(user_key)
        
        if not session.messages:
            return "ℹ️ No messages to consolidate in current session."
        
        message_count = len(session.messages)
        
        try:
            await self.sessions.consolidate_memory(session, archive_all=False)
            self.sessions.save(session)
            
            new_count = len(session.messages)
            saved = message_count - new_count
            
            return (
                f"✅ **Memory Consolidated**\n\n"
                f"Messages before: {message_count}\n"
                f"Messages after: {new_count}\n"
                f"Compressed: {saved} messages into memory\n\n"
                f"💡 Old messages have been summarized and stored in memory."
            )
        except Exception as e:
            logger.error(f"Consolidation failed: {e}")
            return f"❌ Failed to consolidate memory: {str(e)}"
    async def handle_new(self, user_key: str) -> str:
        """
        Handle /new command - create a new session.
        
        Returns:
            Response message
        """
        # Create new session with memory consolidation
        # Consolidate old session if requested and available
        old_session = self.sessions.get_or_create(user_key)
        old_session_id = self.sessions.session_table.get(user_key)
        logger.info(f"Consolidating old session {old_session_id}")
        await self.sessions.consolidate_memory(old_session, archive_all=True)
        self.sessions.save(old_session)
        new_session = self.sessions.create_new_session(user_key)
        return (
            f"🆕 **New Session Created**\n\n"
            f"🐈 Memory from previous session has been consolidated.\n"
            f"New session key: `{new_session.key}`"
        )
    async def handle_reset(self, args: argparse.Namespace, user_key: str) -> str:
        """
        Handle /reset command - reset current session.
        
        Args:
            args: Parsed arguments
        
        Returns:
            Response message
        """
        # if not args.confirm:
        #     return (
        #         "⚠️ **Reset Session**\n\n"
        #         "This will clear all messages in the current session.\n"
        #         "Configuration (model) will be preserved.\n\n"
        #         "To confirm, use: `/reset --confirm`"
        #     )
        
        # Clear session messages
        session = self.sessions.get_or_create(user_key)
        session.clear()
        self.sessions.save(session)
        
        return "✅ Session reset! All messages cleared. Configuration preserved."
    
    async def handle_revoke(self, args: argparse.Namespace, user_key: str) -> str:
        """
        Handle /revoke command - revoke previously granted permissions.
        
        Args:
            args: Parsed arguments containing permissions and mode
            user_key: The user's session key
        
        Returns:
            Response message
        """
        permissions = set(args.permissions)
        mode = args.mode
        
        # Get the session
        session = self.sessions.get_or_create(user_key)
        
        # Check if any of these permissions are currently granted
        current_persistent = session.granted_permissions.get('persistent', set())
        
        if mode == 'persistent':
            to_revoke = permissions & current_persistent
            if not to_revoke:
                return (
                    f"ℹ️ No matching persistent permissions found.\n\n"
                    f"Requested to revoke: {', '.join(f'`{p}`' for p in sorted(permissions))}\n"
                    f"Current persistent: {', '.join(f'`{p}`' for p in sorted(current_persistent)) if current_persistent else 'none'}"
                )
        else:
            to_revoke = permissions
        
        # Revoke the permissions
        try:
            session.revoke_permission(to_revoke, mode=mode)
            
            # Save the session
            self.sessions.save(session)
            
            perms_str = ', '.join(f'`{p}`' for p in sorted(to_revoke))
            
            return (
                f"🚫 **Permissions Revoked**\n\n"
                f"Revoked: {perms_str}\n"
                f"Mode: **{mode}**\n\n"
                f"💡 These permissions have been removed from the session."
            )
        except Exception as e:
            logger.error(f"Failed to revoke permissions: {e}")
            return f"❌ Failed to revoke permissions: {str(e)}"
    
    async def handle_permissions(self, user_key: str) -> str:
        """
        Handle /permissions command - show current permissions status.
        
        Args:
            user_key: The user's session key
        
        Returns:
            Permissions status message
        """
        session = self.sessions.get_or_create(user_key)
        
        lines = ["# 🔑 Permission Status", ""]
        
        # Persistent permissions
        persistent_perms = session.granted_permissions.get('persistent', set())
        if persistent_perms:
            lines.append("## 🔓 Granted Persistent Permissions")
            lines.append("")
            for perm in sorted(persistent_perms):
                lines.append(f"- `{perm}`")
            lines.append("")
        else:
            lines.append("## 🔓 Granted Persistent Permissions")
            lines.append("")
            lines.append("_None_")
            lines.append("")
        
        # One-time permissions
        one_time_perms = session.granted_permissions.get('one_time', {})
        if one_time_perms:
            lines.append("## ⏱️ Granted One-Time Permissions")
            lines.append("")
            for cmd_hash, perms in one_time_perms.items():
                perms_str = ', '.join(f'`{p}`' for p in sorted(perms))
                lines.append(f"- Command `{cmd_hash[:8]}...`: {perms_str}")
            lines.append("")
        
        # Usage tips
        lines.extend([
            "---",
            "",
            "## 💡 Quick Actions",
            "",
            "- Revoke permissions: `/revoke net file_write`",
            "- View help: `/help`",
        ])
        
        return "\n".join(lines)
    
    def handle_help(self) -> str:
        """
        Handle /help command - show available commands.
        Dynamically generates help text from argparse definitions.
        
        Returns:
            Help text with all available commands
        """
        lines = ["# 🤖 nanobot Commands", ""]
        
        # Custom examples for specific commands (no verbose descriptions)
        custom_examples = {
            'model': [
                "/model                    # show current model",
                "/model list               # list available models",
                "/model <model_name>       # switch model",
            ],
            'session': [
                "/session                  # show current session info",
                "/session list             # list all sessions",
                "/session consolidate      # compress memory",
                "/session <session_id>     # switch to session",
            ],
            'revoke': [
                "/revoke net file_write    # revoke permissions",
                "/revoke net --mode all",
            ],
            'permissions': [
                "/permissions              # view permission status",
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
    
