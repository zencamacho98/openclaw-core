# frank_lloyd/provider_router.py
#
# Provider-routing foundation for Frank Lloyd.
#
# Frank Lloyd's LM work is categorised into five task classes, each mapped to
# a provider tier. Claude is NOT the default — OpenRouter cheap-tier models
# handle spec drafting. Stronger lanes exist for Stage 2 code generation work
# but require explicit operator authorization before use.
#
# Provider tiers (in cost/capability order):
#
#   cheap            — OpenRouter default lane (FL_CHEAP_MODEL, default: openai/gpt-4o-mini)
#                      provider_family=openrouter, transport_mode=api, executability=executable
#                      Stage 1 spec drafting, Stage 2 low-risk isolated code.
#                      No operator approval gate.
#
#   coding           — OpenRouter coding lane (FL_CODING_MODEL, default: openai/gpt-4o)
#                      provider_family=openrouter, transport_mode=api, executability=config_only
#                      Stage 2 medium-risk code (integration required). Approval gated.
#
#   codex_supervised — Codex supervised lane (FL_CODEX_MODEL, default: "codex")
#                      provider_family=codex, transport_mode=supervised_external,
#                      executability=external_supervised
#                      Stage 2 critical-file / architecture-sensitive code.
#                      NOT callable via API — requires Codex CLI or supervised tooling.
#                      FLLMHelper.call() returns ok=False immediately for this tier.
#                      Approval gated.
#
#   strong           — Claude explicit escalation (FL_STRONG_MODEL, default: claude-sonnet-4-6)
#                      provider_family=claude, transport_mode=api, executability=executable
#                      NOT in any default task policy — only reachable via risk_override.
#                      Operator authorization mandatory before use.
#
#   critical_only    — Claude proof/architecture (FL_CRITICAL_MODEL, default: claude-opus-4-6)
#                      provider_family=claude, transport_mode=api, executability=executable
#                      Final review, proof, architecture escalation. Rarest, most expensive.
#                      Operator mandatory; never called automatically.
#
# Executability classification:
#   executable          — callable via OpenRouter API right now
#   config_only         — model configured but not yet validated in Stage 2 production use
#   external_supervised — requires Codex CLI or other external tooling; not an API call
#
# What is real vs config-only vs external-supervised in this pass:
#   EXECUTABLE NOW  — cheap lane (spec_draft actively used by spec_writer)
#   CONFIG_ONLY     — openrouter coding lane (policy + model set, no Stage 2 calls yet)
#   EXTERNAL_SUPERVISED — codex_supervised (policy complete, Codex CLI not yet integrated)
#   EXPLICIT_ONLY   — strong (Claude sonnet; not in default policy, available via risk_override)
#   EXPLICIT_ONLY   — critical_only (Claude opus; review_proof default; approval mandatory)
#
# Claude constraint rule:
#   Claude is NOT the silent default for any code generation task.
#   - code_draft_critical → codex_supervised (not Claude)
#   - review_proof        → critical_only (Claude, but explicitly marked, approval mandatory)
#   - strong tier         → available only via explicit risk_override (not in task policy)
#
# Design rules:
#   - Claude is not the default for critical code work.
#   - Codex is first-class even when external_supervised (not pretending it's an API).
#   - operator_approval_required=True tiers must not be called without operator sign-off.
#   - Stage restrictions are enforced: fl_route() returns stage_allowed=False if violated.
#   - FLLMHelper refuses external_supervised lanes with a clear error — no fake calls.
#   - FLLMHelper delegates executable API calls to app.cost_warden.LMHelper.
#   - Risk override only upgrades tier, never downgrades.
#
# Public API:
#   FLTaskClass                                         — task class enum
#   FLProviderTier                                      — provider tier enum
#   FLProviderConfig                                    — per-tier config dataclass
#   FLTaskPolicy                                        — per-class policy dataclass
#   FLRoutingDecision                                   — routing result dataclass
#   FL_PROVIDER_REGISTRY: dict[FLProviderTier, FLProviderConfig]
#   FL_TASK_POLICY:       dict[FLTaskClass,    FLTaskPolicy]
#   fl_route(task_class, stage, risk_override)          → FLRoutingDecision
#   FLLMHelper(task_class, max_tokens, temperature)
#     .call(system, user, stage, risk_override, json_mode) → LMResult
#     .routing_decision(stage, risk_override)              → FLRoutingDecision
#   get_fl_policy_report()                              → dict

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from typing import Optional


