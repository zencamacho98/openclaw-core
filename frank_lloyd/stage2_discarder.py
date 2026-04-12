# frank_lloyd/stage2_discarder.py
#
# Stage 2 draft discard / retry-lane for Frank Lloyd.
#
# Clears staged draft artifacts so the build can return to stage2_authorized
# and a new draft attempt can begin. Does NOT touch Stage 1 artifacts or the
# Stage 2 authorization record.
#
# Discardable states (explicit, justified):
#   draft_generated — reviewed draft that the operator does not want to promote
#   draft_blocked   — generation was blocked; retry after resolving the issue
#
# Not discardable (by design):
#   draft_promoted  — live in the repo; discard would corrupt the audit trail
#   draft_generating — in-flight; discarding during generation could race the drafter
#   stage2_authorized — no draft exists yet; already the "ready" state
#   anything earlier — Stage 1 state; Stage 2 artifacts do not exist
#
# What is removed on discard:
#   staging/frank_lloyd/{build_id}/stage2/   (entire directory)
#
# What is preserved:
#   staging/frank_lloyd/{build_id}/stage1/   (spec archive)
#   staging/frank_lloyd/{build_id}/stage2_authorization.json
#   data/frank_lloyd/archives/{build_id}/    (promotion or other archive records)
#   data/frank_lloyd/build_log.jsonl         (audit trail — append-only)
#
# After discard:
#   draft_discarded event appended to build_log.jsonl
#   Status derives as stage2_authorized (same as before draft generation started)
#
# Public API:
#   DISCARDABLE_STATES                        — frozenset of discardable status strings
#   discard_draft(build_id, notes="") → dict
#   Return shape: {ok, build_id, discarded_at, error}

from __future__ import annotations

import json
import pathlib
import shutil
from datetime import datetime, timezone
from typing import Optional

_ROOT         = pathlib.Path(__file__).resolve().parent.parent
_FL_BUILD_LOG = _ROOT / "data" / "frank_lloyd" / "build_log.jsonl"
_FL_STAGING   = _ROOT / "staging" / "frank_lloyd"

# Status derivation map — must include draft_discarded so derive_status() works
# correctly when called on a log that already has a discard event.
_STATUS_FROM_EVENT: dict[str, str] = {
    "request_queued":            "pending_spec",
    "spec_ready":                "pending_review",
    "spec_approved":             "spec_approved",
    "spec_rejected":             "spec_rejected",
    "abandoned":                 "abandoned",
    "stage2_authorized":         "stage2_authorized",
    "draft_generation_started":  "draft_generating",
    "draft_generated":           "draft_generated",
    "draft_blocked":             "draft_blocked",
    "draft_promoted":            "draft_promoted",
    "draft_discarded":           "stage2_authorized",  # resets to retry-ready state
}

# Explicitly allowed discard states. Anything not in this set is rejected.
DISCARDABLE_STATES = frozenset({"draft_generated", "draft_blocked"})


# ── Public API ────────────────────────────────────────────────────────────────

def discard_draft(build_id: str, notes: str = "") -> dict:
    """
    Discard the current Stage 2 draft artifacts and reset the build to
    stage2_authorized so a new draft attempt can begin.

    Safety constraints:
    - Build must exist in the build log.
    - Build must be in a discardable state (draft_generated or draft_blocked).
    - staging/frank_lloyd/{build_id}/stage2/ must exist.
    - Stage 1 artifacts and the Stage 2 authorization record are never touched.
    - Promoted builds cannot be discarded.

    On success:
    - Removes staging/frank_lloyd/{build_id}/stage2/ entirely.
    - Appends draft_discarded event to build_log.jsonl.
    - Status derives back to stage2_authorized.

    Returns {ok, build_id, discarded_at, error}.
    """
    build_id = build_id.strip().upper()

    # ── State validation (no writes on failure) ───────────────────────────────
    events = _read_log(_FL_BUILD_LOG)
    build_events = [e for e in events if e.get("build_id") == build_id]

    if not build_events:
        return _err(
            build_id,
            f"No events found for {build_id}. "
            "Check the build ID — use 'status' or GET /frank-lloyd/status.",
        )

    status = _derive_status(build_id, events)
    if status is None:
        return _err(
            build_id,
            f"{build_id} has no recognized status events in the build log.",
        )

    if status == "draft_promoted":
        return _err(
            build_id,
            f"{build_id} has already been promoted to the live repo. "
            "Discarding a promoted build would corrupt the audit trail.",
        )

    if status == "draft_generating":
        return _err(
            build_id,
            f"{build_id} has an in-progress draft generation. "
            "Wait for generation to complete before discarding.",
        )

    if status not in DISCARDABLE_STATES:
        return _err(
            build_id,
            f"{build_id} is in state '{status}', which is not discardable. "
            f"Only {sorted(DISCARDABLE_STATES)} drafts can be discarded.",
        )

    # ── Staging artifact validation ───────────────────────────────────────────
    stage2_dir = _FL_STAGING / build_id / "stage2"
    if not stage2_dir.exists():
        return _err(
            build_id,
            f"No Stage 2 staging directory found at {stage2_dir}. "
            "Cannot discard — stage2 artifacts are absent.",
        )

    # ── Remove stage2 artifacts ───────────────────────────────────────────────
    now_str = datetime.now(timezone.utc).isoformat()
    try:
        shutil.rmtree(str(stage2_dir))
    except OSError as exc:
        return _err(build_id, f"Failed to remove stage2 artifacts: {exc}")

    # ── Append draft_discarded event ──────────────────────────────────────────
    _append_log(
        _FL_BUILD_LOG, build_id, "draft_discarded",
        notes=f"Stage 2 draft discarded by operator. Previous state: {status}.",
        extra={"previous_status": status, "notes": notes or None},
    )

    return {
        "ok":           True,
        "build_id":     build_id,
        "discarded_at": now_str,
        "error":        None,
    }


# ── Log helpers ───────────────────────────────────────────────────────────────

def _derive_status(build_id: str, events: list[dict]) -> Optional[str]:
    build_events = sorted(
        [e for e in events if e.get("build_id") == build_id],
        key=lambda e: e.get("timestamp", ""),
    )
    latest: Optional[str] = None
    for ev in build_events:
        etype = ev.get("event")
        if etype in _STATUS_FROM_EVENT:
            latest = etype
    return _STATUS_FROM_EVENT.get(latest) if latest else None


def _read_log(path: pathlib.Path) -> list[dict]:
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


def _append_log(
    path: pathlib.Path,
    build_id: str,
    event: str,
    notes: str = "",
    extra: Optional[dict] = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "build_id":  build_id,
        "event":     event,
        "notes":     notes,
        "extra":     extra or {},
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


# ── Error helper ──────────────────────────────────────────────────────────────

def _err(build_id: str, message: str) -> dict:
    return {
        "ok":           False,
        "build_id":     build_id,
        "discarded_at": None,
        "error":        message,
    }
