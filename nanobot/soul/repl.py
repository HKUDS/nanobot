"""Interactive REPL for Soul & Memory testing.

Provides a local REPL for testing soul persona and memory features
without requiring a full gateway or LLM connection.

Modes:
  - REPL: Interactive commands to inspect soul, memory, search
  - Demo: Automated demonstration of all features
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger

from nanobot.soul.workspace import AgentWorkspace
from nanobot.soul.tools import MemoryManager, get_memory_manager
from nanobot.soul.prompt import build_soul_system_prompt


# ANSI colors
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
DIM = "\033[2m"
RESET = "\033[0m"
BOLD = "\033[1m"
MAGENTA = "\033[35m"
BLUE = "\033[34m"


def _colored_prompt() -> str:
    return f"{CYAN}{BOLD}You > {RESET}"


def _print_info(text: str) -> None:
    print(f"{DIM}{text}{RESET}")


def _print_result(text: str) -> None:
    print(f"\n{GREEN}{BOLD}Result:{RESET} {text}\n")


def run_repl(workspace: AgentWorkspace) -> None:
    """Interactive REPL for testing Soul & Memory features.

    Commands:
      /quit           Exit REPL
      /soul           View SOUL.md
      /memory         View memory status
      /search <query> Search memory
      /write <text>   Write to daily memory
      /read <path>    Read a memory file
      /prompt         View full system prompt
      /agents         List available agents (if multi-agent)
    """
    mgr = get_memory_manager(workspace.agent_id, workspace.workspace_dir)

    _print_info("=" * 60)
    _print_info(f"  Soul & Memory REPL")
    _print_info(f"  Agent: {workspace.agent_id}")
    _print_info(f"  Workspace: {workspace.workspace_dir}")
    _print_info("")
    _print_info("  Commands:")
    _print_info("    /quit             Exit REPL")
    _print_info("    /soul             View SOUL.md")
    _print_info("    /memory           View memory status")
    _print_info("    /search <query>   Search memory")
    _print_info("    /write <text>     Write to daily memory")
    _print_info("    /read <path>      Read a memory file")
    _print_info("    /prompt           View full system prompt")
    _print_info("=" * 60)
    print()

    # Show soul status
    if workspace.has_soul():
        soul = workspace.read_soul()
        first_line = soul.split("\n")[0].strip()
        _print_info(f"Soul loaded: {first_line}")
    else:
        _print_info("No soul found. Use /soul to create one.")
    print()

    while True:
        try:
            user_input = input(_colored_prompt()).strip()
        except (KeyboardInterrupt, EOFError):
            print(f"\n{DIM}Goodbye.{RESET}")
            break

        if not user_input:
            continue

        if user_input.lower() in ("/quit", "/exit", "q"):
            print(f"{DIM}Goodbye.{RESET}")
            break

        if user_input == "/soul":
            if workspace.has_soul():
                print(f"\n{MAGENTA}--- SOUL.md ---{RESET}")
                print(workspace.read_soul())
                print(f"{MAGENTA}--- end ---{RESET}\n")
            else:
                _print_info("No SOUL.md found.")
            continue

        if user_input == "/memory":
            evergreen = mgr.load_evergreen()
            recent = mgr.get_recent_daily(days=7)
            print(f"\n{MAGENTA}--- Memory Status ---{RESET}")
            print(f"Workspace: {workspace.workspace_dir}")
            if evergreen:
                print(f"MEMORY.md: {len(evergreen)} chars")
            else:
                print("MEMORY.md: (not found)")
            print(f"Recent daily logs: {len(recent)} files")
            for entry in recent:
                lines_cnt = entry["content"].count("\n") + 1
                print(f"  {entry['date']}: {lines_cnt} lines")
            print(f"{MAGENTA}--- end ---{RESET}\n")
            continue

        if user_input.startswith("/search "):
            query = user_input[8:].strip()
            if not query:
                print("  Usage: /search <query>")
                continue
            results = mgr.search(query)
            if results:
                print(f"\n{MAGENTA}--- Search Results ({len(results)}) ---{RESET}")
                for r in results:
                    print(f"  [{r['score']:.4f}] {r['citation']}")
                    snippet = r["snippet"][:200]
                    print(f"           {snippet}{'...' if len(r['snippet']) > 200 else ''}")
                print(f"{MAGENTA}--- end ---{RESET}\n")
            else:
                _print_info("No results found.")
            continue

        if user_input.startswith("/write "):
            text = user_input[7:].strip()
            if not text:
                print("  Usage: /write <text>")
                continue
            rel = mgr.write_daily(text, "repl")
            _print_result(f"Written to {rel}")
            continue

        if user_input.startswith("/read "):
            path = user_input[6:].strip()
            if not path:
                print("  Usage: /read <path>")
                continue
            result = mgr.read_file(path)
            if result.get("error"):
                print(f"  Error: {result['error']}")
            else:
                print(f"\n{result['text']}\n")
            continue

        if user_input == "/prompt":
            prompt = build_soul_system_prompt(workspace, "You are a helpful assistant.")
            print(f"\n{MAGENTA}--- System Prompt ---{RESET}")
            print(prompt[:3000])
            if len(prompt) > 3000:
                print(f"\n... ({len(prompt)} total chars)")
            print(f"{MAGENTA}--- end ---{RESET}\n")
            continue

        print(f"  Unknown command: {user_input}")
        print("  Type /quit to exit, or use /soul, /memory, /search, /write, /read, /prompt")
