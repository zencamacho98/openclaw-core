# ui/peter_build.py
#
# Build task router for Peter.
#
# Peter routes operator coding requests among three paths:
#   A. Deterministic  — handled by existing peter_command dispatch (not this module)
#   B. Cheap Builder  — cheap model for routine, bounded edits
#   C. Strong Reviewer— stronger model for architecture/safety/complex work
#
# This module owns paths B and C.
# Peter (dashboard) chooses between A/B/C; this module only runs after Peter has
# decided the request is a build/coding task.
#
# Safety guarantees:
#   - Never executes file writes; returns a draft for operator review
#   - needs_approval is always True — operator must confirm before anything applies
#   - Protected files trigger automatic reviewer escalation
#   - old_string in patches is validated against read file contents before returning
#   - No raw log dumps in prompts; bounded file context (max 3 files × 200 lines)
#
# Cost discipline:
#   - Classifier: ~100 tokens, cheap model
#   - Builder: ~700 tokens, cheap model
#   - Reviewer: ~900 tokens, strong model (only when escalated)
#   - Model choices are env-configurable; no expensive call by default
#
# Public API:
#   is_build_task(text)                    -> bool   (heuristic, no LM)
#   route_build_task(task_text, context)   -> BuildOutcome dict
#
# BuildOutcome keys:
#   route               str   "builder" | "reviewer" | "error"
#   ok                  bool  True if edits are ready for operator review
#   summary             str   Peter's plain-English explanation to show operator
#   edits               list  [{file, description, old_string, new_string}]
#   needs_approval      bool  always True (operator must confirm)
#   escalation_reason   str   reason for reviewer escalation, "" if none
#   builder_confidence  float 0.0-1.0
#   model_used          str

from __future__ import annotations

import json
import os
import pathlib
import re

import requests as _http

# ── Model config (env-overridable) ─────────────────────────────────────────────
BUILDER_MODEL  = os.getenv("PETER_BUILD_MODEL",  "openai/gpt-4o-mini")
REVIEWER_MODEL = os.getenv("PETER_REVIEW_MODEL", "anthropic/claude-3.5-sonnet")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

# Files that always escalate to the strong reviewer.
# Changes here affect routing, safety, cost, or system integrity.
_PROTECTED_PATHS: frozenset[str] = frozenset({
    "app/supervisor.py",
    "app/checker.py",
    "ui/peter_lm.py",
    "ui/peter_build.py",
    "ui/peter_command.py",
    "peter/commands.py",
    "peter/router.py",
    "peter/handlers.py",
    "app/strategy/applier.py",
    "scripts/promote_candidate.py",
})

_MAX_FILE_LINES   = 200   # lines per file fed to LM
_MAX_CONTEXT_FILES = 3    # max files read per task
_AUTO_ESCALATE_THRESHOLD = 0.65  # builder confidence below this → escalate


# ── Keyword heuristic (no LM) ─────────────────────────────────────────────────

_BUILD_KEYWORDS: frozenset[str] = frozenset({
    "fix", "edit", "change", "update", "add", "remove", "delete",
    "refactor", "implement", "write", "create", "modify", "rename",
    "move", "test", "bug", "error", "patch", "improve", "rewrite",
    "clean up", "cleanup", "replace", "extract", "split", "merge",
})


def is_build_task(text: str) -> bool:
    """
    Quick heuristic: does this text look like a coding/build task?
    No LM call — used to decide whether to invoke this module at all.
    """
    lower = text.lower()
    return any(kw in lower for kw in _BUILD_KEYWORDS)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _load_api_key() -> str:
    key = os.getenv("OPENROUTER_API_KEY", "")
    if key:
        return key
    env_file = pathlib.Path(".env")
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("OPENROUTER_API_KEY="):
                return line.split("=", 1)[1].strip()
    return ""


def _call(
    messages: list[dict],
    max_tokens: int,
    model: str,
    temperature: float = 0.2,
    json_mode: bool = False,
) -> dict:
    """
    Single OpenRouter call. Returns {"content": str} or {"error": str}.
    Never raises.
    """
    api_key = _load_api_key()
    if not api_key:
        return {"error": "OPENROUTER_API_KEY not set"}

    payload: dict = {
        "model":       model,
        "messages":    messages,
        "max_tokens":  max_tokens,
        "temperature": temperature,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    try:
        resp = _http.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type":  "application/json",
            },
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return {"content": data["choices"][0]["message"]["content"].strip()}
    except _http.exceptions.RequestException as exc:
        return {"error": f"OpenRouter request failed: {exc}"}
    except (KeyError, IndexError, ValueError) as exc:
        return {"error": f"Unexpected response shape: {exc}"}


