# app/supervisor.py
#
# Continuous learning loop supervisor for Mr Belfort.
#
# Runs as a singleton daemon thread inside the FastAPI backend.
# Polls Belfort's agent state every TICK_INTERVAL seconds and drives
# the continuous learning loop when enabled.
#
# Role boundary:
#   - Supervisor: execution coordinator — triggers cycles, applies policy, queues candidates
#   - Peter:      operator interface — reads supervisor state, presents findings
#   - Checker:    auditor — read-only observer, flags problems
#
# Imports only from: research/, observability/, app/strategy/  (never from ui/)
#
# Singleton guard: start_supervisor() is idempotent — safe to call on every
# backend startup. Uses a module-level threading.Lock to prevent duplicate threads.
#
# Canonical runtime: ./scripts/ctl.sh start  (uvicorn without --reload)
# Do NOT use --reload; the lifespan hook would run twice and the singleton
# guard handles it, but --reload is not part of the canonical workflow.
#
# Public API:
#   start_supervisor()       → None  (idempotent)
#   stop_supervisor()        → None  (requests graceful stop)
#   enable_continuous()      → dict  {ok, message}
#   disable_continuous()     → dict  {ok, message}
#   get_supervisor_state()   → dict
#   supervisor_enabled()     → bool

from __future__ import annotations

import json
import pathlib
import threading
import time
from datetime import datetime, timezone
from typing import Any, Optional

# ── Imports from neutral layers only ─────────────────────────────────────────
from research.approval_policy import (
    classify_candidate,
    auto_apply_eligible,
    build_risk_summary,
    should_continue_loop,
)
from research.campaign_service import (
    start_campaign,
    resume_campaign,
    list_campaigns,
    list_resumable_campaigns,
    load_campaign_state,
    get_validation_record,
    auto_continue_goal,
    check_lock,
)
from research.candidate_queue import add_to_queue, update_queue_item
from observability.agent_state import (
    load_state,
    transition,
    MR_BELFORT,
    STATUS_IDLE,
    STATUS_WAITING_FOR_REVIEW,
    STATUS_REVIEW_HELD,
    STATUS_PAUSED_BY_BUDGET,
    STATUS_STOPPED_GUARDRAIL,
)
from observability.event_log import append_event

_ROOT             = pathlib.Path(__file__).resolve().parent.parent
_STATE_PATH       = _ROOT / "data" / "supervisor_state.json"
_PENDING_GOAL_PATH = _ROOT / "data" / "pending_research_goal.json"

TICK_INTERVAL     = 10    # seconds between ticks
_MAX_START_ERRORS = 3     # consecutive start failures before auto-disable

# ── Singleton guard ───────────────────────────────────────────────────────────

_thread: Optional[threading.Thread] = None
_lock   = threading.Lock()


def start_supervisor() -> None:
    """
    Start the supervisor daemon thread if not already running.
    Idempotent — safe to call multiple times (e.g., on backend restart).
    """
    global _thread
    with _lock:
        if _thread is not None and _thread.is_alive():
            return   # already running
        _thread = threading.Thread(
            target    = _supervisor_loop,
            daemon    = True,
            name      = "openclaw-supervisor",
        )
        _thread.start()


def stop_supervisor() -> None:
    """
    Request a graceful stop of the continuous loop.
    The thread will exit after the current tick completes.
    """
    _update_state(stop_requested=True, enabled=False)


def supervisor_enabled() -> bool:
    return _load_state().get("enabled", False)


# ── State persistence ─────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_pending_goal(goal: str) -> None:
    """Store a trigger-derived goal to seed the next auto-started campaign."""
    _ROOT.joinpath("data").mkdir(exist_ok=True)
    _PENDING_GOAL_PATH.write_text(
        json.dumps({"goal": goal.strip(), "written_at": _now()}, ensure_ascii=False),
        encoding="utf-8",
    )


def read_and_clear_pending_goal() -> str | None:
    """
    Read the pending goal file and delete it.
    Returns the goal string or None if not present / empty.
    """
    if not _PENDING_GOAL_PATH.exists():
        return None
    try:
        g = json.loads(_PENDING_GOAL_PATH.read_text(encoding="utf-8")).get("goal", "").strip()
        _PENDING_GOAL_PATH.unlink(missing_ok=True)
        return g or None
    except Exception:
        return None


