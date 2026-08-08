"""
LUMINA C2 v2.5.0 — Multi-Agent Orchestrator
Async Executive Solutions | Wildwulfie Studios



Five specialized agents coordinated by a central COORDINATOR.
Boss talks to COORDINATOR in plain language.
COORDINATOR breaks the task down and delegates to specialists.
Specialists execute in parallel where possible.
Results assembled and delivered back to Boss.

COORDINATOR  — routes, delegates, assembles final output
RESEARCHER   — deep research via Perplexity + NVIDIA
WRITER       — client-facing reports, polished long-form content
ANALYST      — crypto, finance, market data, pattern recognition
MONITOR      — watches feeds, surfaces proactive intelligence
EXECUTOR     — browser automation, web actions, form fills (Web 4.0)

Each agent has:
- Its own system prompt and personality
- Its own preferred models
- Its own memory context slice
- Its own task queue
- Its own tool access

Agents communicate through the orchestrator — never directly.
Boss communicates only with COORDINATOR.
"""

import asyncio
import json
import uuid
import time
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, field
from enum import Enum

from memory_manager import memory
from perplexica_client import perplexica as perplexity  # self-hosted, zero cost
from nvidia_client import nvidia, NimModel, TaskType
from bitnet_client import bitnet, should_use_local
from situational_awareness import awareness
from trigger_engine import triggers, Alert, AlertCategory, AlertLevel
from obsidian_client import obsidian


# ── AGENT DEFINITIONS ─────────────────────────────

class AgentRole(str, Enum):
    COORDINATOR = "coordinator"
    RESEARCHER  = "researcher"
    WRITER      = "writer"
    ANALYST     = "analyst"
    MONITOR     = "monitor"
    EXECUTOR    = "executor"


AGENT_SYSTEM_PROMPTS = {

    AgentRole.COORDINATOR: """
You are Lumina (COORDINATOR) — the central intelligence and voice of the Lumina C2 system.
You work for Boss (Brent Wilf) at Async Executive Solutions.

Your job is to:
1. Understand what Boss needs from a plain language request
2. Break it into subtasks for the right specialist agents
3. Delegate clearly and efficiently
4. Assemble the results into a coherent final output
5. Deliver directly to Boss — no fluff, no filler

Boss hates redundant questions and incomplete work.
Do the job right the first time.
Be direct. Be fast. Be accurate.
Every task you coordinate contributes to reaching $10,000/month by May 9th.
""",

    AgentRole.RESEARCHER: """
You are Lumina (RESEARCHER) — the deep research specialist of the Lumina C2 system.
You have access to Perplexity real-time search and NVIDIA NIM models.

Your job is to:
1. Find accurate, current, cited information on any topic
2. Synthesize multiple sources into clear findings
3. Structure research for direct use in client deliverables
4. Flag anything uncertain or requiring verification

Be comprehensive. Cite sources. Be factual.
Research is the foundation everything else is built on — get it right.
""",

    AgentRole.WRITER: """
You are Lumina (WRITER) — the content and report specialist of the Lumina C2 system.
You produce professional deliverables that clients pay for.

Your job is to:
1. Take research findings and turn them into polished reports
2. Match the tone and format the client expects
3. Write executive summaries, full reports, briefs, analyses
4. Never sound like AI — sound like an expert who did the work

Report structure: Executive summary first. Key findings second. 
Supporting detail third. Conclusion and recommendations last.
Professional tone. Direct. No corporate fluff. No filler sentences.
""",

    AgentRole.ANALYST: """
You are Lumina (ANALYST) — the market and financial intelligence specialist.
You handle crypto, finance, market data, competitive analysis, and pattern recognition.

Your job is to:
1. Interpret market data and price action
2. Identify patterns and trends in financial data
3. Produce crypto and market analysis with specific numbers
4. Flag significant movements and opportunities

Be specific. Use numbers. Use dates. Cite sources.
Analysis without specifics is worthless — give Boss actionable intelligence.
""",

    AgentRole.MONITOR: """
You are Lumina (MONITOR) — the proactive intelligence specialist.
You watch things without being asked and surface what matters.

Your job is to:
1. Continuously scan Upwork for job opportunities matching Boss's skills
2. Watch crypto markets for significant movements
3. Monitor news in client industries
4. Flag anything Boss needs to know before he asks

Be proactive. Be specific. Be timely.
If something matters — surface it immediately.
""",

    AgentRole.EXECUTOR: """
You are Lumina (EXECUTOR) — the web action and automation specialist.
You are the Web 4.0 agent — you don't just read the web, you operate within it.

Your job is to:
1. Navigate web interfaces autonomously via browser automation
2. Extract data from dynamic web pages
3. Execute sequences of web actions (search, navigate, extract, report)
4. Handle multi-step web workflows

Be precise. Verify actions before executing.
Report exactly what was done and what was found.
""",
}


