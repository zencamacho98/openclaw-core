# frank_lloyd/job.py
#
# BUILD-018: Unified Frank Lloyd job model.
#
# Consolidates state derivation for a build into a single place.
# All other modules (spec_writer, spec_approver, stage2_*) still read the
# build_log individually — this module provides a consolidated API/UI layer.
#
# Phase model:
#   intake     — pending_spec, pending_review, blocked (spec generation failed)
#   plan       — spec_approved (awaiting Stage 2 authorization)
#   authorized — stage2_authorized (ready for draft generation)
#   building   — draft_generating, draft_generated, draft_blocked
#   live       — draft_promoted (complete)
#   closed     — spec_rejected, abandoned
#
# Public API:
#   load_job(build_id)      → FLJob | None
#   load_active_job()       → FLJob | None  (highest-priority build)
#   list_jobs()             → list[FLJob]   (all builds, priority order)

from __future__ import annotations

import json
import pathlib
import re
from dataclasses import dataclass, field
from typing import Optional

_ROOT         = pathlib.Path(__file__).resolve().parent.parent
_FL_BUILD_LOG = _ROOT / "data" / "frank_lloyd" / "build_log.jsonl"
_FL_REQUESTS  = _ROOT / "data" / "frank_lloyd" / "requests"

# All recognised log events
_ALL_EVENTS = frozenset({
    "request_queued", "spec_ready", "spec_approved", "spec_rejected",
    "abandoned", "stage2_authorized", "draft_generation_started",
    "draft_generated", "draft_blocked", "draft_promoted", "draft_discarded",
    "blocked",
})

# Status derived from the latest known event
_STATUS_FROM_EVENT: dict[str, str] = {
    "request_queued":           "pending_spec",
    "spec_ready":               "pending_review",
    "spec_approved":            "spec_approved",
    "spec_rejected":            "spec_rejected",
    "abandoned":                "abandoned",
    "stage2_authorized":        "stage2_authorized",
    "draft_generation_started": "draft_generating",
    "draft_generated":          "draft_generated",
    "draft_blocked":            "draft_blocked",
    "draft_promoted":           "draft_promoted",
    "draft_discarded":          "stage2_authorized",  # resets to stage2_authorized
    "blocked":                  "blocked",
}

# Lifecycle phase for each status
_PHASE_FROM_STATUS: dict[str, str] = {
    "pending_spec":       "intake",
    "pending_review":     "intake",
    "blocked":            "intake",
    "spec_approved":      "plan",
    "stage2_authorized":  "authorized",
    "draft_generating":   "building",
    "draft_generated":    "building",
    "draft_blocked":      "building",
    "draft_promoted":     "live",
    "spec_rejected":      "closed",
    "abandoned":          "closed",
}

# What the operator should do next
_NEXT_ACTION: dict[str, str] = {
    "pending_spec":       "Generate spec",
    "pending_review":     "Review spec — then approve or reject",
    "blocked":            "Spec generation blocked — check LM availability",
    "spec_approved":      "Authorize Stage 2 to start draft generation",
    "stage2_authorized":  "Generate draft when ready",
    "draft_generating":   "Wait — Frank Lloyd is generating the draft",
    "draft_generated":    "Review draft — then promote to repo or discard",
    "draft_blocked":      "Review block reason — discard and retry",
    "draft_promoted":     "Complete — code is live in repo",
    "spec_rejected":      "Closed — spec rejected",
    "abandoned":          "Closed — build abandoned",
}

# Who is responsible for the next step
_WAITING_ON: dict[str, str] = {
    "pending_spec":       "system",
    "pending_review":     "operator",
    "blocked":            "operator",
    "spec_approved":      "operator",
    "stage2_authorized":  "operator",
    "draft_generating":   "system",
    "draft_generated":    "operator",
    "draft_blocked":      "operator",
    "draft_promoted":     "complete",
    "spec_rejected":      "complete",
    "abandoned":          "complete",
}

# Operator-attention priority for load_active_job() — lower = higher priority
_PRIORITY: dict[str, int] = {
    "pending_review":     1,
    "draft_generated":    2,
    "draft_blocked":      3,
    "spec_approved":      4,
    "stage2_authorized":  5,
    "draft_generating":   6,
    "pending_spec":       7,
    "blocked":            8,
    "draft_promoted":     90,
    "spec_rejected":      91,
    "abandoned":          92,
}

_TITLE_BOILERPLATE_RE = re.compile(
    r'^(?:peter[,.\s]+)?(?:please\s+)?(?:have|tell|ask)\s+frank\s*lloyd\s+(?:to\s+)?',
    re.IGNORECASE,
)
_TITLE_SKIP = frozenset({"a", "an", "the", "new", "that", "which", "with", "and", "for", "so", "to"})


_MODE_FROM_SOURCE: dict[str, str] = {
    "smart_queue_build":    "build",
    "smart_queue_refactor": "refactor",
    "smart_queue_cleanup":  "cleanup",
    "smart_queue_diagnose": "diagnose",
    "smart_queue_improve":  "improve",
    "smart_queue_monitor":  "monitor",
    "smart_queue_docs":     "docs",
}


