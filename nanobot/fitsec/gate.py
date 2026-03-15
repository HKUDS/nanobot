"""
FIT-Sec Monitorability Gate
===========================
Dynamic gate based on operational usability metrics.

Key principle: execution is blocked when the detector/policy
is not *operationally usable* (not just "accurate").
"""
from __future__ import annotations
from typing import Optional

from .types import GateMetrics, GateStatus


class MonitorabilityGate:
    """
    Evaluates operational usability of safety mechanisms.

    The gate checks:
    1. FPR controllability - false positives are bounded
    2. Coverage @ target FPR - sufficient detection without FPR overflow
    3. Calibration sanity - probability outputs are reliable
    4. Lead time stability - alerts come early enough consistently
    """

    def __init__(
        self,
        fpr_target: float = 0.05,
        coverage_target: float = 0.80,
        calibration_threshold: float = 0.70,
        lead_time_cv_max: float = 0.50,
    ):
        self.fpr_target = fpr_target
        self.coverage_target = coverage_target
        self.calibration_threshold = calibration_threshold
        self.lead_time_cv_max = lead_time_cv_max

        # Current metrics (can be updated by external metric providers)
        self._metrics: Optional[GateMetrics] = None

    def update_metrics(self, metrics: GateMetrics) -> None:
        """Update gate metrics from external provider."""
        self._metrics = metrics

    def check(self, metrics: Optional[GateMetrics] = None) -> GateStatus:
        """
        Evaluate the monitorability gate.

        Returns GateStatus indicating pass/fail and reason.
        """
        m = metrics or self._metrics

        if m is None:
            # No metrics = unknown state
            # Conservative: we could return UNKNOWN or FAIL
            # For safety, we allow with UNKNOWN (policy layer handles)
            return GateStatus.UNKNOWN

        # Check FPR controllability
        if m.fpr is not None and m.fpr > m.fpr_target:
            return GateStatus.FAIL_FPR

        # Check coverage at target FPR
        if m.coverage_at_fpr is not None and m.coverage_at_fpr < m.coverage_target:
            return GateStatus.FAIL_COVERAGE

        # Check calibration sanity
        if m.calibration_score is not None and m.calibration_score < m.calibration_threshold:
            return GateStatus.FAIL_CALIBRATION

        # Check lead time stability (if applicable)
        if m.lead_time_mean is not None and m.lead_time_std is not None:
            if m.lead_time_mean > 0:
                cv = m.lead_time_std / m.lead_time_mean
                if cv > m.lead_time_cv_max:
                    return GateStatus.FAIL_LEAD_TIME

        return GateStatus.PASS

    def get_metrics(self) -> Optional[GateMetrics]:
        """Get current metrics snapshot."""
        return self._metrics

    def is_operational(self, metrics: Optional[GateMetrics] = None) -> bool:
        """Simple boolean check for operational usability."""
        status = self.check(metrics)
        return status in (GateStatus.PASS, GateStatus.UNKNOWN)

    def get_failure_reason(self, metrics: Optional[GateMetrics] = None) -> Optional[str]:
        """Get human-readable failure reason if gate fails."""
        status = self.check(metrics)

        if status == GateStatus.PASS:
            return None
        if status == GateStatus.UNKNOWN:
            return None

        m = self._metrics
        if m is None:
            return f"Gate failed: {status.name} (no metrics)"

        fpr_str = f"{m.fpr:.3f}" if m.fpr is not None else "N/A"
        cov_str = f"{m.coverage_at_fpr:.3f}" if m.coverage_at_fpr is not None else "N/A"
        cal_str = f"{m.calibration_score:.3f}" if m.calibration_score is not None else "N/A"

        reasons = {
            GateStatus.FAIL_FPR: f"FPR ({fpr_str}) exceeds target ({self.fpr_target})",
            GateStatus.FAIL_COVERAGE: f"Coverage ({cov_str}) below target ({self.coverage_target})",
            GateStatus.FAIL_CALIBRATION: f"Calibration ({cal_str}) below threshold ({self.calibration_threshold})",
            GateStatus.FAIL_LEAD_TIME: "Lead time coefficient of variation too high",
        }
        return reasons.get(status, f"Gate failed: {status.name}")


class EmergencyGate:
    """
    Emergency gate that triggers Emptiness Window.

    When activated, this gate returns FAIL for all checks,
    forcing the runtime into Emptiness mode.
    """

    def __init__(self):
        self._emergency_active = False
        self._reason: str = ""

    def activate(self, reason: str = "Manual emergency activation") -> None:
        """Activate emergency mode."""
        self._emergency_active = True
        self._reason = reason

    def deactivate(self) -> None:
        """Deactivate emergency mode."""
        self._emergency_active = False
        self._reason = ""

    def is_active(self) -> bool:
        """Check if emergency mode is active."""
        return self._emergency_active

    def get_reason(self) -> str:
        """Get activation reason."""
        return self._reason
