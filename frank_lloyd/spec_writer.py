# frank_lloyd/spec_writer.py
#
# Stage 1 spec packet generator for Frank Lloyd.
#
# Given a queued build request this module produces:
#   staging/frank_lloyd/{build_id}/spec.yaml
#   staging/frank_lloyd/{build_id}/preflight.md
# and appends a spec_ready event to data/frank_lloyd/build_log.jsonl.
#
# If the LM is unavailable, a blocked.md is written instead and a blocked
# event is appended — the build stays in pending_spec state from the status
# endpoint's perspective.
#
# Deterministic operations:
#   - Queue selection (read log, find first pending_spec build)
#   - Request file loading
#   - Off-limits file check (preflight Q4)
#   - YAML and Markdown rendering
#   - File writes and log append
#
# LM-assisted operations (strong tier — architecture reasoning):
#   - build_type, risk_level
#   - affected_files (new/modified) — Frank Lloyd cannot name these deterministically
#   - reuse decisions
#   - architecture_layer + justification
#   - sentinel_scope (test file, coverage note)
#   - blast_radius fields
#   - preflight Q1–Q3, Q5–Q7 answers
#
# Public API:
#   generate_spec_packet(build_id: str) → dict
#   find_next_queued_build()            → str | None

from __future__ import annotations

import json
import pathlib
import re
from datetime import datetime, timezone
from typing import Optional

_ROOT         = pathlib.Path(__file__).resolve().parent.parent
_FL_REQUESTS  = _ROOT / "data" / "frank_lloyd" / "requests"
_FL_BUILD_LOG = _ROOT / "data" / "frank_lloyd" / "build_log.jsonl"
_STAGING_ROOT = _ROOT / "staging" / "frank_lloyd"

# ── Domain constants ───────────────────────────────────────────────────────────

# Build log — Stage 1 events that advance a build past pending_spec
_PAST_PENDING_EVENTS = frozenset({
    "spec_ready", "spec_approved", "spec_rejected", "abandoned",
})

# Status mapping: latest known Stage 1 event → logical status
_STATUS_FROM_EVENT: dict[str, str] = {
    "request_queued": "pending_spec",
    "spec_ready":     "pending_review",
    "spec_approved":  "spec_approved",
    "spec_rejected":  "spec_rejected",
    "abandoned":      "abandoned",
}

# Off-limits files (HANDOFF_SPEC §4, FRANK_LLOYD_SPEC §12)
_OFFLIMITS = frozenset({
    "app/main.py",
    "scripts/ctl.sh",
    "app/loop.py",
    "app/routes/neighborhood.py",
})

# Mandatory reuse capabilities (HANDOFF_SPEC §7)
_MANDATORY_REUSE_TEXT = """\
  - LM calls: app/cost_warden.LMHelper
  - Agent state: observability/agent_state.py
  - Event/audit logging: observability/event_log.py
  - Telemetry: observability/telemetry.py
  - Approval flow: research/approval_policy.py
  - Governance: research/governance.py"""

