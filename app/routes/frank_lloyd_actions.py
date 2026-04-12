# app/routes/frank_lloyd_actions.py
#
# Frank Lloyd action control endpoints.
#
# Provides structured POST endpoints for the neighborhood UI action buttons.
# Each endpoint calls the same audited internal module used by Peter's command layer —
# no separate action path, no state duplication.
#
# Endpoints:
#   POST /frank-lloyd/{build_id}/approve-spec      — approve a pending_review spec
#   POST /frank-lloyd/{build_id}/reject-spec       — reject a pending_review spec (reason required)
#   POST /frank-lloyd/{build_id}/authorize-stage2  — authorize Stage 2 for a spec_approved build
#
# Return shape (success):  {ok: True,  build_id, outcome, message}
# Return shape (failure):  {ok: False, build_id, error}
#
# These are thin wrappers — all validation, archiving, and log appending
# happens inside the corresponding frank_lloyd.* modules (same path as Peter commands).

from __future__ import annotations

import json
import pathlib

from fastapi import APIRouter, BackgroundTasks, Body

router = APIRouter()

_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent

# Status derivation map — local copy kept intentionally minimal.
_SPEC_STATUS_FROM_EVENT: dict[str, str] = {
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
    "draft_discarded":           "stage2_authorized",
}


@router.get("/frank-lloyd/{build_id}/spec-review")
def get_spec_review(build_id: str) -> dict:
    """
    Return spec review artifacts for a build.

    Source:
      pending_review state → staging/frank_lloyd/{build_id}/spec.yaml + preflight.md
      post-approval states → data/frank_lloyd/archives/{build_id}/spec.yaml + preflight.md
      (falls back to staging if archives don't have the file yet)

    Returns {ok, build_id, status, spec_yaml, preflight_md, error}.
    """
    build_id   = build_id.upper()
    build_log  = _ROOT / "data" / "frank_lloyd" / "build_log.jsonl"
    staging    = _ROOT / "staging" / "frank_lloyd" / build_id
    archive    = _ROOT / "data" / "frank_lloyd" / "archives" / build_id

    # Derive current status from the build log
    status: str | None = None
    if build_log.exists():
        try:
            for line in build_log.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                    if ev.get("build_id") == build_id and ev.get("event") in _SPEC_STATUS_FROM_EVENT:
                        status = _SPEC_STATUS_FROM_EVENT[ev["event"]]
                except (json.JSONDecodeError, ValueError):
                    pass
        except OSError:
            pass

    if status is None:
        return {"ok": False, "build_id": build_id,
                "error": f"{build_id} not found in build log."}

    if status == "pending_spec":
        return {"ok": False, "build_id": build_id, "status": status,
                "error": "Spec has not been generated yet for this build."}

    # For pending_review: artifacts live in staging.
    # For all post-approval states: artifacts live in archives (fall back to staging).
    if status == "pending_review":
        spec_dir = staging
    else:
        spec_dir = archive if (archive / "spec.yaml").exists() else staging

    spec_yaml    = _read_text(spec_dir / "spec.yaml")
    preflight_md = _read_text(spec_dir / "preflight.md")

    if not spec_yaml and not preflight_md:
        return {"ok": False, "build_id": build_id, "status": status,
                "error": f"Spec artifacts not found for {build_id}."}

    return {
        "ok":           True,
        "build_id":     build_id,
        "status":       status,
        "spec_yaml":    spec_yaml,
        "preflight_md": preflight_md,
    }


def _read_text(path: pathlib.Path) -> str:
    """Read a text file; return empty string on any error."""
    try:
        return path.read_text(encoding="utf-8") if path.exists() else ""
    except OSError:
        return ""


@router.post("/frank-lloyd/{build_id}/approve-spec")
def approve_spec(build_id: str, body: dict = Body(default={})) -> dict:
    """
    Approve a pending_review spec packet.

    Delegates to frank_lloyd.spec_approver.approve_build() — same path as
    Peter command 'approve BUILD-N'. Validates state, copies staging artifacts
    to archive, writes decision.json + manifest.json, appends spec_approved event.

    Body: {notes: str}  — optional approval notes
    """
    import frank_lloyd.spec_approver as _fl_approver
    notes  = (body.get("notes") or "").strip()
    result = _fl_approver.approve_build(build_id.upper(), notes=notes)
    if not result["ok"]:
        return {"ok": False, "build_id": build_id.upper(), "error": result["error"]}
    return {
        "ok":      True,
        "build_id": build_id.upper(),
        "outcome": "spec_approved",
        "message": (
            f"{build_id.upper()} spec approved. Stage 1 complete. "
            f"Stage 2 authorization is a separate step."
        ),
    }


