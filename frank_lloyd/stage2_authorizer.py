# frank_lloyd/stage2_authorizer.py
#
# Stage 2 authorization gate for Frank Lloyd.
#
# A build must be in spec_approved state before Stage 2 draft generation
# can begin. This module implements the explicit operator-controlled gate
# that bridges Stage 1 completion and Stage 2 eligibility.
#
# This module does NOT generate code. It does NOT initiate any LM call.
# It does NOT implement Codex CLI transport.
# Authorization only — Stage 2 generation is a separate future pass.
#
# Validation fails cleanly if:
#   - build_id has no log events
#   - current status is not spec_approved
#   - decision.json missing from archive
#   - decision.json outcome != spec_approved
#   - stage2_authorization.json already exists
#
# Archive file written:
#   data/frank_lloyd/archives/{build_id}/stage2_authorization.json
#
# Fields in stage2_authorization.json:
#   build_id, stage, authorized_at, authorized_by, authorization_notes,
#   stage1_decision_outcome, provider_readiness
#
# provider_readiness captures which lanes are executable now vs config_only
# vs external_supervised — snapshotted from FL_PROVIDER_REGISTRY at auth time.
# This answers "can Stage 2 actually run yet?" without pre-deciding task class.
#
# Log event appended:
#   event: "stage2_authorized"
#
# Public API:
#   authorize_stage2(build_id, notes="") → dict
#   Return shape: {ok, build_id, archive_path, authorization_path, error}

from __future__ import annotations

import json
import pathlib
from datetime import datetime, timezone
from typing import Optional

_ROOT         = pathlib.Path(__file__).resolve().parent.parent
_FL_BUILD_LOG = _ROOT / "data" / "frank_lloyd" / "build_log.jsonl"
_FL_ARCHIVES  = _ROOT / "data" / "frank_lloyd" / "archives"

# Status derivation — extends spec_approver._STATUS_FROM_EVENT with stage2_authorized.
# Defined locally to avoid cross-module dependency on spec_approver internals.
_STATUS_FROM_EVENT: dict[str, str] = {
    "request_queued":    "pending_spec",
    "spec_ready":        "pending_review",
    "spec_approved":     "spec_approved",
    "spec_rejected":     "spec_rejected",
    "abandoned":         "abandoned",
    "stage2_authorized": "stage2_authorized",
}


# ── Public API ────────────────────────────────────────────────────────────────