# LM system prompt for spec content generation.
# Uses SPEC_SCHEMA.md vocabulary for build_type and risk_level.
# Note: risk_level from LM is advisory — spec_validator.py will recompute it
# deterministically from affected_files before writing. Do not trust risk_level
# alone to be accurate; the validator is the authority.
_SPEC_SYSTEM = (
    "You are Frank Lloyd, construction architect for THE ABODE AI workforce system.\n"
    "Produce a Stage 1 build spec from the request. Be specific — no vague answers.\n"
    "\n"
    "4-LAYER ARCHITECTURE:\n"
    "  experience        – Neighborhood HTML frontend, /neighborhood\n"
    "  executive_control – Peter, Supervisor daemon, Checker daemon\n"
    "  specialist_house  – Mr Belfort (trading), Frank Lloyd (construction)\n"
    "  operating_services – Custodian, Test Sentinel, Cost Warden\n"
    "\n"
    "MANDATORY REUSE (never rebuild):\n"
    + _MANDATORY_REUSE_TEXT + "\n"
    "\n"
    "OFF-LIMITS FILES (flag explicitly if any must be touched):\n"
    "  app/main.py, scripts/ctl.sh, app/loop.py, app/routes/neighborhood.py\n"
    "\n"
    "RISK LEVELS (SPEC_SCHEMA.md §1 — exact vocabulary):\n"
    "  low      — docs only; OR new isolated file with no integration requirements\n"
    "  medium   — new file requiring route registration or integration\n"
    "  high     — any modification to an existing file; new house build\n"
    "  critical — any change to app/main.py, scripts/ctl.sh, app/routes/neighborhood.py, or runtime infra\n"
    "\n"
    "BUILD TYPES (SPEC_SCHEMA.md §1 — exact vocabulary):\n"
    "  new_house, new_service, modification, platform_capability, clone, docs_only\n"
    "\n"
    "Return ONLY valid JSON — no other text, no markdown fences. Schema:\n"
    '{\n'
    '  "build_type": "new_house|new_service|modification|platform_capability|clone|docs_only",\n'
    '  "risk_level": "low|medium|high|critical",\n'
    '  "affected_files_new": [{"path": "...", "purpose": "..."}],\n'
    '  "affected_files_modified": [{"path": "...", "change": "..."}],\n'
    '  "reuse_decisions": [{"capability": "...", "decision": "not_needed|used", "reason": "..."}],\n'
    '  "architecture_layer": "experience|executive_control|specialist_house|operating_services",\n'
    '  "layer_justification": "one sentence",\n'
    '  "sentinel_test_file": "tests/test_NAME.py",\n'
    '  "sentinel_coverage_note": "one sentence",\n'
    '  "blast_radius_failure_mode": "loud|silent",\n'
    '  "blast_radius_rollback": "one sentence",\n'
    '  "blast_radius_scope": "one sentence",\n'
    '  "preflight_q1": "capability reuse check answer",\n'
    '  "preflight_q2": "house domain check answer",\n'
    '  "preflight_q3": "minimum file set answer",\n'
    '  "preflight_q5": "architecture layer compliance answer",\n'
    '  "preflight_q6": "blast radius assessment answer",\n'
    '  "preflight_q7": "test coverage plan — name source file and test file"\n'
    "}\n"
    "Name exact file paths. No vague answers.\n"
    "Note: Q4 (off-limits) and Q8 (approval gates) are generated separately."
)


# ── Public API ─────────────────────────────────────────────────────────────────