@dataclass
class FLJob:
    """Unified view of a Frank Lloyd build job."""
    build_id:     str
    title:        str
    status:       str
    phase:        str
    next_action:  str
    waiting_on:   str              # "operator" | "system" | "complete"
    requested_at: Optional[str]
    updated_at:   Optional[str]
    build_type:   Optional[str]         = None
    risk_level:   Optional[str]         = None
    mode:         Optional[str]         = None   # brief_shaper mode (build/refactor/…)
    events:       list[dict]            = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "build_id":     self.build_id,
            "title":        self.title,
            "status":       self.status,
            "phase":        self.phase,
            "next_action":  self.next_action,
            "waiting_on":   self.waiting_on,
            "requested_at": self.requested_at,
            "updated_at":   self.updated_at,
            "build_type":   self.build_type,
            "risk_level":   self.risk_level,
            "mode":         self.mode,
            "events":       self.events,
        }


# ── Event humanization ────────────────────────────────────────────────────────

# Human-readable label, CSS class, actor for each log event type
_EVENT_META: dict[str, tuple[str, str]] = {
    "request_queued":           ("Build request queued",        "ok"),
    "spec_ready":               ("Plan generated",               "ok"),
    "spec_approved":            ("Plan approved",                "ok"),
    "spec_rejected":            ("Plan rejected",                "blocked"),
    "abandoned":                ("Build abandoned",              "blocked"),
    "stage2_authorized":        ("Stage 2 authorized",           "ok"),
    "draft_generation_started": ("Generating code draft\u2026", "active"),
    "draft_generated":          ("Draft ready for review",       "review"),
    "draft_blocked":            ("Draft generation blocked",     "blocked"),
    "draft_promoted":           ("Applied to repo",              "done"),
    "draft_discarded":          ("Draft discarded \u2014 retrying", "ok"),
    "blocked":                  ("Spec generation blocked",      "blocked"),
}

_AUTO_KEYWORDS = ("auto-approved", "auto-authorized", "safe lane", "auto_runner")


def _humanize_event(ev: dict) -> Optional[dict]:
    """
    Convert a raw build log event dict to a humanized stream entry.

    Returns None for unrecognised event types.
    Each entry: {event, ts, ts_short, label, detail, cls}
    """
    etype = ev.get("event", "")
    if etype not in _EVENT_META:
        return None

    label, cls = _EVENT_META[etype]
    notes = (ev.get("notes") or "").lower()
    extra = ev.get("extra") or {}
    ts    = ev.get("timestamp") or ""

    # Auto-approval / auto-authorization detection
    auto = any(kw in notes for kw in _AUTO_KEYWORDS)
    if auto:
        if etype == "spec_approved":
            label = "Plan auto-approved (low risk)"
        elif etype == "stage2_authorized":
            label = "Stage 2 auto-authorized"

    # Build detail string from extra fields
    detail_parts: list[str] = []
    if etype == "spec_ready":
        bt = extra.get("build_type") or ""
        rl = extra.get("risk_level") or ""
        if bt: detail_parts.append(bt.replace("_", " "))
        if rl: detail_parts.append(rl + " risk")
    elif etype in ("draft_generated", "draft_generation_started"):
        model = extra.get("model") or ""
        if model:
            # Use only the model short-name after last "/"
            detail_parts.append(model.split("/")[-1])
    elif etype == "draft_blocked":
        reason = (extra.get("reason") or "").replace("_", " ")
        if reason: detail_parts.append(reason)
    elif etype == "draft_promoted":
        # Try to get the target path from notes or extra
        pass

    # Short HH:MM timestamp
    ts_short = ts[11:16] if len(ts) >= 16 else ""

    return {
        "event":    etype,
        "ts":       ts,
        "ts_short": ts_short,
        "label":    label,
        "detail":   " \u00b7 ".join(detail_parts),
        "cls":      cls,
    }


# ── Public API ─────────────────────────────────────────────────────────────────

def load_job(build_id: str) -> Optional[FLJob]:
    """
    Load the current FLJob for a build_id from the build log.
    Returns None if the build_id has no recognised events.
    """
    events = _read_log(_FL_BUILD_LOG)
    return _build_job(build_id.upper(), events)


def load_active_job() -> Optional[FLJob]:
    """
    Return the highest-priority build needing operator attention.

    Priority (highest first):
      pending_review → draft_generated → draft_blocked → spec_approved
      → stage2_authorized → draft_generating → pending_spec → blocked

    Terminal builds (promoted, rejected, abandoned) are excluded.
    Returns None if no active builds exist.
    """
    events = _read_log(_FL_BUILD_LOG)
    active_jobs = [
        j for bid in _ordered_build_ids(events)
        for j in [_build_job(bid, events)]
        if j and j.waiting_on != "complete"
    ]
    if not active_jobs:
        return None
    return min(active_jobs, key=lambda j: _PRIORITY.get(j.status, 99))


