# frank_lloyd/relay.py
#
# Peter relay queue — Frank Lloyd → operator progress messages.
#
# auto_runner calls append() at key pipeline moments. The neighborhood state
# poll calls consume_unread() on each tick; consumed messages are injected
# into Peter's chat panel as Frank Lloyd progress updates.
#
# Design:
#   - Append-only JSONL log in data/frank_lloyd/peter_relay.jsonl
#   - Cursor pointer in data/frank_lloyd/peter_relay_cursor.txt
#   - Single writer (auto_runner background task); multiple safe readers
#   - Messages have sequential IDs; cursor tracks last-delivered ID
#
# Public API:
#   append(build_id, event, message) → None
#   consume_unread(max_messages=5)   → list[dict]

from __future__ import annotations

import json
import pathlib
from datetime import datetime, timezone

_ROOT         = pathlib.Path(__file__).resolve().parent.parent
_RELAY_LOG    = _ROOT / "data" / "frank_lloyd" / "peter_relay.jsonl"
_RELAY_CURSOR = _ROOT / "data" / "frank_lloyd" / "peter_relay_cursor.txt"


# ── Public API ────────────────────────────────────────────────────────────────

def append(build_id: str, event: str, message: str) -> None:
    """
    Append a relay message for delivery to Peter.

    Called by auto_runner at meaningful pipeline moments only:
      pipeline_start    — safe lane has begun running
      review_needed     — paused; operator approval required
      spec_blocked      — spec generation failed; operator action needed
      draft_ready       — draft generated; ready for apply
      draft_blocked     — draft generation failed; operator action needed
      promoted          — code applied to repo

    Thread-safe for single-writer (background task) use.
    """
    entry_id = _next_id()
    entry = {
        "id":       entry_id,
        "ts":       datetime.now(timezone.utc).isoformat(),
        "build_id": build_id,
        "event":    event,
        "msg":      message,
    }
    try:
        _RELAY_LOG.parent.mkdir(parents=True, exist_ok=True)
        with _RELAY_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except OSError:
        pass  # relay failure is non-fatal


def consume_unread(max_messages: int = 5) -> list[dict]:
    """
    Return unread relay messages and advance the cursor.

    Returns [] if there are no unread messages or on any I/O error.
    Each call advances the cursor so the same messages are never returned twice.
    """
    if not _RELAY_LOG.exists():
        return []

    cursor  = _read_cursor()
    entries = _read_after(cursor)

    if not entries:
        return []

    consumed = entries[:max_messages]
    _write_cursor(max(e["id"] for e in consumed))
    return consumed


# ── Internals ─────────────────────────────────────────────────────────────────

def _next_id() -> int:
    """Derive the next entry ID from the current line count."""
    if not _RELAY_LOG.exists():
        return 0
    try:
        return sum(
            1 for line in _RELAY_LOG.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    except OSError:
        return 0


def _read_after(cursor: int) -> list[dict]:
    """Read all entries with id > cursor, in log order."""
    out: list[dict] = []
    try:
        for line in _RELAY_LOG.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
                if isinstance(e.get("id"), int) and e["id"] > cursor:
                    out.append(e)
            except (json.JSONDecodeError, ValueError):
                pass
    except OSError:
        pass
    return out


def _read_cursor() -> int:
    """Read last consumed ID. Returns -1 if cursor file missing or invalid."""
    if not _RELAY_CURSOR.exists():
        return -1
    try:
        return int(_RELAY_CURSOR.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return -1


def _write_cursor(last_id: int) -> None:
    try:
        _RELAY_CURSOR.write_text(str(last_id), encoding="utf-8")
    except OSError:
        pass
