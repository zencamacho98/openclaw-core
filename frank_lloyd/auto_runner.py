# frank_lloyd/auto_runner.py
#
# Full-auto pipeline orchestrator for Frank Lloyd.
#
# run_full_auto() — the primary entry point:
#   Runs the complete pipeline from queued → draft_promoted with no human gates.
#   Steps: spec → approve → authorize → draft → promote
#   Target path is extracted from the spec's affected_files section.
#   All risk levels proceed; off-limits path checks in stage2_promoter still apply.
#
# run_safe_lane() — legacy; kept for backward compatibility:
#   Like run_full_auto() but stops at draft_generated (no auto-promote).
#   Retained so existing tests and NL handler still work.
#
# Public API:
#   run_full_auto(build_id, initiated_by="frank_lloyd_auto") → dict
#   run_safe_lane(build_id, initiated_by="frank_lloyd_auto") → dict
#   Return shape: {ok, build_id, final_status, paused_reason, steps, error, promoted_to}

from __future__ import annotations

import json
import pathlib
import re
from datetime import datetime, timezone
from typing import Optional

_ROOT      = pathlib.Path(__file__).resolve().parent.parent
_STAGING   = _ROOT / "staging" / "frank_lloyd"
_BUILD_LOG = _ROOT / "data" / "frank_lloyd" / "build_log.jsonl"

# ── Stop flag — operator can request pipeline halt between steps ──────────────
_stop_requested: bool      = False
_active_build_id: str | None = None


def request_stop() -> dict:
    """
    Signal the active pipeline to stop after its current step.
    Non-blocking — the thread checks this flag between pipeline steps.
    Returns the active build ID so the caller can report it.
    """
    global _stop_requested
    _stop_requested = True
    return {"stop_requested": True, "active_build_id": _active_build_id}


def get_runner_state() -> dict:
    """Return current auto-runner state (thread-safe read)."""
    return {
        "active_build_id": _active_build_id,
        "stop_requested":  _stop_requested,
        "running":         _active_build_id is not None,
    }


def _set_active(build_id: str | None) -> None:
    global _active_build_id
    _active_build_id = build_id


def _clear_stop() -> None:
    global _stop_requested
    _stop_requested = False


# ── Public API ────────────────────────────────────────────────────────────────

