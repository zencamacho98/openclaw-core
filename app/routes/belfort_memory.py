# app/routes/belfort_memory.py
#
# BELFORT LEARNING MEMORY
#
# Lightweight persistent learning history — one entry per session/reset.
# Stored as append-only JSONL: data/learning_history.jsonl
# No database. No complex schema. No UI.
#
# Public API:
#   append_snapshot(entry: dict) → None
#   load_history(n: int)        → list[dict]  newest-first
#   detect_patterns(entries)    → list[str]   plain-English signals
#   build_historical_context(entries) → dict

from __future__ import annotations

import json
import pathlib

_ROOT         = pathlib.Path(__file__).resolve().parent.parent.parent
_HISTORY_PATH = _ROOT / "data" / "learning_history.jsonl"

# ── Pattern detection thresholds ──────────────────────────────────────────────
_PATTERN_MIN_ENTRIES  = 2     # need at least this many before patterns fire
_PATTERN_LOOKBACK     = 5     # examine at most last N entries
_LOW_WIN_RATE         = 0.40  # below → "low win rate"
_NEG_EXPECT_THRESHOLD = 0.0   # below → "negative expectancy"


# ── Storage ───────────────────────────────────────────────────────────────────

def append_snapshot(entry: dict) -> None:
    """
    Append one learning snapshot to the persistent JSONL history.
    Silently swallows write errors — never raises.
    """
    try:
        _ROOT.joinpath("data").mkdir(exist_ok=True)
        with _HISTORY_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def load_history(n: int = 10) -> list[dict]:
    """
    Return the last n entries from learning history, newest-first.
    Returns [] when no history file exists yet.
    """
    if not _HISTORY_PATH.exists():
        return []
    try:
        lines  = _HISTORY_PATH.read_text(encoding="utf-8").strip().splitlines()
        parsed = []
        for line in lines:
            line = line.strip()
            if line:
                try:
                    parsed.append(json.loads(line))
                except Exception:
                    pass
        # parsed is oldest-first; reverse to newest-first and take n
        return list(reversed(parsed))[:n]
    except Exception:
        return []


# ── Pattern detection ─────────────────────────────────────────────────────────

def detect_patterns(entries: list[dict]) -> list[str]:
    """
    Detect repeated weakness or success signals from learning history entries
    (newest-first).  Deterministic — no LM calls.
    Returns up to 4 plain-English pattern strings.
    """
    if len(entries) < _PATTERN_MIN_ENTRIES:
        return []

    recent  = entries[:_PATTERN_LOOKBACK]   # newest first, cap at lookback
    n       = len(recent)
    patterns: list[str] = []

    # 1. Repeated negative expectancy
    neg_exp = sum(
        1 for e in recent
        if e.get("expectancy") is not None and e["expectancy"] < _NEG_EXPECT_THRESHOLD
    )
    if neg_exp >= 2:
        suffix = f"last {n}" if n > 2 else f"{n}"
        patterns.append(
            f"{neg_exp} of the {suffix} sessions had negative expectancy"
        )

    # 2. Repeated low win rate
    low_wr = sum(
        1 for e in recent
        if e.get("win_rate") is not None and e["win_rate"] < _LOW_WIN_RATE
    )
    if low_wr >= 2:
        suffix = f"last {n}" if n > 2 else f"{n}"
        patterns.append(
            f"{low_wr} of the {suffix} sessions had win rate below {int(_LOW_WIN_RATE*100)}%"
        )

    # 3. Consecutive negative P&L (most recent → oldest)
    cons_loss = 0
    for e in recent:
        if (e.get("realized_pnl") or 0.0) < 0:
            cons_loss += 1
        else:
            break
    if cons_loss >= 2:
        patterns.append(f"{cons_loss} consecutive sessions ended with negative P&L")

    # 4. Repeated research triggers
    research_ct = sum(1 for e in recent if e.get("research_triggered"))
    if research_ct >= 2:
        suffix = f"last {n}" if n > 2 else f"{n}"
        patterns.append(
            f"Research recommended in {research_ct} of the {suffix} sessions"
        )

    # 5. Repeated regime mismatch
    regime_miss = sum(1 for e in recent if e.get("regime_fit") == "poor")
    if regime_miss >= 2:
        patterns.append(
            f"Regime mismatch flagged in {regime_miss} of the last {n} sessions"
        )

    return patterns[:4]  # cap to keep historical context compact


# ── Historical context builder ────────────────────────────────────────────────

def build_historical_context(entries: list[dict]) -> dict:
    """
    Build the historical context block included in /belfort/learning.
    Returns:
      {entry_count, patterns, summary, last_verdict, last_research_goal}
    summary is None when there is no history.
    """
    entry_count = len(entries)

    if entry_count == 0:
        return {
            "entry_count":        0,
            "patterns":           [],
            "summary":            None,
            "last_verdict":       None,
            "last_research_goal": None,
        }

    patterns          = detect_patterns(entries)
    last              = entries[0]   # newest-first → index 0 is most recent
    last_verdict      = last.get("verdict")
    last_research_goal = last.get("research_goal")

    # Compose summary
    if entry_count == 1:
        v       = (last_verdict or "unknown").upper()
        summary = f"One prior session recorded \u2014 verdict was {v}."
    elif patterns:
        # Lead with the two most meaningful patterns
        parts   = patterns[:2]
        summary = parts[0]
        if len(parts) > 1:
            summary += "; " + parts[1]
        summary = summary[0].upper() + summary[1:]  # capitalize first char
    else:
        summary = f"{entry_count} sessions in history \u2014 no repeated patterns detected."

    return {
        "entry_count":        entry_count,
        "patterns":           patterns,
        "summary":            summary,
        "last_verdict":       last_verdict,
        "last_research_goal": last_research_goal,
    }
