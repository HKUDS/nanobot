#!/usr/bin/env python3
"""
Raw Archive Compactor - Daily reconciliation task for nanobot memory system.

This script runs daily (recommended at 2:00 AM) to re-process [RAW] archived
messages in HISTORY.md that were created due to LLM timeout or failures.
It uses the same MemoryStore.consolidate() logic as nanobot runtime.

Usage:
    # Single instance
    python raw_compactor.py --workspace ~/.nanobot/workspace
    
    # With custom model
    python raw_compactor.py --workspace ~/.nanobot/workspace --model gpt-4o

Crontab configuration (for multiple instances with staggered execution):
    0 2 * * * python raw_compactor.py --workspace ~/.nanobot-agent1/workspace
    5 2 * * * python raw_compactor.py --workspace ~/.nanobot-agent2/workspace
    10 2 * * * python raw_compactor.py --workspace ~/.nanobot-agent3/workspace
"""

import argparse
import asyncio
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# Add nanobot package to path
NANOBOT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(NANOBOT_ROOT))

from nanobot.agent.memory import MemoryStore, _SAVE_MEMORY_TOOL, _ensure_text, _normalize_save_memory_args
from nanobot.providers import create_provider
from nanobot.utils.helpers import ensure_dir

# Regex pattern to match RAW archive blocks in HISTORY.md
RAW_PATTERN = re.compile(
    r'^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\] \[RAW\] (\d+) messages\n((?:\[.*\n?)*)',
    re.MULTILINE
)

# Regex pattern to parse individual messages within RAW block
MESSAGE_PATTERN = re.compile(
    r'^\[(\d{4}-\d{2}-\d{2}T\d{2}:\d{2})\] (USER|ASSISTANT)(?: \[tools: (.*?)\])?: (.*)$'
)


def parse_raw_messages(raw_text: str) -> list[dict]:
    """Parse message list from RAW archive text."""
    messages = []
    
    for line in raw_text.strip().split('\n'):
        match = MESSAGE_PATTERN.match(line)
        if match:
            timestamp, role, tools, content = match.groups()
            msg = {
                "timestamp": timestamp,
                "role": role.lower(),
                "content": content
            }
            if tools:
                msg["tools_used"] = tools.split(", ")
            messages.append(msg)
    
    return messages


def find_raw_blocks(content: str) -> list[tuple]:
    """
    Find all RAW archive blocks in HISTORY.md content.
    
    Returns list of tuples: (full_match, timestamp, count, raw_messages_text)
    """
    blocks = []
    for match in RAW_PATTERN.finditer(content):
        full_match = match.group(0)
        timestamp = match.group(1)
        count = match.group(2)
        raw_messages = match.group(3)
        blocks.append((full_match, timestamp, count, raw_messages))
    return blocks


def remove_raw_block(content: str, block_text: str) -> str:
    """Remove a RAW block from HISTORY.md content."""
    # Remove the block and any trailing newlines
    content = content.replace(block_text, "")
    # Clean up multiple consecutive blank lines
    content = re.sub(r'\n{3,}', '\n\n', content)
    return content.strip()


async def consolidate_raw_block(
    store: MemoryStore,
    provider: Any,
    model: str,
    raw_messages: list[dict]
) -> tuple[bool, str | None]:
    """
    Consolidate a RAW block using MemoryStore.consolidate() logic.
    
    Returns: (success: bool, history_entry: str | None)
    """
    if not raw_messages:
        return False, None
    
    # Call the same consolidate method used by nanobot runtime
    success = await store.consolidate(raw_messages, provider, model)
    
    if not success:
        return False, None
    
    # Read the last entry from HISTORY.md (the one we just added)
    history_content = store.read_history() if hasattr(store, 'read_history') else ""
    if not history_content:
        # Fallback: read directly from file
        if store.history_file.exists():
            history_content = store.history_file.read_text(encoding="utf-8")
    
    if history_content:
        lines = history_content.strip().split('\n')
        # Find the last non-empty line that looks like a history entry
        for line in reversed(lines):
            line = line.strip()
            if line and line.startswith('[') and not line.startswith('[RAW]'):
                return True, line
    
    return True, None