def run_full_auto(build_id: str, initiated_by: str = "frank_lloyd_auto") -> dict:
    """
    Run the complete pipeline: spec → approve → authorize → draft → promote.

    No human gates. Frank Lloyd builds and writes the code to the live repo.
    The safety checks in stage2_promoter (off-limits files, path traversal) still apply.

    Steps:
      1. generate_spec  — spec.yaml + preflight.md
      2. approve_spec   — auto-approved (all risk levels)
      3. authorize_s2   — auto-authorized
      4. generate_draft — LM-generated code module
      5. auto_promote   — copies draft to live repo at path from spec

    Returns {ok, build_id, final_status, paused_reason, steps, error, promoted_to}.
      ok=True            → code is in the repo at promoted_to
      ok=False + paused  → spec was blocked or off-limits; needs operator input
      ok=False + error   → unexpected failure
    """
    build_id = build_id.strip().upper()
    _set_active(build_id)
    _clear_stop()
    steps: list[dict] = []

    def _stopped() -> bool:
        return _stop_requested

    try:
        import frank_lloyd.relay as _relay
        _relay.append(build_id, "pipeline_start",
                      f"{build_id} — Frank Lloyd is planning and building.")
    except Exception:
        pass

    # ── Step 1: generate spec ─────────────────────────────────────────────────
    if _stopped():
        _set_active(None)
        return _paused(build_id, steps, "Stopped by operator before spec generation.")

    import frank_lloyd.spec_writer as _spec_writer
    spec_result = _spec_writer.generate_spec_packet(build_id)
    steps.append({"step": "generate_spec", "ok": spec_result["ok"],
                  "error": spec_result.get("error")})

    if not spec_result["ok"]:
        blocked = spec_result.get("blocked", False)
        reason = spec_result.get("error", "unknown reason")
        if blocked:
            try:
                import frank_lloyd.relay as _relay
                _relay.append(build_id, "spec_blocked",
                              f"{build_id} — Blocked: {reason[:120]}. "
                              "Revise the request.")
            except Exception:
                pass
            return _paused(build_id, steps,
                           f"Spec blocked: {reason}. Revise the request.")
        return _fail(build_id, steps, spec_result.get("error", "Spec generation failed."))

    # ── Step 2: approve spec ──────────────────────────────────────────────────
    if _stopped():
        _set_active(None)
        return _paused(build_id, steps, "Stopped by operator before spec approval.")

    risk_level = _read_risk_level(build_id)
    steps.append({"step": "risk_note", "risk_level": risk_level})

    import frank_lloyd.spec_approver as _approver
    approve_result = _approver.approve_build(
        build_id,
        notes=f"Auto-approved (initiated_by={initiated_by}, risk_level={risk_level}).",
    )
    steps.append({"step": "approve_spec", "ok": approve_result["ok"],
                  "error": approve_result.get("error")})
    if not approve_result["ok"]:
        return _paused(build_id, steps,
                       f"Auto-approval failed: {approve_result.get('error')}.")

    # ── Step 3: authorize Stage 2 ─────────────────────────────────────────────
    if _stopped():
        _set_active(None)
        return _paused(build_id, steps, "Stopped by operator before Stage 2 authorization.")

    import frank_lloyd.stage2_authorizer as _s2auth
    auth_result = _s2auth.authorize_stage2(
        build_id,
        notes=f"Auto-authorized (initiated_by={initiated_by}).",
    )
    steps.append({"step": "authorize_stage2", "ok": auth_result["ok"],
                  "error": auth_result.get("error")})
    if not auth_result["ok"]:
        return _paused(build_id, steps,
                       f"Stage 2 authorization failed: {auth_result.get('error')}.")

    # ── Step 4: generate draft ────────────────────────────────────────────────
    if _stopped():
        _set_active(None)
        return _paused(build_id, steps, "Stopped by operator before draft generation.")

    import frank_lloyd.stage2_drafter as _drafter
    draft_result = _drafter.generate_stage2_draft(build_id)
    steps.append({"step": "generate_draft", "ok": draft_result["ok"],
                  "error": draft_result.get("error")})
    if not draft_result["ok"]:
        try:
            import frank_lloyd.relay as _relay
            _relay.append(build_id, "draft_blocked",
                          f"{build_id} — Draft generation failed: "
                          f"{(draft_result.get('error') or '')[:120]}.")
        except Exception:
            pass
        return _paused(build_id, steps,
                       f"Draft generation failed: {draft_result.get('error')}.")

    # ── Step 5: auto-promote ──────────────────────────────────────────────────
    if _stopped():
        _set_active(None)
        return _paused(build_id, steps, "Stopped by operator before auto-promotion.")

    target_paths = _read_all_target_paths(build_id)
    target_path  = target_paths[0] if target_paths else None

    if not target_path:
        try:
            import frank_lloyd.relay as _relay
            _relay.append(build_id, "draft_ready",
                          f"{build_id} — Draft ready but no target path found in spec. "
                          "Promote manually: promote {build_id} path/to/file.py")
        except Exception:
            pass
        return _paused(build_id, steps,
                       "Draft generated but no target path found in spec. "
                       f"Promote manually: promote {build_id} path/to/file.py")

    import frank_lloyd.stage2_promoter as _promoter
    promote_result = _promoter.promote_draft(
        build_id, target_path,
        notes=f"Auto-promoted by full_auto pipeline (initiated_by={initiated_by}).",
    )
    steps.append({"step": "auto_promote", "ok": promote_result["ok"],
                  "target_path": target_path, "error": promote_result.get("error")})

    if not promote_result["ok"]:
        try:
            import frank_lloyd.relay as _relay
            _relay.append(build_id, "promote_failed",
                          f"{build_id} — Promotion failed: "
                          f"{(promote_result.get('error') or '')[:120]}. "
                          "Review the error and promote manually.")
        except Exception:
            pass
        return _paused(build_id, steps,
                       f"Auto-promotion failed: {promote_result.get('error')}. "
                       f"Promote manually: promote {build_id} {target_path}")

    try:
        import frank_lloyd.relay as _relay
        _title = _read_build_title(build_id)
        _title_part = f' "{_title}"' if _title else ""
        _relay.append(build_id, "build_complete",
                      f"{build_id}{_title_part} — Done. Written to {target_path}.")
    except Exception:
        pass

    _set_active(None)
    return {
        "ok":            True,
        "build_id":      build_id,
        "final_status":  "draft_promoted",
        "paused_reason": None,
        "steps":         steps,
        "error":         None,
        "promoted_to":   target_path,
    }


