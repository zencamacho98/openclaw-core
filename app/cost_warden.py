# app/cost_warden.py
#
# LM routing policy and cost governance for The Abode.
#
# Cost Warden establishes three things:
#   1. MODEL_REGISTRY   — pricing and tier for every model The Abode may use
#   2. TASK_POLICY      — which tier each task type should use by default
#   3. LMHelper         — shared call pattern all backstage agents can adopt
#
# Agent LM architecture rule (applies to all agents in The Abode):
#   bones      = deterministic checks / rules / data access / safe actions
#   brain      = LM-backed summarization / interpretation / recommendation
#   guardrails = bounded context, allowlists, confirmation for risky actions,
#                cost-aware routing
#
# Do NOT replace deterministic cores with vague LM behaviour.
# Do NOT make expensive models the default path.
#
# Model tier defaults (env-overridable):
#   CHEAP_MODEL  = openai/gpt-4o-mini          (routine summaries, intent, analysis)
#   STRONG_MODEL = anthropic/claude-sonnet-4-6  (architecture, safety, complex review)
#
# Usage log: data/warden_usage.jsonl (append-only, one line per LM call)
#
# Public API:
#   route(task, context)              → RoutingDecision
#   LMHelper(agent, task, max_tokens) → call(system, user) → LMResult
#   get_usage_summary(limit)          → dict
#   get_policy_report()               → dict

from __future__ import annotations

import json
import os
import pathlib
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Optional

import requests as _http

_ROOT        = pathlib.Path(__file__).resolve().parent.parent
_USAGE_LOG   = _ROOT / "data" / "warden_usage.jsonl"
_API_ENV     = _ROOT / ".env"

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# ── Model registry ────────────────────────────────────────────────────────────

@dataclass
class ModelSpec:
    tier:                  str    # "cheap" | "strong"
    cost_per_1m_input:     float  # USD per 1M input tokens
    cost_per_1m_output:    float  # USD per 1M output tokens
    description:           str    # when to use this model


MODEL_REGISTRY: dict[str, ModelSpec] = {
    # Cheap tier — routine, bounded, low-risk tasks
    "openai/gpt-4o-mini": ModelSpec(
        tier="cheap", cost_per_1m_input=0.15, cost_per_1m_output=0.60,
        description="Routine summaries, intent parsing, bounded analysis",
    ),
    "anthropic/claude-haiku-4-5-20251001": ModelSpec(
        tier="cheap", cost_per_1m_input=0.25, cost_per_1m_output=1.25,
        description="Fast Claude tasks, simple classification",
    ),
    # Legacy slug without date
    "anthropic/claude-haiku-4-5": ModelSpec(
        tier="cheap", cost_per_1m_input=0.25, cost_per_1m_output=1.25,
        description="Fast Claude tasks, simple classification",
    ),
    # Strong tier — architecture, safety review, complex reasoning
    "anthropic/claude-sonnet-4-6": ModelSpec(
        tier="strong", cost_per_1m_input=3.0, cost_per_1m_output=15.0,
        description="Architecture, safety review, complex reasoning",
    ),
    "anthropic/claude-3.5-sonnet": ModelSpec(
        tier="strong", cost_per_1m_input=3.0, cost_per_1m_output=15.0,
        description="Architecture, safety review (legacy slug)",
    ),
    "anthropic/claude-opus-4-6": ModelSpec(
        tier="strong", cost_per_1m_input=15.0, cost_per_1m_output=75.0,
        description="Most complex tasks; use sparingly",
    ),
}

# Env-overridable model defaults
CHEAP_MODEL  = os.getenv("CHEAP_MODEL",  "openai/gpt-4o-mini")
STRONG_MODEL = os.getenv("STRONG_MODEL", "anthropic/claude-sonnet-4-6")


# ── Task routing policy ───────────────────────────────────────────────────────

@dataclass
class TaskPolicy:
    tier:        str   # "deterministic" | "cheap" | "strong"
    description: str   # why this tier is appropriate


