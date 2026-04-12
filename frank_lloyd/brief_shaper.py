# frank_lloyd/brief_shaper.py
#
# Backstage LM-backed build brief shaper.
#
# Turns freeform operator intent into a structured build brief that
# frank_lloyd.request_writer can queue without additional clarification.
#
# shape(raw_input) tries LM first; falls back to deterministic_shape().
# deterministic_shape() handles the common case without any LM cost.
#
# Modes:
#   build      — new code, endpoint, module, feature, command
#   refactor   — restructure existing code without changing interface
#   cleanup    — remove stale UI, dead entries, confusing state
#   diagnose   — investigate why something doesn't work or feels wrong
#   improve    — make existing behavior better without interface change
#   monitor    — add logging, metrics, observability, health checks
#   docs       — documentation or comments only
#
# Public API:
#   shape(raw_input: str) → ShapedBrief
#   deterministic_shape(raw_input: str) → ShapedBrief

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

_SYSTEM_PROMPT = """\
You are a build brief writer for The Abode — an AI system workspace.
The operator is directing Frank Lloyd (the builder agent) to do something.

Classify the mode:
- build: adding new code, endpoint, module, feature, command
- refactor: restructuring or rewriting existing code without new behavior
- cleanup: removing stale UI, dead code, old entries, confusing state
- diagnose: investigating why something doesn't work or feels wrong
- improve: making existing behavior better, faster, clearer
- monitor: adding logging, metrics, observability, health checks
- docs: writing or updating documentation only

Extract or infer:
- description: what exactly should be done (1-3 sentences, specific)
- success_criterion: how to verify it worked (must be testable and concrete)

Rules:
- For diagnose: success_criterion = what the diagnosis should reveal or show
- For cleanup: success_criterion = what the UI/behavior looks like after cleanup
- For improve: success_criterion = what specifically improved and how to verify
- If the request is genuinely too vague (just "make it better", "fix stuff"): set needs_clarification=true
- Otherwise: produce description + success_criterion even if you infer them
- Keep description and success_criterion plain and specific — no jargon

Respond ONLY with JSON:
{
  "mode": "build|refactor|cleanup|diagnose|improve|monitor|docs",
  "description": "specific description of what to do",
  "success_criterion": "testable criterion — what confirms it worked",
  "needs_clarification": false,
  "clarification_question": ""
}
If needs_clarification is true: leave description/success_criterion as "" and put the clarifying question in clarification_question.
"""

_MODE_DEFAULT_CRITERIA = {
    "build":    "the new feature is accessible and returns expected output when called",
    "refactor": "the refactored code passes existing tests and behavior is unchanged",
    "cleanup":  "the cleaned-up state no longer shows the old behavior",
    "diagnose": "the diagnosis identifies the root cause with a clear explanation",
    "improve":  "the improved behavior is demonstrably better and verifiable",
    "monitor":  "the new monitoring surface is visible and reports accurate data",
    "docs":     "the documentation accurately describes the current system state",
}

_MODE_KEYWORDS = {
    "refactor":  ["refactor", "rewrite", "restructure", "reorganize", "rework"],
    "cleanup":   ["clean up", "cleanup", "stale", "old entries", "dead code", "remove"],
    "diagnose":  ["diagnose", "debug", "investigate", "figure out", "broken", "not working", "doesn't work", "weird", "disconnected"],
    "improve":   ["improve", "better", "faster", "cleaner", "nicer", "enhance", "strengthen"],
    "monitor":   ["monitor", "observ", "log", "metric", "telemetry", "health check", "visibility"],
    "docs":      ["docs", "documentation", "readme", "comment", "docstring"],
}

_VAGUE_ALONE = frozenset({"better", "nicer", "cleaner", "faster", "fix it", "fix stuff", "make it better"})


@dataclass
class ShapedBrief:
    mode: str
    description: str
    success_criterion: str
    needs_clarification: bool
    clarification_question: str
    lm_shaped: bool  # True = LM was used; False = deterministic fallback


