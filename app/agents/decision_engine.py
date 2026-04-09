# app/agents/decision_engine.py
#
# Pure logic layer. Accepts analyzer output and returns a structured decision.
# No API calls, no state mutations, no side effects.
# Always deterministic: same input → same output.

from datetime import datetime, timezone

# Thresholds
MIN_TRADES_FOR_SIGNAL = 10  # below this, data is too thin to act on

# Decision values
COLLECT_MORE_DATA = "collect_more_data"
MONITOR = "monitor"
FLAG_FOR_TUNING = "flag_for_tuning"


def evaluate(analyzer_output: dict) -> dict:
    """
    Interpret analyzer output and return a decision object.

    Input fields used:
      - win_rate_assessment: "strong" | "acceptable" | "weak" | "insufficient_data"
      - confidence:          "high" | "medium" | "low"
      - trades_analyzed:     int
      - biggest_issue:       str  (informational, surfaced in reason)
      - suggested_improvement: str (passed through to recommended_action)

    Returns a dict with:
      - decision:           one of the three decision constants above
      - reason:             plain-English explanation of the decision
      - priority:           "low" | "medium" | "high"
      - recommended_action: what a human (or future agent) should do next
      - inputs_used:        the fields that drove the decision (for auditability)
      - timestamp:          ISO UTC timestamp of evaluation
    """
    if "error" in analyzer_output:
        return {
            "decision":        COLLECT_MORE_DATA,
            "action_type":     "continue",
            "confidence_score": 0.0,
            "reason":          f"Analyzer returned an error: {analyzer_output['error']}",
            "priority":        "low",
            "recommended_action": "Fix the analyzer error, then re-run.",
            "inputs_used":     {},
            "timestamp":       _now(),
        }

    assessment = analyzer_output.get("win_rate_assessment", "")
    confidence = analyzer_output.get("confidence", "")
    trades = analyzer_output.get("trades_analyzed", 0)
    issue = analyzer_output.get("biggest_issue", "unspecified")
    suggestion = analyzer_output.get("suggested_improvement", "")

    inputs_used = {
        "win_rate_assessment": assessment,
        "confidence":          confidence,
        "trades_analyzed":     trades,
    }

    # --- Rule 1: insufficient data ---
    # Thin data makes any signal unreliable regardless of what the model says.
    if assessment == "insufficient_data" or trades < MIN_TRADES_FOR_SIGNAL or confidence == "low":
        reasons = []
        if assessment == "insufficient_data":
            reasons.append("win rate assessment is inconclusive")
        if trades < MIN_TRADES_FOR_SIGNAL:
            reasons.append(f"only {trades} trades analyzed (minimum {MIN_TRADES_FOR_SIGNAL})")
        if confidence == "low":
            reasons.append("model confidence is low")
        return {
            "decision":        COLLECT_MORE_DATA,
            "action_type":     "continue",
            "confidence_score": 0.2,
            "reason":          "Not enough reliable data to act: " + "; ".join(reasons) + ".",
            "priority":        "low",
            "recommended_action": (
                f"Run at least {max(0, MIN_TRADES_FOR_SIGNAL - trades)} more trades, "
                "then re-run analysis."
            ),
            "inputs_used":     inputs_used,
            "timestamp":       _now(),
        }

    # --- Rule 2: weak performance with reliable signal → tuning needed ---
    if assessment == "weak" and confidence in ("high", "medium"):
        priority = "high" if confidence == "high" else "medium"
        score = 0.9 if confidence == "high" else 0.65
        return {
            "decision":        FLAG_FOR_TUNING,
            "action_type":     "adjust",
            "confidence_score": score,
            "reason": (
                f"Win rate is weak and the model is {confidence}-confidence the cause is: {issue}."
            ),
            "priority":        priority,
            "recommended_action": suggestion or "Review strategy parameters before running more trades.",
            "inputs_used":     inputs_used,
            "timestamp":       _now(),
        }

    # --- Rule 3: acceptable or strong → keep monitoring ---
    priority = "low" if assessment == "strong" else "medium"
    score = 0.8 if assessment == "strong" else 0.55
    return {
        "decision":        MONITOR,
        "action_type":     "continue",
        "confidence_score": score,
        "reason": (
            f"Win rate assessment is '{assessment}' with {confidence} confidence. "
            "Strategy is performing within acceptable bounds."
        ),
        "priority":        priority,
        "recommended_action": "Continue running trades. Re-run analysis after 10+ more cycles.",
        "inputs_used":     inputs_used,
        "timestamp":       _now(),
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