@router.post("/frank-lloyd/{build_id}/reject-spec")
def reject_spec(build_id: str, body: dict = Body(default={})) -> dict:
    """
    Reject a pending_review spec packet with a stated reason.

    Delegates to frank_lloyd.spec_approver.reject_build() — same path as
    Peter command 'reject BUILD-N reason'. Reason is required.

    Body: {reason: str}  — required rejection reason
    """
    import frank_lloyd.spec_approver as _fl_approver
    reason = (body.get("reason") or "").strip()
    if not reason:
        return {
            "ok":       False,
            "build_id": build_id.upper(),
            "error":    "A reason is required to reject a build.",
        }
    result = _fl_approver.reject_build(build_id.upper(), reason=reason)
    if not result["ok"]:
        return {"ok": False, "build_id": build_id.upper(), "error": result["error"]}
    return {
        "ok":      True,
        "build_id": build_id.upper(),
        "outcome": "spec_rejected",
        "message": f"{build_id.upper()} spec rejected. Reason: {reason}",
    }


@router.get("/frank-lloyd/{build_id}/draft")
def get_draft(build_id: str) -> dict:
    """
    Return draft review data for a build.

    Reads staging/frank_lloyd/{build_id}/stage2/ artifacts if present.
    Returns manifest metadata, module code, and notes for draft_generated builds.
    Returns the block reason from the build log for draft_blocked builds with no artifacts.
    Returns ok=False with a clear error if no draft exists or the build is unknown.
    """
    import frank_lloyd.stage2_drafter as _fl_drafter
    return _fl_drafter.get_draft_review(build_id.upper())


@router.post("/frank-lloyd/{build_id}/promote-draft")
def promote_draft(build_id: str, body: dict = Body(default={})) -> dict:
    """
    Promote a staged draft to the live repo.

    First-pass: CODE_DRAFT_LOW only. New .py files only. target_path required.

    Delegates to frank_lloyd.stage2_promoter.promote_draft(). Validates build
    state, manifest task class, target path safety, and that the target file
    does not already exist. Copies draft_module.py, archives promotion_record.json,
    appends draft_promoted log event.

    Body: {target_path: str, notes: str}  — target_path required
    """
    import frank_lloyd.stage2_promoter as _fl_promoter
    target_path = (body.get("target_path") or "").strip()
    notes       = (body.get("notes") or "").strip()
    if not target_path:
        return {
            "ok":       False,
            "build_id": build_id.upper(),
            "error":    "target_path is required in the request body.",
        }
    result = _fl_promoter.promote_draft(
        build_id.upper(), target_path=target_path, notes=notes
    )
    if not result["ok"]:
        return {"ok": False, "build_id": build_id.upper(), "error": result["error"]}
    # Relay promotion notification to Peter
    try:
        import frank_lloyd.relay as _relay
        _relay.append(
            build_id.upper(), "promoted",
            f"{build_id.upper()} applied to repo: {result['target_path']}. "
            "Inspect the file and run tests before importing.",
        )
    except Exception:
        pass
    return {
        "ok":          True,
        "build_id":    build_id.upper(),
        "outcome":     "draft_promoted",
        "target_path": result["target_path"],
        "promoted_at": result["promoted_at"],
        "message": (
            f"{build_id.upper()} draft promoted to live repo: {result['target_path']}. "
            "Inspect the file and run tests before importing."
        ),
    }