TASK_POLICY: dict[str, TaskPolicy] = {
    # ── Deterministic — no LM needed ─────────────────────────────────────────
    "health_check":      TaskPolicy("deterministic", "Rule-based checks; no interpretation needed"),
    "test_run":          TaskPolicy("deterministic", "Test execution is deterministic"),
    "status_lookup":     TaskPolicy("deterministic", "Data reads; no LM synthesis needed"),
    "queue_check":       TaskPolicy("deterministic", "Structured data; deterministic"),
    "cost_report":       TaskPolicy("deterministic", "Aggregation over logs; deterministic"),
    # ── Cheap LM — bounded context, low-risk output ───────────────────────────
    "intent_parsing":    TaskPolicy("cheap", "Fixed-schema output from bounded operator context"),
    "briefing":          TaskPolicy("cheap", "Summarization from bounded structured state data"),
    "trade_analysis":    TaskPolicy("cheap", "Pattern analysis from recent trade data"),
    "candidate_summary": TaskPolicy("cheap", "Structured experiment result summarization"),
    "health_explain":    TaskPolicy("cheap", "Plain-English explanation of health findings"),
    "test_explain":      TaskPolicy("cheap", "Plain-English explanation of test failures"),
    "event_summary":     TaskPolicy("cheap", "Compact narrative from event log entries"),
    # ── Strong model — architecture, safety, ambiguous tradeoffs ─────────────
    "code_review":       TaskPolicy("strong", "File-level edits touching safety or architecture"),
    "safety_review":     TaskPolicy("strong", "Touches routing, guardrails, or policy files"),
    "routing_change":    TaskPolicy("strong", "Changes operator command dispatch or identity"),
    "architecture":      TaskPolicy("strong", "Structural decisions with broad impact"),
    "escalated_build":   TaskPolicy("strong", "Builder confidence below threshold"),
}

# Escalation conditions (cheap → strong override)
ESCALATION_REASONS: dict[str, str] = {
    "protected_file":       "Task touches a protected routing/safety/policy file",
    "low_confidence":       "Builder confidence below auto-escalation threshold (0.65)",
    "explicit_review":      "Operator explicitly requested stronger review",
    "ambiguous_tradeoff":   "Task involves ambiguous architectural tradeoff",
}


# ── Routing decision ──────────────────────────────────────────────────────────

@dataclass
class RoutingDecision:
    task:              str
    tier:              str          # "deterministic" | "cheap" | "strong"
    model:             Optional[str]  # None if deterministic
    reason:            str          # plain English: why this tier
    escalated:         bool         # True if cheap was bumped to strong
    escalation_reason: str          # "" if not escalated
    est_cost_cents:    float        # rough per-call estimate (fractional cents)


def route(
    task:             str,
    context:          dict[str, Any] | None = None,
    force_tier:       str | None            = None,
    escalation_reason: str                  = "",
) -> RoutingDecision:
    """
    Determine which tier and model to use for a task.

    Args:
        task:             task key from TASK_POLICY (or free-form string)
        context:          optional dict with hints like budget_pct_used, confidence
        force_tier:       override: "deterministic" | "cheap" | "strong"
        escalation_reason: if provided, forces escalation to strong with this reason
    """
    ctx = context or {}

    # Look up base policy
    policy = TASK_POLICY.get(task)
    if policy:
        base_tier   = policy.tier
        base_reason = policy.description
    else:
        # Unknown task → cheap by default, with a note
        base_tier   = "cheap"
        base_reason = f"Unknown task '{task}' — defaulting to cheap tier"

    # Apply force override
    if force_tier in ("deterministic", "cheap", "strong"):
        base_tier   = force_tier
        base_reason = f"Tier forced to '{force_tier}' by caller"

    # Apply escalation
    escalated = False
    esc_reason = ""

    if escalation_reason and base_tier == "cheap":
        base_tier  = "strong"
        escalated  = True
        esc_reason = escalation_reason

    # Budget pressure: if budget is very tight, downgrade strong → cheap
    # (only for non-critical tasks)
    budget_pct = ctx.get("budget_pct_used", 0.0)
    if base_tier == "strong" and budget_pct >= 90.0 and task not in ("safety_review", "routing_change"):
        base_tier   = "cheap"
        base_reason = f"Downgraded to cheap: budget at {budget_pct:.0f}% ({base_reason})"

    # Resolve model
    if base_tier == "deterministic":
        model = None
    elif base_tier == "strong":
        model = STRONG_MODEL
    else:
        model = CHEAP_MODEL

    # Rough cost estimate (assumes ~200 input + 100 output tokens for a typical small call)
    est_cost_cents = 0.0
    if model:
        spec = MODEL_REGISTRY.get(model)
        if spec:
            est_cost_cents = (
                (200 / 1_000_000) * spec.cost_per_1m_input
                + (100 / 1_000_000) * spec.cost_per_1m_output
            ) * 100  # → fractional cents

    return RoutingDecision(
        task              = task,
        tier              = base_tier,
        model             = model,
        reason            = base_reason,
        escalated         = escalated,
        escalation_reason = esc_reason,
        est_cost_cents    = round(est_cost_cents, 4),
    )