# ── Task classes ──────────────────────────────────────────────────────────────

class FLTaskClass(str, Enum):
    """
    Frank Lloyd task classes, ordered by expected cost and risk.

    Stage 1: spec_draft only.
    Stage 2: all code_draft_* and review_proof (not yet implemented — policy complete).
    """
    SPEC_DRAFT           = "spec_draft"           # Stage 1 — doc/spec generation
    CODE_DRAFT_LOW       = "code_draft_low"       # Stage 2 — new isolated file, no integration
    CODE_DRAFT_MEDIUM    = "code_draft_medium"    # Stage 2 — new file requiring integration
    CODE_DRAFT_CRITICAL  = "code_draft_critical"  # Stage 2 — critical-file / architecture-sensitive
    REVIEW_PROOF         = "review_proof"         # Stage 2 — final review / proof / escalation


# ── Provider tiers ────────────────────────────────────────────────────────────

class FLProviderTier(str, Enum):
    """
    Provider tier labels for Frank Lloyd routing (ordered by capability/cost).

    cheap            — OpenRouter default (executable now)
    coding           — OpenRouter coding lane (config_only — model set, no Stage 2 calls yet)
    codex_supervised — Codex supervised lane (external_supervised — not an API call)
    strong           — Claude API escalation (explicit-only — not in default task policy)
    critical_only    — Claude proof/architecture (explicit, approval-mandatory)
    """
    CHEAP            = "cheap"             # OpenRouter default lane
    CODING           = "coding"            # OpenRouter coding lane
    CODEX_SUPERVISED = "codex_supervised"  # Codex supervised lane (external)
    STRONG           = "strong"            # Claude escalation (explicit-only, not default policy)
    CRITICAL         = "critical_only"     # Claude final-proof lane (operator-mandatory)


# ── Env-overridable model IDs ─────────────────────────────────────────────────

FL_CHEAP_MODEL    = os.getenv("FL_CHEAP_MODEL",    "openai/gpt-4o-mini")
FL_CODING_MODEL   = os.getenv("FL_CODING_MODEL",   "openai/gpt-4o")
# FL_CODEX_MODEL is a logical identifier for the Codex supervised lane.
# It is not passed to any API — this lane uses supervised_external transport.
# When Codex CLI integration is built, this label will identify the model used there.
FL_CODEX_MODEL    = os.getenv("FL_CODEX_MODEL",    "codex")
FL_STRONG_MODEL   = os.getenv("FL_STRONG_MODEL",   "anthropic/claude-sonnet-4-6")
FL_CRITICAL_MODEL = os.getenv("FL_CRITICAL_MODEL", "anthropic/claude-opus-4-6")


# ── Provider config registry ──────────────────────────────────────────────────

@dataclass(frozen=True)
class FLProviderConfig:
    """Per-tier provider configuration for Frank Lloyd."""
    tier:                       FLProviderTier
    model:                      str    # model ID (API model or logical label for external lanes)
    provider_family:            str    # "openrouter" | "codex" | "claude"
    transport_mode:             str    # "api" | "supervised_external"
    executability:              str    # "executable" | "config_only" | "external_supervised"
    description:                str    # when this tier is appropriate
    cost_per_1m_input:          float  # USD per 1M input tokens (0.0 for external lanes)
    cost_per_1m_output:         float  # USD per 1M output tokens (0.0 for external lanes)
    operator_approval_required: bool   # must operator authorize before this tier is used?


