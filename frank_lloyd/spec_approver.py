# frank_lloyd/spec_approver.py
#
# Stage 1 approval/rejection terminal gate for Frank Lloyd.
#
# Given a build in pending_review state, either:
#   approve_build — copies staging artifacts to archive, writes decision.json
#                   + manifest.json, appends spec_approved log event
#   reject_build  — same archiving, writes rejection decision.json + manifest.json,
#                   appends spec_rejected log event
#
# Both operations validate:
#   - Build exists in the log
#   - Build is currently in pending_review state
#   - Staging spec.yaml and preflight.md are present
#   - Request file exists
#
# Failure is clean: nothing is written if validation fails.
#
# Archive layout written here (per DATA_MODEL.md §3):
#   data/frank_lloyd/archives/{build_id}/
#     request.json   (copy from data/frank_lloyd/requests/)
#     spec.yaml      (copy from staging)
#     preflight.md   (copy from staging)
#     decision.json  (written by this module — NOT approval.json)
#     manifest.json  (written by this module — contents index)
#
# Public API:
#   approve_build(build_id, notes="")                   → dict
#   reject_build(build_id, reason, revision_cycle=None) → dict
#
# Return shape: {ok, build_id, archive_path, error}

from __future__ import annotations

import hashlib
import json
import pathlib
import shutil
from datetime import datetime, timezone
from typing import Optional

_ROOT         = pathlib.Path(__file__).resolve().parent.parent
_FL_REQUESTS  = _ROOT / "data" / "frank_lloyd" / "requests"
_FL_BUILD_LOG = _ROOT / "data" / "frank_lloyd" / "build_log.jsonl"
_FL_ARCHIVES  = _ROOT / "data" / "frank_lloyd" / "archives"
_FL_STAGING   = _ROOT / "staging" / "frank_lloyd"

# Stage 1 status derivation — same contract as spec_writer.py / frank_lloyd_status.py
_STATUS_FROM_EVENT: dict[str, str] = {
    "request_queued": "pending_spec",
    "spec_ready":     "pending_review",
    "spec_approved":  "spec_approved",
    "spec_rejected":  "spec_rejected",
    "abandoned":      "abandoned",
}


# ── Public API ────────────────────────────────────────────────────────────────

def approve_build(build_id: str, notes: str = "") -> dict:
    """
    Approve a Stage 1 spec packet.

    Validates pending_review state, copies staging artifacts to
    data/frank_lloyd/archives/{build_id}/, writes decision.json +
    manifest.json, appends spec_approved log event.

    Returns {ok, build_id, archive_path, error}.
    """
    build_id = build_id.strip().upper()

    # Validate state
    err = _validate_pending_review(build_id)
    if err:
        return _err(build_id, err)

    # Validate staging artifacts
    staging_dir = _FL_STAGING / build_id
    spec_path   = staging_dir / "spec.yaml"
    pf_path     = staging_dir / "preflight.md"
    if not spec_path.exists():
        return _err(build_id,
                    f"Staging spec missing: {spec_path}. "
                    "Generate the spec first (POST /frank-lloyd/{build_id}/spec).")
    if not pf_path.exists():
        return _err(build_id,
                    f"Staging preflight missing: {pf_path}. "
                    "Generate the spec first (POST /frank-lloyd/{build_id}/spec).")

    req_file = _FL_REQUESTS / f"{build_id}_request.json"
    if not req_file.exists():
        return _err(build_id, f"Request file not found: {req_file}.")

    # Read staging content before writing anything
    spec_text = spec_path.read_text(encoding="utf-8")
    pf_text   = pf_path.read_text(encoding="utf-8")
    spec_hash = "sha256:" + hashlib.sha256(spec_text.encode("utf-8")).hexdigest()

    now_str     = datetime.now(timezone.utc).isoformat()
    archive_dir = _FL_ARCHIVES / build_id
    archive_dir.mkdir(parents=True, exist_ok=True)

    # Copy artifacts to archive
    shutil.copy2(str(req_file), str(archive_dir / "request.json"))
    (archive_dir / "spec.yaml").write_text(spec_text, encoding="utf-8")
    (archive_dir / "preflight.md").write_text(pf_text, encoding="utf-8")

    # Write decision.json (DATA_MODEL.md §3b)
    spec_fields = _parse_spec_fields(spec_text)
    decision = {
        "build_id":          build_id,
        "outcome":           "spec_approved",
        "stage":             1,
        "decided_at":        now_str,
        "decided_by":        "operator",
        "notes":             notes or None,
        "deferred_items":    None,
        "stage2_authorized": False,
        "spec_hash":         spec_hash,
        "revision_cycle":    None,
    }
    (archive_dir / "decision.json").write_text(
        json.dumps(decision, indent=2), encoding="utf-8"
    )

    # Write manifest.json (DATA_MODEL.md §3)
    _write_manifest(archive_dir, build_id, "spec_approved", now_str)

    # Append spec_approved log event
    _append_log(
        _FL_BUILD_LOG, build_id, "spec_approved",
        notes=f"Spec approved by operator for {build_id}",
        extra={
            "build_type":        spec_fields.get("build_type", ""),
            "risk_level":        spec_fields.get("risk_level", ""),
            "stage_completed":   1,
            "stage2_authorized": False,
        },
    )

    return {
        "ok":           True,
        "build_id":     build_id,
        "archive_path": str(archive_dir),
        "error":        None,
    }