# ── LMHelper — shared call pattern for backstage agents ──────────────────────

@dataclass
class LMResult:
    """Result from a LMHelper.call() invocation."""
    ok:           bool
    content:      str
    model_used:   str    # "" if deterministic or failed
    tier_used:    str    # "deterministic" | "cheap" | "strong"
    reason:       str    # why this tier was chosen
    error:        str    # "" on success, error message on failure
    input_tokens:  int   # 0 if unavailable
    output_tokens: int   # 0 if unavailable
    cost_usd:     float  # 0.0 if unavailable


class LMHelper:
    """
    Shared LM call pattern for backstage agents in The Abode.

    Architecture:
      bones      = deterministic routing via TASK_POLICY
      brain      = optional LM call (cheap by default, strong when justified)
      guardrails = API key check, bounded max_tokens, graceful fallback, usage log

    Usage:
        helper = LMHelper("custodian", "health_explain", max_tokens=200)
        result = helper.call(
            system="Explain health findings in plain English.",
            user=json.dumps(health_items),
        )
        if result.ok:
            explanation = result.content
        else:
            explanation = f"[LM unavailable: {result.error}]"

    Always safe to call — never raises, falls back gracefully when no API key is set.
    """

    def __init__(
        self,
        agent_name:   str,
        task:         str,
        max_tokens:   int   = 400,
        temperature:  float = 0.4,
        force_tier:   str | None = None,
    ) -> None:
        self.agent_name  = agent_name
        self.task        = task
        self.max_tokens  = max_tokens
        self.temperature = temperature
        self.force_tier  = force_tier

    def call(
        self,
        system:           str,
        user:             str,
        context:          dict[str, Any] | None = None,
        escalation_reason: str                  = "",
        json_mode:        bool                  = False,
    ) -> LMResult:
        """
        Route task, call LM if appropriate, log usage, return result.
        Never raises — all errors are returned as LMResult(ok=False, error=...).
        """
        decision = route(
            self.task,
            context           = context,
            force_tier        = self.force_tier,
            escalation_reason = escalation_reason,
        )

        if decision.tier == "deterministic":
            return LMResult(
                ok=False, content="", model_used="", tier_used="deterministic",
                reason=decision.reason,
                error="Task is deterministic — no LM call needed.",
                input_tokens=0, output_tokens=0, cost_usd=0.0,
            )

        api_key = _load_api_key()
        if not api_key:
            _log_usage(self.agent_name, self.task, decision, 0, 0, 0.0, ok=False, error="no_api_key")
            return LMResult(
                ok=False, content="", model_used=decision.model or "", tier_used=decision.tier,
                reason=decision.reason,
                error="OPENROUTER_API_KEY not set — LM layer unavailable.",
                input_tokens=0, output_tokens=0, cost_usd=0.0,
            )

        raw = _openrouter_call(
            model       = decision.model,
            system      = system,
            user        = user,
            max_tokens  = self.max_tokens,
            temperature = self.temperature,
            json_mode   = json_mode,
        )

        in_tok  = raw.get("input_tokens", 0)
        out_tok = raw.get("output_tokens", 0)
        cost    = _estimate_cost(decision.model, in_tok, out_tok)

        _log_usage(
            self.agent_name, self.task, decision,
            in_tok, out_tok, cost,
            ok    = "error" not in raw,
            error = raw.get("error", ""),
        )

        if "error" in raw:
            return LMResult(
                ok=False, content="", model_used=decision.model or "", tier_used=decision.tier,
                reason=decision.reason, error=raw["error"],
                input_tokens=in_tok, output_tokens=out_tok, cost_usd=cost,
            )

        return LMResult(
            ok=True, content=raw["content"], model_used=decision.model or "",
            tier_used=decision.tier, reason=decision.reason, error="",
            input_tokens=in_tok, output_tokens=out_tok, cost_usd=cost,
        )


