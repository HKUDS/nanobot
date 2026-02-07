"""
Slash Command Handler for nanobot.

This module provides a clean, extensible system for handling slash commands.
Commands are intercepted BEFORE reaching the AI and executed directly.
"""

from dataclasses import dataclass
from typing import Callable, Any
from loguru import logger


@dataclass
class CommandResult:
    """Result of a command execution."""
    content: str
    success: bool = True


class CommandHandler:
    """
    Handles slash commands (messages starting with '/').
    
    Commands are registered with decorators or directly, and are executed
    without involving the LLM. This keeps system commands fast and deterministic.
    """
    
    def __init__(self):
        self._commands: dict[str, Callable] = {}
        self._register_builtins()
    
    def _register_builtins(self) -> None:
        """Register built-in commands."""
        
        @self.register("help")
        def cmd_help(args: list[str], ctx: dict[str, Any]) -> CommandResult:
            """Show available commands."""
            lines = ["**Available Commands:**"]
            for name, func in sorted(self._commands.items()):
                doc = func.__doc__ or "No description"
                lines.append(f"• `/{name}` - {doc.strip()}")
            return CommandResult("\n".join(lines))
        
        @self.register("model")
        def cmd_model(args: list[str], ctx: dict[str, Any]) -> CommandResult:
            """Show model. Use '/model list' or '/model set <name>'."""
            if not args:
                return CommandResult(f"Current model: `{ctx.get('model', 'unknown')}`\n\n_Use `/model list` or `/model set <name>`_")
            
            subcommand = args[0].lower()
            
            if subcommand == "list":
                # Try to fetch from OpenCode API
                try:
                    import requests
                    resp = requests.get("https://opencode.ai/zen/v1/models", timeout=5)
                    models_data = resp.json()
                    models = [f"opencode/{m['id']}" for m in models_data.get('data', [])]
                except Exception:
                    # Fallback to hardcoded list
                    models = [
                        "opencode/claude-sonnet-4",
                        "opencode/gpt-5.1",
                        "opencode/kimi-k2.5-free",
                        "opencode/gemini-3-flash",
                    ]
                
                lines = [f"**Available Models ({len(models)}):**"]
                current = ctx.get("model", "")
                
                # Group by type for readability
                for m in models[:30]:  # Limit to 30
                    marker = " ✓" if m == current else ""
                    lines.append(f"• `{m}`{marker}")
                
                if len(models) > 30:
                    lines.append(f"_...and {len(models) - 30} more_")
                
                lines.append("\n_Use `/model set <name>` to switch._")
                return CommandResult("\n".join(lines))
            
            if subcommand == "set":
                if len(args) < 2:
                    return CommandResult("Usage: `/model set <model_name>`", success=False)
                
                new_model = args[1]
                set_model = ctx.get("set_model")
                
                if set_model:
                    old_model = ctx.get("model", "unknown")
                    set_model(new_model)
                    return CommandResult(
                        f"✅ Model changed!\n"
                        f"• From: `{old_model}`\n"
                        f"• To: `{new_model}`\n\n"
                        f"_This change applies immediately, no rebuild needed._"
                    )
                return CommandResult("Model setter not available.", success=False)
            
            return CommandResult(f"Unknown subcommand: `{subcommand}`. Use `list` or `set`.", success=False)
        
        @self.register("context")
        def cmd_context(args: list[str], ctx: dict[str, Any]) -> CommandResult:
            """Show context usage. Use '/context details' for full breakdown."""
            # Check for subcommand
            if args and args[0].lower() == "details":
                return self._context_details(ctx)
            
            # Basic context: show token usage estimate
            context_builder = ctx.get("context_builder")
            session = ctx.get("session")
            
            # Estimate token usage
            system_prompt = ""
            history_tokens = 0
            if context_builder:
                system_prompt = context_builder.build_system_prompt()
            if session:
                history = session.get_history()
                # Rough estimate: 4 chars per token
                history_tokens = sum(len(m.get("content", "")) for m in history) // 4
            
            system_tokens = len(system_prompt) // 4
            total_tokens = system_tokens + history_tokens
            
            lines = [
                "**Context Usage (Estimated):**",
                f"• System Prompt: ~{system_tokens:,} tokens",
                f"• Conversation History: ~{history_tokens:,} tokens",
                f"• **Total**: ~{total_tokens:,} tokens",
                "",
                "_Use `/context details` for full breakdown._"
            ]
            return CommandResult("\n".join(lines))
        
        @self.register("session")
        def cmd_session(args: list[str], ctx: dict[str, Any]) -> CommandResult:
            """Show session info, or switch with '/session <id>'."""
            sessions = ctx.get("sessions")
            session = ctx.get("session")
            
            # If argument provided, switch to that session
            if args:
                new_key = args[0]
                # If it doesn't contain channel prefix, add current channel
                if ":" not in new_key:
                    channel = ctx.get("channel", "telegram")
                    new_key = f"{channel}:{new_key}"
                
                # Actually switch to the session
                set_session = ctx.get("set_session")
                if set_session:
                    set_session(new_key)
                
                new_session = sessions.get_or_create(new_key)
                history = new_session.get_history()
                return CommandResult(
                    f"✅ Switched to session: `{new_key}`\n"
                    f"• Messages in history: {len(history)}\n\n"
                    f"_All future messages will use this session._"
                )
            
            # No args: show current session
            if session:
                history = session.get_history()
                
                # List other available sessions
                all_sessions = sessions.list_sessions()
                other_sessions = [s for s in all_sessions if s.get("key") != session.key][:5]
                
                lines = [
                    f"**Current Session:** `{session.key}`",
                    f"• Messages: {len(history)}",
                ]
                
                if other_sessions:
                    lines.append(f"\n**Other Sessions ({len(all_sessions) - 1} total):**")
                    for s in other_sessions:
                        lines.append(f"• `{s.get('key')}`")
                    lines.append("\n_Use `/session <key>` to switch._")
                
                return CommandResult("\n".join(lines))
            return CommandResult("No active session.", success=False)
        
        @self.register("new")
        def cmd_new(args: list[str], ctx: dict[str, Any]) -> CommandResult:
            """Start a new conversation (creates and switches to new session)."""
            session = ctx.get("session")
            sessions = ctx.get("sessions")
            channel = ctx.get("channel", "telegram")
            set_session = ctx.get("set_session")
            
            if sessions:
                # Generate new session key with numeric ID similar to original format
                import random
                import time
                # Use timestamp + random component to create a 10-digit numeric ID
                numeric_id = int(time.time() * 1000) % 10000000000 + random.randint(0, 999999)
                new_key = f"{channel}:{numeric_id}"
                
                # Create the new session
                new_session = sessions.get_or_create(new_key)
                sessions.save(new_session)
                
                # Switch to the new session
                if set_session:
                    set_session(new_key)
                
                old_key = session.key if session else "none"
                return CommandResult(
                    f"🆕 New session created and activated!\n"
                    f"• New: `{new_key}`\n"
                    f"• Previous: `{old_key}` (preserved)\n\n"
                    f"_All future messages will use the new session._"
                )
            return CommandResult("Session manager not available.", success=False)
        
        @self.register("sessions")
        def cmd_sessions(args: list[str], ctx: dict[str, Any]) -> CommandResult:
            """List all sessions."""
            sessions = ctx.get("sessions")
            current_session = ctx.get("session")
            
            if not sessions:
                return CommandResult("Session manager not available.", success=False)
            
            all_sessions = sessions.list_sessions()
            
            if not all_sessions:
                return CommandResult("No sessions found.")
            
            current_key = current_session.key if current_session else ""
            
            lines = [f"**Sessions ({len(all_sessions)}):**"]
            for s in all_sessions[:20]:  # Limit to 20
                key = s.get("key", "unknown")
                updated = s.get("updated_at", "")[:10] if s.get("updated_at") else ""
                marker = " ← current" if key == current_key else ""
                lines.append(f"• `{key}` ({updated}){marker}")
            
            if len(all_sessions) > 20:
                lines.append(f"_...and {len(all_sessions) - 20} more_")
            
            lines.append("\n_Use `/session <key>` to switch, `/new` to create._")
            return CommandResult("\n".join(lines))
        
        @self.register("clear")
        def cmd_clear(args: list[str], ctx: dict[str, Any]) -> CommandResult:
            """Clear the current session history."""
            session = ctx.get("session")
            sessions = ctx.get("sessions")
            if session and sessions:
                session.clear()
                sessions.save(session)
                return CommandResult("Session history cleared.")
            return CommandResult("No active session to clear.", success=False)
        
        @self.register("tools")
        def cmd_tools(args: list[str], ctx: dict[str, Any]) -> CommandResult:
            """List available tools."""
            tools = ctx.get("tools")
            if tools:
                defs = tools.get_definitions()
                names = [t["function"]["name"] for t in defs]
                return CommandResult(f"**Available Tools ({len(names)}):**\n" + ", ".join(f"`{n}`" for n in names))
            return CommandResult("No tools available.")
        
        @self.register("skills")
        def cmd_skills(args: list[str], ctx: dict[str, Any]) -> CommandResult:
            """List available skills."""
            context_builder = ctx.get("context_builder")
            if not context_builder:
                return CommandResult("Context builder not available.", success=False)
            
            skills_loader = context_builder.skills
            all_skills = skills_loader.list_skills(filter_unavailable=False)
            
            if not all_skills:
                return CommandResult("No skills available.")
            
            lines = [f"**Available Skills ({len(all_skills)}):**"]
            for skill in all_skills:
                name = skill.get("name", "unknown")
                source = skill.get("source", "unknown")
                desc = skills_loader._get_skill_description(name) or "No description"
                available = "✅" if skill.get("available", True) else "❌"
                lines.append(f"• {available} `{name}` ({source}) - {desc}")
            
            return CommandResult("\n".join(lines))
    
    def _context_details(self, ctx: dict[str, Any]) -> CommandResult:
        """Show detailed context breakdown."""
        context_builder = ctx.get("context_builder")
        session = ctx.get("session")
        
        lines = ["**Context Details:**"]
        
        # 1. Bootstrap files
        if context_builder:
            workspace = context_builder.workspace
            bootstrap_files = []
            for fname in context_builder.BOOTSTRAP_FILES:
                path = workspace / fname
                if path.exists():
                    size = len(path.read_text()) // 4
                    bootstrap_files.append(f"  - `{fname}`: ~{size:,} tokens")
            if bootstrap_files:
                lines.append("\n**Bootstrap Files:**")
                lines.extend(bootstrap_files)
            else:
                lines.append("\n**Bootstrap Files:** None found")
        
        # 2. Memory
        if context_builder:
            memory_content = context_builder.memory.get_memory_context()
            memory_tokens = len(memory_content) // 4 if memory_content else 0
            lines.append(f"\n**Memory:** ~{memory_tokens:,} tokens")
        
        # 3. Skills
        if context_builder:
            always_skills = context_builder.skills.get_always_skills()
            if always_skills:
                lines.append(f"\n**Always-Loaded Skills ({len(always_skills)}):** " + ", ".join(f"`{s}`" for s in always_skills))
            else:
                lines.append("\n**Always-Loaded Skills:** None")
        
        # 4. Conversation history
        if session:
            history = session.get_history()
            lines.append(f"\n**Conversation History:** {len(history)} messages")
            
            # Show last few messages (truncated)
            if history:
                lines.append("  _Last 3 messages:_")
                for msg in history[-3:]:
                    role = msg.get("role", "?")
                    content = msg.get("content", "")[:50]
                    lines.append(f"  - [{role}] {content}...")
        
        # 5. Current session info
        lines.append(f"\n**Channel:** `{ctx.get('channel', 'unknown')}`")
        lines.append(f"**Chat ID:** `{ctx.get('chat_id', 'unknown')}`")
        lines.append(f"**Workspace:** `{ctx.get('workspace', 'unknown')}`")
        
        return CommandResult("\n".join(lines))
    
    def register(self, name: str) -> Callable:
        """Decorator to register a command."""
        def decorator(func: Callable) -> Callable:
            self._commands[name.lower()] = func
            logger.debug(f"Registered command: /{name}")
            return func
        return decorator
    
    def is_command(self, content: str) -> bool:
        """Check if the message is a slash command."""
        return content.strip().startswith("/")
    
    def execute(self, content: str, context: dict[str, Any]) -> CommandResult:
        """Execute a slash command."""
        parts = content.strip().split()
        command_name = parts[0][1:].lower()  # Remove leading '/'
        args = parts[1:] if len(parts) > 1 else []
        
        if command_name in self._commands:
            try:
                return self._commands[command_name](args, context)
            except Exception as e:
                logger.error(f"Command /{command_name} failed: {e}")
                return CommandResult(f"Error executing `/{command_name}`: {e}", success=False)
        
        # Unknown command
        available = ", ".join(f"`/{c}`" for c in sorted(self._commands.keys()))
        return CommandResult(
            f"Unknown command: `/{command_name}`\n\nAvailable: {available}",
            success=False
        )
