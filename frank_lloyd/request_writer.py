# frank_lloyd/request_writer.py
#
# Canonical request-creation logic for Frank Lloyd build intake.
# Used by:
#   - app/routes/frank_lloyd_actions.py (compose_request endpoint — neighborhood UI)
#   - peter/handlers.py re-uses the same logic via its own private wrappers;
#     this module is the single authoritative implementation.
#
# Design:
#   readiness_check()   — pure validation, no I/O
#   queue_build()       — assign build ID, write request file, append log event
#   extract_*()         — text helpers shared across intake surfaces
#
# Public API:
#   SUCCESS_MARKERS                                           — success-criterion prefixes
#   VAGUE_TERMS                                              — description vagueness signals
#   extract_success_criterion(text)                          → str
#   extract_title(description)                               → str
#   readiness_check(description, success_criterion)          → list[str]
#   queue_build(description, success_criterion, source, ...) → dict
#   Return shape: {ok, build_id, title, request_path, error}

from __future__ import annotations

import json
import pathlib
import re
from datetime import datetime, timezone
from typing import Optional

_ROOT         = pathlib.Path(__file__).resolve().parent.parent
_FL_REQUESTS  = _ROOT / "data" / "frank_lloyd" / "requests"
_FL_BUILD_LOG = _ROOT / "data" / "frank_lloyd" / "build_log.jsonl"

# Recognised success-criterion markers (same set as peter/handlers.py)
SUCCESS_MARKERS = ("success:", "success criterion:", "done when:", "test:", "verify:")

# Terms that flag a description as too vague when combined with short length
VAGUE_TERMS = frozenset({"better", "nicer", "cleaner", "faster", "improve", "fix it"})

# Conversational boilerplate patterns stripped before deriving a display title.
# e.g. "Peter, have Frank Lloyd build X" → "build X"
_BOILERPLATE_RE = re.compile(
    r'^(?:peter[,.\s]+)?(?:please\s+)?(?:have|tell|ask)\s+frank\s*lloyd\s+(?:to\s+)?',
    re.IGNORECASE,
)


# ── Text helpers ──────────────────────────────────────────────────────────────

def extract_success_criterion(text: str) -> str:
    """Return the text following the first recognised success-criterion marker, or ''."""
    lower = text.lower()
    for marker in SUCCESS_MARKERS:
        idx = lower.find(marker)
        if idx != -1:
            return text[idx + len(marker):].strip()
    return ""


def extract_title(description: str) -> str:
    """Derive a short title (≤ 6 meaningful words) from the description.

    Strips common conversational boilerplate before extracting so that a
    message like "Peter, have Frank Lloyd fix Belfort's stopping UI" yields
    "fix Belfort's stopping UI" rather than "Peter have Frank Lloyd fix".
    """
    text = _BOILERPLATE_RE.sub("", description).strip() or description
    skip = {"a", "an", "the", "new", "that", "which", "with", "and", "for", "so", "to"}
    words = text.split()
    meaningful = [w for w in words[:12] if w.lower().rstrip(".,;") not in skip]
    title = " ".join(meaningful[:6]).rstrip(".,;")
    return title or description[:40]


# ── Validation ────────────────────────────────────────────────────────────────

def readiness_check(description: str, success_criterion: str) -> list[str]:
    """
    Return a list of readiness failures (empty = ready to queue).

    Checks (mirrors peter/handlers.py _fl_readiness_check):
      description_too_vague     — fewer than 5 words, or only vague terms
      missing_success_criteria  — no success criterion supplied
      success_criteria_too_vague — criterion is under 4 words
    """
    missing: list[str] = []

    words = description.split()
    if len(words) < 5:
        missing.append("description_too_vague")
    else:
        lower_desc = description.lower()
        if any(term in lower_desc for term in VAGUE_TERMS) and len(words) < 12:
            missing.append("description_too_vague")

    if not success_criterion:
        missing.append("missing_success_criteria")
    elif len(success_criterion.split()) < 4:
        missing.append("success_criteria_too_vague")

    return missing


# ── Request creation ──────────────────────────────────────────────────────────

def queue_build(
    description:      str,
    success_criterion: str,
    source:           str                 = "operator",
    requests_dir:     Optional[pathlib.Path] = None,
    build_log:        Optional[pathlib.Path] = None,
) -> dict:
    """
    Assign a build ID, write the request file, and append the log event.

    Does NOT call readiness_check() — caller must validate first.
    Returns {ok, build_id, title, request_path, error}.
    """
    rdir = requests_dir or _FL_REQUESTS
    blog = build_log    or _FL_BUILD_LOG

    title    = extract_title(description)
    build_id = _next_build_id(rdir)

    try:
        req_path = _write_request_file(rdir, build_id, title, description, success_criterion)
        _append_log_event(blog, build_id, title, source)
    except OSError as exc:
        return {
            "ok":           False,
            "build_id":     None,
            "title":        title,
            "request_path": None,
            "error":        f"Failed to write build request: {exc}",
        }

    return {
        "ok":           True,
        "build_id":     build_id,
        "title":        title,
        "request_path": str(req_path),
        "error":        None,
    }


# ── Private file helpers ──────────────────────────────────────────────────────

def _next_build_id(requests_dir: pathlib.Path) -> str:
    """Return the next zero-padded build ID (BUILD-001, BUILD-002, …)."""
    existing: list[int] = []
    if requests_dir.exists():
        for f in requests_dir.iterdir():
            stem = f.stem
            if stem.upper().startswith("BUILD-"):
                try:
                    n = int(stem.split("-", 1)[1].split("_", 1)[0])
                    existing.append(n)
                except (IndexError, ValueError):
                    pass
    return f"BUILD-{max(existing, default=0) + 1:03d}"


def _write_request_file(
    requests_dir:     pathlib.Path,
    build_id:         str,
    title:            str,
    description:      str,
    success_criterion: str,
) -> pathlib.Path:
    """Write the request JSON file and return the path."""
    requests_dir.mkdir(parents=True, exist_ok=True)
    req_path = requests_dir / f"{build_id}_request.json"
    payload = {
        "request_id":       build_id,
        "title":            title,
        "description":      description,
        "requester":        "operator",
        "requested_at":     datetime.now(timezone.utc).isoformat(),
        "success_criteria": success_criterion,
        "build_type_hint":  "",
        "context_refs":     [],
        "constraints":      [],
    }
    req_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return req_path


def _append_log_event(
    build_log: pathlib.Path,
    build_id:  str,
    title:     str,
    source:    str = "operator",
) -> None:
    """Append a request_queued event to data/frank_lloyd/build_log.jsonl."""
    build_log.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "build_id":  build_id,
        "event":     "request_queued",
        "notes":     f"Request queued by {source}: {title}",
        "extra":     {"title": title, "build_type_hint": "", "source": source},
    }
    with build_log.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event) + "\n")
