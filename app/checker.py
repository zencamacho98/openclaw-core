# app/checker.py
#
# Loop health auditor for the continuous learning supervisor.
#
# Runs as a singleton daemon thread inside the FastAPI backend.
# Ticks every CHECK_INTERVAL seconds, performs read-only checks,
# and surfaces findings through the event log and a findings JSONL file.
#
# Role boundary:
#   - Checker: auditor — flags problems; NEVER modifies state
#   - Supervisor: execution coordinator — acts on Belfort state
#   - Peter:      operator interface — shows checker findings
#
# Severity mapping (internal → event_log):
#   "warning" → "important"  (visible in default event log filter)
#   "info"    → "routine"    (lower-noise; filtered out by default)
#
# Deduplication: a finding of the same type is suppressed if the same
# type was emitted less than DEDUP_THRESHOLD_SECS ago.
#
# Findings are written to data/checker_findings.jsonl (append-only).
# Each line is a JSON object with fields: timestamp, finding_id, finding_type,
# severity, title, detail, acknowledged, acknowledged_at, acknowledged_by.
#
# Imports only from: observability/, research/, stdlib — never from ui/ or app/routes/
#
# Public API:
#   start_checker()                                   → None  (idempotent)
#   stop_checker()                                    → None  (sets _stop flag)
#   get_checker_state()                               → dict
#   read_findings(limit, include_acknowledged)        → list[dict]
#   acknowledge_finding(finding_id, operator_id)      → bool

from __future__ import annotations

import json
import pathlib
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from observability.agent_state import (
    load_state,
    MR_BELFORT,
    ACTIVE_STATUSES,
    STATUS_IDLE,
    STATUS_WAITING_FOR_REVIEW,
    STATUS_REVIEW_HELD,
)
from observability.event_log import append_event
from research.candidate_queue import pending_candidates

_ROOT             = pathlib.Path(__file__).resolve().parent.parent
_FINDINGS_PATH    = _ROOT / "data" / "checker_findings.jsonl"
_SUPERVISOR_STATE = _ROOT / "data" / "supervisor_state.json"

CHECK_INTERVAL       = 60         # seconds between checker ticks
DEDUP_THRESHOLD_SECS = 3600       # suppress repeat finding_type within 1 hour

# Thresholds for each check type
_STALL_THRESHOLD_SECS     = 1800  # 30 min without heartbeat → stall
_QUEUE_BACKLOG_LIMIT      = 5     # pending queue items before warning
_SUPERVISOR_ERRORS_WARN   = 2     # consecutive start errors before warning

# ── Singleton guard ───────────────────────────────────────────────────────────

_thread: Optional[threading.Thread] = None
_stop_flag = threading.Event()
_lock = threading.Lock()


def start_checker() -> None:
    """Start the checker daemon thread. Idempotent — safe to call on every restart."""
    global _thread
    with _lock:
        if _thread is not None and _thread.is_alive():
            return
        _stop_flag.clear()
        _thread = threading.Thread(
            target=_checker_loop,
            daemon=True,
            name="openclaw-checker",
        )
        _thread.start()


def stop_checker() -> None:
    """Signal the checker thread to exit after the current tick."""
    _stop_flag.set()


# ── State ─────────────────────────────────────────────────────────────────────

def get_checker_state() -> dict[str, Any]:
    """Return lightweight checker status for API/UI."""
    return {
        "running": _thread is not None and _thread.is_alive(),
        "check_interval_secs": CHECK_INTERVAL,
        "dedup_threshold_secs": DEDUP_THRESHOLD_SECS,
        "findings_path": str(_FINDINGS_PATH),
    }


# ── Main loop ─────────────────────────────────────────────────────────────────

def _checker_loop() -> None:
    """Daemon thread body — ticks every CHECK_INTERVAL seconds."""
    while not _stop_flag.is_set():
        try:
            _run_checks()
        except Exception:
            pass  # never let the thread die on an unhandled exception
        # Use Event.wait so stop_checker() wakes the thread immediately
        _stop_flag.wait(timeout=CHECK_INTERVAL)


