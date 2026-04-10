# observability/telemetry.py
#
# Token and cost telemetry for agent operations.
#
# Records are appended to data/telemetry/{scope_id}_telemetry.jsonl.
# One JSONL file per campaign (scope_id = campaign_id) aggregates all batch
# costs within that campaign.
#
# IMPORTANT — Cost labeling policy:
#   All cost figures in this layer are ESTIMATED based on published model
#   pricing and are labeled is_estimated=True until OpenRouter live billing
#   data is wired in. Simulation batches (in-process Python) cost $0 in
#   API fees — those records are explicitly recorded with 0 tokens and
#   provider="simulation". The structure is ready for live wiring.
#
# Public API:
#   record_event(agent_name, *, scope, scope_id, ...) → TelemetryEvent
#   load_events(scope_id) → list[TelemetryEvent]
#   summarize(scope_id) → TelemetrySummary | None

from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional

_ROOT         = pathlib.Path(__file__).resolve().parent.parent
TELEMETRY_DIR = _ROOT / "data" / "telemetry"

# Published pricing (USD per 1M tokens) for known models.
# Update these constants when prices change — do not bury them in formulas.
_COST_PER_1M_TOKENS: dict[str, dict[str, float]] = {
    # Anthropic models
    "anthropic/claude-opus-4-6":           {"input": 15.0,  "output": 75.0},
    "anthropic/claude-sonnet-4-6":         {"input": 3.0,   "output": 15.0},
    "anthropic/claude-3.5-sonnet":         {"input": 3.0,   "output": 15.0},
    "anthropic/claude-haiku-4-5-20251001": {"input": 0.25,  "output": 1.25},
    "anthropic/claude-haiku-4-5":          {"input": 0.25,  "output": 1.25},
    # OpenAI models (via OpenRouter)
    "openai/gpt-4o-mini":                  {"input": 0.15,  "output": 0.60},
    "openai/gpt-4o":                       {"input": 2.50,  "output": 10.0},
    # Non-billable providers
    "simulation":                           {"input": 0.0,   "output": 0.0},
    "placeholder":                          {"input": 0.0,   "output": 0.0},
}


@dataclass
class TelemetryEvent:
    timestamp:          str
    agent_name:         str
    provider:           str             # "openrouter" | "simulation" | "placeholder"
    model:              str             # model slug or "simulation"
    scope:              str             # "request" | "batch" | "session" | "campaign"
    scope_id:           str             # batch_id, session_id, or campaign_id
    input_tokens:       int
    output_tokens:      int
    total_tokens:       int
    request_count:      int
    estimated_cost_usd: float
    is_estimated:       bool            # True until live billing data is wired in


@dataclass
class TelemetrySummary:
    scope_id:           str
    agent_name:         str
    event_count:        int
    request_count:      int
    input_tokens:       int
    output_tokens:      int
    total_tokens:       int
    estimated_cost_usd: float
    is_estimated:       bool            # True if any event is estimated


# ── Cost estimation ───────────────────────────────────────────────────────────

def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """
    Estimate cost in USD using published model pricing.
    Returns 0.0 for unknown models — label as is_estimated=True.
    """
    rates = _COST_PER_1M_TOKENS.get(model, {"input": 0.0, "output": 0.0})
    return (input_tokens * rates["input"] + output_tokens * rates["output"]) / 1_000_000


# ── Recording ─────────────────────────────────────────────────────────────────

def record_event(
    agent_name:     str,
    *,
    scope:          str,
    scope_id:       str,
    provider:       str = "placeholder",
    model:          str = "placeholder",
    input_tokens:   int = 0,
    output_tokens:  int = 0,
    request_count:  int = 1,
    is_estimated:   bool = True,
) -> TelemetryEvent:
    """
    Record one telemetry event and append it to the scope's JSONL file.

    For in-process simulation batches: provider="simulation", model="simulation",
    all token counts are 0 (no API calls made). is_estimated=True.

    For real OpenRouter calls: pass actual token counts and set is_estimated=False
    once live billing data is confirmed.
    """
    total = input_tokens + output_tokens
    cost  = estimate_cost_usd(model, input_tokens, output_tokens)

    event = TelemetryEvent(
        timestamp          = _now(),
        agent_name         = agent_name,
        provider           = provider,
        model              = model,
        scope              = scope,
        scope_id           = scope_id,
        input_tokens       = input_tokens,
        output_tokens      = output_tokens,
        total_tokens       = total,
        request_count      = request_count,
        estimated_cost_usd = cost,
        is_estimated       = is_estimated,
    )

    _append(scope_id, event)
    return event


def _append(scope_id: str, event: TelemetryEvent) -> None:
    TELEMETRY_DIR.mkdir(parents=True, exist_ok=True)
    path = TELEMETRY_DIR / f"{scope_id}_telemetry.jsonl"
    with path.open("a") as f:
        f.write(json.dumps(asdict(event)) + "\n")


# ── Reading ───────────────────────────────────────────────────────────────────

def load_events(scope_id: str) -> list[TelemetryEvent]:
    """Load all telemetry events for a scope, oldest first."""
    path = TELEMETRY_DIR / f"{scope_id}_telemetry.jsonl"
    if not path.exists():
        return []
    events = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(TelemetryEvent(**json.loads(line)))
        except Exception:
            pass
    return events


def summarize(scope_id: str) -> Optional[TelemetrySummary]:
    """
    Aggregate all telemetry events for a scope into a summary.
    Returns None if no events have been recorded for this scope.
    """
    events = load_events(scope_id)
    if not events:
        return None

    return TelemetrySummary(
        scope_id           = scope_id,
        agent_name         = events[0].agent_name,
        event_count        = len(events),
        request_count      = sum(e.request_count      for e in events),
        input_tokens       = sum(e.input_tokens        for e in events),
        output_tokens      = sum(e.output_tokens       for e in events),
        total_tokens       = sum(e.total_tokens        for e in events),
        estimated_cost_usd = sum(e.estimated_cost_usd  for e in events),
        is_estimated       = any(e.is_estimated        for e in events),
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