FL_PROVIDER_REGISTRY: dict[FLProviderTier, FLProviderConfig] = {
    FLProviderTier.CHEAP: FLProviderConfig(
        tier                       = FLProviderTier.CHEAP,
        model                      = FL_CHEAP_MODEL,
        provider_family            = "openrouter",
        transport_mode             = "api",
        executability              = "executable",
        description                = (
            "OpenRouter default lane. Stage 1 spec drafting and Stage 2 low-risk isolated "
            "code. Executable now. No operator approval gate — the deterministic validator "
            "and spec review are the safety nets."
        ),
        cost_per_1m_input          = 0.15,
        cost_per_1m_output         = 0.60,
        operator_approval_required = False,
    ),
    FLProviderTier.CODING: FLProviderConfig(
        tier                       = FLProviderTier.CODING,
        model                      = FL_CODING_MODEL,
        provider_family            = "openrouter",
        transport_mode             = "api",
        executability              = "config_only",
        description                = (
            "OpenRouter coding lane. Stage 2 medium-risk code requiring route registration "
            "or integration. Stronger than cheap, not Claude. Policy and model configured; "
            "no Stage 2 calls made yet. Operator approval gated."
        ),
        cost_per_1m_input          = 5.00,
        cost_per_1m_output         = 15.00,
        operator_approval_required = True,
    ),
    FLProviderTier.CODEX_SUPERVISED: FLProviderConfig(
        tier                       = FLProviderTier.CODEX_SUPERVISED,
        model                      = FL_CODEX_MODEL,
        provider_family            = "codex",
        transport_mode             = "supervised_external",
        executability              = "external_supervised",
        description                = (
            "Codex supervised lane. Stage 2 critical-file or architecture-sensitive code. "
            "NOT callable via API — requires Codex CLI or supervised external tooling. "
            "FLLMHelper refuses API calls for this tier and returns a clear error. "
            "Operator must explicitly authorize before supervised execution begins."
        ),
        cost_per_1m_input          = 0.0,   # external — no token billing via our API
        cost_per_1m_output         = 0.0,
        operator_approval_required = True,
    ),
    FLProviderTier.STRONG: FLProviderConfig(
        tier                       = FLProviderTier.STRONG,
        model                      = FL_STRONG_MODEL,
        provider_family            = "claude",
        transport_mode             = "api",
        executability              = "executable",
        description                = (
            "Claude explicit escalation lane. NOT in any default task policy. "
            "Reachable only via risk_override for cases where Codex is insufficient. "
            "Operator must explicitly authorize. Prefer codex_supervised for critical code."
        ),
        cost_per_1m_input          = 3.00,
        cost_per_1m_output         = 15.00,
        operator_approval_required = True,
    ),
    FLProviderTier.CRITICAL: FLProviderConfig(
        tier                       = FLProviderTier.CRITICAL,
        model                      = FL_CRITICAL_MODEL,
        provider_family            = "claude",
        transport_mode             = "api",
        executability              = "executable",
        description                = (
            "Claude proof/architecture lane. Final review, proof, or architecture escalation. "
            "Most expensive. Operator mandatory — never called automatically. "
            "Default for review_proof task class."
        ),
        cost_per_1m_input          = 15.00,
        cost_per_1m_output         = 75.00,
        operator_approval_required = True,
    ),
}


# ── Task policy ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class FLTaskPolicy:
    """Routing policy for a single Frank Lloyd task class."""
    provider_tier:              FLProviderTier
    stages_allowed:             tuple[int, ...]  # which build stages may use this class
    operator_approval_required: bool             # inherited from provider tier
    description:                str              # policy rationale