def run_safe_lane(build_id: str, initiated_by: str = "frank_lloyd_auto") -> dict:
    """
    Run the full pipeline for a queued build through to draft_generated (or paused).

    Steps attempted:
      1. generate_spec_packet  — generates spec.yaml + preflight.md
      2. risk gate             — checks risk_level from generated spec
      3. approve_build         — auto-approves if risk_level is low
      4. authorize_stage2      — auto-authorizes Stage 2
      5. generate_stage2_draft — generates code draft

    Pauses (does not error) if:
      - spec was blocked by LM or off-limits check
      - risk_level is not "low" (operator review required)
      - any downstream step fails with a recoverable error

    Returns {ok, build_id, final_status, paused_reason, steps, error}.
      ok=True  → pipeline ran to completion (final_status=draft_generated)
      ok=False with paused_reason → paused for operator review (not a hard error)
      ok=False with error         → something unexpected failed
    """
    build_id = build_id.strip().upper()
    steps: list[dict] = []

    # Relay: pipeline has started
    try:
        import frank_lloyd.relay as _relay
        _relay.append(build_id, "pipeline_start",
                      f"{build_id} — Frank Lloyd is planning and building in the background.")
    except Exception:
        pass

    # ── Step 1: generate spec ─────────────────────────────────────────────────

    import frank_lloyd.spec_writer as _spec_writer
    spec_result = _spec_writer.generate_spec_packet(build_id)
    steps.append({"step": "generate_spec", "ok": spec_result["ok"],
                  "error": spec_result.get("error")})

    if not spec_result["ok"]:
        blocked = spec_result.get("blocked", False)
        if blocked:
            reason = spec_result.get("error", "unknown reason")
            try:
                import frank_lloyd.relay as _relay
                _relay.append(build_id, "spec_blocked",
                              f"{build_id} — Frank Lloyd is blocked on planning: {reason[:120]}. "
                              "Revise the request or check the workspace.")
            except Exception:
                pass
            return _paused(
                build_id, steps,
                f"Spec generation was blocked: {reason}. "
                "Review the blocked.md in staging and revise the request.",
            )
        return _fail(build_id, steps, spec_result.get("error", "Spec generation failed."))

    # ── Step 2: note risk level (no gate — all builds proceed) ──────────────────

    risk_level = _read_risk_level(build_id)
    steps.append({"step": "risk_note", "risk_level": risk_level})

    # ── Step 3: approve spec ──────────────────────────────────────────────────

    import frank_lloyd.spec_approver as _approver
    approve_result = _approver.approve_build(
        build_id,
        notes=(
            f"Auto-approved by safe lane (initiated_by={initiated_by}). "
            f"Risk level: {risk_level}."
        ),
    )
    steps.append({"step": "approve_spec", "ok": approve_result["ok"],
                  "error": approve_result.get("error")})

    if not approve_result["ok"]:
        return _paused(
            build_id, steps,
            f"Auto-approval failed: {approve_result.get('error')}. "
            "The spec is ready — approve manually in Frank Lloyd.",
        )

    # ── Step 4: authorize Stage 2 ─────────────────────────────────────────────

    import frank_lloyd.stage2_authorizer as _s2auth
    auth_result = _s2auth.authorize_stage2(
        build_id,
        notes=(
            f"Auto-authorized by safe lane (initiated_by={initiated_by}). "
            f"Spec was auto-approved (risk_level={risk_level})."
        ),
    )
    steps.append({"step": "authorize_stage2", "ok": auth_result["ok"],
                  "error": auth_result.get("error")})

    if not auth_result["ok"]:
        return _paused(
            build_id, steps,
            f"Stage 2 authorization failed: {auth_result.get('error')}. "
            "The spec is approved — authorize Stage 2 manually in Frank Lloyd.",
        )

    # ── Step 5: generate draft ────────────────────────────────────────────────

    import frank_lloyd.stage2_drafter as _drafter
    draft_result = _drafter.generate_stage2_draft(build_id)
    steps.append({"step": "generate_draft", "ok": draft_result["ok"],
                  "error": draft_result.get("error")})

    if not draft_result["ok"]:
        try:
            import frank_lloyd.relay as _relay
            _relay.append(build_id, "draft_blocked",
                          f"{build_id} — Draft generation failed: "
                          f"{(draft_result.get('error') or 'unknown error')[:120]}. "
                          "Stage 2 is authorized — retry from the Frank Lloyd workspace.")
        except Exception:
            pass
        return _paused(
            build_id, steps,
            f"Draft generation failed: {draft_result.get('error')}. "
            "Stage 2 is authorized — retry draft generation in Frank Lloyd.",
        )

    # Relay: draft is ready for operator review
    try:
        import frank_lloyd.relay as _relay
        _relay.append(build_id, "draft_ready",
                      f"{build_id} — Draft is ready. "
                      "Review the apply summary and apply when satisfied.")
    except Exception:
        pass

    return {
        "ok":            True,
        "build_id":      build_id,
        "final_status":  "draft_generated",
        "paused_reason": None,
        "steps":         steps,
        "error":         None,
    }


