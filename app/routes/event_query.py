# app/routes/event_query.py
#
# BUILD-001: Read-only event log query endpoint.
#
# Provides filtered access to data/event_log.jsonl via the API.
# Does not write to the log or mutate any state.
#
# Design assumptions:
#   - No severity filter → all severities returned (differs from read_recent_events
#     default which returns action_needed + important only; this is a query endpoint,
#     not a dashboard widget).
#   - 'agent' query param maps to the 'source' field in event records.
#   - 'since' is inclusive: events at exactly that timestamp are included.
#   - _MAX_READ limits how many events are pulled from the log before agent/since
#     filtering. If the log is very large and the user's filter is very narrow,
#     results may be incomplete. This is an explicit tradeoff against unbounded reads.
#
# Endpoints:
#   GET /events  — return recent events with optional filters

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from observability.event_log import SEVERITIES, read_recent_events

router = APIRouter()

# Max events read from the log before agent/since filters are applied.
# Prevents unbounded file reads while still supporting useful filter combinations.
_MAX_READ = 500

# Hard cap on events returned per request (enforced by FastAPI Query validation).
_MAX_LIMIT = 200


@router.get("/events")
def query_events(
    agent:    Optional[str] = Query(default=None,  description="Filter by source agent (e.g. 'belfort', 'operator')"),
    severity: Optional[str] = Query(default=None,  description="Filter by severity: action_needed, important, routine, debug"),
    since:    Optional[str] = Query(default=None,  description="Return only events at or after this ISO 8601 timestamp (e.g. 2026-04-11T00:00:00Z)"),
    limit:    int            = Query(default=20, ge=1, le=_MAX_LIMIT, description=f"Max events to return (1–{_MAX_LIMIT}, default 20)"),
) -> dict:
    """
    Query the event log with optional filters. Returns events newest-first.

    With no filters: returns the 20 most recent events across all severity levels.
    """
    # ── Validate severity param ───────────────────────────────────────────────
    severity_filter: Optional[frozenset] = None
    if severity is not None:
        if severity not in SEVERITIES:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown severity {severity!r}. Valid values: {sorted(SEVERITIES)}",
            )
        severity_filter = frozenset({severity})
    else:
        # Query endpoint returns all severities by default (not just action_needed + important)
        severity_filter = SEVERITIES

    # ── Parse since param ────────────────────────────────────────────────────
    since_dt: Optional[datetime] = None
    if since is not None:
        try:
            since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
            if since_dt.tzinfo is None:
                since_dt = since_dt.replace(tzinfo=timezone.utc)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid 'since' value {since!r}. Use ISO 8601 format, e.g. 2026-04-11T00:00:00Z",
            )

    # ── Read and filter ───────────────────────────────────────────────────────
    events = read_recent_events(limit=_MAX_READ, severity_filter=severity_filter)

    if agent is not None:
        events = [e for e in events if e.get("source") == agent]

    if since_dt is not None:
        filtered = []
        for e in events:
            try:
                ts = datetime.fromisoformat(e["timestamp"].replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts >= since_dt:
                    filtered.append(e)
            except (KeyError, ValueError):
                pass  # skip events with unparseable timestamps — never crash
        events = filtered

    total_matched = len(events)
    events = events[:limit]

    return {
        "events": events,
        "count": len(events),
        "total_matched": total_matched,
        "filters_applied": {
            "agent": agent,
            "severity": severity,
            "since": since,
            "limit": limit,
        },
        "truncated": total_matched > limit,
    }
