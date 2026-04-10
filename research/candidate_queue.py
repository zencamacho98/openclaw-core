# research/candidate_queue.py
#
# Persistent candidate queue for the continuous learning supervisor.
# No imports from app/, ui/, or peter/ — neutral data layer.
#
# The queue is a JSON file at data/candidate_queue.json, written atomically.
# Each entry represents a strategy improvement candidate produced by a research
# cycle. Entries accumulate until the operator resolves them.
#
# Status values:
#   pending       — awaiting operator decision
#   held          — operator deferred (does NOT block the loop)
#   auto_applied  — supervisor applied automatically by policy
#   approved      — operator approved and applied
#   rejected      — operator rejected
#
# Public API:
#   read_queue()                          → list[dict]  (newest-first)
#   pending_candidates()                  → list[dict]
#   add_to_queue(entry: dict)             → str  (queue_id)
#   update_queue_item(queue_id, **fields) → bool
#   get_queue_item(queue_id)              → dict | None
#   ensure_queue_exists()                 → None

from __future__ import annotations

import json
import pathlib
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

_ROOT       = pathlib.Path(__file__).resolve().parent.parent
_QUEUE_PATH = _ROOT / "data" / "candidate_queue.json"

_SCHEMA_VERSION = "1.0"
_VALID_STATUSES = frozenset({"pending", "held", "auto_applied", "approved", "rejected"})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_queue_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    uid = str(uuid.uuid4())[:8]
    return f"cq_{ts}_{uid}"


# ── Persistence ───────────────────────────────────────────────────────────────

def _load() -> dict:
    """Load queue from disk, returning a valid structure on any error."""
    if not _QUEUE_PATH.exists():
        return {"schema_version": _SCHEMA_VERSION, "updated_at": _now(), "candidates": []}
    try:
        data = json.loads(_QUEUE_PATH.read_text(encoding="utf-8"))
        if not isinstance(data.get("candidates"), list):
            data["candidates"] = []
        return data
    except Exception:
        return {"schema_version": _SCHEMA_VERSION, "updated_at": _now(), "candidates": []}


def _save(data: dict) -> None:
    """Atomically write queue to disk (temp file → rename)."""
    _QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = _now()
    tmp = _QUEUE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.rename(_QUEUE_PATH)


def ensure_queue_exists() -> None:
    """Create the queue file with an empty structure if it does not exist."""
    if not _QUEUE_PATH.exists():
        _save({"schema_version": _SCHEMA_VERSION, "updated_at": _now(), "candidates": []})


# ── Public API ────────────────────────────────────────────────────────────────

def read_queue() -> list[dict]:
    """
    Return all candidates, newest-first.

    Reads from disk on every call — no in-process cache.
    """
    data = _load()
    candidates = data.get("candidates", [])
    # Sort newest-first by created_at; fall back to queue_id for ties
    return sorted(
        candidates,
        key=lambda c: (c.get("created_at", ""), c.get("queue_id", "")),
        reverse=True,
    )


def pending_candidates() -> list[dict]:
    """Return candidates with status 'pending', newest-first."""
    return [c for c in read_queue() if c.get("status") == "pending"]


def get_queue_item(queue_id: str) -> Optional[dict]:
    """Return a specific queue item by queue_id, or None."""
    for item in read_queue():
        if item.get("queue_id") == queue_id:
            return item
    return None


def add_to_queue(entry: dict) -> str:
    """
    Add a new candidate entry to the queue.

    The entry dict should contain the candidate fields defined in the plan.
    queue_id and created_at are set here if not already present.

    Returns the queue_id of the added entry.
    """
    data = _load()
    queue_id = entry.get("queue_id") or _make_queue_id()
    entry = dict(entry)  # copy — don't mutate caller's dict
    entry["queue_id"]   = queue_id
    entry.setdefault("created_at",  _now())
    entry.setdefault("status",      "pending")
    entry.setdefault("resolved_at", None)
    entry.setdefault("resolution",  None)
    data["candidates"].append(entry)
    _save(data)
    return queue_id


def update_queue_item(queue_id: str, **fields: Any) -> bool:
    """
    Update fields on a specific queue item in place.

    Returns True if the item was found and updated, False otherwise.
    Only 'status', 'resolved_at', 'resolution' and other non-identity fields
    should be updated this way.  queue_id, created_at are immutable.
    """
    data = _load()
    candidates = data.get("candidates", [])
    for item in candidates:
        if item.get("queue_id") == queue_id:
            # Guard: do not overwrite identity fields
            fields.pop("queue_id",   None)
            fields.pop("created_at", None)
            # Validate status if provided
            if "status" in fields and fields["status"] not in _VALID_STATUSES:
                fields.pop("status")
            item.update(fields)
            data["candidates"] = candidates
            _save(data)
            return True
    return False


def top_pending() -> Optional[dict]:
    """Return the most recent pending candidate, or None."""
    pending = pending_candidates()
    return pending[0] if pending else None