# ── Usage summary ─────────────────────────────────────────────────────────────

def get_usage_summary(limit: int = 50) -> dict:
    """
    Return a summary of recent LM usage from the warden usage log.
    Reads the last `limit` entries from data/warden_usage.jsonl.
    """
    if not _USAGE_LOG.exists():
        return {
            "total_calls":    0,
            "total_cost_usd": 0.0,
            "tier_breakdown": {"cheap": 0, "strong": 0, "deterministic": 0},
            "escalation_rate_pct": 0.0,
            "recent":         [],
            "note":           "No LM calls recorded yet via LMHelper.",
        }

    try:
        lines = _USAGE_LOG.read_text(encoding="utf-8").splitlines()
    except Exception:
        return {"total_calls": 0, "total_cost_usd": 0.0, "recent": [], "error": "unreadable"}

    records: list[dict] = []
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except Exception:
            continue
        if len(records) >= limit:
            break

    total_cost = sum(r.get("cost_usd", 0.0) for r in records)
    tiers      = {"cheap": 0, "strong": 0, "deterministic": 0}
    escalated  = 0
    for r in records:
        t = r.get("tier", "cheap")
        tiers[t] = tiers.get(t, 0) + 1
        if r.get("escalated"):
            escalated += 1

    lm_calls   = tiers["cheap"] + tiers["strong"]
    esc_rate   = (escalated / lm_calls * 100.0) if lm_calls > 0 else 0.0

    return {
        "total_calls":         len(records),
        "total_cost_usd":      round(total_cost, 6),
        "tier_breakdown":      tiers,
        "escalation_rate_pct": round(esc_rate, 1),
        "recent":              records[:10],
    }


_POLICY_CACHE = _ROOT / "data" / "warden_policy.json"


def cache_policy() -> None:
    """
    Write the routing policy to data/warden_policy.json.
    Called on backend startup so Peter handlers can read it from disk
    without importing from app/ (transport isolation rule).
    """
    try:
        report = get_policy_report()
        _POLICY_CACHE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _POLICY_CACHE.with_suffix(".tmp")
        tmp.write_text(json.dumps(report, indent=2), encoding="utf-8")
        tmp.rename(_POLICY_CACHE)
    except Exception:
        pass


def get_policy_report() -> dict:
    """Return a structured summary of the routing policy for Peter and the UI."""
    cheap_spec  = MODEL_REGISTRY.get(CHEAP_MODEL)
    strong_spec = MODEL_REGISTRY.get(STRONG_MODEL)

    cheap_tasks  = [t for t, p in TASK_POLICY.items() if p.tier == "cheap"]
    strong_tasks = [t for t, p in TASK_POLICY.items() if p.tier == "strong"]
    det_tasks    = [t for t, p in TASK_POLICY.items() if p.tier == "deterministic"]

    return {
        "cheap_model":         CHEAP_MODEL,
        "strong_model":        STRONG_MODEL,
        "cheap_description":   cheap_spec.description  if cheap_spec  else "unknown",
        "strong_description":  strong_spec.description if strong_spec else "unknown",
        "cheap_cost_per_1m":   f"${cheap_spec.cost_per_1m_input:.2f}/${cheap_spec.cost_per_1m_output:.2f} (in/out)" if cheap_spec else "?",
        "strong_cost_per_1m":  f"${strong_spec.cost_per_1m_input:.2f}/${strong_spec.cost_per_1m_output:.2f} (in/out)" if strong_spec else "?",
        "task_counts": {
            "deterministic": len(det_tasks),
            "cheap":         len(cheap_tasks),
            "strong":        len(strong_tasks),
        },
        "cheap_tasks":         sorted(cheap_tasks),
        "strong_tasks":        sorted(strong_tasks),
        "deterministic_tasks": sorted(det_tasks),
        "escalation_reasons":  ESCALATION_REASONS,
        "env_overrides": {
            "CHEAP_MODEL":  os.getenv("CHEAP_MODEL",  "(default)"),
            "STRONG_MODEL": os.getenv("STRONG_MODEL", "(default)"),
        },
    }