def _load_state() -> dict:
    if not _STATE_PATH.exists():
        return _default_state()
    try:
        data = json.loads(_STATE_PATH.read_text(encoding="utf-8"))
        # Ensure required keys exist
        for k, v in _default_state().items():
            data.setdefault(k, v)
        return data
    except Exception:
        return _default_state()


def _default_state() -> dict:
    return {
        "enabled":        False,
        "stop_requested": False,
        "cycle_count":    0,
        "started_at":     "",
        "last_cycle_at":  "",
        "consecutive_start_errors": 0,
        "last_error":     "",
    }


def _save_state(data: dict) -> None:
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.rename(_STATE_PATH)


def _update_state(**kwargs: Any) -> dict:
    data = _load_state()
    data.update(kwargs)
    _save_state(data)
    return data


# ── Public enable / disable ───────────────────────────────────────────────────

def enable_continuous() -> dict[str, Any]:
    """Enable the continuous learning loop. Starts the daemon thread if needed."""
    state = _load_state()
    if state.get("enabled"):
        return {"ok": True, "message": "Continuous learning is already running."}

    _update_state(
        enabled=True,
        stop_requested=False,
        started_at=_now(),
        consecutive_start_errors=0,
        last_error="",
    )
    start_supervisor()
    append_event(
        "continuous_learning_enabled",
        "Operator enabled continuous learning loop.",
        "important",
        source="operator",
    )
    return {"ok": True, "message": "Continuous learning enabled. Belfort will loop until stopped."}


def disable_continuous() -> dict[str, Any]:
    """Request graceful stop of the continuous loop after the current cycle."""
    state = _load_state()
    if not state.get("enabled"):
        return {"ok": False, "message": "Continuous learning is not currently enabled."}

    _update_state(stop_requested=True)
    append_event(
        "continuous_learning_stop_requested",
        "Operator requested continuous learning stop — will halt after current cycle.",
        "important",
        source="operator",
    )
    return {
        "ok": True,
        "message": "Stop requested. Belfort will finish the current cycle then halt.",
    }


def get_supervisor_state() -> dict[str, Any]:
    """Return current supervisor state for API/UI consumption."""
    return _load_state()


# ── Main loop ─────────────────────────────────────────────────────────────────

def _supervisor_loop() -> None:
    """Daemon thread body — ticks every TICK_INTERVAL seconds."""
    while True:
        try:
            state = _load_state()
            if not state.get("enabled"):
                break  # loop disabled — exit thread
            _tick(state)
        except Exception:
            pass  # never let the thread die on an unhandled exception
        time.sleep(TICK_INTERVAL)


def _tick(state: dict) -> None:
    """Single supervisor tick — evaluate Belfort state and act."""
    agent = load_state(MR_BELFORT, agent_role="trading_researcher")
    status = agent.status

    # ── Hard stops — disable loop ─────────────────────────────────────────────
    if status in (STATUS_PAUSED_BY_BUDGET, STATUS_STOPPED_GUARDRAIL):
        _update_state(enabled=False, stop_requested=False)
        append_event(
            "continuous_learning_hard_stopped",
            f"Continuous loop disabled: Belfort in hard-stop state ({status}).",
            "important",
            source="supervisor",
        )
        return

    # ── Operator requested stop ───────────────────────────────────────────────
    if state.get("stop_requested"):
        _update_state(enabled=False, stop_requested=False)
        append_event(
            "continuous_learning_stopped",
            "Continuous learning stopped as requested by operator.",
            "important",
            source="supervisor",
        )
        return

    # ── Waiting for review — apply policy ────────────────────────────────────
    if status == STATUS_WAITING_FOR_REVIEW:
        _handle_waiting_for_review(agent, state)
        return

    # ── Review held by operator — do nothing (respect operator deferral) ──────
    if status == STATUS_REVIEW_HELD:
        return

    # ── Active (running / stop_pending) — already working, do nothing ─────────
    if agent.actively_learning:
        return

    # ── Idle — start next cycle ───────────────────────────────────────────────
    ok, reason = should_continue_loop(state, status)
    if ok:
        _start_next_cycle(state)
    else:
        _update_state(enabled=False, stop_requested=False)
        append_event(
            "continuous_learning_stopped",
            f"Continuous loop ended: {reason}.",
            "important",
            source="supervisor",
        )


