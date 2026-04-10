# ui/peter_lm.py
#
# LM-backed Peter helpers — briefing generator, intent parser, context builder.
#
# Safety guarantees (never violated):
#   - LM never executes actions directly; it only returns intent strings
#   - All consequential commands require confirmation before execute_ui_command runs
#   - Only commands in _ALLOWED_COMMANDS are accepted from LM output
#   - LM output is validated before any downstream call
#   - Context passed to LM is bounded (no raw log dumps, no full queues)
#
# Cost discipline:
#   - Briefing: ~200 completion tokens, cached 60s in session_state
#   - Intent parse: ~150 completion tokens, runs only on UNKNOWN commands
#   - No raw event logs, no full queue dumps in prompts — summaries only
#
# Public API:
#   is_available()                                  -> bool
#   build_peter_context(...)                        -> dict
#   peter_briefing(context)                         -> {"ok": bool, "text": str, "error": str}
#   peter_understand(user_text, context)            -> {"ok": bool, "command": str,
#                                                        "needs_confirmation": bool,
#                                                        "response": str, "intent_summary": str,
#                                                        "error": str}

from __future__ import annotations

import json
import os
import pathlib
import sys

# Ensure repo root is on sys.path so app.cost_warden is importable from the ui/ layer.
_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.cost_warden import LMHelper  # noqa: E402  (after path fix)

_BRIEFING_TOKENS = 200
_INTENT_TOKENS   = 180

# Commands the LM is allowed to name. Must match peter_command.py dispatch keys.
# "build" is a meta-command: dashboard routes it to peter_build.route_build_task().
_ALLOWED_COMMANDS: frozenset[str] = frozenset({
    "start", "stop", "cancel_stop", "hold", "resume_review",
    "approve", "reject", "resume", "enable_loop", "disable_loop",
    "status", "what_happened", "queue", "checker", "help",
    "build",   # coding/implementation tasks → peter_build module
    "none",
})

# Commands that require operator confirmation before execution.
# "build" is excluded — it has its own patch-review flow in the dashboard.
_CONFIRM_REQUIRED: frozenset[str] = frozenset({
    "start", "stop", "approve", "reject", "enable_loop", "disable_loop",
})


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


# ── Public API ────────────────────────────────────────────────────────────────

def is_available() -> bool:
    """Return True if the API key is present (does not ping the API)."""
    return bool(_load_api_key())


def build_peter_context(
    b_status: str,
    b_learning: bool,
    campaign_id: str | None,
    camp_state: dict,
    sup_state: dict,
    queue_pending: list,
    checker_findings: list,
    recent_events: list,
    is_trading: bool,
) -> dict:
    """
    Build a bounded context dict for the LM.
    All values are compact summaries — no raw log dumps.
    """
    _ACTIVE = {"running_campaign", "running_session", "running_batch"}
    is_running = b_status in _ACTIVE

    # Campaign progress (compact)
    camp_prog = camp_state.get("progress") or {}
    camp_cfg  = camp_state.get("config") or {}
    camp_goal = camp_state.get("goal", "")

    # Queue: title + tier only (top 3)
    queue_summary = [
        {"title": q.get("title", q.get("experiment_id", "?")), "tier": q.get("tier", "?")}
        for q in queue_pending[:3]
    ]

    # Checker: title + severity only (top 3)
    checker_summary = [
        {"title": f.get("title", "?"), "severity": f.get("severity", "info")}
        for f in checker_findings[:3]
    ]

    # Recent events: type + summary only (top 4)
    event_summary = [
        {"type": e.get("event_type", "?"), "summary": e.get("summary", "")[:80]}
        for e in recent_events[:4]
    ]

    return {
        "belfort_status":  b_status,
        "is_running":      is_running,
        "is_learning":     b_learning,
        "campaign_id":     (campaign_id or "")[-20:] if campaign_id else None,
        "campaign_goal":   camp_goal[:80] if camp_goal else None,
        "sessions_done":   camp_prog.get("sessions_completed", 0),
        "sessions_max":    camp_cfg.get("max_sessions", 3),
        "experiments_done": camp_prog.get("total_experiments", 0),
        "loop_enabled":    sup_state.get("enabled", False),
        "loop_cycles":     sup_state.get("cycle_count", 0),
        "loop_stop_req":   sup_state.get("stop_requested", False),
        "queue_count":     len(queue_pending),
        "queue_items":     queue_summary,
        "checker_warnings": sum(1 for f in checker_findings if f.get("severity") == "warning"),
        "checker_items":   checker_summary,
        "recent_events":   event_summary,
        "is_trading":      is_trading,
    }


