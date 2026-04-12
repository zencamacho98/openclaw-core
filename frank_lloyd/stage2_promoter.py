# frank_lloyd/stage2_promoter.py
#
# Stage 2 first-pass safe promote flow for Frank Lloyd.
#
# Promotes a reviewed staged draft (draft_generated) into the live repo.
# This is the first bounded promotion pass — conservative and narrow:
#
#   Promotable drafts:   CODE_DRAFT_LOW, CODE_PATCH_LOW, doc/text variants
#   Destination:         .py or safe text/doc files (.md, .yaml, .yml, .json, .txt, .rst)
#   Source:              staging/frank_lloyd/{build_id}/stage2/draft_module.py
#   Evidence archived:   data/frank_lloyd/archives/{build_id}/promotion_record.json
#
# Safety constraints enforced here:
#   _PROMOTABLE_TASK_CLASSES — only code_draft_low in this pass
#   _OFFLIMITS_FILES         — exact file paths that can never be written to
#   _OFFLIMITS_PREFIXES      — directory prefixes that are never written into
#   new-file-only guard      — target_path must not already exist in the live repo
#   no path traversal        — target_path must not escape the repo root
#
# Promotion events:
#   draft_promoted — appended to data/frank_lloyd/build_log.jsonl on success
#
# Staging artifacts in staging/frank_lloyd/{build_id}/stage2/ are preserved after
# promotion as an audit trail. They are NOT deleted.
#
# Public API:
#   promote_draft(build_id, target_path, notes="") → dict
#   Return shape: {ok, build_id, target_path, promoted_at, archive_path, error}

from __future__ import annotations

import json
import pathlib
import shutil
from datetime import datetime, timezone
from typing import Optional

_ROOT         = pathlib.Path(__file__).resolve().parent.parent
_FL_BUILD_LOG = _ROOT / "data" / "frank_lloyd" / "build_log.jsonl"
_FL_ARCHIVES  = _ROOT / "data" / "frank_lloyd" / "archives"
_FL_STAGING   = _ROOT / "staging" / "frank_lloyd"

# Full status derivation map including draft_promoted.
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

# First-pass: code_draft_low (new isolated module), code_patch_low (file modification),
# and doc/text equivalents — all produced by the standard stage2 drafter.
_PROMOTABLE_TASK_CLASSES = frozenset({
    "code_draft_low", "code_patch_low",
    "doc_draft_low",  "doc_patch_low",
    "text_draft_low", "text_patch_low",
})

# File extensions allowed for safe text / doc targets (in addition to .py).
# Must not be in any off-limits directory — the existing prefix check still applies.
_SAFE_TEXT_EXTENSIONS = frozenset({
    ".md", ".yaml", ".yml", ".json", ".txt", ".rst",
})

# Files that can NEVER be a promotion target — core runtime entrypoints only.
# app/routes/neighborhood.py is intentionally NOT here — Frank Lloyd may modify it.
_OFFLIMITS_FILES = frozenset({
    "app/main.py",
    "scripts/ctl.sh",
    "app/loop.py",
})

# Directory prefixes that are never written into on promotion.
# Relative paths — no leading slash.
_OFFLIMITS_PREFIXES = (
    "data/",
    "staging/",
    "logs/",
    "run/",
    ".venv/",
    ".git/",
)


# ── Public API ────────────────────────────────────────────────────────────────

