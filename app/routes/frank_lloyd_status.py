# app/routes/frank_lloyd_status.py
#
# BUILD-002: Read-only Frank Lloyd Stage 1 status endpoint.
#
# Reads data/frank_lloyd/build_log.jsonl and derives current build state per build_id.
# Returns a response shaped per docs/frank_lloyd/DATA_MODEL.md §Schema 4.
#
# Design decisions:
#   - build_log.jsonl is the sole source of truth for status derivation.
#     The requests/ directory is consulted only as a title fallback when the
#     request_queued event carries no title.
#   - Unknown event types (Stage 2+ events like "promoted", "staged") are silently
#     skipped. Only the 5 Stage 1 events are recognised. This keeps the endpoint
#     valid if a Stage 2 event appears in the log in the future.
#   - Malformed JSONL lines are skipped — same pattern as observability/event_log.py.
#   - Missing data/frank_lloyd/ directory or missing build_log.jsonl returns an
#     empty-state 200 response. The endpoint never crashes on absent files.
#
# Status derivation: the latest known Stage 1 event per build_id determines status.
#   request_queued → pending_spec   (pending bucket)
#   spec_ready     → pending_review (pending bucket)
#   spec_approved  → spec_approved  (completed bucket)
#   spec_rejected  → spec_rejected  (completed bucket)
#   abandoned      → abandoned      (completed bucket)
#
# Endpoints:
#   GET /frank-lloyd/status  — Frank Lloyd Stage 1 status

from __future__ import annotations

import json
import pathlib
import re
from typing import Optional

# Strip conversational boilerplate before deriving display titles (mirrors request_writer).
_TITLE_BOILERPLATE_RE = re.compile(
    r'^(?:peter[,.\s]+)?(?:please\s+)?(?:have|tell|ask)\s+frank\s*lloyd\s+(?:to\s+)?',
    re.IGNORECASE,
)
_TITLE_SKIP = frozenset({"a", "an", "the", "new", "that", "which", "with", "and", "for", "so", "to"})


def _clean_display_title(description: str) -> str:
    """Derive a clean 6-word display title from a raw build description."""
    text = _TITLE_BOILERPLATE_RE.sub("", description).strip() or description
    words = text.split()
    meaningful = [w for w in words[:12] if w.lower().rstrip(".,;") not in _TITLE_SKIP]
    title = " ".join(meaningful[:6]).rstrip(".,;")
    return title or description[:40]

from fastapi import APIRouter

router = APIRouter()

_ROOT         = pathlib.Path(__file__).resolve().parent.parent.parent
_BUILD_LOG    = _ROOT / "data" / "frank_lloyd" / "build_log.jsonl"
_REQUESTS_DIR = _ROOT / "data" / "frank_lloyd" / "requests"

# Recognised events — anything else is silently ignored.
# Stage 1 events cover intake through approval/rejection/abandonment.
# Stage 2 draft events (draft_generation_started, draft_generated, draft_blocked)
# are included so that a build's status advances correctly through Stage 2.
_STAGE1_EVENTS  = frozenset({
    "request_queued", "spec_ready", "spec_approved", "spec_rejected", "abandoned",
    "stage2_authorized",
    "draft_generation_started", "draft_generated", "draft_blocked",
    "draft_promoted",
    "draft_discarded",
})
_PENDING_EVENTS    = frozenset({"request_queued", "spec_ready"})
# Builds actively moving through the pipeline — spec approved but not yet shipped.
# draft_discarded is included because it resets to stage2_authorized (still in progress).
_INPROGRESS_EVENTS = frozenset({
    "spec_approved", "stage2_authorized",
    "draft_generation_started", "draft_generated", "draft_blocked",
    "draft_discarded",
})
# Truly terminal — build is done (shipped, rejected, or abandoned).
_COMPLETED_EVENTS  = frozenset({"draft_promoted", "spec_rejected", "abandoned"})