# ── Waiting-for-review handler ────────────────────────────────────────────────

def _handle_waiting_for_review(agent: Any, state: dict) -> None:
    """
    Evaluate policy on the best candidate and act.
    If any field is missing or malformed → review_required (fail-safe).
    """
    campaign_id = agent.campaign_id
    if not campaign_id:
        # No campaign context — just advance to idle
        _advance_to_idle(agent, "no campaign context")
        _start_next_cycle(state)
        return

    camp_state = load_campaign_state(campaign_id)
    if not camp_state:
        _advance_to_idle(agent, "campaign state not found")
        _start_next_cycle(state)
        return

    best = camp_state.get("best_candidate")
    rec_path = (camp_state.get("artifacts") or {}).get("best_validation_record") or ""

    if not best or not rec_path:
        # No valid candidate — continue loop
        _advance_to_idle(agent, "no best candidate")
        _start_next_cycle(state)
        return

    enriched = _enrich_candidate(best, rec_path)
    decision = classify_candidate(enriched)

    if decision == "auto_apply":
        _do_auto_apply(enriched, campaign_id, agent)
        _start_next_cycle(state)

    elif decision == "review_required":
        _do_queue_for_review(enriched, campaign_id, agent)
        _start_next_cycle(state)

    else:  # skip
        _advance_to_idle(agent, f"skip: tier={enriched.get('tier', '?')}")
        _start_next_cycle(state)


def _enrich_candidate(best: dict, rec_path: str) -> dict:
    """
    Merge best_candidate summary with full validation record fields.
    Computes n_changed_params against current strategy baseline.
    Returns enriched dict; missing fields left absent (triggers fail-safe in policy).
    """
    enriched = dict(best)
    enriched["rec_path"] = rec_path

    record = get_validation_record(rec_path)
    if record:
        # Fill fields from validation record that may not be in campaign summary
        for field_name in ("quality_labels", "flags", "candidate_config", "pnl_delta",
                           "worst_pnl_delta", "score", "tier"):
            if field_name not in enriched and field_name in record:
                enriched[field_name] = record[field_name]

    # Compute n_changed_params vs current baseline
    candidate_cfg = enriched.get("candidate_config") or {}
    if candidate_cfg:
        try:
            from app.strategy.config import get_config
            current = get_config()
            enriched["n_changed_params"] = sum(
                1 for k, v in candidate_cfg.items() if current.get(k) != v
            )
        except Exception:
            enriched["n_changed_params"] = 99  # fail-safe: assume many changes

    return enriched


def _do_auto_apply(enriched: dict, campaign_id: str, agent: Any) -> None:
    """Apply candidate automatically and record in queue + event log."""
    eligible, fail_reasons = auto_apply_eligible(enriched)
    risk_summary = build_risk_summary(enriched, eligible, fail_reasons)
    rec_path = enriched.get("rec_path", "")

    try:
        from app.strategy.applier import promote_from_record
        promote_from_record(rec_path, reason="Supervisor auto-apply — policy criteria met")
        result_ok = True
        err_msg = ""
    except Exception as exc:
        result_ok = False
        err_msg = str(exc)

    if result_ok:
        entry = _build_queue_entry(enriched, campaign_id, "auto_apply", "auto_applied",
                                   eligible=True, fail_reasons=[], risk_summary=risk_summary)
        add_to_queue(entry)
        append_event(
            "candidate_auto_applied",
            (f"Auto-applied: {enriched.get('experiment_id', '?')} "
             f"(score={enriched.get('score', '?')}, tier={enriched.get('tier', '?')})."),
            "important",
            source="supervisor",
            campaign_id=campaign_id,
        )
    else:
        # Apply failed — queue for review instead
        entry = _build_queue_entry(enriched, campaign_id, "review_required", "pending",
                                   eligible=False,
                                   fail_reasons=[f"auto-apply failed: {err_msg}"],
                                   risk_summary=f"Auto-apply failed: {err_msg}. Queued for review.")
        add_to_queue(entry)
        append_event(
            "candidate_queued_for_review",
            (f"Auto-apply failed ({err_msg[:80]}); queued for review: "
             f"{enriched.get('experiment_id', '?')}."),
            "important",
            source="supervisor",
            campaign_id=campaign_id,
        )

    _advance_to_idle(agent, f"auto_apply: {enriched.get('experiment_id', '?')}")