# ── AGENT TASK ────────────────────────────────────

@dataclass
class AgentTask:
    id:          str
    role:        AgentRole
    instruction: str
    context:     str            = ""
    depends_on:  list           = field(default_factory=list)
    result:      Optional[str]  = None
    citations:   list           = field(default_factory=list)
    status:      str            = "pending"  # pending | running | complete | failed
    model_used:  str            = ""
    started_at:  Optional[str]  = None
    completed_at: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "id":          self.id,
            "role":        self.role.value,
            "instruction": self.instruction[:200],
            "status":      self.status,
            "model_used":  self.model_used,
            "result":      self.result[:300] if self.result else None,
            "citations":   self.citations[:3],
            "started_at":  self.started_at,
            "completed_at": self.completed_at,
        }


# ── ORCHESTRATION PLAN ────────────────────────────

@dataclass
class OrchestrationPlan:
    id:            str
    original_task: str
    tasks:         list[AgentTask] = field(default_factory=list)
    status:        str             = "planning"
    final_result:  Optional[str]   = None
    started_at:    str             = field(default_factory=lambda: datetime.now().isoformat())
    completed_at:  Optional[str]   = None

    def to_dict(self) -> dict:
        return {
            "id":            self.id,
            "original_task": self.original_task[:200],
            "status":        self.status,
            "tasks":         [t.to_dict() for t in self.tasks],
            "final_result":  self.final_result[:500] if self.final_result else None,
            "started_at":    self.started_at,
            "completed_at":  self.completed_at,
            "task_count":    len(self.tasks),
            "completed_count": sum(1 for t in self.tasks if t.status == "complete"),
        }


# ── AGENT EXECUTOR ────────────────────────────────

