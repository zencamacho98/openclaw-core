# frank_lloyd/stage2_drafter.py
#
# Stage 2 draft generation for Frank Lloyd.
#
# Given a build in stage2_authorized state, generates a first bounded draft
# artifact set using the cheapest executable provider lane (CODE_DRAFT_LOW →
# cheap OpenRouter lane, openrouter/gpt-4o-mini, executability=executable).
#
# Artifacts are written to staging ONLY — never to the live repo:
#   staging/frank_lloyd/{build_id}/stage2/
#     draft_manifest.json   — generation metadata (provider, model, files, timestamps)
#     draft_module.py       — generated Python module
#     draft_notes.md        — LM generation notes
#
# Validation fails cleanly if:
#   - build_id has no log events
#   - current status is not stage2_authorized
#   - stage2_authorization.json not found in archive
#   - decision.json not found in archive
#   - spec.yaml not found in archive (needed for LM prompt)
#   - a draft already exists (draft_manifest.json present in staging output dir)
#   - chosen task class has executability != "executable"
#   - LM call fails or returns malformed JSON
#
# Stage 2 events introduced:
#   draft_generation_started — appended before LM call; always paired with a follow-up
#   draft_generated          — appended on success
#   draft_blocked            — appended on failure AFTER validation passes
#                              (wrong executability, LM error, parse/write error)
#
# Failure cases that produce NO log events (build not ready to attempt generation):
#   - wrong state (not stage2_authorized)
#   - missing authorization file in archive
#   - missing decision.json in archive
#   - missing spec.yaml in archive
#   - draft_manifest.json already present (idempotency guard)
#
# Executability refusal (draft_blocked, NO draft_generation_started):
#   - task class routes to config_only or external_supervised lane
#   - FLLMHelper.call() would also refuse external_supervised, but we check first
#
# Public API:
#   generate_stage2_draft(build_id, task_class=CODE_DRAFT_LOW, notes="") → dict
#   Return shape: {ok, build_id, staging_path, manifest_path, files_generated, routing, error}

from __future__ import annotations

import json
import pathlib
from datetime import datetime, timezone
from typing import Optional

from frank_lloyd.provider_router import (
    FLLMHelper,
    FLTaskClass,
    fl_route,
)

_ROOT         = pathlib.Path(__file__).resolve().parent.parent
_FL_BUILD_LOG = _ROOT / "data" / "frank_lloyd" / "build_log.jsonl"
_FL_ARCHIVES  = _ROOT / "data" / "frank_lloyd" / "archives"
_FL_STAGING   = _ROOT / "staging" / "frank_lloyd"

# Status derivation map — extends stage2_authorizer with Stage 2 draft events.
# Defined locally to keep modules independent.
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
    "draft_discarded":           "stage2_authorized",
}

# Default task class for Stage 2 first draft — cheapest executable lane.
_DEFAULT_TASK_CLASS = FLTaskClass.CODE_DRAFT_LOW

# System prompt for new-file builds.
_DRAFT_SYSTEM = (
    "You are Frank Lloyd, the construction AI for THE ABODE. "
    "You generate minimal, reviewable Python module drafts for builds that have "
    "been reviewed and approved by an operator.\n\n"
    "This is a code_draft_low task: a new isolated Python module with no route "
    "registration or integration requirements — it must be self-contained and "
    "importable.\n\n"
    "Output JSON with exactly two keys:\n"
    "  \"module_code\" — complete Python source code, no markdown fences\n"
    "  \"notes\" — 1-3 sentences: what was produced, key design choices, notable gaps\n\n"
    "Rules:\n"
    "- Write real, minimal, working Python code — not pseudocode or placeholders\n"
    "- The module should do what the spec describes and nothing else\n"
    "- No speculative features, no tests, no docstrings beyond what is needed\n"
    "- Do not include markdown code fences in module_code — raw Python only"
)

# System prompt for doc / text builds — generates appropriate file content.
_DOC_SYSTEM = (
    "You are Frank Lloyd, the construction AI for THE ABODE. "
    "You generate documentation, configuration, and text files for builds that have "
    "been reviewed and approved by an operator.\n\n"
    "Output JSON with exactly two keys:\n"
    "  \"module_code\" — complete file content in the appropriate format "
    "(Markdown, YAML, plain text, etc.) — no code fences, no language markers\n"
    "  \"notes\" — 1-3 sentences: what was produced, key design choices, notable gaps\n\n"
    "Rules:\n"
    "- Write actual content, not pseudocode or placeholders\n"
    "- Match the format appropriate for the target file type described in the spec\n"
    "- No markdown code fences or language specifiers — raw content only\n"
    "- Do not add Python code unless the spec explicitly requires it"
)

