# app/proposal_parser.py
#
# Rule-based parser. Converts the most common recommendation text from the
# pattern aggregator into a structured parameter proposal.
#
# Deterministic: same input → same output. No LLM call required.
# Returns None if no known pattern matches — never invents a proposal.
# Never writes anything. Never applies changes.

import re
from app.strategy.config import get_config

STRATEGY_NAME = "MA Crossover"

# Each rule covers one known tunable parameter.
# keywords   — phrases that trigger this rule
# increases  — words indicating the value should go up
# decreases  — words indicating the value should go down
# delta_up   — delta when increasing and no explicit target found
# delta_down — delta when decreasing (negative) and no explicit target found
# is_float   — True for ratio/percentage parameters (STOP_LOSS_PCT, POSITION_SIZE)
# reason_*   — human-readable reason returned in the proposal
_RULES = [
    {
        "keywords": [
            "short ma", "short window", "short_window",
            "short moving average", "short-term ma",
        ],
        "increases": ["increase", "widen", "larger", "raise", "extend", "higher", "expand"],
        "decreases": ["decrease", "reduce", "lower", "smaller", "shrink", "tighten"],
        "parameter":   "SHORT_WINDOW",
        "delta_up":    2,
        "delta_down":  -1,
        "is_float":    False,
        "reason_up":   "reduce sensitivity to short-term price noise",
        "reason_down": "increase responsiveness to recent price movements",
    },
    {
        "keywords": [
            "long ma", "long window", "long_window",
            "long moving average", "long-term ma",
        ],
        "increases": ["increase", "widen", "larger", "raise", "extend", "higher", "expand"],
        "decreases": ["decrease", "reduce", "lower", "smaller", "shrink", "tighten"],
        "parameter":   "LONG_WINDOW",
        "delta_up":    3,
        "delta_down":  -2,
        "is_float":    False,
        "reason_up":   "capture longer-term trend more accurately",
        "reason_down": "increase responsiveness to trend direction changes",
    },
    {
        "keywords": [
            "stop loss", "stop-loss", "stoploss", "stop_loss_pct", "limit downside",
            "downside protection", "loss limit",
        ],
        "increases": ["raise", "increase", "widen", "higher", "larger", "loosen"],
        "decreases": ["reduce", "lower", "tighten", "smaller", "decrease", "tighter", "stricter"],
        "parameter":   "STOP_LOSS_PCT",
        "delta_up":    0.005,
        "delta_down":  -0.005,
        "is_float":    True,
        "reason_up":   "allow more price movement before cutting a losing position",
        "reason_down": "tighten downside protection to cut losses sooner",
    },
    {
        "keywords": [
            "position size", "position sizing", "position_size",
            "reduce exposure", "trade size", "allocation",
        ],
        "increases": ["increase", "larger", "raise", "bigger", "higher", "expand", "more"],
        "decreases": ["reduce", "lower", "smaller", "decrease", "tighten", "less", "cut"],
        "parameter":   "POSITION_SIZE",
        "delta_up":    0.05,
        "delta_down":  -0.05,
        "is_float":    True,
        "reason_up":   "deploy more capital per trade for larger returns",
        "reason_down": "reduce per-trade exposure to limit risk",
    },
]

# Hard bounds per parameter — mirrors BOUNDS in applier.py
_BOUNDS = {
    "SHORT_WINDOW":  (2,     30),
    "LONG_WINDOW":   (4,     60),
    "STOP_LOSS_PCT": (0.005, 0.1),
    "POSITION_SIZE": (0.01,  0.5),
}


def _extract_explicit_target(text: str, is_float: bool = False):
    """
    Find an explicit numeric target in text.

    Handles:
      "to 5"       → 5  (int)
      "to 0.015"   → 0.015
      "to 1.5%"    → 0.015  (normalised from %)
    """
    # Percentage form: "to 1.5%"
    pct_match = re.search(r"\bto\s+([\d]*\.[\d]+|\d+)\s*%", text)
    if pct_match:
        return round(float(pct_match.group(1)) / 100, 6)

    # Plain numeric: "to 0.015" or "to 5"
    match = re.search(r"\bto\s+([\d]*\.[\d]+|\d+)\b", text)
    if not match:
        return None
    raw = match.group(1)
    if "." in raw or is_float:
        return float(raw)
    return int(raw)


def _derive_confidence(occurrence_ratio: float, confidence_trend: str) -> str:
    """Map occurrence ratio + trend to a single confidence label."""
    if occurrence_ratio >= 0.6 and confidence_trend in ("increasing", "stable"):
        return "high"
    if occurrence_ratio >= 0.3 and confidence_trend != "decreasing":
        return "medium"
    return "low"


def _clamp(value, parameter: str):
    """Enforce safe bounds per parameter so proposals are always valid."""
    cfg = get_config()
    if parameter == "SHORT_WINDOW":
        return max(2, min(int(value), cfg["LONG_WINDOW"] - 1))
    if parameter == "LONG_WINDOW":
        return max(cfg["SHORT_WINDOW"] + 2, min(int(value), 60))
    if parameter in _BOUNDS:
        lo, hi = _BOUNDS[parameter]
        return max(lo, min(float(value), hi))
    return value


def parse(
    recommendation: str,
    confidence_trend: str,
    occurrences: int,
    records_analyzed: int,
) -> dict | None:
    """
    Try to match `recommendation` against known parameter rules.

    Returns a structured proposal dict, or None if no rule matches.
    The caller decides what to do with the proposal — this function only reads.
    """
    if not recommendation or not records_analyzed:
        return None

    text = recommendation.lower()
    occurrence_ratio = occurrences / records_analyzed

    for rule in _RULES:
        # Step 1: does this recommendation mention the parameter at all?
        if not any(kw in text for kw in rule["keywords"]):
            continue

        # Step 2: which direction?
        going_up = any(w in text for w in rule["increases"])
        going_down = any(w in text for w in rule["decreases"])

        parameter = rule["parameter"]
        is_float = rule["is_float"]
        cfg = get_config()
        current = cfg[parameter]
        explicit = _extract_explicit_target(text, is_float=is_float)

        if going_up == going_down:
            # No direction word — try to infer from explicit target vs current
            if explicit is None:
                continue  # truly ambiguous
            if explicit > current:
                going_up = True
            elif explicit < current:
                going_down = True
            else:
                continue  # target equals current — nothing to do

        # Step 3: determine proposed value

        if going_up:
            raw_proposed = explicit if explicit is not None else current + rule["delta_up"]
            reason = rule["reason_up"]
        else:
            raw_proposed = explicit if explicit is not None else current + rule["delta_down"]
            reason = rule["reason_down"]

        proposed = _clamp(raw_proposed, parameter)

        if proposed == current:
            continue  # clamping collapsed the change — no real delta, skip

        # Round floats cleanly for display
        if is_float:
            proposed = round(proposed, 4)
            current = round(current, 4)

        return {
            "strategy_name":          STRATEGY_NAME,
            "parameter":              parameter,
            "current_value":          current,
            "proposed_value":         proposed,
            "reason":                 reason,
            "source_confidence":      _derive_confidence(occurrence_ratio, confidence_trend),
            "occurrence_ratio":       round(occurrence_ratio, 2),
            "matched_recommendation": recommendation,
        }

    # No rule matched
    return None