@router.get("/frank-lloyd/status")
def frank_lloyd_status() -> dict:
    """
    Return Frank Lloyd status derived from data/frank_lloyd/build_log.jsonl.

    Three honest buckets:
      pending    — awaiting action before pipeline starts (pending_spec, pending_review)
      inprogress — spec approved, pipeline active, not yet shipped
      completed  — truly terminal (draft_promoted, spec_rejected, abandoned)

    Returns empty lists if no builds exist or if data/frank_lloyd/ is missing.
    """
    raw_events = _read_log(_BUILD_LOG)

    # Group events by build_id, preserving file order (assumed chronological)
    by_build: dict[str, list[dict]] = {}
    for ev in raw_events:
        bid = ev.get("build_id")
        if bid:
            by_build.setdefault(bid, []).append(ev)

    pending:    list[dict] = []
    inprogress: list[dict] = []
    completed:  list[dict] = []

    for build_id, events in by_build.items():
        item = _build_status_item(build_id, events)
        if item is None:
            continue
        bucket = item.pop("_bucket")
        if bucket == "pending":
            pending.append(item)
        elif bucket == "inprogress":
            inprogress.append(item)
        else:
            completed.append(item)

    # Newest first within each bucket
    pending.sort(   key=lambda b: b.get("requested_at") or "", reverse=True)
    inprogress.sort(key=lambda b: b.get("resolved_at")  or "", reverse=True)
    completed.sort( key=lambda b: b.get("resolved_at")  or "", reverse=True)

    # approved_count = builds that passed spec approval (all inprogress + promoted)
    approved_count = len(inprogress) + sum(
        1 for b in completed if b["status"] == "draft_promoted"
    )

    return {
        "builder_stage":    1,
        "pending_builds":   pending,
        "inprogress_builds": inprogress,
        "completed_builds": completed,
        "summary": {
            "pending_count":    len(pending),
            "inprogress_count": len(inprogress),
            "completed_count":  len(completed),
            "approved_count":   approved_count,
            "rejected_count":   sum(1 for b in completed if b["status"] == "spec_rejected"),
            "abandoned_count":  sum(1 for b in completed if b["status"] == "abandoned"),
        },
    }


# ── Internal helpers ──────────────────────────────────────────────────────────

def _build_status_item(build_id: str, events: list[dict]) -> Optional[dict]:
    """
    Derive the status item for one build from its events.
    Returns None if no recognised Stage 1 event is present.
    The returned dict contains a temporary '_bucket' key
    ('pending', 'inprogress', or 'completed') that the caller removes.
    """
    # Sort ascending by timestamp — ISO 8601 strings sort correctly lexicographically
    sorted_evs = sorted(events, key=lambda e: e.get("timestamp") or "")

    request_ev:        Optional[dict] = None
    latest_stage1_ev:  Optional[dict] = None

    for ev in sorted_evs:
        etype = ev.get("event")
        if etype == "request_queued" and request_ev is None:
            request_ev = ev
        if etype in _STAGE1_EVENTS:
            latest_stage1_ev = ev

    if latest_stage1_ev is None:
        return None  # no known Stage 1 events — skip this build

    etype = latest_stage1_ev.get("event")
    extra = latest_stage1_ev.get("extra") or {}

    title        = _extract_title(build_id, request_ev)
    requested_at = request_ev.get("timestamp") if request_ev else None

    if etype in _PENDING_EVENTS:
        req_extra = (request_ev.get("extra") or {}) if request_ev else {}
        return {
            "_bucket":         "pending",
            "build_id":        build_id,
            "title":           title,
            "status":          "pending_spec" if etype == "request_queued" else "pending_review",
            "requested_at":    requested_at,
            "build_type_hint": req_extra.get("build_type_hint"),
        }

    # draft_discarded resets the build to stage2_authorized for a new attempt.
    derived_status = "stage2_authorized" if etype == "draft_discarded" else etype

    # Builds in the active pipeline (spec approved through draft ready/blocked)
    # are "in progress" — not completed.  Only shipped/rejected/abandoned are done.
    bucket = "inprogress" if etype in _INPROGRESS_EVENTS else "completed"
    return {
        "_bucket":         bucket,
        "build_id":        build_id,
        "title":           title,
        "status":          derived_status,
        "stage_completed": extra.get("stage_completed") if etype == "spec_approved" else None,
        "requested_at":    requested_at,
        "resolved_at":     latest_stage1_ev.get("timestamp"),
        "build_type":      extra.get("build_type") if etype == "spec_approved" else None,
        "risk_level":      extra.get("risk_level") if etype == "spec_approved" else None,
    }


def _extract_title(build_id: str, request_ev: Optional[dict]) -> str:
    """
    Return a clean display title for the build.

    Prefers deriving from the full description (stripping conversational
    boilerplate) so that titles like "Peter, have Frank Lloyd fix Belfort's"
    become "fix Belfort's stopping-state UI control" instead.

    Priority: description from request file → stored title in request file
              → title in request_queued event → build_id.
    """
    req_file = _REQUESTS_DIR / f"{build_id}_request.json"
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
    # Fallback: title from the request_queued event
    if request_ev:
        title = (request_ev.get("extra") or {}).get("title")
        if title:
            return title
    return build_id  # last resort


def _read_log(path: pathlib.Path) -> list[dict]:
    """
    Read all entries from a JSONL file.
    Returns [] if the file is missing, unreadable, or all lines are malformed.
    Skips individual malformed lines without crashing.
    """
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
                pass  # skip — never crash on bad data
    except OSError:
        pass
    return out