def generate_spec_packet(build_id: str) -> dict:
    """
    Generate spec.yaml + preflight.md for a queued build.

    Returns:
        {ok, build_id, staging_path, spec_path, preflight_path, blocked, error}

    Possible outcomes:
      ok=True, blocked=False  — spec.yaml + preflight.md written, spec_ready logged
      ok=False, blocked=True  — blocked.md written, blocked event logged
      ok=False, blocked=False — validation error (wrong state, missing request file)
    """
    # 1. Validate build state
    log_events = _read_log(_FL_BUILD_LOG)
    status = _derive_build_status(build_id, log_events)

    if status is None:
        return _err(build_id, f"No request_queued event found for {build_id}.")
    if status != "pending_spec":
        return _err(
            build_id,
            f"{build_id} is not in pending_spec state (current status: {status}).",
        )

    # 2. Load request
    req = _load_request(_FL_REQUESTS, build_id)
    if req is None:
        return _err(build_id, f"Request file not found for {build_id}.")

    # 3. Deterministic off-limits check (HANDOFF_SPEC §4)
    offlimits_found = _check_offlimits(
        req.get("description", "") + " " + str(req.get("success_criteria", ""))
    )

    # 4. LM call for spec content (cheap tier — see cost-discipline note below).
    # The deterministic validator in step 5 is the safety net; cheap tier is
    # sufficient because: (a) the operator reviews and approves the spec, and
    # (b) the validator corrects all doctrine-violating fields before writing.
    # Stage 2 code generation will use strong tier — code bugs have higher
    # blast radius than spec quality issues.
    lm_result = _call_spec_lm(req)

    staging_dir = _STAGING_ROOT / build_id
    staging_dir.mkdir(parents=True, exist_ok=True)

    if not lm_result["ok"]:
        # Write blocked.md instead of spec (HANDOFF_SPEC §8)
        blocked_path = staging_dir / "blocked.md"
        _write_blocked_md(blocked_path, build_id, lm_result["error"])
        _append_log(
            _FL_BUILD_LOG, build_id, "blocked",
            notes=f"Frank Lloyd blocked: {lm_result['error']}",
            extra={"blocked_state": "uncertain_scope", "reason": lm_result["error"]},
        )
        return {
            "ok":             False,
            "build_id":       build_id,
            "staging_path":   str(staging_dir),
            "spec_path":      None,
            "preflight_path": None,
            "blocked":        True,
            "error":          lm_result["error"],
        }

    # 5. Deterministic validation — must run before any files are written.
    # Rules win over LM output when there is a conflict.
    from frank_lloyd.spec_validator import validate_and_correct
    spec_data, corrections = validate_and_correct(
        lm_result["data"], req, offlimits_found
    )

    # 6. Write staging artifacts
    spec_path      = staging_dir / "spec.yaml"
    preflight_path = staging_dir / "preflight.md"

    spec_path.write_text(
        _format_spec_yaml(build_id, req, spec_data, offlimits_found, corrections),
        encoding="utf-8",
    )
    preflight_path.write_text(
        _format_preflight_md(build_id, req, spec_data, offlimits_found),
        encoding="utf-8",
    )

    # 7. Append spec_ready to build log (includes corrections for auditability)
    _append_log(
        _FL_BUILD_LOG, build_id, "spec_ready",
        notes=f"Spec packet generated for {build_id}",
        extra={
            "spec_path":      str(spec_path),
            "preflight_path": str(preflight_path),
            "build_type":     spec_data.get("build_type", ""),
            "risk_level":     spec_data.get("risk_level", ""),
            "corrections":    corrections,
        },
    )

    return {
        "ok":             True,
        "build_id":       build_id,
        "staging_path":   str(staging_dir),
        "spec_path":      str(spec_path),
        "preflight_path": str(preflight_path),
        "blocked":        False,
        "error":          None,
        "corrections":    corrections,
    }


def find_next_queued_build() -> Optional[str]:
    """
    Return the build_id of the first pending_spec build in the log, or None.
    FIFO: the build whose request_queued event appears earliest in the log wins.
    """
    events = _read_log(_FL_BUILD_LOG)

    # Collect build IDs in log order (first appearance)
    seen: list[str] = []
    seen_set: set[str] = set()
    for ev in events:
        bid = ev.get("build_id")
        if bid and bid not in seen_set:
            seen.append(bid)
            seen_set.add(bid)

    for bid in seen:
        if _derive_build_status(bid, events) == "pending_spec":
            return bid

    return None


# ── Internal: queue and log helpers ───────────────────────────────────────────

def _derive_build_status(build_id: str, events: list[dict]) -> Optional[str]:
    """
    Return the current logical status for a build_id, or None if no events exist.
    Latest known Stage 1 event wins.
    """
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


