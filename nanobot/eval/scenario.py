"""Scenario and criterion dataclasses for agent evaluation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable

from nanobot.providers.base import LLMResponse

# ---------------------------------------------------------------------------
# Criteria
# ---------------------------------------------------------------------------


class Criterion(ABC):
    """Base class for evaluation criteria."""

    @abstractmethod
    def evaluate(self, result: EvalResult) -> CriterionResult:
        """Evaluate this criterion against an eval result."""


@dataclass
class CriterionResult:
    """Result of evaluating a single criterion."""

    name: str
    passed: bool
    detail: str = ""


class ContainsCriterion(Criterion):
    """Pass if the final output contains the expected text."""

    def __init__(self, text: str, case_sensitive: bool = False):
        self.text = text
        self.case_sensitive = case_sensitive

    def evaluate(self, result: EvalResult) -> CriterionResult:
        output = result.final_output or ""
        haystack = output if self.case_sensitive else output.lower()
        needle = self.text if self.case_sensitive else self.text.lower()
        passed = needle in haystack
        return CriterionResult(
            name=f"contains({self.text!r})",
            passed=passed,
            detail="Found in output" if passed else "Not found in output",
        )


class ToolCalledCriterion(Criterion):
    """Pass if a specific tool was called at least *min_times*."""

    def __init__(self, tool_name: str, min_times: int = 1):
        self.tool_name = tool_name
        self.min_times = min_times

    def evaluate(self, result: EvalResult) -> CriterionResult:
        count = result.metrics.tools_called.count(self.tool_name)
        passed = count >= self.min_times
        return CriterionResult(
            name=f"tool_called({self.tool_name}, >={self.min_times})",
            passed=passed,
            detail=f"Called {count} time(s)",
        )


class NoToolCriterion(Criterion):
    """Pass if a specific tool was *never* called."""

    def __init__(self, tool_name: str):
        self.tool_name = tool_name

    def evaluate(self, result: EvalResult) -> CriterionResult:
        count = result.metrics.tools_called.count(self.tool_name)
        passed = count == 0
        return CriterionResult(
            name=f"no_tool({self.tool_name})",
            passed=passed,
            detail="Not called" if passed else f"Called {count} time(s)",
        )


class TokenBudgetCriterion(Criterion):
    """Pass if total tokens stayed within budget."""

    def __init__(self, max_tokens: int):
        self.max_tokens = max_tokens

    def evaluate(self, result: EvalResult) -> CriterionResult:
        used = result.metrics.total_tokens
        passed = used <= self.max_tokens
        return CriterionResult(
            name=f"token_budget(<={self.max_tokens})",
            passed=passed,
            detail=f"Used {used} tokens",
        )


class CustomCriterion(Criterion):
    """Pass if a user-supplied function returns True."""

    def __init__(self, name: str, fn: Callable[[EvalResult], bool], detail: str = ""):
        self._name = name
        self._fn = fn
        self._detail = detail

    def evaluate(self, result: EvalResult) -> CriterionResult:
        passed = self._fn(result)
        return CriterionResult(
            name=self._name,
            passed=passed,
            detail=self._detail if self._detail else ("Passed" if passed else "Failed"),
        )


# ---------------------------------------------------------------------------
# Metrics & Results
# ---------------------------------------------------------------------------


@dataclass
class EvalMetrics:
    """Metrics captured during an evaluation run."""

    total_tokens: int = 0
    total_iterations: int = 0
    tools_called: list[str] = field(default_factory=list)
    duration_ms: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class EvalResult:
    """Complete result of running a scenario."""

    scenario_name: str
    final_output: str | None = None
    criteria_results: list[CriterionResult] = field(default_factory=list)
    metrics: EvalMetrics = field(default_factory=EvalMetrics)

    @property
    def passed(self) -> bool:
        """True if all criteria passed."""
        return all(cr.passed for cr in self.criteria_results)

    def summary(self) -> str:
        """Human-readable summary."""
        status = "PASS" if self.passed else "FAIL"
        lines = [f"[{status}] {self.scenario_name}"]
        for cr in self.criteria_results:
            mark = "+" if cr.passed else "-"
            lines.append(f"  [{mark}] {cr.name}: {cr.detail}")
        m = self.metrics
        lines.append(
            f"  Metrics: {m.total_iterations} iterations, "
            f"{m.total_tokens} tokens, {m.duration_ms}ms, "
            f"tools={m.tools_called}"
        )
        if m.errors:
            lines.append(f"  Errors: {m.errors}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Scenario
# ---------------------------------------------------------------------------


@dataclass
class Scenario:
    """A reproducible evaluation scenario for the agent loop.

    Uses a list of scripted LLM responses to drive the agent deterministically.
    """

    name: str
    description: str
    user_messages: list[str]
    scripted_responses: list[LLMResponse]
    tool_results: dict[str, str] = field(default_factory=dict)
    criteria: list[Criterion] = field(default_factory=list)
    max_iterations: int = 20
