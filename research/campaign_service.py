# research/campaign_service.py
#
# Neutral campaign control service — no UI or Streamlit dependencies.
# Shared by both app/supervisor.py (backend daemon) and ui/campaign_control.py (UI layer).
#
# This module is the single canonical place for:
#   - launching/resuming campaign subprocesses
#   - reading stop signals
#   - listing campaigns
#   - loading campaign state from disk
#
# Deliberately has no imports from app/, ui/, or peter/.
# Only depends on: stdlib, research.campaign (for lock primitives), observability.
#
# Public API:
#   start_campaign(goal, ...)           → {ok, message, pid}
#   resume_campaign(campaign_id)        → {ok, message, pid}
#   request_stop()                      → {ok, message}
#   cancel_stop_signal()                → {ok, message}
#   stop_signal_pending()               → bool
#   check_lock()                        → dict | None
#   list_campaigns()                    → list[dict]
#   list_resumable_campaigns()          → list[dict]
#   load_campaign_state(campaign_id)    → dict | None
#   get_best_candidate(campaign_id)     → dict | None
#   auto_continue_goal(all_campaigns)   → str

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
from typing import Any, Optional

_ROOT    = pathlib.Path(__file__).resolve().parent.parent
_SCRIPTS = _ROOT / "scripts"
_CAMPS   = _ROOT / "data" / "campaigns"

# Hard caps — mirrored from policy constants
_CAP_SESSIONS      = 6
_DEFAULT_SESSIONS  = 3
_CAP_BATCHES       = 4
_DEFAULT_BATCHES   = 3
_MIN_EXP_BATCH     = 3
_CAP_EXP_BATCH     = 5
_DEFAULT_EXP       = 3
_CAP_EXP_TOTAL     = 100
_DEFAULT_EXP_TOTAL = 60
_GOAL_MIN_LEN      = 5


# ── Lock / running check ──────────────────────────────────────────────────────

def check_lock() -> Optional[dict]:
    """Return live lock data if a campaign is running, else None."""
    try:
        from research.campaign import check_existing_lock
        return check_existing_lock(_CAMPS)
    except Exception:
        return None


def stop_signal_pending() -> bool:
    """True if a stop signal is currently pending."""
    try:
        from research.campaign import stop_requested
        return stop_requested(_CAMPS)
    except Exception:
        return False


# ── Campaign launch ───────────────────────────────────────────────────────────

def start_campaign(
    goal:            str,
    notes:           str   = "",
    max_sessions:    int   = _DEFAULT_SESSIONS,
    max_batches:     int   = _DEFAULT_BATCHES,
    experiments:     int   = _DEFAULT_EXP,
    max_experiments: int   = _DEFAULT_EXP_TOTAL,
    budget_usd:      float = 0.0,
    dry_run:         bool  = False,
) -> dict[str, Any]:
    """
    Validate inputs then spawn run_campaign.py as a background subprocess.

    Returns {ok, message, pid}.
    """
    goal_stripped = (goal or "").strip()
    if len(goal_stripped) < _GOAL_MIN_LEN:
        return {
            "ok":      False,
            "message": f"Goal must be at least {_GOAL_MIN_LEN} characters.",
            "pid":     None,
        }

    live = check_lock()
    if live:
        return {
            "ok":      False,
            "message": (
                f"Campaign '{live.get('campaign_id')}' is already running "
                f"(PID {live.get('pid')}). Stop it first."
            ),
            "pid": None,
        }

    # Clamp to hard caps
    max_sessions    = max(1,            min(max_sessions,    _CAP_SESSIONS))
    max_batches     = max(1,            min(max_batches,     _CAP_BATCHES))
    experiments     = max(_MIN_EXP_BATCH, min(experiments,  _CAP_EXP_BATCH))
    max_experiments = max(1,            min(max_experiments, _CAP_EXP_TOTAL))
    budget_usd      = max(0.0, budget_usd)

    cmd = [
        sys.executable,
        str(_SCRIPTS / "run_campaign.py"),
        "--goal",            goal_stripped,
        "--max-sessions",    str(max_sessions),
        "--max-batches",     str(max_batches),
        "--experiments",     str(experiments),
        "--max-experiments", str(max_experiments),
    ]
    if notes.strip():
        cmd += ["--notes", notes.strip()]
    if dry_run:
        cmd += ["--dry-run"]

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=str(_ROOT),
        )
        return {
            "ok":      True,
            "message": (
                f"Campaign started (PID {proc.pid}). "
                "State will appear in the Belfort tab within a few seconds."
            ),
            "pid": proc.pid,
        }
    except Exception as exc:
        return {
            "ok":      False,
            "message": f"Failed to launch campaign process: {exc}",
            "pid":     None,
        }


