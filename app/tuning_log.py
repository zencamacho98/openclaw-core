# app/tuning_log.py
#
# Append-only log of analyzer + decision outputs.
# Stored as JSONL (one record per line) in data/tuning_log.jsonl.
#
# Never modifies past records. Never auto-applies any recommendation.
# Intended as an auditable history for human review and future tuning agents.

import json
import pathlib
from datetime import datetime, timezone

LOG_FILE = pathlib.Path("data/tuning_log.jsonl")


def append(analysis: dict, decision: dict, strategy_name: str) -> dict:
    """
    Build a recommendation record from analyzer + decision output and append
    it to the log. Returns the stored record.
    """
    record = {
        "timestamp":              datetime.now(timezone.utc).isoformat(),
        "strategy_name":          strategy_name,
        # Analyzer fields
        "analyzer_summary":       analysis.get("analysis", ""),
        "win_rate_assessment":    analysis.get("win_rate_assessment", ""),
        "biggest_issue":          analysis.get("biggest_issue", ""),
        "suggested_improvement":  analysis.get("suggested_improvement", ""),
        "confidence":             analysis.get("confidence", ""),
        "trades_analyzed":        analysis.get("trades_analyzed", 0),
        # Structured parameter recommendation produced by the analyzer
        "structured_recommendation": analysis.get("recommendation", ""),
        # Decision fields
        "decision":               decision.get("decision", ""),
        "priority":               decision.get("priority", ""),
        "reason":                 decision.get("reason", ""),
        "recommended_action":     decision.get("recommended_action", ""),
    }

    LOG_FILE.parent.mkdir(exist_ok=True)
    with LOG_FILE.open("a") as f:
        f.write(json.dumps(record) + "\n")

    return record


def get_recent(n: int = 20) -> list:
    """Return the last N records, most recent first."""
    if not LOG_FILE.exists():
        return []
    lines = [line for line in LOG_FILE.read_text().splitlines() if line.strip()]
    records = [json.loads(line) for line in lines]
    return list(reversed(records[-n:]))
