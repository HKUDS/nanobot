#!/usr/bin/env python3
"""
Checkpoint system for Agent Swarm tasks
Allows resumption of long-running tasks
"""

import os
import json
import hashlib
from datetime import datetime
from pathlib import Path

CHECKPOINT_DIR = Path("/root/.nanobot/workspace/checkpoints")

def generate_task_id(description: str) -> str:
    """Generate short task ID from description and timestamp"""
    timestamp = datetime.now().strftime("%m%d%H%M")
    hash_part = hashlib.md5(description.encode()).hexdigest()[:6]
    return f"{timestamp}-{hash_part}"

def save_checkpoint(task_id: str, description: str, completed: list, pending: list, decisions: list, context: str = ""):
    """Save current task state to checkpoint file"""
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    
    checkpoint = {
        "task_id": task_id,
        "description": description,
        "created": datetime.now().isoformat(),
        "updated": datetime.now().isoformat(),
        "completed": completed,
        "pending": pending,
        "key_decisions": decisions,
        "context": context
    }
    
    filepath = CHECKPOINT_DIR / f"swarm-{task_id}.json"
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(checkpoint, f, indent=2, ensure_ascii=False)
    
    return str(filepath)

def load_checkpoint(task_id: str) -> dict:
    """Load checkpoint by task ID"""
    filepath = CHECKPOINT_DIR / f"swarm-{task_id}.json"
    if not filepath.exists():
        # Try partial match
        matches = list(CHECKPOINT_DIR.glob(f"swarm-*{task_id}*.json"))
        if matches:
            filepath = matches[0]
        else:
            return None
    
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)

def list_checkpoints():
    """List all swarm checkpoints"""
    if not CHECKPOINT_DIR.exists():
        return []
    
    checkpoints = []
    for filepath in CHECKPOINT_DIR.glob("swarm-*.json"):
        with open(filepath, 'r') as f:
            data = json.load(f)
            checkpoints.append({
                "task_id": data["task_id"],
                "description": data["description"][:50] + "..." if len(data["description"]) > 50 else data["description"],
                "updated": data["updated"],
                "pending_count": len(data["pending"]),
                "completed_count": len(data["completed"])
            })
    
    return sorted(checkpoints, key=lambda x: x["updated"], reverse=True)

def update_checkpoint(task_id: str, completed_item: str = None, pending_items: list = None, new_decision: str = None):
    """Update existing checkpoint with progress"""
    checkpoint = load_checkpoint(task_id)
    if not checkpoint:
        return None
    
    if completed_item and completed_item not in checkpoint["completed"]:
        checkpoint["completed"].append(completed_item)
        if completed_item in checkpoint["pending"]:
            checkpoint["pending"].remove(completed_item)
    
    if pending_items:
        for item in pending_items:
            if item not in checkpoint["pending"] and item not in checkpoint["completed"]:
                checkpoint["pending"].append(item)
    
    if new_decision:
        checkpoint["key_decisions"].append({
            "decision": new_decision,
            "timestamp": datetime.now().isoformat()
        })
    
    checkpoint["updated"] = datetime.now().isoformat()
    
    filepath = CHECKPOINT_DIR / f"swarm-{task_id}.json"
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(checkpoint, f, indent=2, ensure_ascii=False)
    
    return checkpoint

def format_checkpoint_for_resume(checkpoint: dict) -> str:
    """Format checkpoint data for agent resumption"""
    lines = [
        f"# Resuming Task: {checkpoint['description']}",
        f"Original started: {checkpoint['created']}",
        "",
        "## Previously Completed",
    ]
    
    for item in checkpoint["completed"]:
        lines.append(f"- [x] {item}")
    
    lines.extend(["", "## Still Pending"])
    for item in checkpoint["pending"]:
        lines.append(f"- [ ] {item}")
    
    if checkpoint["key_decisions"]:
        lines.extend(["", "## Key Decisions Made"])
        for decision in checkpoint["key_decisions"]:
            if isinstance(decision, dict):
                lines.append(f"- {decision['decision']}")
            else:
                lines.append(f"- {decision}")
    
    if checkpoint["context"]:
        lines.extend(["", "## Context", checkpoint["context"]])
    
    lines.extend(["", "---", "Continue from the next pending item."])
    
    return "\n".join(lines)

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: checkpoint.py [save|load|list|update] [args...]")
        sys.exit(1)
    
    cmd = sys.argv[1]
    
    if cmd == "list":
        checkpoints = list_checkpoints()
        if not checkpoints:
            print("No checkpoints found")
        else:
            for cp in checkpoints[:10]:
                print(f"{cp['task_id']}: {cp['description']} ({cp['completed_count']} done, {cp['pending_count']} pending)")
    
    elif cmd == "load" and len(sys.argv) >= 3:
        task_id = sys.argv[2]
        cp = load_checkpoint(task_id)
        if cp:
            print(format_checkpoint_for_resume(cp))
        else:
            print(f"Checkpoint not found: {task_id}")
            sys.exit(1)
