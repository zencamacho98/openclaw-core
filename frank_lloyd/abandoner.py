# frank_lloyd/abandoner.py
#
# Abandon a Frank Lloyd build cleanly.
#
# Writes an `abandoned` log event for any non-terminal build.
# Allowed from any non-terminal status; blocked if already terminal.
#
# Public API:
#   abandon_build(build_id, notes="") → dict
#   Return shape: {ok, build_id, outcome, error}

from __future__ import annotations

import json
import pathlib
from datetime import datetime, timezone
from typing import Optional

_ROOT      = pathlib.Path(__file__).resolve().parent.parent
_BUILD_LOG = _ROOT / "data" / "frank_lloyd" / "build_log.jsonl"

# Events whose latest occurrence signals a terminal state
_TERMINAL_EVENTS = frozenset({
    "abandoned", "spec_rejected", "draft_promoted",
})

# Events that are recognised as lifecycle transitions
_LIFECYCLE_EVENTS = frozenset({
    "request_queued", "spec_ready", "spec_approved", "spec_rejected",
    "abandoned", "stage2_authorized", "draft_generation_started",
    "draft_generated", "draft_blocked", "draft_promoted", "draft_discarded",
    "blocked",
})


def abandon_build(build_id: str, notes: str = "") -> dict:
    """
    Abandon a non-terminal Frank Lloyd build.

    Appends an `abandoned` event to the build log. Allowed from any
    non-terminal state. Returns ok=False if the build is not found,
    already terminal, or the log cannot be written.

    Returns {ok, build_id, outcome, error}.
    """
    build_id = build_id.strip().upper()

    # Check current state from log
    current_event = _latest_lifecycle_event(build_id)
    if current_event is None:
        return {"ok": False, "build_id": build_id,
                "error": f"{build_id} not found in build log."}

    if current_event in _TERMINAL_EVENTS:
        state_label = current_event.replace("_", " ")
        return {"ok": False, "build_id": build_id,
                "error": f"{build_id} is already {state_label} and cannot be abandoned."}

    # Append abandoned event
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "build_id":  build_id,
        "event":     "abandoned",
        "notes":     (notes.strip() or f"Abandoned by operator from state: {current_event}"),
        "extra":     {"abandoned_from": current_event},
    }
    try:
        _BUILD_LOG.parent.mkdir(parents=True, exist_ok=True)
        with _BUILD_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event) + "\n")
    except OSError as exc:
        return {"ok": False, "build_id": build_id,
                "error": f"Failed to write abandon event: {exc}"}

    # Relay notification to Peter
    try:
        import frank_lloyd.relay as _relay
        _relay.append(
            build_id, "abandoned",
            f"{build_id} was abandoned (was: {current_event.replace('_', ' ')}).",
        )
    except Exception:
        pass

    return {
        "ok":      True,
        "build_id": build_id,
        "outcome": "abandoned",
        "error":   None,
    }


# ── Internal helpers ──────────────────────────────────────────────────────────

def _latest_lifecycle_event(build_id: str) -> Optional[str]:
    """Return the most recent lifecycle event name for build_id, or None."""
    if not _BUILD_LOG.exists():
        return None
    latest: Optional[str] = None
    try:
        for line in _BUILD_LOG.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
                if ev.get("build_id") == build_id and ev.get("event") in _LIFECYCLE_EVENTS:
                    latest = ev["event"]
            except (json.JSONDecodeError, ValueError):
                pass
    except OSError:
        return None
    return latest