def _load_request(requests_dir: pathlib.Path, build_id: str) -> Optional[dict]:
    req_file = requests_dir / f"{build_id}_request.json"
    if not req_file.exists():
        return None
    try:
        return json.loads(req_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _check_offlimits(text: str) -> list[str]:
    """Return off-limits file paths mentioned anywhere in text."""
    lower = text.lower()
    return [f for f in sorted(_OFFLIMITS) if f.lower() in lower]


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


def _err(build_id: str, message: str) -> dict:
    return {
        "ok":             False,
        "build_id":       build_id,
        "staging_path":   None,
        "spec_path":      None,
        "preflight_path": None,
        "blocked":        False,
        "error":          message,
    }


# ── Internal: LM call ─────────────────────────────────────────────────────────

def _load_capability_excerpt() -> str:
    """
    Return a compact list of live capabilities from CAPABILITY_REGISTRY.md.

    Injected into the spec LM prompt so the LM can make better reuse decisions.
    Returns empty string on any read error (non-fatal).
    """
    reg_path = _ROOT / "docs" / "CAPABILITY_REGISTRY.md"
    if not reg_path.exists():
        return ""
    try:
        text = reg_path.read_text(encoding="utf-8")
    except OSError:
        return ""

    lines_out: list[str] = []
    in_live_entry = False
    current_cap   = ""

    for line in text.splitlines():
        # Section headers (## X.Y Name)
        if line.startswith("## ") and not line.startswith("### "):
            in_live_entry = False
            current_cap   = line.lstrip("# ").strip()
        # Table rows: | Status | live |
        elif "| Status" in line and "| live" in line.lower():
            in_live_entry = True
        elif in_live_entry and "| Code location" in line:
            loc = line.split("|")[-2].strip() if "|" in line else ""
            if current_cap and loc:
                lines_out.append(f"  - {current_cap}: {loc}")
            in_live_entry = False

    if not lines_out:
        return ""
    return "LIVE CAPABILITIES IN THE SYSTEM (check these before proposing new files):\n" + "\n".join(lines_out[:30])


def _call_spec_lm(req: dict) -> dict:
    """
    Call the LM to generate spec content fields, routed through FLLMHelper.
    Returns {ok, data, error}.

    Routes via FLTaskClass.SPEC_DRAFT → cheap OpenRouter lane (FL_CHEAP_MODEL).
    Cheap tier is appropriate for Stage 1 because:
    - The deterministic validator (spec_validator.py) corrects doctrine violations
    - The operator reviews and approves before any code is written
    - Stage 2 code generation uses the coding/strong tiers (higher blast radius)
    """
    try:
        from frank_lloyd.provider_router import FLLMHelper, FLTaskClass
    except ImportError as exc:
        return {"ok": False, "data": None, "error": f"provider_router unavailable: {exc}"}

    cap_excerpt = _load_capability_excerpt()
    user_msg = (
        f"Title: {req.get('title', '')}\n"
        f"Description: {req.get('description', '')}\n"
        f"Success criteria: {req.get('success_criteria', '')}"
    )
    if cap_excerpt:
        user_msg = cap_excerpt + "\n\n" + user_msg

    try:
        helper = FLLMHelper(FLTaskClass.SPEC_DRAFT, max_tokens=700)
        result = helper.call(system=_SPEC_SYSTEM, user=user_msg, stage=1)
    except Exception as exc:
        return {"ok": False, "data": None, "error": str(exc)}

    if not result.ok:
        return {"ok": False, "data": None, "error": result.error}

    data = _parse_json_response(result.content)
    if data is None:
        return {"ok": False, "data": None, "error": "LM response was not valid JSON"}

    return {"ok": True, "data": data, "error": None}


def _parse_json_response(text: str) -> Optional[dict]:
    """Extract a JSON object from LM response text (handles trailing text/fences)."""
    text = text.strip()
    # Direct parse first
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
    except (json.JSONDecodeError, ValueError):
        pass
    # Fallback: find first {...} block
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group())
            if isinstance(result, dict):
                return result
        except (json.JSONDecodeError, ValueError):
            pass
    return None


# ── Internal: artifact rendering ──────────────────────────────────────────────

