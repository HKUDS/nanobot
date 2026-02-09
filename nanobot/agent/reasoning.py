"""Reasoning Engine: Handles task planning, execution reflection, and result verification"""

import json
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict
from loguru import logger

from nanobot.providers.base import LLMProvider


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

    def __init__(self, provider: LLMProvider, model: str):
        self.provider = provider
        self.model = model
        self.planning_history: List[TaskPlan] = []
        self.reflection_history: List[ReflectionResult] = []

    async def create_plan(
            self,
            messages: List[Dict[str, Any]],
            task: str,
            context: Optional[str] = None
    ) -> Optional[TaskPlan]:
        """
        Create task execution plan

        Args:
            messages: Conversation history
            task: Current task description
            context: Additional context information

        Returns:
            TaskPlan or None (when planning fails)
        """
        logger.info("Creating task plan...")

        # Build planning prompt
        planning_prompt = self._build_planning_prompt(task, context)

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

    def _build_planning_prompt(self, task: str, context: Optional[str] = None) -> str:
        """Build planning prompt"""
        prompt = f"""你是一个擅长任务规划的AI助手。请分析以下任务并制定详细的执行计划。

任务：{task}
"""

        if context:
            prompt += f"\n补充上下文：{context}\n"

        prompt += """
请按以下JSON格式输出计划：

{
  "goal": "任务的核心目标（一句话概括）",
  "analysis": "任务分析：需要做什么？有哪些挑战？需要哪些信息？",
  "steps": [
    {
      "id": 1,
      "action": "具体要执行的操作（清晰、可执行）",
      "tool": "需要使用的工具名称（如：web_search, read_file, exec, write_file等）",
      "expected": "期望得到的结果",
      "rationale": "为什么需要这一步？"
    }
  ],
  "success_criteria": "如何判断任务真正完成？列出明确的标准",
  "estimated_iterations": "预估需要的工具调用次数"
}

规划原则：
1. 步骤要具体、可执行、有先后顺序
2. 每步只做一件事，不要合并多个操作
3. 考虑可能的失败情况和备选方案
4. 步骤数量：简单任务2-3步，复杂任务5-8步
5. tool字段必须是实际存在的工具名称

请只输出JSON，不要其他内容。"""

        return prompt

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

        reflection_prompt = f"""请反思刚才的执行步骤：

计划的步骤：
- 操作: {step.action}
- 预期工具: {step.tool}
- 预期结果: {step.expected}

实际执行：
- 使用的工具: {', '.join(actual_tools_used)}
- 实际结果: {actual_result[:500]}

请评估：
1. 这一步是否成功？
2. 结果是否符合预期？
3. 有什么值得注意的洞察？
4. 是否需要调整后续计划？

输出JSON格式：
{{
  "success": true/false,
  "insights": "关键洞察和发现",
  "needs_adjustment": true/false,
  "suggested_adjustment": "如果需要调整，建议如何调整"
}}

只输出JSON，不要其他内容。"""

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

        verification_prompt = f"""请验证任务是否真正完成。

原始任务：
{original_task}

执行计划：
{plan.to_readable_string()}

最终结果：
{final_result[:1000]}

请从以下维度评估：
1. 任务是否完成？（对照success_criteria）
2. 完成质量如何？（0-1分）
3. 是否有遗漏的项目？
4. 是否有明显的问题或错误？
5. 有什么改进建议？

输出JSON格式：
{{
  "task_completed": true/false,
  "quality_score": 0.0-1.0,
  "missing_items": ["缺失项1", "缺失项2"],
  "issues": ["问题1", "问题2"],
  "recommendations": ["建议1", "建议2"]
}}

只输出JSON，不要其他内容。"""

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