@router.post("/frank-lloyd/{build_id}/discard-draft")
def discard_draft(build_id: str, body: dict = Body(default={})) -> dict:
    """
    Discard the current Stage 2 draft and reset the build to stage2_authorized.

    Allowed states: draft_generated, draft_blocked.
    Removes staging/frank_lloyd/{build_id}/stage2/ entirely.
    Preserves Stage 1 archive, Stage 2 authorization record, and build_log.jsonl.
    Appends draft_discarded event. Status derives back to stage2_authorized.

    Body: {notes: str}  — optional discard notes
    """
    import frank_lloyd.stage2_discarder as _fl_discarder
    notes  = (body.get("notes") or "").strip()
    result = _fl_discarder.discard_draft(build_id.upper(), notes=notes)
    if not result["ok"]:
        return {"ok": False, "build_id": build_id.upper(), "error": result["error"]}
    return {
        "ok":           True,
        "build_id":     build_id.upper(),
        "outcome":      "draft_discarded",
        "discarded_at": result["discarded_at"],
        "message": (
            f"{build_id.upper()} Stage 2 draft discarded. "
            "Build is back to stage2_authorized — a new draft can be generated."
        ),
    }


@router.post("/frank-lloyd/compose-request")
def compose_request(body: dict = Body(default={})) -> dict:
    """
    Queue a new Frank Lloyd build request submitted from the neighborhood UI.

    Delegates to frank_lloyd.request_writer — the same validated request-creation
    logic used by Peter's build-intake handler. Runs the readiness check before
    writing any files.

    Body: {description: str, success_criterion: str}
    Returns: {ok, build_id, title, message, error}
    """
    import frank_lloyd.request_writer as _fl_rw
    description       = (body.get("description") or "").strip()
    success_criterion = (body.get("success_criterion") or "").strip()

    # If success_criterion not provided separately, try to extract from description
    if not success_criterion:
        success_criterion = _fl_rw.extract_success_criterion(description)

    missing = _fl_rw.readiness_check(description, success_criterion)
    if missing:
        problems: list[str] = []
        if "description_too_vague" in missing:
            problems.append("Description is too vague — be specific about what should be built.")
        if "missing_success_criteria" in missing:
            problems.append(
                'Add a success criterion, e.g. "success: the endpoint returns 200 with the expected payload".'
            )
        if "success_criteria_too_vague" in missing:
            problems.append("Success criterion is too short — describe what exact test or check confirms it works.")
        return {
            "ok":             False,
            "build_id":       None,
            "error":          " ".join(problems),
            "missing_fields": missing,
        }

    result = _fl_rw.queue_build(
        description=description,
        success_criterion=success_criterion,
        source="neighborhood_ui",
    )
    if not result["ok"]:
        return {"ok": False, "build_id": None, "error": result["error"]}
    return {
        "ok":      True,
        "build_id": result["build_id"],
        "title":   result["title"],
        "message": (
            f"{result['build_id']} queued: \"{result['title']}\". "
            "Frank Lloyd will generate a spec for review."
        ),
    }


@router.post("/frank-lloyd/{build_id}/authorize-stage2")
def authorize_stage2(build_id: str, body: dict = Body(default={})) -> dict:
    """
    Authorize Stage 2 draft generation for a spec_approved build.

    Delegates to frank_lloyd.stage2_authorizer.authorize_stage2() — same path as
    Peter command 'authorize BUILD-N stage2'. Does NOT start code generation.
    Writes stage2_authorization.json and appends stage2_authorized log event.

    Body: {notes: str}  — optional authorization notes
    """
    import frank_lloyd.stage2_authorizer as _fl_s2auth
    notes  = (body.get("notes") or "").strip()
    result = _fl_s2auth.authorize_stage2(build_id.upper(), notes=notes)
    if not result["ok"]:
        return {"ok": False, "build_id": build_id.upper(), "error": result["error"]}
    return {
        "ok":      True,
        "build_id": build_id.upper(),
        "outcome": "stage2_authorized",
        "message": (
            f"{build_id.upper()} Stage 2 authorized. "
            f"Use Generate Draft to start code generation."
        ),
    }


@router.get("/frank-lloyd/active-job")
def get_active_job() -> dict:
    """
    Return the highest-priority build needing operator attention.

    Uses frank_lloyd.job.load_active_job() to derive a consolidated view
    with phase, next_action, and waiting_on fields.  Reads the build log
    once; no staging or archive reads.

    Returns {ok, job: {...}} or {ok: False, job: None, error: str}.
    """
    try:
        from frank_lloyd.job import load_active_job
    except ImportError as exc:
        return {"ok": False, "job": None, "error": f"job module unavailable: {exc}"}

    job = load_active_job()
    if job is None:
        return {"ok": False, "job": None, "error": "No active builds."}
    return {"ok": True, "job": job.to_dict()}


