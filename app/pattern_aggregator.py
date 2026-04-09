# app/pattern_aggregator.py
#
# Read-only. Reads the tuning log and identifies repeated patterns.
# No side effects, no writes, no auto-applying of anything.

from collections import Counter
from app.tuning_log import get_recent

# Confidence level → numeric weight for trend calculation
_CONFIDENCE_WEIGHT = {"high": 3, "medium": 2, "low": 1}

DEFAULT_N = 20


def _confidence_trend(records: list) -> str:
    """
    Compare average confidence weight in the first half vs the second half
    of the records (oldest → newest order).
    Returns "increasing", "decreasing", or "stable".
    """
    weights = [
        _CONFIDENCE_WEIGHT.get(r.get("confidence", ""), 0)
        for r in records
        if r.get("confidence")
    ]
    if len(weights) < 4:
        return "stable"  # not enough data to judge a trend

    mid = len(weights) // 2
    first_avg = sum(weights[:mid]) / mid
    second_avg = sum(weights[mid:]) / (len(weights) - mid)

    if second_avg > first_avg + 0.25:
        return "increasing"
    elif second_avg < first_avg - 0.25:
        return "decreasing"
    else:
        return "stable"


def summarize(n: int = DEFAULT_N) -> dict:
    """
    Read the last N log entries and return a structured pattern summary.

    Returns:
      records_analyzed          — how many records were examined
      most_common_issue         — the biggest_issue text seen most often
      occurrences               — how many times it appears
      issue_frequency           — full count of every issue seen
      most_common_recommendation — the suggested_improvement seen most often
      recommendation_frequency  — full count of every recommendation seen
      confidence_trend          — "increasing" | "stable" | "decreasing"
      decision_counts           — count of each decision type
    """
    # get_recent returns newest-first; reverse to oldest-first for trend math
    records = list(reversed(get_recent(n)))

    if not records:
        return {
            "records_analyzed": 0,
            "most_common_issue": None,
            "occurrences": 0,
            "issue_frequency": {},
            "most_common_recommendation": None,
            "recommendation_frequency": {},
            "confidence_trend": "stable",
            "decision_counts": {
                "flag_for_tuning": 0,
                "monitor": 0,
                "collect_more_data": 0,
            },
        }

    issues = [r["biggest_issue"] for r in records if r.get("biggest_issue")]
    # Use the structured recommendation from the analyzer (parseable by proposal_parser).
    # Multi-line recommendations are split so each parameter change is counted individually.
    # Falls back to recommended_action for records written before this field existed.
    recommendations = []
    for r in records:
        rec = r.get("structured_recommendation") or r.get("recommended_action", "")
        if not rec:
            continue
        for line in rec.splitlines():
            line = line.strip()
            if line:
                recommendations.append(line)
    decisions = [r["decision"] for r in records if r.get("decision")]

    issue_counts = Counter(issues)
    rec_counts = Counter(recommendations)
    decision_counts = Counter(decisions)

    top_issue, top_occurrences = issue_counts.most_common(1)[0] if issue_counts else (None, 0)
    top_rec = rec_counts.most_common(1)[0][0] if rec_counts else None

    return {
        "records_analyzed": len(records),
        "most_common_issue": top_issue,
        "occurrences": top_occurrences,
        "issue_frequency": dict(issue_counts.most_common()),
        "most_common_recommendation": top_rec,
        "recommendation_frequency": dict(rec_counts.most_common()),
        "confidence_trend": _confidence_trend(records),
        "decision_counts": {
            "flag_for_tuning": decision_counts.get("flag_for_tuning", 0),
            "monitor": decision_counts.get("monitor", 0),
            "collect_more_data": decision_counts.get("collect_more_data", 0),
        },
    }
