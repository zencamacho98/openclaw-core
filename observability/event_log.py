# observability/event_log.py
#
# Minimal append-only event log for operator actions.
# One JSONL file; one record per event.
#
# Public API:
#   append_event(event_type, summary, severity, source, campaign_id, extra) → None
#   read_recent_events(limit, severity_filter) → list[dict]
#
# Severity levels (most → least urgent):
#   action_needed  — operator must act (e.g. review_held)
#   important      — notable outcomes (apply, skip, start, stop)
#   routine        — low-noise (cancel_stop, review_resumed)
#   debug          — reserved, not rendered in UI
#
# Storage: data/event_log.jsonl  (append-only, oldest at top, newest at bottom)
# Reads return newest-first (reversed).
# Write errors are swallowed — event loss is acceptable; never block an action.

from __future__ import annotations

import json
import pathlib
from datetime import datetime, timezone
from typing import Optional

_ROOT     = pathlib.Path(__file__).resolve().parent.parent
_LOG_PATH = _ROOT / "data" / "event_log.jsonl"

# Severities understood by read_recent_events
SEVERITIES = frozenset({"action_needed", "important", "routine", "debug"})

# Default filter: show action_needed + important only
DEFAULT_FILTER = frozenset({"action_needed", "important"})


def append_event(
    event_type: str,
    summary:    str,
    severity:   str,
    source:     str = "operator",
    campaign_id: Optional[str] = None,
    extra:       Optional[dict] = None,
) -> None:
    """
    Append one event to data/event_log.jsonl.

    Silently swallows any write error — callers must not depend on this
    succeeding. The action that triggered the event has already completed
    before this is called.
    """
    record = {
        "timestamp":   datetime.now(timezone.utc).isoformat(),
        "severity":    severity,
        "source":      source,
        "event_type":  event_type,
        "summary":     summary,
        "campaign_id": campaign_id,
        "extra":       extra or {},
    }
    try:
        _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except Exception:
        pass


def read_recent_events(
    limit:            int = 20,
    severity_filter:  Optional[frozenset] = None,
) -> list[dict]:
    """
    Return recent events, newest-first.

    severity_filter — severities to include (default: action_needed + important).
    Malformed JSONL lines are skipped without raising.
    Missing file returns [].
    """
    if severity_filter is None:
        severity_filter = DEFAULT_FILTER

    if not _LOG_PATH.exists():
        return []

    try:
        raw = _LOG_PATH.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []

    results: list[dict] = []
    for line in reversed(raw):
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except Exception:
            continue  # skip malformed lines — never crash
        if event.get("severity") in severity_filter:
            results.append(event)
            if len(results) >= limit:
                break

    return results