def authorize_stage2(build_id: str, notes: str = "") -> dict:
    """
    Authorize Stage 2 draft generation for a spec_approved build.

    Validates that the build is in spec_approved state, that Stage 2 has not
    already been authorized, and that the Stage 1 decision.json is present and
    confirms spec_approved outcome. Writes stage2_authorization.json to the
    archive and appends a stage2_authorized event to the build log.

    Does NOT initiate code generation. Does NOT call any LM.

    Returns {ok, build_id, archive_path, authorization_path, error}.
    """
    build_id = build_id.strip().upper()

    err = _validate_spec_approved(build_id)
    if err:
        return _err(build_id, err)

    archive_dir   = _FL_ARCHIVES / build_id
    decision_path = archive_dir / "decision.json"
    auth_path     = archive_dir / "stage2_authorization.json"

    # decision.json must be present
    if not decision_path.exists():
        return _err(build_id,
                    f"Stage 1 decision.json not found in archive ({decision_path}). "
                    "The build may not have completed Stage 1 archiving correctly.")

    # Already authorized? (belt and suspenders — status check above catches this first)
    if auth_path.exists():
        return _err(build_id,
                    f"{build_id} Stage 2 is already authorized "
                    f"({auth_path}). No action taken.")

    # Confirm decision.json carries spec_approved outcome
    try:
        decision = json.loads(decision_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _err(build_id, f"Could not read decision.json: {exc}")

    if decision.get("outcome") != "spec_approved":
        return _err(build_id,
                    f"decision.json outcome is '{decision.get('outcome')}', not 'spec_approved'. "
                    "Stage 2 authorization requires a completed spec approval.")

    now_str = datetime.now(timezone.utc).isoformat()

    # Write stage2_authorization.json
    auth_record = {
        "build_id":                build_id,
        "stage":                   2,
        "authorized_at":           now_str,
        "authorized_by":           "operator",
        "authorization_notes":     notes or None,
        "stage1_decision_outcome": "spec_approved",
        "provider_readiness":      _provider_readiness(),
    }
    archive_dir.mkdir(parents=True, exist_ok=True)
    auth_path.write_text(json.dumps(auth_record, indent=2), encoding="utf-8")

    # Append stage2_authorized event
    _append_log(
        _FL_BUILD_LOG, build_id, "stage2_authorized",
        notes=f"Stage 2 authorized by operator for {build_id}",
        extra={
            "authorization_notes": notes or None,
            "provider_readiness":  auth_record["provider_readiness"],
        },
    )

    return {
        "ok":                 True,
        "build_id":           build_id,
        "archive_path":       str(archive_dir),
        "authorization_path": str(auth_path),
        "error":              None,
    }


# ── Validation ────────────────────────────────────────────────────────────────

def _validate_spec_approved(build_id: str) -> Optional[str]:
    """
    Return an error string if the build cannot be Stage-2-authorized, or None if valid.
    Valid = build exists AND current status is spec_approved.
    """
    events = _read_log(_FL_BUILD_LOG)
    build_events = [e for e in events if e.get("build_id") == build_id]
    if not build_events:
        return (f"No events found for {build_id}. "
                "Check the build ID — use 'status' or GET /frank-lloyd/status.")

    status = _derive_status(build_id, events)
    if status is None:
        return f"{build_id} has no recognized status events in the build log."
    if status == "stage2_authorized":
        return f"{build_id} Stage 2 is already authorized. No action taken."
    if status == "pending_spec":
        return (f"{build_id} is in pending_spec — the spec has not been generated yet. "
                "Complete Stage 1 first: generate the spec, then approve it.")
    if status == "pending_review":
        return (f"{build_id} is in pending_review — the spec has not been approved yet. "
                "Approve the spec before authorizing Stage 2.")
    if status == "spec_rejected":
        return (f"{build_id} spec was rejected. "
                "Stage 2 authorization is not possible for a rejected build.")
    if status == "abandoned":
        return f"{build_id} is abandoned. Stage 2 authorization is not possible."
    if status != "spec_approved":
        return (f"{build_id} is in an unexpected state: {status}. "
                "Expected spec_approved for Stage 2 authorization.")

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


# ── Provider readiness ────────────────────────────────────────────────────────

def _provider_readiness() -> dict:
    """
    Derive current provider lane readiness from FL_PROVIDER_REGISTRY.

    Snapshotted at authorization time so the record reflects the policy
    active when Stage 2 was authorized. Answers the question "can Stage 2
    actually run via API right now?" without pre-deciding task class.
    Fails gracefully if provider_router is unavailable.
    """
    try:
        from frank_lloyd.provider_router import FL_PROVIDER_REGISTRY
        executable: list[str] = []
        config_only: list[str] = []
        external_supervised: list[str] = []
        for tier, cfg in FL_PROVIDER_REGISTRY.items():
            if cfg.executability == "executable":
                executable.append(tier.value)
            elif cfg.executability == "config_only":
                config_only.append(tier.value)
            elif cfg.executability == "external_supervised":
                external_supervised.append(tier.value)
        return {
            "executable_lanes":          executable,
            "config_only_lanes":         config_only,
            "external_supervised_lanes": external_supervised,
        }
    except ImportError:
        return {
            "executable_lanes":          [],
            "config_only_lanes":         [],
            "external_supervised_lanes": [],
            "warning": "provider_router unavailable at authorization time",
        }


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


# ── Error helper ──────────────────────────────────────────────────────────────

def _err(build_id: str, message: str) -> dict:
    return {
        "ok":                 False,
        "build_id":           build_id,
        "archive_path":       None,
        "authorization_path": None,
        "error":              message,
    }
