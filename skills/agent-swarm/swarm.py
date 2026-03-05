#!/usr/bin/env python3
"""
Agent Swarm orchestration for nanobot
Simulates multi-agent collaboration within single LLM call
"""

import sys
from pathlib import Path

# Add checkpoint and memory modules
sys.path.insert(0, str(Path(__file__).parent))

def get_swarm_prompt(task: str, agents: list = None) -> str:
    """
    Generate the swarm orchestration prompt
    
    Args:
        task: The task description
        agents: List of agent roles to include (default: auto-select based on task)
    
    Returns:
        Complete prompt for swarm execution
    """
    
    # Available agents
    all_agents = {
        "researcher": {
            "icon": "🔍",
            "name": "Researcher",
            "expertise": "Information gathering, web search, finding facts and data",
            "use_when": "need facts, market data, competitors, technical details"
        },
        "architect": {
            "icon": "🏗️", 
            "name": "Architect",
            "expertise": "System design, technical architecture, solution structure",
            "use_when": "building something, choosing technology, designing systems"
        },
        "strategist": {
            "icon": "🎯",
            "name": "Strategist", 
            "expertise": "Business strategy, market positioning, opportunity analysis",
            "use_when": "business decisions, go-to-market, competitive positioning"
        },
        "critic": {
            "icon": "⚠️",
            "name": "Critic",
            "expertise": "Risk identification, edge cases, failure modes, devil's advocate",
            "use_when": "high-stakes decisions, production systems, safety-critical"
        },
        "analyst": {
            "icon": "📊",
            "name": "Analyst",
            "expertise": "Data analysis, metrics, quantitative comparison, evaluation",
            "use_when": "comparing options, ROI analysis, performance evaluation"
        },
        "writer": {
            "icon": "✍️",
            "name": "Writer",
            "expertise": "Synthesis, clear communication, documentation",
            "use_when": "final output needs polish, complex ideas need simplification"
        }
    }
    
    # Auto-select agents if not specified
    if not agents:
        agents = auto_select_agents(task)
    
    # Build agent descriptions
    agent_descriptions = []
    for agent_key in agents:
        if agent_key in all_agents:
            a = all_agents[agent_key]
            agent_descriptions.append(
                f"{a['icon']} **{a['name']}**: {a['expertise']}"
            )
    
    prompt = f"""You are coordinating a team of specialized AI agents to solve this task comprehensively.

## 🎯 Task
{task}

## 🤖 Your Team
{chr(10).join(agent_descriptions)}

## 📋 Execution Protocol

You are the Coordinator. Follow this exact structure:

### Step 1: Task Analysis (Coordinator)
Briefly analyze what needs to be done and which agents are most relevant.

### Step 2: Agent Contributions
Each agent provides their perspective in the following format:

"""
    
    # Add sections for each agent
    for agent_key in agents:
        if agent_key in all_agents:
            a = all_agents[agent_key]
            prompt += f"""
## {a['icon']} {a['name']} Perspective
[{a['name']} speaks in first person about the task from their expertise]

Key points:
- Point 1
- Point 2
- Point 3

"""
    
    prompt += """
### Step 3: Conflict Resolution (Coordinator)
Identify any conflicts between agent perspectives (e.g., Architect suggests X, Critic warns about Y). Resolve these by making clear trade-off decisions.

### Step 4: Final Recommendation
## ✅ Final Recommendation
[Clear, actionable output that integrates all perspectives]

Include:
- **Decision**: What should be done
- **Rationale**: Why this is the best approach
- **Next Steps**: Specific, numbered action items
- **Risks & Mitigations**: Key risks and how to handle them

## ⚠️ Important Rules
1. Each agent must provide UNIQUE value - no generic responses
2. Be specific - include real examples, numbers, or concrete recommendations
3. If agents disagree, explain the trade-off and make a decision
4. End with CLEAR next steps, not just analysis
"""
    
    return prompt

def auto_select_agents(task: str) -> list:
    """Auto-select relevant agents based on task keywords"""
    task_lower = task.lower()
    
    selected = ["researcher"]  # Always include researcher
    
    # Technical tasks
    if any(kw in task_lower for kw in ["architecture", "design", "build", "implement", "system", "api", "database", "code", "technical", "infrastructure"]):
        selected.append("architect")
    
    # Business tasks
    if any(kw in task_lower for kw in ["business", "market", "strategy", "launch", "product", "revenue", "pricing", "customer", "competition", "growth"]):
        selected.append("strategist")
    
    # Risk-sensitive tasks
    if any(kw in task_lower for kw in ["production", "deploy", "security", "risk", "compliance", "scale", "critical", "important decision"]):
        selected.append("critic")
    
    # Comparison/choice tasks
    if any(kw in task_lower for kw in ["compare", "choose", "vs", "versus", "decision", "which", "better", "evaluate", "assess", "analyze"]):
        selected.append("analyst")
    
    # Always end with writer for synthesis
    selected.append("writer")
    
    return selected

def is_swarm_worthy(task: str) -> tuple:
    """
    Determine if a task should trigger swarm mode automatically
    
    Returns: (should_use_swarm: bool, reason: str)
    """
    task_lower = task.lower()
    
    # Explicit triggers
    if task.startswith("/swarm"):
        return True, "Explicit /swarm command"
    
    # Complex task indicators
    complex_keywords = [
        "architecture", "design", "strategy", "comprehensive", "detailed",
        "review", "evaluate", "assess", "analyze", "compare multiple",
        "recommendation", "should i", "vs", "versus"
    ]
    
    complex_count = sum(1 for kw in complex_keywords if kw in task_lower)
    
    if complex_count >= 2:
        return True, f"Complex task ({complex_count} complexity indicators)"
    
    # Length-based (long tasks often need multiple perspectives)
    if len(task) > 200:
        return True, "Long task description"
    
    # Multi-domain indicators
    domains = []
    if any(kw in task_lower for kw in ["technical", "architecture", "code", "system"]):
        domains.append("technical")
    if any(kw in task_lower for kw in ["business", "market", "revenue", "customer"]):
        domains.append("business")
    if any(kw in task_lower for kw in ["risk", "security", "compliance", "legal"]):
        domains.append("risk")
    
    if len(domains) >= 2:
        return True, f"Multi-domain task ({', '.join(domains)})"
    
    return False, "Simple task"

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: swarm.py [prompt|check|auto] <task>")
        print("  prompt <task>  - Generate swarm prompt for task")
        print("  check <task>   - Check if task should use swarm")
        print("  auto <task>    - Auto-select agents and show config")
        sys.exit(1)
    
    cmd = sys.argv[1]
    task = " ".join(sys.argv[2:])
    
    if cmd == "prompt":
        print(get_swarm_prompt(task))
    
    elif cmd == "check":
        should, reason = is_swarm_worthy(task)
        print(f"Swarm worthy: {should}")
        print(f"Reason: {reason}")
    
    elif cmd == "auto":
        agents = auto_select_agents(task)
        print(f"Task: {task[:100]}...")
        print(f"\nSelected agents: {', '.join(agents)}")
        print("\nGenerated prompt:")
        print("-" * 60)
        print(get_swarm_prompt(task, agents))
