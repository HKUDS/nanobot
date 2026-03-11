"""Gateway runtime compatibility framework.

Read order for new contributors:
1) models.py  -> shared data contracts.
2) policy.py  -> mode decision (CLI/env/rollout).
3) facade.py  -> command-facing orchestration.
4) adapters/  -> execution backend implementations.
"""

from nanobot.gateway_runtime.models import RuntimeMode, RuntimePolicy
from nanobot.gateway_runtime.policy import resolve_runtime_policy

__all__ = [
    "RuntimeMode",
    "RuntimePolicy",
    "resolve_runtime_policy",
]