def _do_queue_for_review(enriched: dict, campaign_id: str, agent: Any) -> None:
    """Queue candidate for operator review without blocking the loop."""
    eligible, fail_reasons = auto_apply_eligible(enriched)
    risk_summary = build_risk_summary(enriched, eligible, fail_reasons)

    entry = _build_queue_entry(enriched, campaign_id, "review_required", "pending",
                               eligible=False, fail_reasons=fail_reasons,
                               risk_summary=risk_summary)
    add_to_queue(entry)
    append_event(
        "candidate_queued_for_review",
        (f"Candidate queued: {enriched.get('experiment_id', '?')} "
         f"(score={enriched.get('score', '?')}, tier={enriched.get('tier', '?')}). "
         "Learning continues."),
        "important",
        source="supervisor",
        campaign_id=campaign_id,
    )
    _advance_to_idle(agent, f"queued for review: {enriched.get('experiment_id', '?')}")


def _advance_to_idle(agent: Any, reason: str) -> None:
    """Transition Belfort from waiting_for_review to idle so the loop can continue."""
    try:
        transition(
            MR_BELFORT,
            agent_role="trading_researcher",
            status=STATUS_IDLE,
            last_completed_action=f"supervisor: {reason}",
        )
    except Exception:
        pass


def _start_next_cycle(state: dict) -> None:
    """Start the next bounded research cycle (resume if possible, else fresh start)."""
    resumable = list_resumable_campaigns()
    if resumable:
        r = resume_campaign(resumable[0]["campaign_id"])
    else:
        pending = read_and_clear_pending_goal()
        goal    = pending or auto_continue_goal(list_campaigns())
        r       = start_campaign(goal=goal)

    if r.get("ok"):
        _update_state(
            cycle_count=state.get("cycle_count", 0) + 1,
            last_cycle_at=_now(),
            consecutive_start_errors=0,
            last_error="",
        )
        append_event(
            "continuous_cycle_started",
            f"Continuous cycle #{state.get('cycle_count', 0) + 1} started.",
            "routine",
            source="supervisor",
        )
    else:
        errors = state.get("consecutive_start_errors", 0) + 1
        _update_state(consecutive_start_errors=errors, last_error=r.get("message", ""))
        if errors >= _MAX_START_ERRORS:
            _update_state(enabled=False)
            append_event(
                "continuous_learning_stopped",
                f"Continuous loop auto-disabled after {errors} consecutive start failures: "
                f"{r.get('message', '?')}",
                "important",
                source="supervisor",
            )


# ── Queue entry builder ───────────────────────────────────────────────────────

def _build_queue_entry(
    enriched:      dict,
    campaign_id:   str,
    approval_level: str,
    status:        str,
    eligible:      bool,
    fail_reasons:  list[str],
    risk_summary:  str,
) -> dict:
    exp_id  = enriched.get("experiment_id", "?")
    tier    = enriched.get("tier", "?")
    score   = enriched.get("score", "?")
    pnl     = enriched.get("pnl_delta", "?")
    w_pnl   = enriched.get("worst_pnl_delta", "?")
    n_chg   = enriched.get("n_changed_params", "?")

    # Short title
    pnl_pct = f"{pnl*100:.1f}%" if isinstance(pnl, (int, float)) else "?"
    title   = f"{tier.replace('_', ' ').title()}: {pnl_pct} PnL · {n_chg} param(s)"

    return {
        "campaign_id":           campaign_id,
        "experiment_id":         exp_id,
        "title":                 title,
        "summary":               enriched.get("hypothesis", "Research experiment result"),
        "why_flagged":           f"Score {score} ({tier}). {risk_summary}",
        "tier":                  tier,
        "score":                 score,
        "n_changed_params":      n_chg,
        "pnl_delta":             pnl,
        "worst_pnl_delta":       w_pnl,
        "quality_labels":        enriched.get("quality_labels", []),
        "flags":                 enriched.get("flags", []),
        "approval_level":        approval_level,
        "auto_apply_eligible":   eligible,
        "auto_apply_fail_reasons": fail_reasons,
        "risk_summary":          risk_summary,
        "record_path":           enriched.get("rec_path", ""),
        "status":                status,
        "resolved_at":           None,
        "resolution":            None,
    }