def _extract_file_hints(task_text: str) -> list[str]:
    """Find source file paths mentioned in the task text (e.g. ui/peter_lm.py)."""
    return re.findall(r'[\w/]+\.\w{1,6}', task_text)


def _read_file_context(file_hints: list[str]) -> dict[str, str]:
    """
    Read file contents for context. Returns {relative_path: content_excerpt}.
    Bounded: max _MAX_CONTEXT_FILES files, max _MAX_FILE_LINES lines each.
    """
    context: dict[str, str] = {}
    seen = 0
    for hint in file_hints:
        if seen >= _MAX_CONTEXT_FILES:
            break
        # Try relative-to-repo then absolute
        candidates = [_REPO_ROOT / hint, pathlib.Path(hint)]
        for cand in candidates:
            try:
                if cand.is_file():
                    lines   = cand.read_text().splitlines()
                    excerpt = "\n".join(lines[:_MAX_FILE_LINES])
                    rel     = str(cand.relative_to(_REPO_ROOT))
                    context[rel] = excerpt
                    seen += 1
                    break
            except Exception:
                continue
    return context


def _files_section(file_context: dict[str, str]) -> str:
    if not file_context:
        return "(No file context available — be as specific as possible.)"
    parts = []
    for rel, content in file_context.items():
        parts.append(f"--- {rel} ---\n{content}")
    return "\n\n".join(parts)


def _validate_edits(edits: list[dict], file_context: dict[str, str]) -> tuple[list[dict], list[str]]:
    """
    Validate each edit's old_string exists in the provided file context.
    Returns (valid_edits, warning_notes).
    """
    valid: list[dict] = []
    warnings: list[str] = []
    for edit in edits:
        old = edit.get("old_string", "")
        f   = edit.get("file", "?")
        if not old:
            # No old_string means this is a new file addition — pass through
            valid.append(edit)
            continue
        found = any(old in content for content in file_context.values())
        if found:
            valid.append(edit)
        else:
            warnings.append(f"`{f}`: old_string not found in file (may be hallucinated)")
    return valid, warnings


# ── Classifier ────────────────────────────────────────────────────────────────

def _classify(task_text: str, context: dict, file_names: list[str]) -> dict:
    """
    Cheap LM call: decide builder vs. reviewer.
    Returns {route, reason, confidence, task_summary}.
    """
    ctx_snippet = json.dumps({
        k: context.get(k)
        for k in ("belfort_status", "is_running", "loop_enabled", "campaign_goal")
    }, default=str)

    system = (
        "You classify coding tasks for an automated trading research system. "
        "Respond ONLY with a JSON object.\n\n"
        "Fields (all required):\n"
        '  "route": "builder" or "reviewer"\n'
        '  "reason": one sentence\n'
        '  "confidence": 0.0-1.0\n'
        '  "task_summary": 5-10 word description\n\n'
        "Route to 'reviewer' when:\n"
        "- Change spans multiple modules / files\n"
        "- Change touches safety, cost, routing, or audit logic\n"
        "- Task is ambiguous with real architectural tradeoffs\n"
        "- You would want a senior engineer to look at this\n\n"
        "Route to 'builder' when:\n"
        "- Small targeted edit in one file\n"
        "- UI text / copy / caption change\n"
        "- Test addition for a known, well-scoped function\n"
        "- Straightforward glue code or bounded one-file refactor\n"
    )

    user = (
        f"System context: {ctx_snippet}\n"
        f"Files involved: {file_names}\n"
        f'Task: "{task_text}"\n\n'
        "Classify."
    )

    result = _call(
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        max_tokens=120,
        model=BUILDER_MODEL,
        temperature=0.1,
        json_mode=True,
    )

    if "error" in result:
        return {"route": "reviewer", "reason": result["error"], "confidence": 0.5,
                "task_summary": task_text[:40]}

    try:
        parsed = json.loads(result["content"])
        route  = parsed.get("route", "reviewer")
        if route not in ("builder", "reviewer"):
            route = "reviewer"
        return {
            "route":        route,
            "reason":       str(parsed.get("reason", "")),
            "confidence":   float(parsed.get("confidence", 0.5)),
            "task_summary": str(parsed.get("task_summary", task_text[:40])),
        }
    except Exception:
        return {"route": "reviewer", "reason": "Classification failed", "confidence": 0.5,
                "task_summary": task_text[:40]}