def _run_checks() -> None:
    """Run all health checks in sequence."""
    now = _now()
    recent = _load_recent_finding_times()

    _check_stalled_belfort(now, recent)
    _check_queue_backlog(now, recent)
    _check_supervisor_errors(now, recent)


# ── Individual checks ─────────────────────────────────────────────────────────

def _check_stalled_belfort(now: str, recent: dict[str, str]) -> None:
    """
    Flag if Belfort is in an active or waiting status but its heartbeat is stale.
    Excludes idle — idle with old heartbeat is normal (nothing is happening).
    """
    finding_type = "stalled_belfort"
    if _is_suppressed(finding_type, recent):
        return

    try:
        agent = load_state(MR_BELFORT, agent_role="trading_researcher")
    except Exception:
        return

    status = agent.status
    # Only check statuses where we expect regular heartbeats
    watchable = ACTIVE_STATUSES | {STATUS_WAITING_FOR_REVIEW, STATUS_REVIEW_HELD}
    if status not in watchable:
        return

    hb = agent.last_heartbeat_at
    if not hb:
        return

    age_secs = _age_secs(hb)
    if age_secs < _STALL_THRESHOLD_SECS:
        return

    age_min = int(age_secs // 60)
    _emit_finding(
        finding_type=finding_type,
        severity="warning",
        title=f"Belfort stalled ({status})",
        detail=(
            f"Mr Belfort has been in status '{status}' for {age_min} minutes "
            f"without a heartbeat update. Last heartbeat: {hb}. "
            "This may indicate a crashed subprocess or a hung campaign."
        ),
    )


def _check_queue_backlog(now: str, recent: dict[str, str]) -> None:
    """Flag if the pending candidate queue has grown large."""
    finding_type = "queue_backlog"
    if _is_suppressed(finding_type, recent):
        return

    try:
        pending = pending_candidates()
    except Exception:
        return

    n = len(pending)
    if n < _QUEUE_BACKLOG_LIMIT:
        return

    _emit_finding(
        finding_type=finding_type,
        severity="warning",
        title=f"Candidate queue backlog ({n} pending)",
        detail=(
            f"{n} candidates are waiting for operator review in the upgrade queue. "
            "The loop continues running, but unreviewed candidates may accumulate. "
            "Use 'show queue' in Peter or the dashboard Upgrade Queue tab to review."
        ),
    )


def _check_supervisor_errors(now: str, recent: dict[str, str]) -> None:
    """Flag if the supervisor has accumulated consecutive start errors."""
    finding_type = "supervisor_start_errors"
    if _is_suppressed(finding_type, recent):
        return

    sup_state = _load_supervisor_state()
    if not sup_state:
        return

    errors = sup_state.get("consecutive_start_errors", 0)
    if errors < _SUPERVISOR_ERRORS_WARN:
        return

    last_err = sup_state.get("last_error", "unknown error")
    _emit_finding(
        finding_type=finding_type,
        severity="warning",
        title=f"Supervisor start errors ({errors} consecutive)",
        detail=(
            f"The supervisor has failed to start a new research cycle {errors} time(s) "
            f"in a row. Last error: {last_err!r}. "
            "At 3 consecutive failures the loop auto-disables. "
            "Check run_campaign.py logs and campaign lock state."
        ),
    )


# ── Findings persistence ──────────────────────────────────────────────────────

def _emit_finding(
    finding_type: str,
    severity: str,
    title: str,
    detail: str,
) -> None:
    """
    Append a finding to data/checker_findings.jsonl and mirror to event_log.

    Severity mapping: "warning" → "important", "info" → "routine"
    """
    finding_id = f"chk_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}_{str(uuid.uuid4())[:6]}"
    record = {
        "timestamp":        _now(),
        "finding_id":       finding_id,
        "finding_type":     finding_type,
        "severity":         severity,
        "title":            title,
        "detail":           detail,
        "acknowledged":     False,
        "acknowledged_at":  None,
        "acknowledged_by":  None,
    }

    try:
        _FINDINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _FINDINGS_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except Exception:
        return  # write failure — don't cascade

    # Mirror to event log with mapped severity
    event_severity = "important" if severity == "warning" else "routine"
    append_event(
        event_type=f"checker_{finding_type}",
        summary=f"[Checker] {title}: {detail[:120]}",
        severity=event_severity,
        source="checker",
    )


def _load_recent_finding_times() -> dict[str, str]:
    """
    Return {finding_type: latest_timestamp} for all findings written within
    DEDUP_THRESHOLD_SECS. Used to suppress duplicate findings.
    """
    if not _FINDINGS_PATH.exists():
        return {}

    now_ts = datetime.now(timezone.utc)
    result: dict[str, str] = {}
    try:
        lines = _FINDINGS_PATH.read_text(encoding="utf-8").splitlines()
    except Exception:
        return {}

    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        ft = rec.get("finding_type")
        ts = rec.get("timestamp")
        if not ft or not ts:
            continue
        if ft in result:
            continue  # already have a more-recent entry for this type

        try:
            age = (now_ts - datetime.fromisoformat(ts)).total_seconds()
        except Exception:
            continue
        if age <= DEDUP_THRESHOLD_SECS:
            result[ft] = ts

    return result


def _is_suppressed(finding_type: str, recent: dict[str, str]) -> bool:
    """True if this finding_type was emitted recently enough to suppress."""
    return finding_type in recent


# ── Findings public readers ───────────────────────────────────────────────────

def read_findings(
    limit: int = 50,
    include_acknowledged: bool = False,
) -> list[dict]:
    """
    Return checker findings, newest-first.

    include_acknowledged=False (default) omits acknowledged findings.
    Malformed lines are skipped.
    """
    if not _FINDINGS_PATH.exists():
        return []

    try:
        lines = _FINDINGS_PATH.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []

    results: list[dict] = []
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if not include_acknowledged and rec.get("acknowledged"):
            continue
        results.append(rec)
        if len(results) >= limit:
            break

    return results


def acknowledge_finding(finding_id: str, operator_id: str = "operator") -> bool:
    """
    Mark a finding as acknowledged (in-place rewrite of JSONL).

    Returns True if the finding was found and updated.
    """
    if not _FINDINGS_PATH.exists():
        return False

    try:
        lines = _FINDINGS_PATH.read_text(encoding="utf-8").splitlines()
    except Exception:
        return False

    updated = False
    new_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            new_lines.append(line)
            continue
        try:
            rec = json.loads(stripped)
        except Exception:
            new_lines.append(line)
            continue
        if rec.get("finding_id") == finding_id and not rec.get("acknowledged"):
            rec["acknowledged"]    = True
            rec["acknowledged_at"] = _now()
            rec["acknowledged_by"] = operator_id
            updated = True
        new_lines.append(json.dumps(rec))

    if updated:
        try:
            tmp = _FINDINGS_PATH.with_suffix(".tmp")
            tmp.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
            tmp.rename(_FINDINGS_PATH)
        except Exception:
            return False

    return updated


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _age_secs(iso_ts: str) -> float:
    """Return age in seconds of an ISO timestamp relative to now."""
    try:
        dt = datetime.fromisoformat(iso_ts)
        return (datetime.now(timezone.utc) - dt).total_seconds()
    except Exception:
        return 0.0


def _load_supervisor_state() -> Optional[dict]:
    if not _SUPERVISOR_STATE.exists():
        return None
    try:
        return json.loads(_SUPERVISOR_STATE.read_text(encoding="utf-8"))
    except Exception:
        return None