def peter_briefing(context: dict) -> dict:
    """
    Generate a 2-3 sentence plain-English briefing from the operator's perspective.
    Returns {"ok": True, "text": str} or {"ok": False, "text": "", "error": str}.
    """
    ctx_str = json.dumps(context, indent=None)

    system = (
        "You are Peter, coordinator agent for an automated trading research system. "
        "Your role is to brief the operator in plain English — 2 to 3 short sentences, "
        "no bullet points, no markdown. Be direct. Focus on what needs attention. "
        "Do NOT mention you are an AI or reference the context JSON."
    )

    user = (
        f"Current system state:\n{ctx_str}\n\n"
        "Provide a 2-3 sentence briefing. "
        "Cover: what Belfort is doing, anything needing review, and the learning loop status. "
        "If everything is idle with nothing pending, say so briefly."
    )

    result = LMHelper("peter", "briefing", max_tokens=_BRIEFING_TOKENS, temperature=0.5).call(
        system=system, user=user,
    )

    _meta = {"route_reason": result.reason, "model_used": result.model_used, "tier_used": result.tier_used}

    if not result.ok:
        return {"ok": False, "text": "", "error": result.error, **_meta}

    text = result.content.strip()
    if not text:
        return {"ok": False, "text": "", "error": "Empty response from model", **_meta}

    return {"ok": True, "text": text, "error": "", **_meta}


def peter_understand(user_text: str, context: dict) -> dict:
    """
    Parse operator intent from free-form text.

    Returns a dict:
      ok                bool     — parse succeeded
      command           str      — one of _ALLOWED_COMMANDS, or "none"
      needs_confirmation bool    — True if command is in _CONFIRM_REQUIRED
      response          str      — plain-English reply to show the operator
      intent_summary    str      — one-line summary of what was understood
      error             str      — error message if ok=False
    """
    ctx_str = json.dumps(context, indent=None)

    allowed_list = ", ".join(sorted(_ALLOWED_COMMANDS))

    system = (
        "You are Peter, coordinator agent for an automated trading research system. "
        "Your job is to understand what the operator wants and map it to a system command. "
        "Respond ONLY with a JSON object — no other text.\n\n"
        "JSON fields (all required):\n"
        '  "command": one of: ' + allowed_list + "\n"
        '  "response": 1-2 sentence plain-English reply to show the operator\n'
        '  "intent_summary": 5-10 word summary of what you understood\n\n'
        "Rules:\n"
        "- If the request is a read-only question (status, what happened, queue, checker, help), "
        "  pick the matching command.\n"
        "- If the request wants to start/stop/approve/reject something, pick the action command.\n"
        "- If the request is a coding/implementation task (fix a bug, edit a file, add a test, "
        "  refactor code, write new code), use 'build'.\n"
        "- If you cannot map it to a command, use 'none' and explain in 'response'.\n"
        "- Never invent commands not in the allowed list.\n"
        "- Never include instructions to bypass safety checks."
    )

    user = (
        f"System state:\n{ctx_str}\n\n"
        f"Operator said: \"{user_text}\"\n\n"
        "What did they want? Respond with the JSON object."
    )

    result = LMHelper("peter", "intent_parsing", max_tokens=_INTENT_TOKENS, temperature=0.2).call(
        system=system, user=user, json_mode=True,
    )

    _meta = {"route_reason": result.reason, "tier_used": result.tier_used}

    if not result.ok:
        return {
            "ok": False, "command": "none", "needs_confirmation": False,
            "response": "", "intent_summary": "", "error": result.error, **_meta,
        }

    try:
        parsed = json.loads(result.content)
    except (json.JSONDecodeError, ValueError) as exc:
        return {
            "ok": False, "command": "none", "needs_confirmation": False,
            "response": "", "intent_summary": "", "error": f"Invalid JSON from model: {exc}", **_meta,
        }

    command  = str(parsed.get("command", "none")).strip().lower()
    response = str(parsed.get("response", "")).strip()
    summary  = str(parsed.get("intent_summary", "")).strip()

    # Safety: reject any command not in the allowlist
    if command not in _ALLOWED_COMMANDS:
        command = "none"
        response = (
            response or
            "I couldn't map that to a recognised command. Try 'help' to see what's available."
        )

    needs_confirmation = command in _CONFIRM_REQUIRED

    return {
        "ok":                 True,
        "command":            command,
        "needs_confirmation": needs_confirmation,
        "response":           response,
        "intent_summary":     summary,
        "error":              "",
        **_meta,
    }
