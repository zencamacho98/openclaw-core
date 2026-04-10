# app/routes/custodian.py
#
# FastAPI router for Custodian runtime health checks.
#
# The Custodian is read/diagnose/report only.
# It does not restart services, kill processes, or repair state.
#
# Endpoints:
#   GET /custodian/health  — run a live check, cache result, return report
#   GET /custodian/last    — return last cached report without live checks

from __future__ import annotations

from fastapi import APIRouter

from app.custodian import get_last_report, report_to_dict, run_health_check

router = APIRouter()


@router.get("/custodian/health")
def custodian_health() -> dict:
    """
    Run a live Custodian health check and return the structured report.
    Also caches the result to data/custodian_health.json for Peter to read.
    """
    report = run_health_check()
    return report_to_dict(report)


@router.get("/custodian/last")
def custodian_last() -> dict:
    """
    Return the last cached Custodian health report without running live checks.
    Returns an 'unknown' stub if no check has been run yet.
    """
    data = get_last_report()
    if data is None:
        return {
            "overall": "unknown",
            "summary": "No health check has been run yet. Call /custodian/health to check.",
            "timestamp": None,
            "items": [],
            "recommendations": [],
        }
    return data