def list_jobs() -> list[FLJob]:
    """
    Return all builds as FLJob list.

    Ordering: active jobs by priority, then terminal jobs newest-first.
    """
    events   = _read_log(_FL_BUILD_LOG)
    build_ids = _ordered_build_ids(events)
    all_jobs  = [j for bid in build_ids for j in [_build_job(bid, events)] if j]

    active   = [j for j in all_jobs if j.waiting_on != "complete"]
    terminal = [j for j in all_jobs if j.waiting_on == "complete"]
    active.sort(  key=lambda j: _PRIORITY.get(j.status, 99))
    terminal.sort(key=lambda j: j.updated_at or "", reverse=True)
    return active + terminal


# ── Internal helpers ──────────────────────────────────────────────────────────

def _build_job(build_id: str, events: list[dict]) -> Optional[FLJob]:
    """Derive FLJob from all events for a given build_id."""
    build_events = sorted(
        [e for e in events if e.get("build_id") == build_id],
        key=lambda e: e.get("timestamp") or "",
    )
    if not build_events:
        return None

    request_ev:        Optional[dict] = None
    latest_event:      Optional[dict] = None
    latest_event_name: Optional[str]  = None

    for ev in build_events:
        etype = ev.get("event", "")
        if etype == "request_queued" and request_ev is None:
            request_ev = ev
        if etype in _ALL_EVENTS:
            latest_event      = ev
            latest_event_name = etype

    if latest_event_name is None:
        return None

    status = _STATUS_FROM_EVENT.get(latest_event_name, latest_event_name)

    # Extract build_type, risk_level, and mode from build events
    build_type: Optional[str] = None
    risk_level:  Optional[str] = None
    mode:        Optional[str] = None
    for ev in reversed(build_events):
        etype  = ev.get("event", "")
        if etype in ("spec_approved", "spec_ready"):
            ev_extra = ev.get("extra") or {}
            build_type = build_type or ev_extra.get("build_type") or None
            risk_level = risk_level  or ev_extra.get("risk_level")  or None
            if build_type and risk_level:
                break

    # Extract mode from source field in request_queued event
    for ev in build_events:
        if ev.get("event") == "request_queued":
            source = (ev.get("extra") or {}).get("source", "")
            # "smart_queue_refactor" → mode="refactor"
            mode = _MODE_FROM_SOURCE.get(source)
            if mode is None and source.startswith("smart_queue_"):
                mode = source[len("smart_queue_"):]  # forward-compat
            break

    # Build humanized event stream (all recognisable events, chronological)
    humanized_events = [
        h for h in (_humanize_event(e) for e in build_events)
        if h is not None
    ]

    return FLJob(
        build_id     = build_id,
        title        = _extract_title(build_id, request_ev),
        status       = status,
        phase        = _PHASE_FROM_STATUS.get(status, "unknown"),
        next_action  = _NEXT_ACTION.get(status, ""),
        waiting_on   = _WAITING_ON.get(status, ""),
        requested_at = request_ev.get("timestamp") if request_ev else None,
        updated_at   = latest_event.get("timestamp") if latest_event else None,
        build_type   = build_type,
        risk_level   = risk_level,
        mode         = mode,
        events       = humanized_events,
    )


def _ordered_build_ids(events: list[dict]) -> list[str]:
    """Return build_ids in the order they first appeared in the log."""
    seen:     list[str] = []
    seen_set: set[str]  = set()
    for ev in events:
        bid = ev.get("build_id")
        if bid and bid not in seen_set:
            seen.append(bid)
            seen_set.add(bid)
    return seen


def _extract_title(build_id: str, request_ev: Optional[dict]) -> str:
    """Derive a clean display title for the build."""
    req_file = _FL_REQUESTS / f"{build_id}_request.json"
    if req_file.exists():
        try:
            data = json.loads(req_file.read_text(encoding="utf-8"))
            description = (data.get("description") or "").strip()
            if description and len(description.split()) >= 5:
                return _clean_display_title(description)
            stored_title = (data.get("title") or "").strip()
            if stored_title:
                return stored_title
        except (OSError, ValueError):
            pass
    if request_ev:
        title = (request_ev.get("extra") or {}).get("title")
        if title:
            return title
    return build_id


def _clean_display_title(description: str) -> str:
    """Derive a clean 6-word display title from a raw build description."""
    text  = _TITLE_BOILERPLATE_RE.sub("", description).strip() or description
    words = text.split()
    meaningful = [w for w in words[:12] if w.lower().rstrip(".,;") not in _TITLE_SKIP]
    title = " ".join(meaningful[:6]).rstrip(".,;")
    return title or description[:40]


def _read_log(path: pathlib.Path) -> list[dict]:
    """Read all entries from a JSONL file."""
    if not path.exists():
        return []
    out: list[dict] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except (json.JSONDecodeError, ValueError):
                pass
    except OSError:
        pass
    return out