def _qs(val: str) -> str:
    """Quote a string value for YAML — escapes inner double-quotes."""
    return '"' + str(val).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _format_spec_yaml(
    build_id: str,
    req: dict,
    spec: dict,
    offlimits_found: list[str],
    corrections: list[dict] | None = None,
) -> str:
    """Render spec.yaml as a string."""
    now = datetime.now(timezone.utc).isoformat()
    new_files      = spec.get("affected_files_new", []) or []
    modified_files = spec.get("affected_files_modified", []) or []
    reuse_decisions = spec.get("reuse_decisions", []) or []

    lines: list[str] = [
        "# Frank Lloyd — Stage 1 Spec",
        "# Review this document before approving.",
        "# Approval does NOT authorize code generation.",
        "",
        f"build_id: {_qs(build_id)}",
        "stage: 1",
        'spec_version: "1.0"',
        f"generated_at: {_qs(now)}",
        "",
        "# ── Request ──────────────────────────────────────────────────────────────────",
        f"title: {_qs(req.get('title', ''))}",
        f"description: {_qs(req.get('description', ''))}",
        f"success_criteria: {_qs(req.get('success_criteria', ''))}",
        "",
        "# ── Build classification ──────────────────────────────────────────────────────",
        f"build_type: {spec.get('build_type', 'unknown')}",
        f"risk_level: {spec.get('risk_level', 'unknown')}",
        "",
        "# ── File set ──────────────────────────────────────────────────────────────────",
        "affected_files:",
        "  new:",
    ]
    if new_files:
        for f in new_files:
            lines.append(f"    - path: {_qs(f.get('path', ''))}")
            lines.append(f"      purpose: {_qs(f.get('purpose', ''))}")
    else:
        lines.append("    []")

    lines.append("  modified:")
    if modified_files:
        for f in modified_files:
            lines.append(f"    - path: {_qs(f.get('path', ''))}")
            lines.append(f"      change: {_qs(f.get('change', ''))}")
    else:
        lines.append("    []")

    lines += [
        "",
        "# ── Reuse ─────────────────────────────────────────────────────────────────────",
        "reuse:",
        "  capability_registry_checked: true",
        "  decisions:",
    ]
    if reuse_decisions:
        for d in reuse_decisions:
            lines.append(f"    - capability: {_qs(d.get('capability', ''))}")
            lines.append(f"      decision: {d.get('decision', 'not_needed')}")
            lines.append(f"      reason: {_qs(d.get('reason', ''))}")
    else:
        lines.append("    []")

    lines += [
        "",
        "# ── Architecture ─────────────────────────────────────────────────────────────",
        f"architecture_layer: {spec.get('architecture_layer', 'unknown')}",
        f"layer_justification: {_qs(spec.get('layer_justification', ''))}",
        "",
        "# ── Sentinel scope ────────────────────────────────────────────────────────────",
        "sentinel_scope:",
        f"  test_file: {_qs(spec.get('sentinel_test_file', ''))}",
        f"  coverage_note: {_qs(spec.get('sentinel_coverage_note', ''))}",
        "",
        "# ── Blast radius ──────────────────────────────────────────────────────────────",
        "blast_radius:",
        f"  failure_mode: {spec.get('blast_radius_failure_mode', 'unknown')}",
        f"  rollback: {_qs(spec.get('blast_radius_rollback', ''))}",
        f"  scope: {_qs(spec.get('blast_radius_scope', ''))}",
    ]

    if offlimits_found:
        lines += [
            "",
            "# ── FLAGGED: off-limits files required ───────────────────────────────────────",
            "offlimits_required:",
        ]
        for f in offlimits_found:
            lines.append(f"  - {f}")

    if corrections:
        lines += [
            "",
            "# ── Validation corrections applied ───────────────────────────────────────────",
            "# These fields were corrected by deterministic rules after LM draft generation.",
            "# Review these corrections — they indicate LM output that conflicted with doctrine.",
            "validation_corrections:",
        ]
        for c in corrections:
            lines.append(f"  - field: {c['field']}")
            lines.append(f"    original: {_qs(str(c['original']))}")
            lines.append(f"    corrected: {_qs(str(c['corrected']))}")
            lines.append(f"    rule: {_qs(c['rule'])}")

    return "\n".join(lines) + "\n"