async def compact_raw_history(
    workspace_dir: Path,
    model: str | None = None,
    dry_run: bool = False
):
    """
    Main function: scan and compact all RAW archives in HISTORY.md.
    """
    history_file = workspace_dir / "memory" / "HISTORY.md"
    memory_file = workspace_dir / "memory" / "MEMORY.md"
    
    print(f"\n{'='*60}")
    print(f"Raw Archive Compactor - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Workspace: {workspace_dir}")
    if dry_run:
        print("Mode: DRY RUN (no changes will be made)")
    print(f"{'='*60}\n")
    
    if not history_file.exists():
        print(f"⚠️  HISTORY.md not found at {history_file}")
        return
    
    # Read HISTORY.md
    content = history_file.read_text(encoding="utf-8")
    blocks = find_raw_blocks(content)
    
    if not blocks:
        print("✅ No RAW blocks found, nothing to compact.")
        return
    
    print(f"📦 Found {len(blocks)} RAW block(s) to process\n")
    
    # Initialize MemoryStore
    store = MemoryStore(workspace_dir)
    
    # Create provider (use default from config or fallback to openai)
    try:
        provider = create_provider(model=model)
        print(f"✅ Provider initialized (model: {model or 'default'})\n")
    except Exception as e:
        print(f"❌ Failed to initialize provider: {e}")
        print("   Please ensure your API keys are configured correctly.")
        return
    
    # Statistics
    success_count = 0
    fail_count = 0
    new_content = content
    
    for i, (full_match, timestamp, count, raw_messages_text) in enumerate(blocks, 1):
        print(f"[{i}/{len(blocks)}] Processing RAW block from {timestamp} ({count} messages)")
        
        # Parse messages from RAW block
        messages = parse_raw_messages(raw_messages_text)
        if not messages:
            print("  ⚠️  No valid messages found in RAW block")
            fail_count += 1
            continue
        
        print(f"  📄 Parsed {len(messages)} messages")
        
        if dry_run:
            print("  🔍 [DRY RUN] Would consolidate these messages")
            success_count += 1
            continue
        
        # Perform consolidation
        try:
            success, history_entry = await consolidate_raw_block(
                store, provider, model or "gpt-4o-mini", messages
            )
            
            if success and history_entry:
                print(f"  ✅ Consolidated: {history_entry[:60]}...")
                # Remove the RAW block from content
                new_content = remove_raw_block(new_content, full_match)
                success_count += 1
            else:
                print("  ❌ Consolidation failed, keeping RAW block")
                fail_count += 1
                
        except Exception as e:
            print(f"  ❌ Error during consolidation: {e}")
            fail_count += 1
    
    # Write updated content back to HISTORY.md
    if not dry_run and success_count > 0:
        try:
            # Write the cleaned content (with RAW blocks removed)
            # Note: successful consolidations are already appended by store.consolidate()
            # We just need to remove the RAW blocks
            history_file.write_text(new_content + "\n\n", encoding="utf-8")
            print(f"\n📝 Updated {history_file}")
        except Exception as e:
            print(f"\n❌ Failed to write HISTORY.md: {e}")
    
    print(f"\n{'='*60}")
    print(f"Summary: {success_count} succeeded, {fail_count} failed/pending")
    if dry_run:
        print("Mode: DRY RUN (no changes made)")
    print(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Re-process RAW archived messages in nanobot HISTORY.md using MemoryStore.consolidate()"
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        required=True,
        help="Path to instance workspace directory (e.g., ~/.nanobot/workspace)"
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Model to use for consolidation (default: from config or gpt-4o-mini)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes"
    )
    args = parser.parse_args()
    
    if not args.workspace.exists():
        print(f"❌ Workspace directory not found: {args.workspace}")
        sys.exit(1)
    
    asyncio.run(compact_raw_history(args.workspace, args.model, args.dry_run))


if __name__ == "__main__":
    main()