FL_TASK_POLICY: dict[FLTaskClass, FLTaskPolicy] = {
    FLTaskClass.SPEC_DRAFT: FLTaskPolicy(
        provider_tier              = FLProviderTier.CHEAP,
        stages_allowed             = (1,),
        operator_approval_required = False,
        description = (
            "Stage 1 spec drafting — cheap OpenRouter model is sufficient because "
            "the deterministic validator corrects doctrine violations and the operator "
            "reviews and approves the spec before any code is written. "
            "Stage 2 code generation uses stronger tiers."
        ),
    ),
    FLTaskClass.CODE_DRAFT_LOW: FLTaskPolicy(
        provider_tier              = FLProviderTier.CHEAP,
        stages_allowed             = (2,),
        operator_approval_required = False,
        description = (
            "Stage 2 low-risk code — new isolated file with no integration requirements "
            "(no route registration, no existing file modifications). "
            "Cheap OpenRouter model acceptable; operator reviews output."
        ),
    ),
    FLTaskClass.CODE_DRAFT_MEDIUM: FLTaskPolicy(
        provider_tier              = FLProviderTier.CODING,
        stages_allowed             = (2,),
        operator_approval_required = True,
        description = (
            "Stage 2 medium-risk code — new file requiring route registration or "
            "integration with existing components. Uses the supervised coding lane "
            "(openrouter non-Claude model). Operator must authorize escalation to this tier."
        ),
    ),
    FLTaskClass.CODE_DRAFT_CRITICAL: FLTaskPolicy(
        provider_tier              = FLProviderTier.CODEX_SUPERVISED,
        stages_allowed             = (2,),
        operator_approval_required = True,
        description = (
            "Stage 2 critical/architecture-sensitive code — existing-file modifications "
            "or proximity to off-limits files. Routed to Codex supervised lane — "
            "not Claude. FLLMHelper will refuse to make an API call for this tier; "
            "requires Codex CLI or supervised external tooling. "
            "Operator must explicitly authorize before supervised execution begins."
        ),
    ),
    FLTaskClass.REVIEW_PROOF: FLTaskPolicy(
        provider_tier              = FLProviderTier.CRITICAL,
        stages_allowed             = (2,),
        operator_approval_required = True,
        description = (
            "Final review, proof, or architecture escalation. Claude Opus only. "
            "Most expensive lane — escalate only when the strong lane is insufficient. "
            "Operator mandatory; never called automatically."
        ),
    ),
}


# ── Routing decision ──────────────────────────────────────────────────────────

@dataclass
class FLRoutingDecision:
    """
    Result of fl_route(). Contains everything needed to proceed with an LM call.

    Callers should check:
      - decision.stage_allowed      — False means this task class is not permitted at this stage
      - decision.operator_approval_required — True means operator must sign off before calling
      - decision.executability      — "external_supervised" means FLLMHelper.call() will refuse
      - decision.error              — non-empty on routing failure
    """
    task_class:                 FLTaskClass
    provider_tier:              FLProviderTier
    provider_family:            str    # "openrouter" | "codex" | "claude"
    transport_mode:             str    # "api" | "supervised_external"
    executability:              str    # "executable" | "config_only" | "external_supervised"
    model:                      str
    stage_allowed:              bool
    operator_approval_required: bool
    description:                str
    error:                      str  # "" on success


def fl_route(
    task_class:    FLTaskClass,
    stage:         int,
    risk_override: Optional[FLProviderTier] = None,
) -> FLRoutingDecision:
    """
    Determine provider tier and model for a Frank Lloyd task.

    Args:
        task_class:    the kind of LM work Frank Lloyd is about to do
        stage:         which build stage (1 or 2) is making this request
        risk_override: force a higher tier than the policy default (never downgrades)

    Returns:
        FLRoutingDecision — always returns, never raises.
    """
    policy = FL_TASK_POLICY[task_class]

    # Stage restriction
    blocked_provider = FL_PROVIDER_REGISTRY[policy.provider_tier]
    if stage not in policy.stages_allowed:
        return FLRoutingDecision(
            task_class                 = task_class,
            provider_tier              = policy.provider_tier,
            provider_family            = blocked_provider.provider_family,
            transport_mode             = blocked_provider.transport_mode,
            executability              = blocked_provider.executability,
            model                      = "",
            stage_allowed              = False,
            operator_approval_required = policy.operator_approval_required,
            description                = policy.description,
            error = (
                f"{task_class.value} is only allowed at Stage(s) "
                f"{list(policy.stages_allowed)} — called from Stage {stage}."
            ),
        )

    # Apply risk override — upgrades only, never downgrades
    tier = policy.provider_tier
    if risk_override is not None and _tier_rank(risk_override) > _tier_rank(tier):
        tier = risk_override

    provider = FL_PROVIDER_REGISTRY[tier]

    return FLRoutingDecision(
        task_class                 = task_class,
        provider_tier              = tier,
        provider_family            = provider.provider_family,
        transport_mode             = provider.transport_mode,
        executability              = provider.executability,
        model                      = provider.model,
        stage_allowed              = True,
        operator_approval_required = provider.operator_approval_required,
        description                = policy.description,
        error                      = "",
    )