def shape(raw_input: str) -> ShapedBrief:
    """
    Shape freeform operator input into a structured build brief.

    Tries LM (cheap tier) first. Falls back to deterministic_shape() on
    any LM failure. The LM can infer success criteria from context, classify
    mode, and ask one targeted clarifying question when genuinely needed.
    """
    raw_input = raw_input.strip()[:1500]
    if not raw_input:
        return ShapedBrief(
            mode="build", description="", success_criterion="",
            needs_clarification=True,
            clarification_question="What would you like Frank Lloyd to build or do?",
            lm_shaped=False,
        )

    try:
        from app.cost_warden import LMHelper
        import json as _json
        helper = LMHelper("frank_lloyd", "brief_shaper", max_tokens=350)
        result = helper.call(system=_SYSTEM_PROMPT, user=f"Operator request:\n{raw_input}")
        if result.ok:
            text = result.content.strip()
            if text.startswith("```"):
                text = "\n".join(text.split("\n")[1:])
                if text.endswith("```"):
                    text = text[:-3]
            parsed = _json.loads(text.strip())
            mode = parsed.get("mode", "build").strip()
            if mode not in _MODE_KEYWORDS and mode != "build":
                mode = "build"
            return ShapedBrief(
                mode=mode,
                description=(parsed.get("description") or "").strip(),
                success_criterion=(parsed.get("success_criterion") or "").strip(),
                needs_clarification=bool(parsed.get("needs_clarification", False)),
                clarification_question=(parsed.get("clarification_question") or "").strip(),
                lm_shaped=True,
            )
    except Exception:
        pass

    return deterministic_shape(raw_input)


def deterministic_shape(raw_input: str) -> ShapedBrief:
    """
    Regex-based fallback brief shaper. No LM cost.

    Classifies mode from keywords, extracts success criterion from markers
    if present, or synthesizes a generic one from mode.
    """
    raw_input = raw_input.strip()

    # Extract success criterion if explicitly provided
    success = _extract_success_criterion(raw_input)
    description = raw_input
    if success:
        for marker in ("success:", "success criterion:", "done when:", "test:", "verify:"):
            idx = raw_input.lower().find(marker)
            if idx != -1:
                description = raw_input[:idx].strip().rstrip(".,;")
                break

    lower = raw_input.lower()

    # Check if genuinely too vague
    words = description.split()
    if len(words) < 4:
        return ShapedBrief(
            mode="build", description="", success_criterion="",
            needs_clarification=True,
            clarification_question=(
                "Could you be more specific? A sentence or two about what "
                "Frank Lloyd should build, fix, or change would help."
            ),
            lm_shaped=False,
        )
    if description.lower().strip() in _VAGUE_ALONE:
        return ShapedBrief(
            mode="improve", description="", success_criterion="",
            needs_clarification=True,
            clarification_question=(
                "What specifically should be improved? Which file, panel, or behavior?"
            ),
            lm_shaped=False,
        )

    # Classify mode from keywords
    mode = "build"
    for candidate_mode, keywords in _MODE_KEYWORDS.items():
        if any(kw in lower for kw in keywords):
            mode = candidate_mode
            break

    # Synthesize success criterion if not provided
    if not success:
        success = _MODE_DEFAULT_CRITERIA.get(mode, "the change is complete and verifiable")

    return ShapedBrief(
        mode=mode,
        description=description,
        success_criterion=success,
        needs_clarification=False,
        clarification_question="",
        lm_shaped=False,
    )


def _extract_success_criterion(text: str) -> str:
    """Extract text following a success-criterion marker, or '' if none found."""
    lower = text.lower()
    for marker in ("success:", "success criterion:", "done when:", "test:", "verify:"):
        idx = lower.find(marker)
        if idx != -1:
            return text[idx + len(marker):].strip()
    return ""