def policy_summary_line() -> str:
    """One-line plain-English summary of the routing policy for Peter."""
    usage = get_usage_summary(limit=20)
    total = usage["total_calls"]
    cost  = usage["total_cost_usd"]
    esc   = usage["escalation_rate_pct"]
    cheap = usage["tier_breakdown"].get("cheap", 0)
    strong = usage["tier_breakdown"].get("strong", 0)

    if total == 0:
        return (
            f"Cheap default: {CHEAP_MODEL}. "
            f"Strong escalation: {STRONG_MODEL}. "
            f"No LM calls recorded via Cost Warden yet."
        )

    return (
        f"Cheap default: {CHEAP_MODEL} ({cheap} call(s)). "
        f"Strong escalation: {STRONG_MODEL} ({strong} call(s), {esc:.0f}% escalation rate). "
        f"Total cost: ${cost:.4f}."
    )


# ── Internal helpers ──────────────────────────────────────────────────────────

def _load_api_key() -> str:
    key = os.getenv("OPENROUTER_API_KEY", "")
    if key:
        return key
    if _API_ENV.exists():
        for line in _API_ENV.read_text().splitlines():
            if line.startswith("OPENROUTER_API_KEY="):
                return line.split("=", 1)[1].strip()
    return ""


def _openrouter_call(
    model:       str | None,
    system:      str,
    user:        str,
    max_tokens:  int,
    temperature: float,
    json_mode:   bool = False,
) -> dict:
    """
    Call OpenRouter. Returns {"content": str, "input_tokens": int, "output_tokens": int}
    on success, {"error": str} on failure. Never raises.
    """
    if not model:
        return {"error": "No model specified"}

    api_key = _load_api_key()
    if not api_key:
        return {"error": "OPENROUTER_API_KEY not set"}

    payload: dict = {
        "model":       model,
        "messages":    [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
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
            json    = payload,
            timeout = 25,
        )
        resp.raise_for_status()
        data    = resp.json()
        content = data["choices"][0]["message"]["content"].strip()
        usage   = data.get("usage", {})
        return {
            "content":       content,
            "input_tokens":  usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
        }
    except _http.exceptions.RequestException as exc:
        return {"error": f"OpenRouter request failed: {exc}"}
    except (KeyError, IndexError, ValueError) as exc:
        return {"error": f"Unexpected response shape: {exc}"}


def _estimate_cost(model: str | None, input_tokens: int, output_tokens: int) -> float:
    if not model:
        return 0.0
    spec = MODEL_REGISTRY.get(model)
    if not spec:
        return 0.0
    return (
        (input_tokens  / 1_000_000) * spec.cost_per_1m_input
        + (output_tokens / 1_000_000) * spec.cost_per_1m_output
    )


def _log_usage(
    agent:      str,
    task:       str,
    decision:   RoutingDecision,
    in_tokens:  int,
    out_tokens: int,
    cost_usd:   float,
    ok:         bool,
    error:      str = "",
) -> None:
    """Append one usage record to data/warden_usage.jsonl. Best-effort."""
    try:
        _USAGE_LOG.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp":        datetime.now(timezone.utc).isoformat(),
            "agent":            agent,
            "task":             task,
            "tier":             decision.tier,
            "model":            decision.model or "",
            "escalated":        decision.escalated,
            "escalation_reason": decision.escalation_reason,
            "input_tokens":     in_tokens,
            "output_tokens":    out_tokens,
            "cost_usd":         round(cost_usd, 8),
            "ok":               ok,
            "error":            error,
        }
        with _USAGE_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except Exception:
        pass
