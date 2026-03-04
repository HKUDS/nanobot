#!/usr/bin/env python3
"""
Demo script for Agent Swarm skill
Shows how the components work together
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from swarm import get_swarm_prompt, auto_select_agents, is_swarm_worthy
from checkpoint import save_checkpoint, load_checkpoint, list_checkpoints
from memory_upgrade import add_timeline_entry, get_recent_context, format_context_for_prompt

def demo_task_evaluation():
    """Demo: Evaluate if tasks should use swarm"""
    print("=" * 60)
    print("DEMO 1: Task Evaluation")
    print("=" * 60)
    
    tasks = [
        "What's the weather today?",
        "/swarm Design a database schema for my app",
        "Should I use PostgreSQL or MongoDB for my AI assistant with vector search requirements?",
        "I'm building an AI coding assistant. Should I target indie developers or enterprise teams?",
        "Write a Python function to calculate fibonacci",
        "Evaluate the technical and business feasibility of launching an AI tax assistant in the US market"
    ]
    
    for task in tasks:
        should, reason = is_swarm_worthy(task)
        status = "✅ SWARM" if should else "❌ Simple"
        print(f"\n{status}: {task[:60]}...")
        print(f"   Reason: {reason}")

def demo_agent_selection():
    """Demo: Auto-select agents"""
    print("\n" + "=" * 60)
    print("DEMO 2: Agent Auto-Selection")
    print("=" * 60)
    
    tasks = [
        "Design a scalable architecture for an AI bot platform",
        "Should I price my SaaS at $29 or $99 per month?",
        "Review my startup idea: AI-powered code reviewer",
        "Compare React vs Vue for my new project"
    ]
    
    for task in tasks:
        agents = auto_select_agents(task)
        print(f"\nTask: {task[:50]}...")
        print(f"Agents: {' → '.join(agents)}")

def demo_checkpoint_system():
    """Demo: Save and load checkpoints"""
    print("\n" + "=" * 60)
    print("DEMO 3: Checkpoint System")
    print("=" * 60)
    
    # Save a sample checkpoint
    task_id = save_checkpoint(
        task_id="demo-task",
        description="Design YourBot MVP architecture",
        completed=[
            "Research existing bot frameworks (OpenClaw, NanoClaw)",
            "Define core feature set",
            "Choose tech stack (FastAPI + PostgreSQL)"
        ],
        pending=[
            "Design database schema",
            "Define API endpoints",
            "Create deployment plan"
        ],
        decisions=[
            "Use PostgreSQL + pgvector over MongoDB for ACID compliance",
            "Start with FastAPI (team familiarity) over Django"
        ],
        context="User wants AI assistant that can spawn personalized bots. Key constraints: low latency, horizontal scaling, multi-tenant."
    )
    
    print(f"✅ Checkpoint saved: {task_id}")
    
    # Load it back
    cp = load_checkpoint("demo-task")
    if cp:
        print(f"\nLoaded checkpoint:")
        print(f"  Description: {cp['description']}")
        print(f"  Completed: {len(cp['completed'])} items")
        print(f"  Pending: {len(cp['pending'])} items")
        print(f"  Decisions: {len(cp['key_decisions'])} items")
    
    # List all checkpoints
    print("\nAll checkpoints:")
    for c in list_checkpoints()[:3]:
        print(f"  - {c['task_id']}: {c['description'][:40]}...")

def demo_memory_timeline():
    """Demo: Timeline memory"""
    print("\n" + "=" * 60)
    print("DEMO 4: Timeline Memory")
    print("=" * 60)
    
    # Add sample entries
    entries = [
        ("YourBot", "Technical architecture v2.3 finalized", None, ["decision"]),
        ("Study", "Analyzed TinyClaw and NanoClaw architecture", None, ["research"]),
        ("Feature", "Implemented Agent Swarm skill", "skills/agent-swarm/SKILL.md", ["swarm"]),
        ("Decision", "Chose PostgreSQL + pgvector for memory system", None, ["database"])
    ]
    
    print("Adding timeline entries...")
    for category, content, link, tags in entries:
        entry = add_timeline_entry(category, content, link, tags)
        print(f"  ✓ {entry[:80]}...")
    
    # Get recent context
    print("\nRecent context (last 24h):")
    recent = get_recent_context(24)
    for e in recent[-3:]:
        print(f"  - {e['content'][:70]}...")
    
    # Format for prompt
    print("\nFormatted for prompt:")
    print(format_context_for_prompt(24))

def demo_full_workflow():
    """Demo: Complete swarm workflow"""
    print("\n" + "=" * 60)
    print("DEMO 5: Full Swarm Workflow")
    print("=" * 60)
    
    task = "Should I use PostgreSQL or MongoDB for my AI assistant's memory system with vector search?"
    
    print(f"\nTask: {task}")
    print("-" * 60)
    
    # Step 1: Check if swarm worthy
    should, reason = is_swarm_worthy(task)
    print(f"\n1. Evaluation: {reason}")
    
    # Step 2: Select agents
    agents = auto_select_agents(task)
    print(f"2. Selected agents: {', '.join(agents)}")
    
    # Step 3: Generate prompt
    prompt = get_swarm_prompt(task, agents)
    print(f"3. Generated prompt ({len(prompt)} chars)")
    print("\nPrompt preview:")
    print("-" * 40)
    print(prompt[:500] + "...")
    print("-" * 40)
    
    # Step 4: Record in timeline
    print("\n4. Recording to timeline...")
    entry = add_timeline_entry("Swarm", f"Analyzed: {task[:50]}...", tags=["architecture", "database"])
    print(f"   {entry[:70]}...")
    
    # Step 5: Create checkpoint for follow-up
    print("\n5. Creating checkpoint...")
    cp_id = save_checkpoint(
        task_id="db-decision",
        description="Database choice for YourBot",
        completed=["Evaluated PostgreSQL vs MongoDB"],
        pending=["Set up PostgreSQL with pgvector", "Design schema", "Benchmark query performance"],
        decisions=["Choose PostgreSQL + pgvector"],
        context="Need ACID compliance for memory consistency. Scale target: 100k vectors initially."
    )
    print(f"   Checkpoint: {cp_id}")

if __name__ == "__main__":
    print("🐝 Agent Swarm Skill Demo")
    print("=" * 60)
    
    demos = {
        "1": demo_task_evaluation,
        "2": demo_agent_selection,
        "3": demo_checkpoint_system,
        "4": demo_memory_timeline,
        "5": demo_full_workflow,
        "all": lambda: [d() for d in [demo_task_evaluation, demo_agent_selection, demo_checkpoint_system, demo_memory_timeline, demo_full_workflow]]
    }
    
    if len(sys.argv) > 1 and sys.argv[1] in demos:
        demos[sys.argv[1]]()
    else:
        print("\nUsage: demo.py [1|2|3|4|5|all]")
        print("  1 - Task evaluation (swarm vs simple)")
        print("  2 - Agent auto-selection")
        print("  3 - Checkpoint system")
        print("  4 - Timeline memory")
        print("  5 - Full workflow")
        print("  all - Run all demos")
        print("\nRunning demo 5 (full workflow) by default...")
        demo_full_workflow()
