"""Prompt templates for reasoning engine.

All prompts are centralized here for easy maintenance and localization.
"""


class PromptTemplates:
    """Prompt templates for reasoning engine"""
    # Planning prompts
    PLANNING_SYSTEM = """You are an AI assistant skilled in task planning. Please analyze the task and create a detailed execution plan."""

    PLANNING_JSON_SCHEMA = """Please output the plan in the following JSON format:
        
        {{
          "goal": "Core objective of the task (one sentence)",
          "analysis": "Task analysis: What needs to be done? What are the challenges? What information is needed?",
          "steps": [
            {{
              "id": 1,
              "action": "Specific action to perform (clear, executable)",
              "tool": "Name of the tool to use (e.g., web_search, read_file, exec, write_file, etc.)",
              "expected": "Expected result",
              "rationale": "Why is this step needed?"
            }}
          ],
          "success_criteria": "How to judge if the task is truly completed? List clear criteria",
          "estimated_iterations": "Estimated number of tool calls needed"
        }}
        
        Planning principles:
        1. Steps should be specific, executable, and sequential
        2. Each step does only one thing, don't combine multiple operations
        3. Consider possible failure scenarios and backup plans
        4. Number of steps: 2-3 for simple tasks, 5-8 for complex tasks
        5. The tool field must be an actual existing tool name: {available_tools}
        
        Please output ONLY the JSON, no other content."""

    PLANNING_WITH_CONTEXT = """Task: {task}
        Additional context: {context}
        """

    PLANNING_WITHOUT_CONTEXT = """Task: {task}

    """

    # Reflection prompts
    REFLECTION_SYSTEM = """Please reflect on the execution step just completed."""

    REFLECTION_TEMPLATE = """Planned step:
        - Action: {action}
        - Expected tool: {expected_tool}
        - Expected result: {expected_result}
        
        Actual execution:
        - Tools used: {actual_tools}
        - Actual result: {actual_result}
        
        Please evaluate:
        1. Was this step successful?
        2. Did the result meet expectations?
        3. Are there any noteworthy insights?
        4. Does the subsequent plan need adjustment?
        
        Output in JSON format:
        {{
          "success": true/false,
          "insights": "Key insights and discoveries",
          "needs_adjustment": true/false,
          "suggested_adjustment": "If adjustment is needed, how should it be adjusted?"
        }}
        
        Please output ONLY the JSON, no other content."""

    # Verification prompts
    VERIFICATION_SYSTEM = """Please verify whether the task is truly completed."""

    VERIFICATION_TEMPLATE = """Original task:
        {original_task}
        
        Execution plan:
        {plan}
        
        Final result:
        {final_result}
        
        Please evaluate from the following dimensions:
        1. Is the task completed? (Compare with success_criteria)
        2. How is the completion quality? (0-1 score)
        3. Are there any missing items?
        4. Are there any obvious problems or errors?
        5. Any improvement suggestions?
        
        Output in JSON format:
        {{
          "task_completed": true/false,
          "quality_score": 0.0-1.0,
          "missing_items": ["missing_item_1", "missing_item_2"],
          "issues": ["issue_1", "issue_2"],
          "recommendations": ["recommendation_1", "recommendation_2"]
        }}
        
        Please output ONLY the JSON, no other content."""

    @classmethod
    def build_planning_prompt(cls, task: str, available_tools: list[str], context: str | None = None) -> str:
        """Build planning prompt"""
        # Build task section
        if context:
            task_section = cls.PLANNING_WITH_CONTEXT.format(
                task=task,
                context=context
            )
        else:
            task_section = cls.PLANNING_WITHOUT_CONTEXT.format(task=task)

        # Build available tools list
        tools_str = "\n ".join(available_tools)

        # Build JSON schema with tools
        json_schema = cls.PLANNING_JSON_SCHEMA.format(available_tools=tools_str)

        # Combine all parts
        return f"""{cls.PLANNING_SYSTEM}
                {task_section}
                {json_schema}"""

    @classmethod
    def build_reflection_prompt(
        cls,
        action: str,
        expected_tool: str,
        expected_result: str,
        actual_tools: list[str],
        actual_result: str
    ) -> str:
        """Build reflection prompt"""
        return f"""{cls.REFLECTION_SYSTEM}
            {cls.REFLECTION_TEMPLATE.format(
                        action=action,
                        expected_tool=expected_tool,
                        expected_result=expected_result,
                        actual_tools=", ".join(actual_tools),
                        actual_result=actual_result[:500]
                    )}"""

    @classmethod
    def build_verification_prompt(
        cls,
        original_task: str,
        plan: str,
        final_result: str
    ) -> str:
        """Build verification prompt"""
        return f"""{cls.VERIFICATION_SYSTEM}

            {cls.VERIFICATION_TEMPLATE.format(
                        original_task=original_task,
                        plan=plan,
                        final_result=final_result[:1000]
                    )}"""