@router.post("/frank-lloyd/{build_id}/auto-run")
def auto_run(build_id: str, background_tasks: BackgroundTasks,
             body: dict = Body(default={})) -> dict:
    """
    Trigger the Frank Lloyd safe-lane pipeline for a queued build (background).

    Runs: generate_spec → risk gate → approve (if low-risk) → authorize Stage 2
          → generate draft.

    Fire-and-forget — returns immediately. The UI polls /frank-lloyd/status and
    /frank-lloyd/active-job at its normal interval to track progress.

    Body: {} — no parameters needed; build_id from path
    Returns: {ok, build_id, message}
    """
    import frank_lloyd.auto_runner as _auto_runner

    def _run():
        _auto_runner.run_safe_lane(build_id.upper(), initiated_by="neighborhood_ui")

    background_tasks.add_task(_run)
    return {
        "ok":      True,
        "build_id": build_id.upper(),
        "message": (
            f"{build_id.upper()} pipeline started. "
            "Frank Lloyd is working — check back in a moment."
        ),
    }


@router.get("/frank-lloyd/{build_id}/apply-summary")
def get_apply_summary(build_id: str, force: int = 0) -> dict:
    """
    Return a plain-English apply summary for a draft_generated build.

    Reads staged draft artifacts and calls the cheap LM to produce a
    structured summary: what was built, files, risk, what happens on apply,
    and uncertainty. Cached in staging; regenerated with ?force=1.

    Returns {ok, build_id, summary, cached, error}.
    """
    import frank_lloyd.apply_summary as _apply_summary
    return _apply_summary.generate_apply_summary(build_id.upper(), force=bool(force))


@router.post("/frank-lloyd/queue-and-run")
def queue_and_run(background_tasks: BackgroundTasks, body: dict = Body(default={})) -> dict:
    """
    Queue a Frank Lloyd build request and immediately fire the safe-lane pipeline.

    Runs frank_lloyd.request_writer.queue_build() then starts auto_runner.run_safe_lane()
    as a background task. Returns immediately — the UI polls for progress.

    Body: {description: str, success_criterion: str, notes: str}
    Returns: {ok, build_id, title, message, error}
    """
    import frank_lloyd.request_writer as _fl_rw
    import frank_lloyd.auto_runner    as _auto_runner

    description       = (body.get("description") or "").strip()
    success_criterion = (body.get("success_criterion") or "").strip()

    # If success_criterion not provided separately, try to extract from description
    if not success_criterion:
        success_criterion = _fl_rw.extract_success_criterion(description)

    missing = _fl_rw.readiness_check(description, success_criterion)
    if missing:
        problems: list[str] = []
        if "description_too_vague" in missing:
            problems.append("Description is too vague — be specific about what should be built.")
        if "missing_success_criteria" in missing:
            problems.append('Add a success criterion, e.g. "success: the endpoint returns 200".')
        if "success_criteria_too_vague" in missing:
            problems.append("Success criterion is too short — describe what confirms it works.")
        return {"ok": False, "build_id": None, "error": " ".join(problems), "missing_fields": missing}

    result = _fl_rw.queue_build(
        description=description,
        success_criterion=success_criterion,
        source="neighborhood_ui",
    )
    if not result["ok"]:
        return {"ok": False, "build_id": None, "error": result["error"]}

    build_id = result["build_id"]

    def _run():
        _auto_runner.run_safe_lane(build_id, initiated_by="queue_and_run")

    background_tasks.add_task(_run)
    return {
        "ok":      True,
        "build_id": build_id,
        "title":   result["title"],
        "message": (
            f"{build_id} queued and pipeline started: \"{result['title']}\". "
            "Frank Lloyd is working — check back in a moment."
        ),
    }