def promote_draft(build_id: str, target_path: str, notes: str = "") -> dict:
    """
    Promote a staged draft module to the live repo.

    First-pass safety rules:
    - Build must be in draft_generated state.
    - draft_manifest.json and draft_module.py must exist in staging.
    - manifest task_class must be code_draft_low.
    - target_path must be a .py or safe doc/text (.md, .yaml, etc.) file.
    - target_path must not be in any off-limits file or directory.
    - target_path must remain within the repo root (no path traversal).

    On success:
    - Copies draft_module.py to {repo_root}/{target_path}.
    - Writes promotion_record.json to archive.
    - Appends draft_promoted event to build log.
    - Preserves all staging artifacts (audit trail).

    Returns {ok, build_id, target_path, promoted_at, archive_path, error}.
    """
    build_id = build_id.strip().upper()

    # ── State validation (no writes on failure) ───────────────────────────────
    err = _validate_draft_generated(build_id)
    if err:
        return _err(build_id, err)

    # ── Staging artifact validation ───────────────────────────────────────────
    stage2_staging = _FL_STAGING / build_id / "stage2"
    manifest_path  = stage2_staging / "draft_manifest.json"
    module_path    = stage2_staging / "draft_module.py"

    if not manifest_path.exists():
        return _err(
            build_id,
            f"draft_manifest.json not found in staging ({manifest_path}). "
            "Cannot promote without a valid draft manifest.",
        )
    if not module_path.exists():
        return _err(
            build_id,
            f"draft_module.py not found in staging ({module_path}). "
            "Cannot promote without the generated module file.",
        )

    # ── Manifest validation ───────────────────────────────────────────────────
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _err(build_id, f"Could not read draft_manifest.json: {exc}")

    task_class = manifest.get("task_class", "")
    if task_class not in _PROMOTABLE_TASK_CLASSES:
        return _err(
            build_id,
            f"Draft task class '{task_class}' is not promotable in this pass. "
            f"Only {sorted(_PROMOTABLE_TASK_CLASSES)} drafts can be promoted. "
            "Higher-risk task classes require manual review and merge.",
        )

    # ── Target path validation ────────────────────────────────────────────────
    target_path = (target_path or "").strip()
    if not target_path:
        return _err(
            build_id,
            "target_path is required. Specify a relative .py path within the repo.",
        )

    path_err = _validate_target_path(target_path)
    if path_err:
        return _err(build_id, path_err)

    live_path = _ROOT / target_path
    is_modification = _is_modification_build(build_id, manifest)
    if live_path.exists() and not is_modification:
        return _err(
            build_id,
            f"Target file already exists: {target_path}. "
            "This build was classified as a new-file build — it cannot overwrite an existing file. "
            "To modify an existing file, describe your request as a modification "
            "(e.g., 'modify X' or 'fix Y in Z') so Frank Lloyd generates a modification plan.",
        )

    # ── Promote ───────────────────────────────────────────────────────────────
    now_str = datetime.now(timezone.utc).isoformat()
    action = "overwritten" if (live_path.exists() and is_modification) else "created"

    try:
        live_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(module_path), str(live_path))
    except OSError as exc:
        return _err(build_id, f"Failed to write to live repo at {target_path}: {exc}")

    # ── Write promotion record to archive ─────────────────────────────────────
    archive_dir = _FL_ARCHIVES / build_id
    archive_dir.mkdir(parents=True, exist_ok=True)

    promotion_record = {
        "build_id":       build_id,
        "promoted_at":    now_str,
        "promoted_by":    "operator",
        "target_path":    target_path,
        "task_class":     task_class,
        "source_staging": str(module_path),
        "model_used":     manifest.get("model_used"),
        "provider_tier":  manifest.get("provider_tier"),
        "generated_at":   manifest.get("generated_at"),
        "notes":          notes or None,
    }
    try:
        (archive_dir / "promotion_record.json").write_text(
            json.dumps(promotion_record, indent=2), encoding="utf-8"
        )
    except OSError:
        # Archive write failed after live write — event still logged
        pass

    # ── Log draft_promoted ────────────────────────────────────────────────────
    _append_log(
        _FL_BUILD_LOG, build_id, "draft_promoted",
        notes=f"Stage 2 draft promoted to live repo: {target_path} ({action})",
        extra={
            "target_path":    target_path,
            "task_class":     task_class,
            "is_modification": is_modification,
            "file_action":    action,
            "promoted_by":    "operator",
            "model_used":     manifest.get("model_used"),
            "provider_tier":  manifest.get("provider_tier"),
        },
    )

    return {
        "ok":           True,
        "build_id":     build_id,
        "target_path":  target_path,
        "promoted_at":  now_str,
        "archive_path": str(archive_dir),
        "error":        None,
    }


# ── Modification detection ────────────────────────────────────────────────────

