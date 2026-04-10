# observability/budget.py
#
# Budget config and guardrail evaluation.
#
# This module is pure computation — no I/O, no side effects.
# CampaignRunner is responsible for reading telemetry and calling
# evaluate_budget() after each session to enforce hard stops.
#
# Stop/pause semantics:
#   pct_used >= warning_threshold_pct  → warning_triggered (log only)
#   pct_used >= hard_stop_pct          → hard_stop_triggered (CampaignRunner breaks)
#
# Public API:
#   BudgetConfig(max_cost_usd, warning_threshold_pct, hard_stop_pct)
#   BudgetStatus — result of evaluate_budget()
#   evaluate_budget(config, spent_usd) → BudgetStatus

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# Sensible defaults for a research campaign
DEFAULT_MAX_COST_USD       = 5.00   # $5 per campaign
DEFAULT_WARNING_THRESHOLD  = 0.80   # warn at 80%
DEFAULT_HARD_STOP          = 1.00   # hard stop at 100%


@dataclass
class BudgetConfig:
    """Budget policy for one campaign."""
    max_cost_usd:           float = DEFAULT_MAX_COST_USD
    warning_threshold_pct:  float = DEFAULT_WARNING_THRESHOLD
    hard_stop_pct:          float = DEFAULT_HARD_STOP

    def to_dict(self) -> dict:
        return {
            "max_cost_usd":          self.max_cost_usd,
            "warning_threshold_pct": self.warning_threshold_pct,
            "hard_stop_pct":         self.hard_stop_pct,
        }

    @staticmethod
    def from_dict(d: dict) -> "BudgetConfig":
        return BudgetConfig(
            max_cost_usd          = float(d.get("max_cost_usd",           DEFAULT_MAX_COST_USD)),
            warning_threshold_pct = float(d.get("warning_threshold_pct",  DEFAULT_WARNING_THRESHOLD)),
            hard_stop_pct         = float(d.get("hard_stop_pct",          DEFAULT_HARD_STOP)),
        )


@dataclass
class BudgetStatus:
    """Result of evaluate_budget()."""
    max_cost_usd:           float
    spent_usd:              float
    remaining_usd:          float
    pct_used:               float
    warning_triggered:      bool
    hard_stop_triggered:    bool
    stop_reason:            Optional[str]   # non-None only when hard_stop_triggered
    is_estimated:           bool            # True if spend figure is estimated

    @property
    def pct_used_display(self) -> str:
        return f"{self.pct_used * 100:.1f}%"

    @property
    def budget_bar(self) -> str:
        """ASCII progress bar, 20 chars wide."""
        filled = int(self.pct_used * 20)
        filled = min(filled, 20)
        bar    = "█" * filled + "░" * (20 - filled)
        return f"[{bar}] {self.pct_used_display}"


def evaluate_budget(
    config:       BudgetConfig,
    spent_usd:    float,
    is_estimated: bool = True,
) -> BudgetStatus:
    """
    Evaluate current spend against the budget policy.

    Args:
        config:       Budget policy to check against.
        spent_usd:    Amount spent so far (from telemetry).
        is_estimated: True if spent_usd is an estimate, not confirmed billing.

    Returns:
        BudgetStatus with threshold flags and stop_reason if hard stop triggered.
    """
    remaining = max(0.0, config.max_cost_usd - spent_usd)
    pct       = (spent_usd / config.max_cost_usd) if config.max_cost_usd > 0 else 0.0

    hard_stop = pct >= config.hard_stop_pct
    warning   = pct >= config.warning_threshold_pct

    stop_reason: Optional[str] = None
    if hard_stop:
        label = " (estimated)" if is_estimated else ""
        stop_reason = (
            f"Budget exhausted{label}: "
            f"spent ${spent_usd:.4f} of ${config.max_cost_usd:.2f} limit "
            f"({pct * 100:.1f}%)."
        )

    return BudgetStatus(
        max_cost_usd        = config.max_cost_usd,
        spent_usd           = spent_usd,
        remaining_usd       = remaining,
        pct_used            = pct,
        warning_triggered   = warning,
        hard_stop_triggered = hard_stop,
        stop_reason         = stop_reason,
        is_estimated        = is_estimated,
    )