# System prompt for modification/patch builds — generates a complete file replacement.
_PATCH_SYSTEM = (
    "You are Frank Lloyd, the construction AI for THE ABODE. "
    "You apply targeted modifications to existing Python files for builds that have "
    "been reviewed and approved by an operator.\n\n"
    "This is a modification task: generate a COMPLETE replacement of the target file "
    "with the approved changes applied. The operator will apply it directly to the repo.\n\n"
    "Output JSON with exactly two keys:\n"
    "  \"module_code\" — complete Python source code of the ENTIRE modified file, no markdown fences\n"
    "  \"notes\" — 1-3 sentences: what was changed, key decisions, what to verify after applying\n\n"
    "Rules:\n"
    "- Output the COMPLETE file — not a diff, not a snippet, the whole file with changes applied\n"
    "- Preserve all existing functionality unless the spec explicitly says to remove it\n"
    "- Make ONLY the changes described in the spec — do not refactor unrelated code\n"
    "- Do not include markdown code fences in module_code — raw Python only\n"
    "- If the spec says which section to change, make only that section's changes"
)


# ── Public API ────────────────────────────────────────────────────────────────

def generate_stage2_draft(
    build_id:   str,
    task_class: FLTaskClass = _DEFAULT_TASK_CLASS,
    notes:      str = "",
) -> dict:
    """
    Generate the first bounded Stage 2 draft artifact set for a stage2_authorized build.

    Uses the cheapest executable provider lane (CODE_DRAFT_LOW → cheap OpenRouter
    lane, openrouter/gpt-4o-mini). Refuses any non-executable lane with a clear
    draft_blocked event — does not silently escalate to Claude.

    Writes to staging/frank_lloyd/{build_id}/stage2/ only.
    Does NOT write to the live repo. Does NOT auto-promote staged output.

    Returns {ok, build_id, staging_path, manifest_path, files_generated, routing, error}.
    """
    build_id = build_id.strip().upper()

    # ── Pre-flight validation (no log events on failure) ──────────────────────

    err = _validate_stage2_authorized(build_id)
    if err:
        return _err(build_id, err)

    archive_dir  = _FL_ARCHIVES / build_id
    auth_path    = archive_dir / "stage2_authorization.json"
    decision_path = archive_dir / "decision.json"
    spec_path    = archive_dir / "spec.yaml"

    if not auth_path.exists():
        return _err(build_id,
                    f"stage2_authorization.json not found in archive ({auth_path}). "
                    "Authorize Stage 2 first: authorize BUILD-N stage2")

    if not decision_path.exists():
        return _err(build_id,
                    f"decision.json not found in archive ({decision_path}). "
                    "The build may not have completed Stage 1 archiving correctly.")

    if not spec_path.exists():
        return _err(build_id,
                    f"spec.yaml not found in archive ({spec_path}). "
                    "The approved spec is required to generate a Stage 2 draft.")

    # Idempotency: refuse if a draft already exists in staging
    stage2_staging_dir = _FL_STAGING / build_id / "stage2"
    manifest_path      = stage2_staging_dir / "draft_manifest.json"
    if manifest_path.exists():
        return _err(build_id,
                    f"A draft already exists for {build_id} "
                    f"({manifest_path}). "
                    "Review or discard the existing draft before generating a new one.")

    # ── Executability check (log draft_blocked, no started event) ─────────────

    route = fl_route(task_class, stage=2)

    if not route.stage_allowed:
        _append_log(_FL_BUILD_LOG, build_id, "draft_blocked",
                    notes=f"Stage 2 draft blocked: {route.error}",
                    extra={"task_class": task_class.value,
                           "provider_tier": route.provider_tier.value,
                           "reason": "stage_not_allowed",
                           "error": route.error})
        return _err(build_id, route.error)

    if route.executability != "executable":
        msg = (
            f"{route.provider_tier.value} lane is {route.executability} — "
            f"not callable via API. "
            f"Model: {route.model}. "
            f"Only executable lanes can be used for automated draft generation."
        )
        _append_log(_FL_BUILD_LOG, build_id, "draft_blocked",
                    notes=f"Stage 2 draft blocked: lane not executable",
                    extra={"task_class":    task_class.value,
                           "provider_tier": route.provider_tier.value,
                           "executability": route.executability,
                           "reason":        "lane_not_executable",
                           "error":         msg})
        return _err(build_id, msg)

    routing_meta = {
        "task_class":      route.task_class.value,
        "provider_tier":   route.provider_tier.value,
        "provider_family": route.provider_family,
        "model":           route.model,
        "executability":   route.executability,
    }

    # ── Read archive content for LM prompt ────────────────────────────────────

    spec_text = spec_path.read_text(encoding="utf-8")

    # Detect build type: doc/text → use doc prompt; modification → use patch prompt; else new-file
    is_doc          = _detect_doc_build_from_spec(spec_text)
    is_modification = _detect_modification_build(spec_text)

    if is_doc:
        system_prompt    = _DOC_SYSTEM
        build_type_label = "doc_or_text"
        max_tokens       = 1400
    elif is_modification:
        system_prompt    = _PATCH_SYSTEM
        build_type_label = "modification"
        max_tokens       = 2400
    else:
        system_prompt    = _DRAFT_SYSTEM
        build_type_label = "new_file"
        max_tokens       = 1400

    request_info: dict = {}
    req_path = archive_dir / "request.json"
    if req_path.exists():
        try:
            request_info = json.loads(req_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass

    title       = request_info.get("title", build_id)
    description = request_info.get("description", "")

    user_prompt = f"Build: {build_id}\n"
    if title and title != build_id:
        user_prompt += f"Title: {title}\n"
    if description:
        user_prompt += f"Request: {description}\n"
    if is_modification:
        user_prompt += f"Build type: modification (generate complete replacement file)\n"
    elif is_doc:
        user_prompt += f"Build type: doc/text (generate appropriate file content, not Python code)\n"
    user_prompt += f"\nApproved Spec:\n{spec_text}"
    if notes:
        user_prompt += f"\n\nGeneration notes from operator: {notes}"

    # ── Log draft_generation_started ─────────────────────────────────────────

    _append_log(_FL_BUILD_LOG, build_id, "draft_generation_started",
                notes=f"Stage 2 draft generation started for {build_id}",
                extra={"task_class":    task_class.value,
                       "build_type":    build_type_label,
                       "provider_tier": route.provider_tier.value,
                       "model":         route.model})

    # ── LM call ───────────────────────────────────────────────────────────────

    helper = FLLMHelper(task_class, max_tokens=max_tokens, temperature=0.4)
    lm_result = helper.call(
        system     = system_prompt,
        user       = user_prompt,
        stage      = 2,
        json_mode  = True,
    )

    if not lm_result.ok:
        _append_log(_FL_BUILD_LOG, build_id, "draft_blocked",
                    notes=f"Stage 2 draft blocked: LM call failed",
                    extra={"task_class":    task_class.value,
                           "provider_tier": route.provider_tier.value,
                           "model":         route.model,
                           "reason":        "lm_failed",
                           "error":         lm_result.error})
        return _err(build_id,
                    f"LM call failed ({route.model}): {lm_result.error}")

    # ── Parse LM output ───────────────────────────────────────────────────────

    try:
        parsed = json.loads(lm_result.content)
        module_code = parsed.get("module_code", "")
        draft_notes = parsed.get("notes", "")
    except (json.JSONDecodeError, ValueError) as exc:
        _append_log(_FL_BUILD_LOG, build_id, "draft_blocked",
                    notes=f"Stage 2 draft blocked: LM output not valid JSON",
                    extra={"task_class":    task_class.value,
                           "provider_tier": route.provider_tier.value,
                           "model":         route.model,
                           "reason":        "parse_failed",
                           "error":         str(exc)})
        return _err(build_id,
                    f"LM returned output that could not be parsed as JSON: {exc}. "
                    "Raw content begins: " + lm_result.content[:120])

    if not module_code.strip():
        _append_log(_FL_BUILD_LOG, build_id, "draft_blocked",
                    notes=f"Stage 2 draft blocked: LM returned empty module_code",
                    extra={"task_class": task_class.value, "reason": "empty_output"})
        return _err(build_id,
                    "LM returned an empty module_code field. "
                    "Cannot write an empty draft artifact.")

    now_str = datetime.now(timezone.utc).isoformat()

    # ── Write staging artifacts ───────────────────────────────────────────────

    try:
        stage2_staging_dir.mkdir(parents=True, exist_ok=True)

        (stage2_staging_dir / "draft_module.py").write_text(
            module_code.strip() + "\n", encoding="utf-8"
        )
        (stage2_staging_dir / "draft_notes.md").write_text(
            f"# Draft Notes — {build_id}\n\n{draft_notes.strip()}\n",
            encoding="utf-8",
        )

        manifest = {
            "build_id":         build_id,
            "stage":            2,
            "task_class":       task_class.value,
            "build_type":       build_type_label,
            "is_modification":  is_modification,
            "provider_tier":    route.provider_tier.value,
            "provider_family":  route.provider_family,
            "model_used":       lm_result.model_used or route.model,
            "generated_at":     now_str,
            "generated_by":     "frank_lloyd",
            "files_generated":  ["draft_module.py", "draft_notes.md"],
            "staging_path":     str(stage2_staging_dir),
            "status":           "draft_generated",
            "input_tokens":     getattr(lm_result, "input_tokens",  0),
            "output_tokens":    getattr(lm_result, "output_tokens", 0),
            "cost_usd":         getattr(lm_result, "cost_usd",      0.0),
            "generation_notes": notes or None,
        }
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    except OSError as exc:
        _append_log(_FL_BUILD_LOG, build_id, "draft_blocked",
                    notes=f"Stage 2 draft blocked: failed to write staging artifacts",
                    extra={"task_class": task_class.value,
                           "reason":     "write_failed",
                           "error":      str(exc)})
        return _err(build_id, f"Failed to write staging artifacts: {exc}")

    files_generated = ["draft_manifest.json", "draft_module.py", "draft_notes.md"]

    # ── Log draft_generated ───────────────────────────────────────────────────

    _append_log(_FL_BUILD_LOG, build_id, "draft_generated",
                notes=f"Stage 2 first draft generated for {build_id}",
                extra={
                    "task_class":      task_class.value,
                    "provider_tier":   route.provider_tier.value,
                    "model":           lm_result.model_used or route.model,
                    "files_generated": files_generated,
                    "staging_path":    str(stage2_staging_dir),
                    "input_tokens":    manifest["input_tokens"],
                    "output_tokens":   manifest["output_tokens"],
                    "cost_usd":        manifest["cost_usd"],
                })

    return {
        "ok":             True,
        "build_id":       build_id,
        "staging_path":   str(stage2_staging_dir),
        "manifest_path":  str(manifest_path),
        "files_generated": files_generated,
        "routing":        routing_meta,
        "error":          None,
    }


# ── Doc / text build detection ───────────────────────────────────────────────

_DOC_EXTENSIONS = frozenset({".md", ".yaml", ".yml", ".json", ".txt", ".rst"})


def _detect_doc_build_from_spec(spec_text: str) -> bool:
    """
    Return True if the spec targets a non-Python text or doc file.

    Checks the affected_files section for path entries with doc/text extensions.
    Used to switch to the _DOC_SYSTEM prompt for appropriate content generation.
    """
    import re as _re
    for m in _re.finditer(r'\s*-\s*path:\s*["\']?([^"\']+)["\']?', spec_text):
        path = m.group(1).strip().strip("\"'")
        dot_idx = path.rfind(".")
        ext = path[dot_idx:].lower() if dot_idx != -1 else ""
        if ext in _DOC_EXTENSIONS:
            return True
    return False


# ── Modification detection ────────────────────────────────────────────────────

def _detect_modification_build(spec_text: str) -> bool:
    """
    Return True if spec_text indicates a file modification (not new file creation).
    Checks build_type field and presence of affected_files.modified section.
    """
    import re as _re
    m = _re.search(r"^\s*build_type\s*:\s*['\"]?(\w+)['\"]?", spec_text, _re.MULTILINE)
    if m:
        return m.group(1).lower() in ("modification", "modification_patch", "patch")
    # Also infer from spec structure: if there's a 'modified:' section with paths
    if _re.search(r"^\s+modified:\s*$", spec_text, _re.MULTILINE):
        # Check it has at least one path entry
        if _re.search(r"modified:.*?path:\s*\"[^\"]+\"", spec_text, _re.DOTALL):
            return True
    return False


# ── Validation ────────────────────────────────────────────────────────────────

def _validate_stage2_authorized(build_id: str) -> Optional[str]:
    """
    Return an error string if the build cannot proceed to draft generation, or None if valid.
    Valid = build exists AND current status is stage2_authorized.
    """
    events = _read_log(_FL_BUILD_LOG)
    build_events = [e for e in events if e.get("build_id") == build_id]
    if not build_events:
        return (f"No events found for {build_id}. "
                "Check the build ID — use 'status' or GET /frank-lloyd/status.")

    status = _derive_status(build_id, events)
    if status is None:
        return f"{build_id} has no recognized status events in the build log."
    if status == "draft_generated":
        return (f"{build_id} already has a generated draft. "
                "Review or discard the existing draft before generating a new one.")
    if status == "draft_blocked":
        return (f"{build_id} has a blocked draft generation. "
                "Resolve the blocking issue and retry, or start a new draft pass.")
    if status == "draft_generating":
        return (f"{build_id} has an in-progress draft generation. "
                "Check staging for partial output.")
    if status in ("pending_spec", "pending_review"):
        return (f"{build_id} is in {status}. "
                "Complete Stage 1 (spec generation → approval) before starting Stage 2.")
    if status == "spec_approved":
        return (f"{build_id} spec is approved but Stage 2 has not been authorized. "
                "Authorize first: authorize BUILD-N stage2")
    if status in ("spec_rejected", "abandoned"):
        return (f"{build_id} is {status}. "
                "Stage 2 draft generation is not possible.")
    if status != "stage2_authorized":
        return (f"{build_id} is in an unexpected state: {status}. "
                "Expected stage2_authorized for Stage 2 draft generation.")
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


# ── Draft review ─────────────────────────────────────────────────────────────

def get_draft_review(build_id: str) -> dict:
    """
    Return draft review data for a build.

    Reads staging/frank_lloyd/{build_id}/stage2/ artifacts if present.
    For draft_blocked builds with no staging artifacts, surfaces the block
    reason from the build log event.

    Return shape:
      {ok, build_id, status, manifest, module_code, notes_text, error}

    ok=True  — manifest, module_code, notes_text populated from staging artifacts
    ok=False — error describes why (no draft, blocked reason, unknown build)
    """
    build_id = build_id.strip().upper()

    events = _read_log(_FL_BUILD_LOG)
    build_events = [e for e in events if e.get("build_id") == build_id]

    if not build_events:
        return _draft_err(build_id,
                          f"No events found for {build_id}.",
                          None)

    status = _derive_status(build_id, events)
    if status is None:
        return _draft_err(build_id,
                          f"{build_id} has no recognized status events.",
                          None)

    stage2_staging = _FL_STAGING / build_id / "stage2"
    manifest_path  = stage2_staging / "draft_manifest.json"
    module_path    = stage2_staging / "draft_module.py"
    notes_path     = stage2_staging / "draft_notes.md"

    # draft_blocked with no staging artifacts — surface reason from log
    if status in ("draft_blocked", "draft_generating") and not manifest_path.exists():
        blocked_ev = next(
            (e for e in reversed(build_events) if e.get("event") == "draft_blocked"),
            None,
        )
        reason = (blocked_ev or {}).get("extra", {}).get("error",
                  "Draft was blocked — see build log for details.")
        return _draft_err(build_id, reason, status)

    if not manifest_path.exists():
        return _draft_err(
            build_id,
            f"No draft found in staging for {build_id} (status: {status}). "
            "Generate a draft first: draft BUILD-N",
            status,
        )

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _draft_err(build_id,
                          f"Could not read draft_manifest.json: {exc}",
                          status)

    module_code: Optional[str] = None
    if module_path.exists():
        try:
            module_code = module_path.read_text(encoding="utf-8")
        except OSError:
            pass

    notes_text: Optional[str] = None
    if notes_path.exists():
        try:
            notes_text = notes_path.read_text(encoding="utf-8")
        except OSError:
            pass

    return {
        "ok":          True,
        "build_id":    build_id,
        "status":      status,
        "manifest":    manifest,
        "module_code": module_code,
        "notes_text":  notes_text,
        "error":       None,
    }


def _draft_err(build_id: str, message: str, status: Optional[str]) -> dict:
    return {
        "ok":          False,
        "build_id":    build_id,
        "status":      status,
        "manifest":    None,
        "module_code": None,
        "notes_text":  None,
        "error":       message,
    }


# ── Error helper ──────────────────────────────────────────────────────────────

def _err(build_id: str, message: str) -> dict:
    return {
        "ok":             False,
        "build_id":       build_id,
        "staging_path":   None,
        "manifest_path":  None,
        "files_generated": [],
        "routing":        None,
        "error":          message,
    }