class AgentExecutor:
    """Executes a single agent task using the right model and tools."""

    async def run(self, task: AgentTask, plan_context: str = "") -> AgentTask:
        task.status     = "running"
        task.started_at = datetime.now().isoformat()
        full_prompt     = self._build_prompt(task, plan_context)

        try:
            # ── BITNET LOCAL FAST PATH ─────────────────────
            # Simple/short tasks route to BitNet on Oracle ARM.
            # Zero API cost, <1 sec, no external call.
            # But live web-data tasks must route through Perplexica.
            needs_live = perplexity.detect_needs_perplexica(task.instruction)
            if (not needs_live) and should_use_local(task.instruction) and await bitnet.check_health():
                result = await self._run_bitnet(task, full_prompt)
            elif task.role == AgentRole.RESEARCHER:
                result = await self._run_researcher(task, full_prompt)
            elif task.role == AgentRole.WRITER:
                result = await self._run_writer(task, full_prompt)
            elif task.role == AgentRole.ANALYST:
                result = await self._run_analyst(task, full_prompt)
            elif task.role == AgentRole.MONITOR:
                result = await self._run_monitor(task, full_prompt)
            elif task.role == AgentRole.EXECUTOR:
                result = await self._run_executor(task, full_prompt)
            else:
                result = await self._run_nvidia(task, full_prompt, NimModel.MAVERICK)

            task.result       = result
            task.status       = "complete"
            task.completed_at = datetime.now().isoformat()

        except Exception as e:
            task.result       = f"Agent error: {str(e)}"
            task.status       = "failed"
            task.completed_at = datetime.now().isoformat()
            print(f"[AGENT:{task.role.value}] Failed: {e}")

        return task

    async def _run_bitnet(self, task: AgentTask, prompt: str) -> str:
        """Fast local inference via BitNet on Oracle ARM. ~0.4GB RAM."""
        task.model_used = "BitNet b1.58 2B4T (oracle-local)"
        r = await bitnet.infer(
            prompt     = task.instruction,
            system     = memory.get_context_prompt(),
            max_tokens = 512,
        )
        return r["result"]

    def _build_prompt(self, task: AgentTask, plan_context: str) -> str:
        mem_ctx  = memory.get_context_prompt()
        sit_ctx  = awareness.get_current_context()
        return f"{mem_ctx}\n\n{sit_ctx}\n\n{plan_context}\n\n---\n\nINSTRUCTION: {task.instruction}"

    async def _run_researcher(self, task: AgentTask, prompt: str) -> str:
        # Use Perplexity for real-time research
        needs_live = perplexity.detect_needs_perplexica(task.instruction)
        if needs_live:
            result = await perplexity.research_report(task.instruction)
            task.citations = result.get("citations", [])[:5]
            task.model_used = result.get("model", "perplexity-sonar-pro")
            return result["answer"]
        else:
            task.model_used = NimModel.MAVERICK.value
            return await nvidia.complete(prompt,
                task_type=TaskType.DEEP_RESEARCH,
                model=NimModel.MAVERICK)

    async def _run_writer(self, task: AgentTask, prompt: str) -> str:
        task.model_used = NimModel.LLAMA70B.value
        return await nvidia.complete(prompt,
            task_type=TaskType.REPORT_WRITING,
            model=NimModel.LLAMA70B,
            max_tokens=3000)

    async def _run_analyst(self, task: AgentTask, prompt: str) -> str:
        # Use DeepSeek for complex financial reasoning
        needs_live = perplexity.detect_needs_perplexica(task.instruction)
        if needs_live:
            result = await perplexity.market_intelligence(task.instruction)
            task.citations  = result.get("citations", [])[:5]
            task.model_used = "perplexity-sonar-pro"
            # Enhance with DeepSeek reasoning
            enhanced = await nvidia.complete(
                f"Given this market data:\n\n{result['answer']}\n\nProvide deep analysis and specific actionable insights.",
                task_type=TaskType.ANALYSIS,
                model=NimModel.DEEPSEEK)
            return enhanced
        task.model_used = NimModel.DEEPSEEK.value
        return await nvidia.complete(prompt,
            task_type=TaskType.ANALYSIS,
            model=NimModel.DEEPSEEK)

    async def _run_monitor(self, task: AgentTask, prompt: str) -> str:
        # Monitor uses Perplexity for live feeds
        result = await perplexity.search(task.instruction, mode="fast")
        task.citations  = result.get("citations", [])[:3]
        task.model_used = "perplexity-sonar"
        return result["answer"]

    async def _run_executor(self, task: AgentTask, prompt: str) -> str:
        # Executor describes web actions — browser MCP handles actual execution
        task.model_used = NimModel.SCOUT.value
        plan = await nvidia.complete(
            f"Create a step-by-step web automation plan for: {task.instruction}\n"
            "List each action precisely. Include: URL, action type, data to enter or extract.",
            task_type=TaskType.QUICK_LOOKUP,
            model=NimModel.SCOUT)
        return f"WEB ACTION PLAN:\n{plan}"

    async def _run_nvidia(self, task: AgentTask, prompt: str, model: NimModel) -> str:
        task.model_used = model.value
        return await nvidia.complete(prompt, model=model)


# ── COORDINATOR ───────────────────────────────────

