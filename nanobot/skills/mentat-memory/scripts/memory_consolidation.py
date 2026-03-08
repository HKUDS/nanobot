#!/usr/bin/env python3
"""
Memory consolidation - semantic deduplication and updating.
Phase 2 enhancement (disabled by default via feature flag).

Consolidation strategy:
1. For each new memory, find semantically similar existing memories
2. LLM decides: ADD (distinct), UPDATE (enhance existing), or NO-OP (redundant)
3. Apply action while maintaining audit trail
"""
import json
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict

import sys
sys.path.insert(0, str(Path(__file__).parent))
from memory_config import MEMORY_CONFIG


def load_memories_from_timeframe(memory_bank_path: Path, days: int = 7) -> List[dict]:
    """
    Load memories from the last N days.
    """
    if not memory_bank_path.exists():
        return []
    
    cutoff = datetime.now() - timedelta(days=days)
    memories = []
    
    with open(memory_bank_path, "r") as f:
        for line in f:
            try:
                mem = json.loads(line)
                mem_time = datetime.fromisoformat(mem["timestamp"])
                
                # Make cutoff timezone-aware
                if mem_time.tzinfo:
                    cutoff = cutoff.replace(tzinfo=mem_time.tzinfo)
                
                if mem_time >= cutoff:
                    memories.append(mem)
            except (json.JSONDecodeError, KeyError, ValueError):
                continue
    
    return memories


def load_all_active_memories(memory_bank_path: Path) -> List[dict]:
    """Load all active memories for similarity checking."""
    if not memory_bank_path.exists():
        return []
    
    memories = []
    with open(memory_bank_path, "r") as f:
        for line in f:
            try:
                mem = json.loads(line)
                if mem.get("status") == "active":
                    memories.append(mem)
            except (json.JSONDecodeError, KeyError):
                continue
    
    return memories


def semantic_similarity_search(new_memory: dict, candidates: List[dict], top_k: int = 3) -> List[dict]:
    """
    Find semantically similar memories.
    
    Simplified version: Use LLM for similarity scoring.
    Production: Use embeddings + cosine similarity.
    """
    if not candidates:
        return []
    
    prompt = f"""New memory: "{new_memory['content']}"

Existing memories:
{json.dumps([{"id": m["id"], "content": m["content"]} for m in candidates], indent=2)}

Which existing memories are semantically similar (same topic/entity)?
Consider memories similar if they discuss the same concept, even with different wording.

Examples of similar:
- "User loves pizza" and "User likes pizza"
- "Dashboard slow" and "Dashboard performance issues"

Return JSON array of IDs: ["mem_123", "mem_456"]
If none are similar, return: []

IMPORTANT: Return ONLY the JSON array, no other text.
"""
    
    try:
        result = subprocess.run(
            ["clawdbot", "sessions", "spawn", 
             "--model", "flash",
             "--cleanup", "delete", 
             "--label", "Similarity Check", 
             prompt],
            capture_output=True, 
            text=True, 
            timeout=30
        )
        
        output = result.stdout.strip()
        
        # Skip metadata lines
        lines = output.split('\n')
        llm_start = 0
        for i, line in enumerate(lines):
            if 'Flags' in line or 'direct' in line:
                llm_start = i + 1
                break
        llm_output = '\n'.join(lines[llm_start:])
        
        # Extract JSON array
        json_start = llm_output.find('[')
        json_end = llm_output.rfind(']') + 1
        if json_start != -1 and json_end > 0:
            similar_ids = json.loads(llm_output[json_start:json_end])
            return [m for m in candidates if m["id"] in similar_ids]
        
        return []
    
    except Exception as e:
        print(f"Similarity search failed: {e}")
        return []