# ── Cheap builder ─────────────────────────────────────────────────────────────

def _run_builder(task_text: str, file_context: dict[str, str]) -> dict:
    """
    Run the cheap builder path. Returns a BuildOutcome dict.
    Validates old_string against file_context before returning.
    """
    system = (
        "You are a coding assistant for an automated trading research system (Python/Streamlit). "
        "Generate a minimal, targeted patch.\n"
        "Respond ONLY with a JSON object.\n\n"
        "Fields (all required):\n"
        '  "edits": list of {\n'
        '      "file": relative path from repo root,\n'
        '      "description": one-line description,\n'
        '      "old_string": EXACT verbatim string to replace (must appear in the file shown),\n'
        '      "new_string": replacement string\n'
        '  }\n'
        '  "explanation": 2-3 sentence plain-English summary\n'
        '  "confidence": 0.0-1.0\n'
        '  "review_flags": list of concerns (empty list if none)\n\n'
        "Rules:\n"
        "- old_string MUST be a verbatim substring of the file content shown below.\n"
        "- If you cannot identify an exact old_string, set edits=[] and confidence=0.3.\n"
        "- Make the smallest change that solves the task — do not refactor beyond scope.\n"
        "- For new files, use old_string='' and new_string=full content.\n"
    )

    user = (
        f"File contents:\n{_files_section(file_context)}\n\n"
        f'Task: "{task_text}"\n\n'
        "Produce the patch."
    )

    result = _call(
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        max_tokens=700,
        model=BUILDER_MODEL,
        temperature=0.2,
        json_mode=True,
    )

    if "error" in result:
        return _error_outcome("builder", f"Builder failed: {result['error']}")

    try:
        parsed = json.loads(result["content"])
    except Exception as exc:
        return _error_outcome("builder", f"Builder returned invalid JSON: {exc}")

    edits      = parsed.get("edits") or []
    confidence = float(parsed.get("confidence", 0.5))
    explanation = str(parsed.get("explanation", ""))
    flags      = list(parsed.get("review_flags") or [])

    valid_edits, warnings = _validate_edits(edits, file_context)
    if warnings:
        flags.extend(warnings)
        confidence = min(confidence, 0.4)

    summary = explanation or f"Draft patch: {len(valid_edits)} edit(s)."
    if flags:
        summary += f" Note: {'; '.join(flags[:2])}"

    return {
        "route":              "builder",
        "ok":                 bool(valid_edits),
        "summary":            summary,
        "edits":              valid_edits,
        "needs_approval":     True,
        "escalation_reason":  "",
        "builder_confidence": confidence,
        "model_used":         BUILDER_MODEL,
    }


# ── Strong reviewer ───────────────────────────────────────────────────────────