def _tier_rank(tier: FLProviderTier) -> int:
    """Higher rank = more expensive / capable."""
    return {
        FLProviderTier.CHEAP:            0,
        FLProviderTier.CODING:           1,
        FLProviderTier.CODEX_SUPERVISED: 2,
        FLProviderTier.STRONG:           3,
        FLProviderTier.CRITICAL:         4,
    }.get(tier, 0)


# ── FLLMHelper ────────────────────────────────────────────────────────────────

class FLLMHelper:
    """
    Frank Lloyd LM call interface.

    Wraps app.cost_warden.LMHelper with Frank Lloyd-specific routing:
      - Routes task class → provider tier → specific model via fl_route()
      - Enforces stage restrictions (returns ok=False when stage not allowed)
      - Surfaces operator_approval_required in routing_decision() for callers to check
      - Delegates actual HTTP calls and usage logging to the shared LMHelper infra
      - Falls back gracefully if LM or API key unavailable

    Usage:
        helper = FLLMHelper(FLTaskClass.SPEC_DRAFT, max_tokens=700)
        # Optional: pre-check routing without calling the LM
        decision = helper.routing_decision(stage=1)
        if decision.operator_approval_required:
            # Check that operator has authorized this tier
            ...
        result = helper.call(system=PROMPT, user=user_msg, stage=1)
        if result.ok:
            content = result.content
        else:
            content = f"[LM unavailable: {result.error}]"
    """

    def __init__(
        self,
        task_class:  FLTaskClass,
        max_tokens:  int   = 500,
        temperature: float = 0.4,
    ) -> None:
        self.task_class  = task_class
        self.max_tokens  = max_tokens
        self.temperature = temperature

    def routing_decision(
        self,
        stage:         int,
        risk_override: Optional[FLProviderTier] = None,
    ) -> FLRoutingDecision:
        """Return the routing decision without making any LM call."""
        return fl_route(self.task_class, stage, risk_override)

    def call(
        self,
        system:        str,
        user:          str,
        stage:         int,
        risk_override: Optional[FLProviderTier] = None,
        json_mode:     bool = False,
    ) -> "LMResult":  # noqa: F821
        """
        Route and execute an LM call for Frank Lloyd.

        Returns LMResult (from app.cost_warden):
          ok=True  — content contains the LM response
          ok=False — error describes the failure (stage restriction, missing key, LM error)

        Never raises.
        """
        try:
            from app.cost_warden import LMHelper, LMResult as _LMResult
        except ImportError as exc:
            # If cost_warden is unavailable at import time, construct a minimal error
            # We can't use LMResult dataclass — return a namespace object instead.
            class _FallbackResult:  # type: ignore[name-defined]
                ok = False; content = ""; model_used = ""; tier_used = ""
                reason = ""; input_tokens = 0; output_tokens = 0; cost_usd = 0.0
                error = f"cost_warden unavailable: {exc}"
            return _FallbackResult()  # type: ignore[return-value]

        decision = fl_route(self.task_class, stage, risk_override)

        if not decision.stage_allowed:
            return _LMResult(
                ok            = False,
                content       = "",
                model_used    = "",
                tier_used     = decision.provider_tier.value,
                reason        = decision.description,
                error         = decision.error,
                input_tokens  = 0,
                output_tokens = 0,
                cost_usd      = 0.0,
            )

        # Refuse external_supervised lanes — not callable via API
        if decision.executability == "external_supervised":
            return _LMResult(
                ok            = False,
                content       = "",
                model_used    = "",
                tier_used     = decision.provider_tier.value,
                reason        = decision.description,
                error         = (
                    f"{decision.provider_tier.value} lane is external_supervised — "
                    f"requires Codex CLI or supervised tooling, not callable via API. "
                    f"Model: {decision.model}."
                ),
                input_tokens  = 0,
                output_tokens = 0,
                cost_usd      = 0.0,
            )

        # Map FL tier to warden tier (cheap → "cheap"; coding/strong/critical → "strong")
        # The specific model is injected via model_override, bypassing CHEAP/STRONG_MODEL globals.
        warden_tier = (
            "cheap"
            if decision.provider_tier == FLProviderTier.CHEAP
            else "strong"
        )

        helper = LMHelper(
            agent_name     = "frank_lloyd",
            task           = self.task_class.value,
            max_tokens     = self.max_tokens,
            temperature    = self.temperature,
            force_tier     = warden_tier,
            model_override = decision.model,
        )
        return helper.call(system=system, user=user, json_mode=json_mode)