def resume_campaign(campaign_id: str) -> dict[str, Any]:
    """
    Resume an interrupted campaign by spawning run_campaign.py --resume.

    Returns {ok, message, pid}.
    """
    if not campaign_id or not campaign_id.strip():
        return {"ok": False, "message": "No campaign ID provided.", "pid": None}

    live = check_lock()
    if live:
        return {
            "ok":      False,
            "message": (
                f"Campaign '{live.get('campaign_id')}' is already running "
                f"(PID {live.get('pid')}). Stop it first."
            ),
            "pid": None,
        }

    state = load_campaign_state(campaign_id)
    if state is None:
        return {
            "ok":      False,
            "message": f"Campaign '{campaign_id}' not found in data/campaigns/.",
            "pid":     None,
        }

    status = state.get("status", "?")
    if status == "completed":
        sc = state.get("stop_condition", "?")
        return {
            "ok":      False,
            "message": f"Campaign '{campaign_id}' is already completed (stop: {sc}).",
            "pid":     None,
        }

    cmd = [sys.executable, str(_SCRIPTS / "run_campaign.py"), "--resume", campaign_id]
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=str(_ROOT),
        )
        done  = state.get("progress", {}).get("sessions_completed", 0)
        total = state.get("config", {}).get("max_sessions", "?")
        return {
            "ok":      True,
            "message": (
                f"Resuming '{campaign_id}' from session {done}/{total} "
                f"(PID {proc.pid})."
            ),
            "pid": proc.pid,
        }
    except Exception as exc:
        return {"ok": False, "message": f"Failed to resume: {exc}", "pid": None}


# ── Stop signal ───────────────────────────────────────────────────────────────

def request_stop() -> dict[str, Any]:
    """Write the stop-signal file so the running campaign stops after the current session."""
    live = check_lock()
    if not live:
        return {
            "ok":      False,
            "message": "No campaign is currently running — nothing to stop.",
        }
    try:
        from research.campaign import request_stop as _write_stop
        _write_stop(_CAMPS)
        return {
            "ok":      True,
            "message": (
                f"Stop signal sent to campaign '{live.get('campaign_id')}'. "
                "It will stop cleanly after the current session completes."
            ),
        }
    except Exception as exc:
        return {"ok": False, "message": f"Could not write stop signal: {exc}"}


def cancel_stop_signal() -> dict[str, Any]:
    """Remove the stop-signal file if present."""
    try:
        from research.campaign import clear_stop_signal
        clear_stop_signal(_CAMPS)
        return {"ok": True, "message": "Stop signal cancelled — campaign will continue."}
    except Exception as exc:
        return {"ok": False, "message": f"Could not cancel stop signal: {exc}"}


# ── Campaign listing ──────────────────────────────────────────────────────────

def list_campaigns() -> list[dict[str, Any]]:
    """All campaigns found in data/campaigns/, newest first."""
    if not _CAMPS.exists():
        return []
    out: list[dict] = []
    for state_file in _CAMPS.glob("*/state.json"):
        try:
            data = json.loads(state_file.read_text())
            p    = data.get("progress", {})
            cfg  = data.get("config", {})
            out.append({
                "campaign_id":        data.get("campaign_id", "?"),
                "goal":               data.get("goal", "?"),
                "status":             data.get("status", "?"),
                "created_at":         data.get("created_at", ""),
                "sessions_completed": p.get("sessions_completed", 0),
                "max_sessions":       cfg.get("max_sessions", "?"),
                "total_experiments":  p.get("total_experiments", 0),
                "total_accepted":     p.get("total_accepted", 0),
                "stop_condition":     data.get("stop_condition"),
                "best_tier":          (data.get("best_candidate") or {}).get("tier"),
            })
        except Exception:
            pass
    return sorted(out, key=lambda d: d.get("created_at", ""), reverse=True)


def list_resumable_campaigns() -> list[dict[str, Any]]:
    """Campaigns that can be resumed (status interrupted or running, excluding live)."""
    live_id = (check_lock() or {}).get("campaign_id")
    return [
        c for c in list_campaigns()
        if c["status"] in ("interrupted", "running")
        and c["campaign_id"] != live_id
    ]


# ── Artifact readers ──────────────────────────────────────────────────────────

def load_campaign_state(campaign_id: str) -> Optional[dict[str, Any]]:
    """Load campaign state JSON for a given campaign_id. Returns None if missing."""
    if not campaign_id:
        return None
    path = _CAMPS / campaign_id / "state.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def get_best_candidate(campaign_id: str) -> Optional[dict[str, Any]]:
    """Best candidate dict from campaign state, or None."""
    state = load_campaign_state(campaign_id)
    return (state or {}).get("best_candidate")


def get_validation_record(rec_path: str) -> Optional[dict[str, Any]]:
    """Load a validation record from disk, or None if missing/malformed."""
    if not rec_path:
        return None
    path = pathlib.Path(rec_path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


# ── Goal helper ───────────────────────────────────────────────────────────────

def auto_continue_goal(all_campaigns: list) -> str:
    """
    Return the goal string for an auto-continue action.

    Picks the goal from the most recent campaign that has one.
    Assumes all_campaigns is newest-first (as returned by list_campaigns()).
    """
    for campaign in all_campaigns:
        goal = campaign.get("goal") or campaign.get("research_goal")
        if goal and isinstance(goal, str) and goal.strip():
            return goal.strip()
    return "systematic strategy research"