def _run_reviewer(task_text: str, file_context: dict[str, str], builder_draft: dict | None) -> dict:
    """
    Run the strong reviewer path. Reviews a builder draft or handles the task directly.
    Returns a BuildOutcome dict.
    """
    if builder_draft and builder_draft.get("edits"):
        draft_section = (
            f"Builder draft (confidence {builder_draft.get('builder_confidence', '?'):.0%}):\n"
            + json.dumps(builder_draft["edits"], indent=2)
        )
    else:
        draft_section = "(No builder draft — handle the task directly.)"

    system = (
        "You are a senior engineer reviewing a code change for an automated trading research "
        "system. Assess safety, correctness, and architectural impact.\n"
        "Respond ONLY with a JSON object.\n\n"
        "Fields (all required):\n"
        '  "verdict": "approve" | "needs_changes" | "reject"\n'
        '  "explanation": 2-4 sentence assessment\n'
        '  "concerns": list of specific issues (empty if none)\n'
        '  "edits": final patch list [{file, description, old_string, new_string}]\n'
        '  "confidence": 0.0-1.0\n\n'
        "- If the builder draft is correct, set verdict=approve and copy the edits unchanged.\n"
        "- If the draft needs fixing, set verdict=needs_changes and provide corrected edits.\n"
        "- If no builder draft exists, generate the edits yourself.\n"
        "- If this should not proceed, set verdict=reject and edits=[].\n"
        "- old_string in edits MUST be verbatim from the file content shown.\n"
    )

    user = (
        f"File contents:\n{_files_section(file_context)}\n\n"
        f"{draft_section}\n\n"
        f'Task: "{task_text}"\n\n'
        "Provide your review and final patch."
    )

    result = _call(
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        max_tokens=900,
        model=REVIEWER_MODEL,
        temperature=0.2,
        json_mode=True,
    )

    if "error" in result:
        return _error_outcome("reviewer", f"Reviewer failed: {result['error']}")

    try:
        parsed = json.loads(result["content"])
    except Exception as exc:
        return _error_outcome("reviewer", f"Reviewer returned invalid JSON: {exc}")

    verdict     = str(parsed.get("verdict", "needs_changes"))
    explanation = str(parsed.get("explanation", ""))
    concerns    = list(parsed.get("concerns") or [])
    edits       = list(parsed.get("edits") or [])
    confidence  = float(parsed.get("confidence", 0.7))

    valid_edits, warnings = _validate_edits(edits, file_context)
    all_concerns          = concerns + warnings

    ok = verdict in ("approve", "needs_changes") and bool(valid_edits)

    summary = explanation or f"Reviewer verdict: {verdict}."
    if all_concerns:
        summary += f" Concerns: {'; '.join(str(c) for c in all_concerns[:2])}"

    return {
        "route":              "reviewer",
        "ok":                 ok,
        "summary":            summary,
        "edits":              valid_edits,
        "needs_approval":     True,
        "escalation_reason":  "; ".join(str(c) for c in concerns[:3]),
        "builder_confidence": confidence,
        "model_used":         REVIEWER_MODEL,
    }


# ── Route selector (main entry point) ────────────────────────────────────────

def route_build_task(task_text: str, context: dict) -> dict:
    """
    Main entry point.

    Routing order:
      1. Protected-file check → always reviewer
      2. LM classifier (cheap) → builder or reviewer
      3. Run builder; if confidence < threshold → auto-escalate to reviewer
      4. Return BuildOutcome for operator review (never applies automatically)
    """
    # Step 1: extract file hints and check protected files
    file_hints = _extract_file_hints(task_text)
    protected  = [
        h for h in file_hints
        if any(h == p or h.endswith("/" + p.split("/")[-1]) for p in _PROTECTED_PATHS)
    ]

    # Step 2: read file context (needed for both classifier and builder)
    file_context = _read_file_context(file_hints)

    # Step 3: determine route
    if protected:
        route             = "reviewer"
        escalation_reason = f"Protected file(s): {', '.join(protected)}"
    else:
        cls               = _classify(task_text, context, list(file_context.keys()))
        route             = cls["route"]
        escalation_reason = ""

    # Step 4: execute
    if route == "builder":
        outcome = _run_builder(task_text, file_context)

        # Auto-escalate on low confidence
        conf = outcome.get("builder_confidence", 1.0)
        if conf < _AUTO_ESCALATE_THRESHOLD:
            esc    = escalation_reason or f"Builder confidence too low ({conf:.0%})"
            rev    = _run_reviewer(task_text, file_context, outcome)
            rev["escalation_reason"] = rev.get("escalation_reason") or esc
            return rev

        if escalation_reason:
            outcome["escalation_reason"] = escalation_reason
        return outcome

    else:  # reviewer
        outcome = _run_reviewer(task_text, file_context, None)
        if escalation_reason:
            outcome["escalation_reason"] = (
                outcome.get("escalation_reason") or escalation_reason
            )
        return outcome


# ── Helpers ───────────────────────────────────────────────────────────────────

def _error_outcome(route: str, message: str) -> dict:
    return {
        "route":              route,
        "ok":                 False,
        "summary":            message,
        "edits":              [],
        "needs_approval":     False,
        "escalation_reason":  "",
        "builder_confidence": 0.0,
        "model_used":         BUILDER_MODEL if route == "builder" else REVIEWER_MODEL,
    }
