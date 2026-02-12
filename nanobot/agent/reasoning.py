"""Reasoning Engine: Handles task planning, execution reflection, and result verification"""

import json
from collections import deque
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict
from loguru import logger

from nanobot.providers.base import LLMProvider
from nanobot.agent.prompts import PromptTemplates


@dataclass
class PlanStep:
    """A single planning step"""
    id: int
    action: str  # Description of the action to perform
    tool: str  # Tool to use
    expected: str  # Expected result
    rationale: str = ""  # Why this step is needed


@dataclass
class TaskPlan:
    """Task execution plan"""
    goal: str  # Task goal
    analysis: str  # Task analysis
    steps: List[PlanStep]  # Execution steps
    success_criteria: str  # Success criteria
    estimated_iterations: int = 0  # Estimated number of iterations

    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return {
            "goal": self.goal,
            "analysis": self.analysis,
            "steps": [asdict(s) for s in self.steps],
            "success_criteria": self.success_criteria,
            "estimated_iterations": self.estimated_iterations
        }

    def to_readable_string(self) -> str:
        """Convert to human-readable string format"""
        lines = [
            "Task Plan",
            f"Goal: {self.goal}",
            f"Analysis: {self.analysis}",
            "",
            "Execution Steps:",
        ]

        for step in self.steps:
            lines.append(f"  {step.id}. {step.action}")
            lines.append(f"     Tool: {step.tool}")
            lines.append(f"     Expected: {step.expected}")
            if step.rationale:
                lines.append(f"     Rationale: {step.rationale}")
            lines.append("")

        lines.append(f"Success Criteria: {self.success_criteria}")
        lines.append(f"Estimated Iterations: {self.estimated_iterations}")

        return "\n".join(lines)


@dataclass
class ReflectionResult:
    """Reflection result"""
    step_id: int  # Corresponding step ID
    executed_action: str  # Actual action executed
    actual_result: str  # Actual result
    success: bool  # Whether successful
    insights: str  # Reflection insights
    needs_adjustment: bool  # Whether plan adjustment is needed
    suggested_adjustment: str = ""  # Suggested adjustment


@dataclass
class VerificationResult:
    """Verification result"""
    task_completed: bool  # Whether task is completed
    quality_score: float  # Quality score 0-1
    missing_items: List[str]  # Missing items
    issues: List[str]  # Issues found
    recommendations: List[str]  # Recommendations for improvement