def reject_build(
    build_id: str,
    reason: str,
    revision_cycle: Optional[int] = None,
) -> dict:
    """
    Reject a Stage 1 spec packet with a stated reason.

    Archives Stage 1 artifacts (same as approval), writes rejection
    decision.json + manifest.json, appends spec_rejected log event.

    reason is required — rejection without a reason is not accepted.

    Returns {ok, build_id, archive_path, error}.
    """
    build_id = build_id.strip().upper()

    if not reason.strip():
        return _err(build_id,
                    "A reason is required to reject a build. "
                    "Usage: reject BUILD-N reason text")

    # Validate state
    err = _validate_pending_review(build_id)
    if err:
        return _err(build_id, err)

    # Validate staging artifacts
    staging_dir = _FL_STAGING / build_id
    spec_path   = staging_dir / "spec.yaml"
    pf_path     = staging_dir / "preflight.md"
    if not spec_path.exists():
        return _err(build_id,
                    f"Staging spec missing: {spec_path}. Cannot archive without a spec.")
    if not pf_path.exists():
        return _err(build_id,
                    f"Staging preflight missing: {pf_path}. Cannot archive without a preflight.")

    req_file = _FL_REQUESTS / f"{build_id}_request.json"
    if not req_file.exists():
        return _err(build_id, f"Request file not found: {req_file}.")

    spec_text = spec_path.read_text(encoding="utf-8")
    pf_text   = pf_path.read_text(encoding="utf-8")
    spec_hash = "sha256:" + hashlib.sha256(spec_text.encode("utf-8")).hexdigest()

    now_str     = datetime.now(timezone.utc).isoformat()
    archive_dir = _FL_ARCHIVES / build_id
    archive_dir.mkdir(parents=True, exist_ok=True)

    # Copy artifacts to archive
    shutil.copy2(str(req_file), str(archive_dir / "request.json"))
    (archive_dir / "spec.yaml").write_text(spec_text, encoding="utf-8")
    (archive_dir / "preflight.md").write_text(pf_text, encoding="utf-8")

    # Write decision.json (DATA_MODEL.md §3b)
    decision = {
        "build_id":          build_id,
        "outcome":           "spec_rejected",
        "stage":             1,
        "decided_at":        now_str,
        "decided_by":        "operator",
        "notes":             reason,
        "deferred_items":    None,
        "stage2_authorized": None,
        "spec_hash":         spec_hash,
        "revision_cycle":    revision_cycle,
    }
    (archive_dir / "decision.json").write_text(
        json.dumps(decision, indent=2), encoding="utf-8"
    )

    # Write manifest.json (DATA_MODEL.md §3)
    _write_manifest(archive_dir, build_id, "spec_rejected", now_str)

    # Append spec_rejected log event
    _append_log(
        _FL_BUILD_LOG, build_id, "spec_rejected",
        notes=f"Spec rejected by operator for {build_id}",
        extra={
            "reason":         reason,
            "revision_cycle": revision_cycle,
        },
    )

    return {
        "ok":           True,
        "build_id":     build_id,
        "archive_path": str(archive_dir),
        "error":        None,
    }


# ── Validation ────────────────────────────────────────────────────────────────

def _validate_pending_review(build_id: str) -> Optional[str]:
    """
    Return an error string if the build cannot be approved/rejected, or None if valid.
    Valid = build exists AND current status is pending_review.
    """
    events = _read_log(_FL_BUILD_LOG)
    build_events = [e for e in events if e.get("build_id") == build_id]
    if not build_events:
        return (f"No events found for {build_id}. "
                "Check the build ID — use 'status' or GET /frank-lloyd/status.")

    status = _derive_status(build_id, events)
    if status is None:
        return f"{build_id} has no recognized status events in the build log."
    if status == "pending_spec":
        return (f"{build_id} is in pending_spec — the spec has not been generated yet. "
                "Generate the spec first, then approve or reject.")
    if status != "pending_review":
        return (f"{build_id} is not in pending_review (current status: {status}). "
                "Only pending_review builds can be approved or rejected.")

    return None


def _derive_status(build_id: str, events: list[dict]) -> Optional[str]:
    """Derive the current logical status for a build from its log events."""
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


# ── Log helpers ───────────────────────────────────────────────────────────────

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


# ── Spec field extraction ─────────────────────────────────────────────────────

def _parse_spec_fields(spec_yaml_text: str) -> dict:
    """
    Extract build_type and risk_level from spec.yaml text.
    Simple line scan — no external YAML parser needed.
    """
    fields: dict[str, str] = {}
    for line in spec_yaml_text.splitlines():
        line = line.strip()
        for key in ("build_type", "risk_level"):
            if line.startswith(key + ":") and key not in fields:
                val = line[len(key) + 1:].strip().strip('"').strip("'")
                if val:
                    fields[key] = val
    return fields


# ── Archive helpers ───────────────────────────────────────────────────────────

def _write_manifest(
    archive_dir: pathlib.Path,
    build_id: str,
    outcome: str,
    archived_at: str,
) -> None:
    """
    Write manifest.json per DATA_MODEL.md §3.
    manifest.json does NOT include itself in contents (per contract).
    """
    contents = [
        {"filename": "request.json",  "author": "peter",   "written_at": archived_at, "sha256": None},
        {"filename": "spec.yaml",     "author": "builder", "written_at": archived_at, "sha256": None},
        {"filename": "preflight.md",  "author": "builder", "written_at": archived_at, "sha256": None},
        {"filename": "decision.json", "author": "builder", "written_at": archived_at, "sha256": None},
    ]
    manifest = {
        "build_id":    build_id,
        "archived_at": archived_at,
        "stage":       1,
        "outcome":     outcome,
        "contents":    contents,
    }
    (archive_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )


def _err(build_id: str, message: str) -> dict:
    return {
        "ok":           False,
        "build_id":     build_id,
        "archive_path": None,
        "error":        message,
    }