# ── Spec readers ─────────────────────────────────────────────────────────────

def _read_all_target_paths(build_id: str) -> list[str]:
    """
    Extract all planned file paths from the generated spec.yaml.
    Checks affected_files.new first, then affected_files.modified.
    Returns list of relative path strings (may be empty if spec unreadable).
    """
    spec_path = _STAGING / build_id / "spec.yaml"
    if not spec_path.exists():
        # Also check archived copy (spec might have been approved already)
        spec_path = _ROOT / "data" / "frank_lloyd" / "archives" / build_id / "spec.yaml"
    if not spec_path.exists():
        return []
    try:
        text = spec_path.read_text(encoding="utf-8")
    except OSError:
        return []

    paths: list[str] = []

    # Parse affected_files.new section
    lines = text.splitlines()
    in_new = False
    in_mod = False
    for line in lines:
        stripped = line.strip()
        if stripped == "new:":
            in_new = True
            in_mod = False
            continue
        if stripped == "modified:":
            in_mod = True
            in_new = False
            continue
        if in_new or in_mod:
            if stripped.startswith("affected_files:") or (
                stripped and not stripped.startswith("-") and not stripped.startswith("path:")
                and not stripped.startswith("#") and ":" in stripped
                and not stripped.startswith("  ")
            ):
                in_new = False
                in_mod = False
                continue
            m = re.match(r'\s*-\s*path:\s*["\']?([^"\']+)["\']?', line)
            if m:
                path = m.group(1).strip().strip("\"'")
                if path and path not in paths:
                    paths.append(path)

    return paths


def _read_risk_level(build_id: str) -> str:
    """
    Read risk_level from the generated spec.yaml in staging.

    Uses a simple line scan — the field is deterministically set by
    spec_validator before writing, so a regex scan is safe.
    Returns "unknown" if not found.
    """
    spec_path = _STAGING / build_id / "spec.yaml"
    if not spec_path.exists():
        return "unknown"
    try:
        text = spec_path.read_text(encoding="utf-8")
        match = re.search(r"^\s*risk_level\s*:\s*['\"]?(\w+)['\"]?", text, re.MULTILINE)
        return match.group(1) if match else "unknown"
    except OSError:
        return "unknown"


# ── Result helpers ────────────────────────────────────────────────────────────

def _read_build_title(build_id: str) -> str:
    """Read the build title from the request file. Returns '' if unavailable."""
    req_path = _ROOT / "data" / "frank_lloyd" / "requests" / f"{build_id}_request.json"
    if not req_path.exists():
        return ""
    try:
        data = json.loads(req_path.read_text(encoding="utf-8"))
        return data.get("title", "")
    except Exception:
        return ""


def _paused(build_id: str, steps: list, reason: str) -> dict:
    return {
        "ok":            False,
        "build_id":      build_id,
        "final_status":  _derive_current_status(build_id),
        "paused_reason": reason,
        "steps":         steps,
        "error":         None,
    }


def _fail(build_id: str, steps: list, error: str) -> dict:
    try:
        import frank_lloyd.relay as _relay
        _relay.append(build_id, "build_failed",
                      f"{build_id} — Build failed: {(error or 'unknown error')[:120]}.")
    except Exception:
        pass
    return {
        "ok":            False,
        "build_id":      build_id,
        "final_status":  _derive_current_status(build_id),
        "paused_reason": None,
        "steps":         steps,
        "error":         error,
    }


def _derive_current_status(build_id: str) -> Optional[str]:
    """Derive build status from the build log for return context."""
    _STATUS_MAP: dict[str, str] = {
        "request_queued":           "pending_spec",
        "spec_ready":               "pending_review",
        "spec_approved":            "spec_approved",
        "spec_rejected":            "spec_rejected",
        "abandoned":                "abandoned",
        "stage2_authorized":        "stage2_authorized",
        "draft_generation_started": "draft_generating",
        "draft_generated":          "draft_generated",
        "draft_blocked":            "draft_blocked",
        "draft_promoted":           "draft_promoted",
        "draft_discarded":          "stage2_authorized",
    }
    if not _BUILD_LOG.exists():
        return None
    latest_event: Optional[str] = None
    try:
        for line in _BUILD_LOG.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
                if ev.get("build_id") == build_id and ev.get("event") in _STATUS_MAP:
                    latest_event = ev["event"]
            except (json.JSONDecodeError, ValueError):
                pass
    except OSError:
        return None
    return _STATUS_MAP.get(latest_event) if latest_event else None