def _is_modification_build(build_id: str, manifest: dict) -> bool:
    """
    Return True if this build is a file-modification task (not a new-file creation).
    Checks manifest build_type first, then falls back to archived spec.yaml.
    """
    import re as _re

    # Manifest build_type is the most reliable — drafter sets it explicitly.
    bt = (manifest.get("build_type") or "").lower()
    if bt in ("modification", "modification_patch", "patch"):
        return True

    # Fallback: read archived spec.yaml and parse build_type field.
    spec_path = _FL_ARCHIVES / build_id / "spec.yaml"
    if spec_path.exists():
        try:
            text = spec_path.read_text(encoding="utf-8")
            m = _re.search(r"^\s*build_type\s*:\s*['\"]?(\w+)['\"]?", text, _re.MULTILINE)
            if m:
                return m.group(1).lower() in ("modification", "modification_patch", "patch")
        except OSError:
            pass
    return False


# ── Validation ────────────────────────────────────────────────────────────────

def _validate_draft_generated(build_id: str) -> Optional[str]:
    """Return error string if build is not in draft_generated state, else None."""
    events = _read_log(_FL_BUILD_LOG)
    build_events = [e for e in events if e.get("build_id") == build_id]
    if not build_events:
        return (
            f"No events found for {build_id}. "
            "Check the build ID — use 'status' or GET /frank-lloyd/status."
        )
    status = _derive_status(build_id, events)
    if status is None:
        return f"{build_id} has no recognized status events in the build log."
    if status == "draft_promoted":
        return (
            f"{build_id} has already been promoted to the live repo. "
            "Each build can only be promoted once."
        )
    if status == "draft_blocked":
        return (
            f"{build_id} has a blocked draft. "
            "Resolve the blocking issue before promoting."
        )
    if status == "draft_generating":
        return (
            f"{build_id} has an in-progress draft generation. "
            "Wait for generation to complete."
        )
    if status in ("pending_spec", "pending_review"):
        return (
            f"{build_id} is in {status}. "
            "Complete Stage 1 before Stage 2 promotion."
        )
    if status == "spec_approved":
        return (
            f"{build_id} spec is approved but Stage 2 has not been started. "
            "Generate a draft before promoting."
        )
    if status == "stage2_authorized":
        return (
            f"{build_id} is stage2_authorized. "
            "Generate a draft first: draft BUILD-N"
        )
    if status in ("spec_rejected", "abandoned"):
        return f"{build_id} is {status}. Promotion is not possible."
    if status != "draft_generated":
        return (
            f"{build_id} is in an unexpected state: {status}. "
            "Expected draft_generated for promotion."
        )
    return None


def _validate_target_path(target_path: str) -> Optional[str]:
    """
    Validate the promotion target path.
    Returns an error string if invalid, else None.

    Allowed file types:
      .py  — Python modules (original pass)
      .md, .yaml, .yml, .json, .txt, .rst — safe doc/text files in non-off-limits paths
    """
    # Must be a known-safe file type
    path_lower = target_path.lower()
    is_py   = path_lower.endswith(".py")
    dot_idx = path_lower.rfind(".")
    ext     = path_lower[dot_idx:] if dot_idx != -1 else ""
    is_safe_text = ext in _SAFE_TEXT_EXTENSIONS

    if not is_py and not is_safe_text:
        return (
            f"target_path must be a Python (.py) or safe doc/text file "
            f"(.md, .yaml, .yml, .json, .txt, .rst) — got: {target_path!r}. "
            "Other file types are not promotable in this pass."
        )

    # No absolute paths or path traversal
    if target_path.startswith("/") or ".." in target_path.split("/"):
        return (
            f"target_path must be a relative path within the repo (got: {target_path!r}). "
            "Absolute paths and path traversal are not permitted."
        )

    # Resolve and confirm path stays within repo root
    try:
        resolved = (_ROOT / target_path).resolve()
        if not str(resolved).startswith(str(_ROOT.resolve())):
            return (
                f"target_path resolves outside the repo root: {target_path!r}. "
                "Path traversal is not permitted."
            )
    except (OSError, ValueError):
        return f"target_path could not be resolved: {target_path!r}."

    # Off-limits exact files
    if target_path in _OFFLIMITS_FILES:
        return (
            f"target_path {target_path!r} is an off-limits file "
            "and cannot be a promotion target."
        )

    # Off-limits directory prefixes
    for prefix in _OFFLIMITS_PREFIXES:
        if target_path.startswith(prefix):
            return (
                f"target_path {target_path!r} is in an off-limits directory ({prefix!r}). "
                "Promotion is not permitted into this directory in this pass."
            )

    return None


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
        "target_path":  None,
        "promoted_at":  None,
        "archive_path": None,
        "error":        message,
    }