@router.post("/frank-lloyd/smart-queue")
def smart_queue(background_tasks: BackgroundTasks, body: dict = Body(default={})) -> dict:
    """
    Smart intake: shape freeform operator text into a build brief, then queue + run.

    Uses frank_lloyd.brief_shaper to classify mode and infer success criteria from
    context. Falls back to asking one clarifying question when the input is too vague.
    On success, fires the safe-lane pipeline in the background.

    Body: {raw_input: str}
    Returns:
      {ok: True,  build_id, title, mode, message}               — queued + running
      {ok: False, needs_clarification: True, question}           — needs more detail
      {ok: False, error}                                          — validation failure
    """
    import frank_lloyd.brief_shaper   as _shaper
    import frank_lloyd.request_writer as _fl_rw
    import frank_lloyd.auto_runner    as _auto_runner

    raw_input = (body.get("raw_input") or "").strip()[:2000]
    if not raw_input:
        return {"ok": False, "needs_clarification": True,
                "question": "What would you like Frank Lloyd to build or do?"}

    brief = _shaper.shape(raw_input)

    if brief.needs_clarification:
        return {
            "ok":                 False,
            "needs_clarification": True,
            "question":           brief.clarification_question or "Could you be more specific?",
        }

    # Validate with request_writer readiness check
    missing = _fl_rw.readiness_check(brief.description, brief.success_criterion)
    if missing:
        # If brief_shaper shaped it but it still fails, synthesize from raw_input
        # as a best-effort fallback
        brief = _shaper.deterministic_shape(raw_input)
        if brief.needs_clarification:
            return {
                "ok":                 False,
                "needs_clarification": True,
                "question":           brief.clarification_question,
            }
        missing = _fl_rw.readiness_check(brief.description, brief.success_criterion)
        if missing:
            return {"ok": False, "needs_clarification": False,
                    "error": "Could not shape a clear enough brief. Please be more specific."}

    result = _fl_rw.queue_build(
        description=brief.description,
        success_criterion=brief.success_criterion,
        source=f"smart_queue_{brief.mode}",
    )
    if not result["ok"]:
        return {"ok": False, "needs_clarification": False, "error": result["error"]}

    build_id = result["build_id"]

    def _run():
        _auto_runner.run_safe_lane(build_id, initiated_by=f"smart_queue_{brief.mode}")

    background_tasks.add_task(_run)
    return {
        "ok":      True,
        "build_id": build_id,
        "title":   result["title"],
        "mode":    brief.mode,
        "message": (
            f"{build_id} queued ({brief.mode}): \"{result['title']}\". "
            "Frank Lloyd is on it."
        ),
    }


@router.post("/frank-lloyd/{build_id}/abandon")
def abandon_build(build_id: str, body: dict = Body(default={})) -> dict:
    """
    Abandon a non-terminal Frank Lloyd build.

    Writes an `abandoned` event to the build log. Allowed from any non-terminal
    state. Blocked if the build is already terminal (promoted, rejected, abandoned).

    Body: {notes: str}  — optional reason
    Returns: {ok, build_id, outcome, message, error}
    """
    import frank_lloyd.abandoner as _abandoner
    notes  = (body.get("notes") or "").strip()
    result = _abandoner.abandon_build(build_id.upper(), notes=notes)
    if not result["ok"]:
        return {"ok": False, "build_id": build_id.upper(), "error": result["error"]}
    return {
        "ok":      True,
        "build_id": build_id.upper(),
        "outcome": "abandoned",
        "message": f"{build_id.upper()} abandoned.",
    }


@router.post("/frank-lloyd/{build_id}/generate-draft")
def generate_draft(build_id: str, body: dict = Body(default={})) -> dict:
    """
    Trigger Stage 2 draft generation for a stage2_authorized build.

    Delegates to frank_lloyd.stage2_drafter.generate_stage2_draft() — the same
    path as Peter command 'draft BUILD-N'. This is a synchronous LM-backed call;
    it will block until the draft is written or the LM fails.

    Body: {notes: str}  — optional generation notes
    Returns: {ok, build_id, outcome, message, error}
    """
    import frank_lloyd.stage2_drafter as _fl_drafter
    notes  = (body.get("notes") or "").strip()
    result = _fl_drafter.generate_stage2_draft(build_id.upper(), notes=notes)
    if not result["ok"]:
        return {"ok": False, "build_id": build_id.upper(),
                "error": result.get("error", "Draft generation failed.")}
    status = result.get("status", "")
    if status == "draft_generated":
        return {
            "ok":      True,
            "build_id": build_id.upper(),
            "outcome": "draft_generated",
            "message": f"{build_id.upper()} draft generated. Review it in the Frank Lloyd panel.",
        }
    return {
        "ok":      False,
        "build_id": build_id.upper(),
        "outcome": status,
        "message": f"{build_id.upper()} draft generation did not complete as expected. Status: {status}.",
        "error":   result.get("error", ""),
    }