def consolidate_decision(new_memory: dict, similar_memories: List[dict]) -> Dict[str, any]:
    """
    LLM decides: ADD, UPDATE, or NO-OP.
    """
    if not similar_memories:
        return {"action": "ADD", "reason": "No similar memories found"}
    
    prompt = f"""New memory: {json.dumps(new_memory, indent=2)}

Existing similar memories:
{json.dumps(similar_memories, indent=2)}

Determine consolidation action:
- ADD: Information is distinct and new (different fact/event)
- UPDATE: New info enhances/updates an existing memory (specify which ID)
- NO-OP: Information is redundant (already captured)

Rules:
- "Loves pizza" and "likes pizza" are semantically same → UPDATE or NO-OP
- Conflicting info (e.g., old: "$500 budget", new: "$750 budget") → UPDATE with newer
- Minor rewording of same fact → NO-OP
- Different specific events (even same topic) → ADD

Return JSON:
{{
  "action": "ADD|UPDATE|NO-OP",
  "target_id": "mem_xxx",
  "reason": "Brief explanation"
}}

IMPORTANT: Return ONLY the JSON object, no other text.
"""
    
    try:
        result = subprocess.run(
            ["clawdbot", "sessions", "spawn", 
             "--model", "flash",
             "--cleanup", "delete", 
             "--label", "Consolidation Decision", 
             prompt],
            capture_output=True, 
            text=True, 
            timeout=30
        )
        
        output = result.stdout.strip()
        
        # Skip metadata lines
        lines = output.split('\n')
        llm_start = 0
        for i, line in enumerate(lines):
            if 'Flags' in line or 'direct' in line:
                llm_start = i + 1
                break
        llm_output = '\n'.join(lines[llm_start:])
        
        # Extract JSON object
        json_start = llm_output.find('{')
        json_end = llm_output.rfind('}') + 1
        if json_start != -1 and json_end > 0:
            decision = json.loads(llm_output[json_start:json_end])
            return decision
        
        # Default to ADD if parsing fails
        return {"action": "ADD", "reason": "LLM decision failed, defaulting to ADD"}
    
    except Exception as e:
        print(f"Consolidation decision failed: {e}")
        return {"action": "ADD", "reason": f"Error: {e}"}


def apply_consolidation(decision: dict, new_memory: dict, memory_bank_path: Path):
    """
    Apply ADD/UPDATE/NO-OP action to memory bank.
    """
    action = decision.get("action", "ADD")
    
    if action == "ADD":
        # Append new memory
        with open(memory_bank_path, "a") as f:
            f.write(json.dumps(new_memory) + "\n")
        print(f"✅ ADD: {new_memory['content'][:60]}... (reason: {decision.get('reason', 'N/A')})")
    
    elif action == "UPDATE":
        # Mark old memory as superseded, add new enhanced version
        target_id = decision.get("target_id")
        if not target_id:
            print(f"⚠️ UPDATE decision missing target_id, defaulting to ADD")
            with open(memory_bank_path, "a") as f:
                f.write(json.dumps(new_memory) + "\n")
            return
        
        # Read all memories
        memories = []
        with open(memory_bank_path, "r") as f:
            for line in f:
                try:
                    mem = json.loads(line)
                    if mem["id"] == target_id:
                        # Mark as superseded
                        mem["status"] = "superseded"
                        mem["superseded_by"] = new_memory["id"]
                    memories.append(mem)
                except json.JSONDecodeError:
                    continue
        
        # Add new memory with consolidation link
        new_memory["consolidated_from"].append(target_id)
        memories.append(new_memory)
        
        # Rewrite memory bank
        with open(memory_bank_path, "w") as f:
            for mem in memories:
                f.write(json.dumps(mem) + "\n")
        
        print(f"🔄 UPDATE: {new_memory['content'][:60]}... (superseded {target_id})")
    
    elif action == "NO-OP":
        print(f"⏭️ NO-OP: {new_memory['content'][:60]}... (reason: {decision.get('reason', 'N/A')})")
    
    else:
        print(f"⚠️ Unknown action: {action}, defaulting to ADD")
        with open(memory_bank_path, "a") as f:
            f.write(json.dumps(new_memory) + "\n")


def consolidate_memories(memory_bank_path: Path, days: int = 7):
    """
    Run consolidation for recent memories.
    
    Args:
        memory_bank_path: Path to JSONL memory bank
        days: Look back N days for new memories to consolidate
    """
    if not MEMORY_CONFIG["ENABLE_CONSOLIDATION"]:
        print("Consolidation disabled via feature flag")
        return
    
    print(f"Loading memories from last {days} days...")
    new_memories = load_memories_from_timeframe(memory_bank_path, days=days)
    
    if not new_memories:
        print("No new memories to consolidate")
        return
    
    print(f"Found {len(new_memories)} memories to consolidate")
    
    # Load existing memories for similarity check
    existing_memories = load_all_active_memories(memory_bank_path)
    
    # Process each new memory
    for new_mem in new_memories:
        # Find similar existing memories (excluding the new memory itself)
        candidates = [m for m in existing_memories if m["id"] != new_mem["id"]]
        
        similar = semantic_similarity_search(
            new_mem, 
            candidates, 
            top_k=MEMORY_CONFIG["CONSOLIDATION_TOP_K"]
        )
        
        # Decide action
        decision = consolidate_decision(new_mem, similar)
        
        # Apply action
        apply_consolidation(decision, new_mem, memory_bank_path)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Consolidate memory bank")
    parser.add_argument("--days", type=int, default=7, help="Look back N days")
    parser.add_argument("--bank", default="memory/diary/2026/memories.jsonl", help="Memory bank path")
    
    args = parser.parse_args()
    
    consolidate_memories(Path(args.bank), days=args.days)