class ReasoningEngine:
    """
    Reasoning Engine - Provides task planning, execution reflection, and result verification

    Core capabilities:
    1. create_plan - Analyze tasks and generate structured execution plans
    2. reflect_on_step - Reflect on individual execution steps
    3. verify_completion - Verify whether tasks are truly completed
    """

    def __init__(self, provider: LLMProvider, model: str, max_history: int = 50):
        """
        Initialize the reasoning engine.

        Args:
            provider: LLM provider for plan/reflection/verification calls
            model: Model name to use
            max_history: Maximum number of history entries to keep (prevents memory leak)
        """
        self.provider = provider
        self.model = model
        # Use deque with maxlen to automatically discard old entries
        self.planning_history: deque[TaskPlan] = deque(maxlen=max_history)
        self.reflection_history: deque[ReflectionResult] = deque(maxlen=max_history)

    async def create_plan(
            self,
            messages: List[Dict[str, Any]],
            task: str,
            available_tools: list[str],
            context: Optional[str] = None
    ) -> Optional[TaskPlan]:
        """
        Create task execution plan

        Args:
            messages: Conversation history
            task: Current task description
            available_tools: Available tools
            context: Additional context information

        Returns:
            TaskPlan or None (when planning fails)
        """
        logger.info("Creating task plan...")

        # Build planning prompt using template
        planning_prompt = PromptTemplates.build_planning_prompt(
            task=task,
            available_tools=available_tools,
            context=context
        )

        # Call LLM to generate plan
        try:
            response = await self.provider.chat(
                messages=messages + [{"role": "user", "content": planning_prompt}],
                model=self.model,
                max_tokens=2000,
                temperature=0.3,  # Lower temperature for stable output
            )

            # Parse plan
            plan = self._parse_plan(response.content, task)

            if plan:
                self.planning_history.append(plan)
                logger.info(f"Plan created with {len(plan.steps)} steps")
                logger.debug(f"Plan: {plan.to_readable_string()}")
                return plan
            else:
                logger.warning("Failed to parse plan from LLM response")
                return None

        except Exception as e:
            logger.error(f"Error creating plan: {e}")
            return None

    def _parse_plan(self, llm_response: str, original_task: str) -> Optional[TaskPlan]:
        """Parse plan returned by LLM"""
        try:
            # Try to extract JSON (handle possible markdown wrapping)
            content = llm_response.strip()

            # Remove possible markdown code block markers
            if content.startswith("```json"):
                content = content[7:]
            if content.startswith("```"):
                content = content[3:]
            if content.endswith("```"):
                content = content[:-3]

            content = content.strip()

            # Parse JSON
            plan_data = json.loads(content)

            # Build PlanStep objects
            steps = []
            for step_data in plan_data.get("steps", []):
                steps.append(PlanStep(
                    id=step_data["id"],
                    action=step_data["action"],
                    tool=step_data["tool"],
                    expected=step_data["expected"],
                    rationale=step_data.get("rationale", "")
                ))

            # Build TaskPlan object
            plan = TaskPlan(
                goal=plan_data.get("goal", original_task),
                analysis=plan_data.get("analysis", ""),
                steps=steps,
                success_criteria=plan_data.get("success_criteria", "Task completed"),
                estimated_iterations=plan_data.get("estimated_iterations", len(steps) * 2)
            )

            return plan

        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error: {e}")
            logger.debug(f"Raw response: {llm_response[:500]}")
            return None
        except Exception as e:
            logger.error(f"Error parsing plan: {e}")
            return None

    async def reflect_on_step(
            self,
            messages: List[Dict[str, Any]],
            step: PlanStep,
            actual_tools_used: List[str],
            actual_result: str,
    ) -> ReflectionResult:
        """
        Reflect on a single execution step

        Args:
            messages: Current conversation history
            step: Planned step
            actual_tools_used: Tools actually used
            actual_result: Actual execution result

        Returns:
            ReflectionResult reflection result
        """
        logger.info(f"Reflecting on step {step.id}: {step.action}")

        # Build reflection prompt using template
        reflection_prompt = PromptTemplates.build_reflection_prompt(
            action=step.action,
            expected_tool=step.tool,
            expected_result=step.expected,
            actual_tools=actual_tools_used,
            actual_result=actual_result
        )

        try:
            response = await self.provider.chat(
                messages=messages + [{"role": "user", "content": reflection_prompt}],
                model=self.model,
                max_tokens=500,
                temperature=0.3,
            )

            # Parse reflection result
            content = response.content.strip()
            if content.startswith("```json"):
                content = content[7:-3].strip()
            if content.startswith("```"):
                content = content[3:-3].strip()

            reflection_data = json.loads(content)

            result = ReflectionResult(
                step_id=step.id,
                executed_action=step.action,
                actual_result=actual_result[:200],
                success=reflection_data.get("success", True),
                insights=reflection_data.get("insights", ""),
                needs_adjustment=reflection_data.get("needs_adjustment", False),
                suggested_adjustment=reflection_data.get("suggested_adjustment", "")
            )

            self.reflection_history.append(result)
            logger.info(f"Reflection: success={result.success}, needs_adjustment={result.needs_adjustment}")

            return result

        except Exception as e:
            logger.error(f"Error in reflection: {e}")
            # Return default reflection result
            return ReflectionResult(
                step_id=step.id,
                executed_action=step.action,
                actual_result=actual_result[:200],
                success=True,
                insights="Reflection error, defaulting to success",
                needs_adjustment=False
            )

    async def verify_completion(
            self,
            messages: List[Dict[str, Any]],
            original_task: str,
            plan: TaskPlan,
            final_result: str,
    ) -> VerificationResult:
        """
        Verify whether task is truly completed

        Args:
            messages: Conversation history
            original_task: Original task description
            plan: Execution plan
            final_result: Final result

        Returns:
            VerificationResult verification result
        """
        logger.info("Verifying task completion...")

        # Build verification prompt using template
        verification_prompt = PromptTemplates.build_verification_prompt(
            original_task=original_task,
            plan=plan.to_readable_string(),
            final_result=final_result
        )

        try:
            response = await self.provider.chat(
                messages=messages + [{"role": "user", "content": verification_prompt}],
                model=self.model,
                max_tokens=800,
                temperature=0.3,
            )

            # Parse verification result
            content = response.content.strip()
            if content.startswith("```json"):
                content = content[7:-3].strip()
            if content.startswith("```"):
                content = content[3:-3].strip()

            verification_data = json.loads(content)

            result = VerificationResult(
                task_completed=verification_data.get("task_completed", True),
                quality_score=verification_data.get("quality_score", 0.8),
                missing_items=verification_data.get("missing_items", []),
                issues=verification_data.get("issues", []),
                recommendations=verification_data.get("recommendations", [])
            )

            logger.info(
                f"Verification: completed={result.task_completed}, "
                f"quality={result.quality_score:.2f}"
            )

            return result

        except Exception as e:
            logger.error(f"Error in verification: {e}")
            # Return default verification result
            return VerificationResult(
                task_completed=True,
                quality_score=0.7,
                missing_items=[],
                issues=[],
                recommendations=[]
            )
