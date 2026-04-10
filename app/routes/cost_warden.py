# app/routes/cost_warden.py
#
# FastAPI router for Cost Warden — LM routing policy and usage reporting.
#
# Endpoints:
#   GET /warden/policy   — routing policy document (models, tiers, task map)
#   GET /warden/summary  — recent LM usage summary (cost, tier breakdown)

from __future__ import annotations

from fastapi import APIRouter

from app.cost_warden import get_policy_report, get_usage_summary, policy_summary_line

router = APIRouter()


@router.get("/warden/policy")
def warden_policy() -> dict:
    """
    Return the Cost Warden routing policy: model tiers, task assignments,
    env overrides, and escalation conditions.
    """
    return get_policy_report()


@router.get("/warden/summary")
def warden_summary() -> dict:
    """
    Return a summary of recent LM usage routed via LMHelper:
    total calls, cost, tier breakdown, escalation rate.
    """
    summary = get_usage_summary(limit=50)
    summary["policy_line"] = policy_summary_line()
    return summary