class Coordinator:
    """
    The central brain. Boss talks to this.
    It figures out what's needed and delegates.
    """

    async def plan(self, task: str, client_name: str = None) -> OrchestrationPlan:
        """
        Use NVIDIA to generate an orchestration plan.
        Returns a structured plan with agent assignments.
        """
        mem_ctx  = memory.get_context_prompt()
        sit_ctx  = awareness.get_current_context()
        pref     = memory.get_preference("report_style", "Professional and direct")

        planning_prompt = f"""
{mem_ctx}

{sit_ctx}

You are COORDINATOR for Lumina C2. 
{'Client: ' + client_name if client_name else ''}
Writing preference: {pref}

TASK FROM BOSS: {task}

Create a concise orchestration plan. Respond ONLY with valid JSON:
{{
  "analysis": "one sentence describing what this task needs",
  "parallel": true or false (can subtasks run simultaneously),
  "subtasks": [
    {{
      "role": "researcher|writer|analyst|monitor|executor",
      "instruction": "specific instruction for this agent",
      "depends_on": [] or [index of subtask this depends on]
    }}
  ],
  "assembly_instruction": "how to combine subtask results into final output"
}}

Use only roles that are genuinely needed. Keep it lean.
Researcher for information gathering.
Writer for polished output.
Analyst for market/financial/crypto work.
Monitor for live feed checks.
Executor for web actions.
"""
        try:
            raw = await nvidia.complete(
                planning_prompt,
                task_type=TaskType.ANALYSIS,
                model=NimModel.DEEPSEEK,
                max_tokens=1000,
                temperature=0.1,
            )
            # Extract JSON from response
            import re
            match = re.search(r'\{.*\}', raw, re.DOTALL)
            if not match:
                raise ValueError("No JSON in coordinator response")
            plan_data = json.loads(match.group())
        except Exception as e:
            print(f"[COORDINATOR] Planning failed: {e} — using default plan")
            plan_data = {
                "analysis": "Direct task",
                "parallel": False,
                "subtasks": [{"role": "researcher", "instruction": task, "depends_on": []}],
                "assembly_instruction": "Return research result directly",
            }

        plan = OrchestrationPlan(id=str(uuid.uuid4())[:8], original_task=task)
        for i, st in enumerate(plan_data.get("subtasks", [])):
            try:
                role = AgentRole(st["role"])
            except ValueError:
                role = AgentRole.RESEARCHER
            plan.tasks.append(AgentTask(
                id=str(uuid.uuid4())[:8],
                role=role,
                instruction=st["instruction"],
                depends_on=st.get("depends_on", []),
            ))
        return plan

    async def assemble(self, plan: OrchestrationPlan,
                        assembly_instruction: str = "") -> str:
        """Assemble completed subtask results into final output."""
        completed = [t for t in plan.tasks if t.status == "complete" and t.result]
        if not completed:
            return "No results from agents."
        if len(completed) == 1:
            return completed[0].result

        # Multi-agent — WRITER assembles the pieces
        results_block = "\n\n---\n\n".join([
            f"[{t.role.value.upper()}]\n{t.result}"
            for t in completed
        ])
        all_citations = []
        for t in completed:
            all_citations.extend(t.citations)

        assembly_prompt = f"""
{memory.get_context_prompt()}

You are WRITER assembling a final report for Boss.
{assembly_instruction}

AGENT RESULTS TO SYNTHESIZE:
{results_block}

Produce the final polished output. 
Executive summary first. Key findings second. Details third.
Professional tone. No filler. Direct.
"""
        try:
            result = await nvidia.complete(
                assembly_prompt,
                task_type=TaskType.REPORT_WRITING,
                model=NimModel.LLAMA70B,
                max_tokens=3000,
            )
            if all_citations:
                result += f"\n\n**Sources:**\n" + "\n".join(
                    f"- {c}" for c in all_citations[:10]
                )
            return result
        except Exception as e:
            return results_block  # Fallback — return raw results


# ── MULTI-AGENT ORCHESTRATOR ─────────────────────