# ── Policy report ─────────────────────────────────────────────────────────────

def get_fl_policy_report() -> dict:
    """
    Return a structured summary of Frank Lloyd's provider-routing policy.

    Suitable for logging, operator status display, and testing.
    """
    providers = {
        tier.value: {
            "model":                       cfg.model,
            "provider_family":             cfg.provider_family,
            "transport_mode":              cfg.transport_mode,
            "executability":               cfg.executability,
            "description":                 cfg.description,
            "cost_per_1m_input":           cfg.cost_per_1m_input,
            "cost_per_1m_output":          cfg.cost_per_1m_output,
            "operator_approval_required":  cfg.operator_approval_required,
        }
        for tier, cfg in FL_PROVIDER_REGISTRY.items()
    }
    tasks = {
        tc.value: {
            "provider_tier":               p.provider_tier.value,
            "model":                       FL_PROVIDER_REGISTRY[p.provider_tier].model,
            "provider_family":             FL_PROVIDER_REGISTRY[p.provider_tier].provider_family,
            "transport_mode":              FL_PROVIDER_REGISTRY[p.provider_tier].transport_mode,
            "executability":               FL_PROVIDER_REGISTRY[p.provider_tier].executability,
            "stages_allowed":              list(p.stages_allowed),
            "operator_approval_required":  p.operator_approval_required,
            "description":                 p.description,
        }
        for tc, p in FL_TASK_POLICY.items()
    }
    return {
        "provider_registry":  providers,
        "task_policy":        tasks,
        "active_lanes": {
            "cheap":    FL_CHEAP_MODEL,
            "coding":   FL_CODING_MODEL,
            "codex":    FL_CODEX_MODEL,
            "strong":   FL_STRONG_MODEL,
            "critical": FL_CRITICAL_MODEL,
        },
        "env_overrides": {
            "FL_CHEAP_MODEL":    os.getenv("FL_CHEAP_MODEL",    "(default)"),
            "FL_CODING_MODEL":   os.getenv("FL_CODING_MODEL",   "(default)"),
            "FL_CODEX_MODEL":    os.getenv("FL_CODEX_MODEL",    "(default)"),
            "FL_STRONG_MODEL":   os.getenv("FL_STRONG_MODEL",   "(default)"),
            "FL_CRITICAL_MODEL": os.getenv("FL_CRITICAL_MODEL", "(default)"),
        },
        "stage_1_active_tasks":  [tc.value for tc, p in FL_TASK_POLICY.items() if 1 in p.stages_allowed],
        "stage_2_ready_tasks":   [tc.value for tc, p in FL_TASK_POLICY.items() if 2 in p.stages_allowed],
    }
