# frank_lloyd/abandoner.py
#
# Abandon a Frank Lloyd build cleanly.
#
# Writes an `abandoned` log event for any non-terminal build.
# Allowed from any non-terminal status; blocked if already terminal.
#
# Public API:
#   abandon_build(build_id, notes="")             → dict
#   abandon_by_source(source, notes="")            → dict
#   Return shape for abandon_build: {ok, build_id, outcome, error}
#   Return shape for abandon_by_source: {ok, source, abandoned, skipped, errors}

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


def abandon_by_source(source: str, notes: str = "") -> dict:
    """
    Bulk-abandon all non-terminal builds originating from a given source channel.

    Source is read from the request_queued event's extra.source field.
    Terminal builds (abandoned, spec_rejected, draft_promoted) are skipped.

    Returns {ok, source, abandoned: list[str], skipped: list[str], errors: list[str]}.
    """
    if not source:
        return {
            "ok":      False,
            "source":  source,
            "abandoned": [],
            "skipped":   [],
            "errors":    ["No source specified"],
        }

    # Collect all build IDs that originated from this source
    source_builds: list[str] = []
    if _BUILD_LOG.exists():
        try:
            for line in _BUILD_LOG.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                    if (ev.get("event") == "request_queued"
                            and (ev.get("extra") or {}).get("source") == source):
                        bid = ev.get("build_id")
                        if bid and bid not in source_builds:
                            source_builds.append(bid)
                except (json.JSONDecodeError, ValueError):
                    pass
        except OSError:
            pass

    abandoned: list[str] = []
    skipped:   list[str] = []
    errors:    list[str] = []

    for bid in source_builds:
        current = _latest_lifecycle_event(bid)
        if current is None:
            errors.append(bid)
            continue
        if current in _TERMINAL_EVENTS:
            skipped.append(bid)
            continue
        result = abandon_build(bid, notes=notes or f"Bulk-abandoned by source: {source}")
        if result.get("ok"):
            abandoned.append(bid)
        else:
            errors.append(bid)

    return {
        "ok":      True,
        "source":  source,
        "abandoned": abandoned,
        "skipped":   skipped,
        "errors":    errors,
    }


def abandon_all(notes: str = "") -> dict:
    """
    Abandon ALL non-terminal Frank Lloyd builds regardless of source.

    Scans the entire build log, collects every build that has ever been created,
    and abandons any that are not already in a terminal state.

    Terminal states that are skipped: abandoned, spec_rejected, draft_promoted.

    Returns {ok, abandoned: list[str], skipped: list[str], errors: list[str]}.
    """
    # Collect all known build IDs (preserving order of first appearance)
    all_builds: list[str] = []
    if _BUILD_LOG.exists():
        try:
            for line in _BUILD_LOG.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                    bid = ev.get("build_id")
                    if bid and bid not in all_builds:
                        all_builds.append(bid)
                except (json.JSONDecodeError, ValueError):
                    pass
        except OSError:
            pass

    abandoned: list[str] = []
    skipped:   list[str] = []
    errors:    list[str] = []

    for bid in all_builds:
        current = _latest_lifecycle_event(bid)
        if current is None:
            errors.append(bid)
            continue
        if current in _TERMINAL_EVENTS:
            skipped.append(bid)
            continue
        result = abandon_build(bid, notes=notes or "Cleared by operator — purge all")
        if result.get("ok"):
            abandoned.append(bid)
        else:
            errors.append(bid)

    return {
        "ok":        True,
        "abandoned": abandoned,
        "skipped":   skipped,
        "errors":    errors,
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