class MultiAgentOrchestrator:
    """
    Friday. The full system.
    Boss gives a task. This handles everything.
    """

    def __init__(self):
        self.coordinator = Coordinator()
        self.executor    = AgentExecutor()
        self._active_plans: dict[str, OrchestrationPlan] = {}
        self._plan_history: list[OrchestrationPlan]      = []
        self.MAX_HISTORY = 50

    async def run(
        self,
        task: str,
        client_name: str  = None,
        job_id: str       = None,
        write_obsidian: bool = True,
    ) -> dict:
        """
        Main entry point. Boss sends task. Friday handles it.
        Returns final result with full plan trace.
        """
        print(f"[FRIDAY] Task received: {task[:80]}")
        start = time.time()

        # 1 — COORDINATOR plans
        plan = await self.coordinator.plan(task, client_name)
        plan.status = "running"
        self._active_plans[plan.id] = plan
        assembly_instruction = ""

        try:
            # 2 — Execute agents
            # Group by dependency level for parallel execution
            independent = [t for t in plan.tasks if not t.depends_on]
            dependent   = [t for t in plan.tasks if t.depends_on]

            plan_context = f"ORCHESTRATION PLAN: {plan.id}\nORIGINAL TASK: {task}"

            # Run independent tasks in parallel
            if independent:
                await asyncio.gather(*[
                    self.executor.run(t, plan_context) for t in independent
                ])

            # Run dependent tasks sequentially with results context
            for dep_task in dependent:
                prior_results = "\n\n".join([
                    f"[{plan.tasks[i].role.value.upper()} RESULT]: {plan.tasks[i].result or 'No result'}"
                    for i in dep_task.depends_on
                    if i < len(plan.tasks) and plan.tasks[i].result
                ])
                if prior_results:
                    dep_task.instruction += f"\n\nPRIOR AGENT RESULTS:\n{prior_results}"
                await self.executor.run(dep_task, plan_context)

            # 3 — COORDINATOR assembles
            final = await self.coordinator.assemble(plan, assembly_instruction)
            plan.final_result  = final
            plan.status        = "complete"
            plan.completed_at  = datetime.now().isoformat()

            elapsed = round(time.time() - start, 1)
            print(f"[FRIDAY] Complete in {elapsed}s — {len(plan.tasks)} agents")

            # 4 — Write to Obsidian
            if write_obsidian and job_id:
                try:
                    all_cites = []
                    for t in plan.tasks: all_cites.extend(t.citations)
                    await obsidian.write_job_report(
                        title=task[:60], platform="multi-agent",
                        prompt=task, result=final,
                        model_used=f"multi-agent({len(plan.tasks)})",
                        client_name=client_name, citations=all_cites,
                    )
                except Exception as e:
                    print(f"[FRIDAY] Obsidian write failed: {e}")

            # 5 — Revenue milestone check
            memory.sync_if_due()

            return {
                "status":       "complete",
                "plan_id":      plan.id,
                "result":       final,
                "agents_used":  [t.role.value for t in plan.tasks],
                "elapsed_s":    elapsed,
                "task_count":   len(plan.tasks),
                "citations":    sum(len(t.citations) for t in plan.tasks),
                "plan":         plan.to_dict(),
            }

        except Exception as e:
            plan.status = "failed"
            plan.completed_at = datetime.now().isoformat()
            print(f"[FRIDAY] Orchestration failed: {e}")
            return {
                "status":  "failed",
                "plan_id": plan.id,
                "error":   str(e),
                "plan":    plan.to_dict(),
            }
        finally:
            self._active_plans.pop(plan.id, None)
            self._plan_history.insert(0, plan)
            if len(self._plan_history) > self.MAX_HISTORY:
                self._plan_history = self._plan_history[:self.MAX_HISTORY]

    def get_active(self) -> list[dict]:
        return [p.to_dict() for p in self._active_plans.values()]

    def get_history(self, limit: int = 20) -> list[dict]:
        return [p.to_dict() for p in self._plan_history[:limit]]

    def stats(self) -> dict:
        total     = len(self._plan_history)
        completed = sum(1 for p in self._plan_history if p.status == "complete")
        failed    = sum(1 for p in self._plan_history if p.status == "failed")
        return {
            "total_plans":    total,
            "completed":      completed,
            "failed":         failed,
            "active":         len(self._active_plans),
            "success_rate":   f"{(completed/total*100):.0f}%" if total > 0 else "N/A",
        }


# Singleton — this is Friday
friday = MultiAgentOrchestrator()