def _format_preflight_md(
    build_id: str,
    req: dict,
    spec: dict,
    offlimits_found: list[str],
) -> str:
    """Render preflight.md as a string."""
    now = datetime.now(timezone.utc).isoformat()

    # Q4 — deterministic off-limits check
    if offlimits_found:
        q4 = (
            "**FLAGGED.** The following off-limits files appear to be required:\n\n"
            + "\n".join(f"  - `{f}`" for f in offlimits_found)
            + "\n\n  Operator must explicitly authorize touching each of these files "
            "before Frank Lloyd will include them in a build."
        )
    else:
        q4 = (
            "No off-limits files required. The proposed file set does not include "
            "`app/main.py`, `scripts/ctl.sh`, `app/loop.py`, or `app/routes/neighborhood.py`."
        )

    # Q8 — deterministic approval gates for Stage 1
    q8 = (
        "1. **Spec approval** (this document) — operator reviews `spec.yaml` + `preflight.md` "
        "and approves before any code is written.\n"
        "2. (Stage 2+) Code review — operator reviews staged code artifacts before promotion to live repo.\n"
        "3. (Stage 2+) Promotion — operator explicitly promotes staged artifacts to the live repo.\n\n"
        "No automated approvals at Stage 1. Spec approval does not authorize Stage 2."
    )

    def _section(n: int, title: str, question: str, answer: str) -> list[str]:
        return [
            f"## {n}. {title}",
            "",
            f"> {question}",
            "",
            f"**Answer**: {answer}",
            "",
            "---",
            "",
        ]

    lines: list[str] = [
        f"# Frank Lloyd — {build_id} Pre-flight Checklist",
        "",
        f"**Build ID**: {build_id}  ",
        f"**Title**: {req.get('title', '')}  ",
        f"**Generated**: {now}  ",
        "**Status**: Awaiting operator review",
        "",
        "---",
        "",
    ]

    lines += _section(
        1, "Capability reuse check",
        "Does anything in CAPABILITY_REGISTRY already cover part of this request? "
        "Did you check docs/frank_lloyd/ for existing data structures this would use?",
        spec.get("preflight_q1", "[Not answered — LM unavailable]"),
    )
    lines += _section(
        2, "Existing house domain check",
        "Does this request belong inside an existing house's domain? "
        "Could it be an extension of Belfort, Peter, or an operating service?",
        spec.get("preflight_q2", "[Not answered — LM unavailable]"),
    )
    lines += _section(
        3, "Minimum file set",
        "What is the smallest set of files that satisfies the success criterion? "
        "Is every proposed file necessary, or is any speculative?",
        spec.get("preflight_q3", "[Not answered — LM unavailable]"),
    )
    lines += _section(
        4, "Off-limits file check",
        "Does this request require touching `app/main.py`, `scripts/ctl.sh`, "
        "`app/loop.py`, or `app/routes/neighborhood.py`? "
        "If yes: name the file, describe the change, and flag it explicitly.",
        q4,
    )
    lines += _section(
        5, "Architecture layer compliance",
        "Where does this artifact sit in the 4-layer model? "
        "Does it cross a layer boundary? If so, why is that crossing justified?",
        spec.get("preflight_q5", "[Not answered — LM unavailable]"),
    )
    lines += _section(
        6, "Blast radius assessment",
        "What breaks if this artifact contains a bug? "
        "Is the failure mode silent (data corruption) or loud (startup crash)? "
        "Can rollback happen by deleting one file?",
        spec.get("preflight_q6", "[Not answered — LM unavailable]"),
    )
    lines += _section(
        7, "Test coverage plan",
        "What existing tests cover related behavior? "
        "What new tests would be needed? Name the test file(s). "
        "Map: source file → test file.",
        spec.get("preflight_q7", "[Not answered — LM unavailable]"),
    )
    lines += _section(
        8, "Approval checkpoint list",
        "List every human approval gate this build will require, in order.",
        q8,
    )

    return "\n".join(lines)


def _write_blocked_md(path: pathlib.Path, build_id: str, reason: str) -> None:
    content = (
        f"# Frank Lloyd — {build_id} Blocked\n\n"
        f"**Blocked state**: uncertain_scope\n"
        f"**Reason**: {reason}\n"
        f"**What is needed to unblock**: LM service must be available for spec generation.\n"
        f"**Recommended operator action**: Check OPENROUTER_API_KEY and retry.\n"
    )
    path.write_text(content, encoding="utf-8")
