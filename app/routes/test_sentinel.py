# app/routes/test_sentinel.py
#
# FastAPI router for Test Sentinel — targeted patch-safety checks.
#
# Endpoints:
#   POST /sentinel/run   — run targeted or smoke tests, return verdict
#   GET  /sentinel/last  — return last cached report (no test run)

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter
from pydantic import BaseModel

from app.test_sentinel import (
    detect_touched_files,
    get_last_report,
    report_to_dict,
    run_sentinel,
)

router = APIRouter()


class SentinelRunRequest(BaseModel):
    files: Optional[List[str]] = None  # source files that changed
    scope: str = "auto"                # "auto" | "smoke" | "full"
    auto_detect: bool = False          # if True, detect touched files via git


@router.post("/sentinel/run")
def sentinel_run(req: SentinelRunRequest = SentinelRunRequest()) -> dict:
    """
    Run targeted (or smoke) tests and return a structured verdict.

    Body fields:
      files:       list of changed source file paths to target
      scope:       "auto" (targeted → smoke fallback), "smoke", or "full"
      auto_detect: if True, detect changed files via git diff HEAD
    """
    files = list(req.files or [])
    if req.auto_detect:
        git_files = detect_touched_files()
        for f in git_files:
            if f not in files:
                files.append(f)

    report = run_sentinel(files=files or None, scope=req.scope)
    return report_to_dict(report)


@router.get("/sentinel/last")
def sentinel_last() -> dict:
    """
    Return the last cached Sentinel report without running tests.
    Returns an 'unknown' stub if no check has been run yet.
    """
    data = get_last_report()
    if data is None:
        return {
            "verdict":    "unknown",
            "summary":    "No Sentinel check has been run yet. Use POST /sentinel/run to check.",
            "scope":      "none",
            "timestamp":  None,
            "passed":     0,
            "failed":     0,
            "errors":     0,
            "failures":   [],
            "tests_run":  [],
        }
    return data
