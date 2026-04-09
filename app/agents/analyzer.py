# app/agents/analyzer.py
#
# Manually-triggered analysis agent. Reads recent trade history, builds a
# compact prompt, and calls OpenRouter to generate structured insights.
#
# NOT connected to the execution loop — call run_analysis() directly or
# via GET /monitor/analysis.
#
# Cache behaviour:
#   run_analysis()         — always calls OpenRouter, updates cache on success
#   get_cached_analysis()  — returns last successful result without any API call
#   clear_cache()          — resets cache (e.g. after a strategy change)

import json
import os
import pathlib
from datetime import datetime, timezone
import requests as http

from app.portfolio import get_trades
from app.report import compute_report

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "openai/gpt-4o-mini"
MAX_TRADES = 20
MAX_RESPONSE_TOKENS = 600

# In-memory cache: {"result": dict, "cached_at": str} or None
_cache: dict | None = None


# --- Cache API ---

def get_cached_analysis() -> dict | None:
    """Return the last successful analysis result, or None if no run has succeeded."""
    return _cache


def clear_cache() -> None:
    """Discard the cached result (e.g. after strategy parameters change)."""
    global _cache
    _cache = None


# --- Internal helpers ---

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


def _build_prompt(trades: list, report: dict) -> str:
    recent = trades[-MAX_TRADES:]

    trade_lines = "\n".join(
        f"  {t['timestamp'][:19]}  {t['side']:4s}  {t['qty']}x @ ${t['price']:.2f}  pnl=${t['pnl']:.2f}"
        for t in recent
    )

    return f"""You are a trading analyst reviewing simulated SPY trades driven by a moving average crossover strategy.

Performance summary:
- Trades analyzed: {len(recent)} (of {report['total_trades']} total)
- Win rate: {report['win_rate'] * 100:.1f}%
- Avg P&L per sell: ${report['avg_pnl_per_sell']:.2f}
- Best trade: ${report['best_trade_pnl']:.2f}   Worst: ${report['worst_trade_pnl']:.2f}
- Total realized P&L: ${report['total_realized_pnl']:.2f}

Recent trades (timestamp, side, qty, price, realized pnl):
{trade_lines}

Respond with a JSON object containing exactly these fields:
{{
  "analysis": "2-3 sentence narrative identifying patterns, streaks, and price levels",
  "win_rate_assessment": "one of: strong | acceptable | weak | insufficient_data",
  "biggest_issue": "single short phrase naming the main problem",
  "suggested_improvement": "one specific, actionable change to the entry or exit logic",
  "confidence": "one of: high | medium | low",
  "recommended_next_step": "one concrete action to take next",
  "recommendation": "ALWAYS REQUIRED. You must output at least one valid parameter change. NEVER null. NEVER empty. Rules: (1) One entry per line, format exactly: PARAMETER_NAME to VALUE — no other text, no explanations. (2) Valid parameters: SHORT_WINDOW (integer), LONG_WINDOW (integer), STOP_LOSS_PCT (percent, e.g. 1.5%), POSITION_SIZE (percent, e.g. 8%). (3) Percent values MUST use the % symbol — never decimals. (4) If unsure, default to: STOP_LOSS_PCT to 1.5% — Example for two changes: STOP_LOSS_PCT to 1.5%\\nPOSITION_SIZE to 8%"
}}"""


# --- Public API ---

def run_analysis() -> dict:
    """
    Call OpenRouter with a summary of recent trades.
    Always makes a fresh API call. Updates the in-memory cache on success.
    Returns structured analysis fields plus token usage for cost tracking.
    """
    global _cache

    api_key = _load_api_key()
    if not api_key:
        return {"error": "OPENROUTER_API_KEY not set in environment or .env"}

    trades = get_trades()
    if not trades:
        return {"error": "No trades in history — run some trades first"}

    report = compute_report()
    prompt = _build_prompt(trades, report)

    try:
        response = http.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": MAX_RESPONSE_TOKENS,
                "temperature": 0.3,
                "response_format": {"type": "json_object"},
            },
            timeout=30,
        )
        response.raise_for_status()
    except http.exceptions.RequestException as e:
        return {"error": f"OpenRouter request failed: {e}"}

    data = response.json()
    raw = data["choices"][0]["message"]["content"].strip()
    usage = data.get("usage", {})

    try:
        structured = json.loads(raw)
    except json.JSONDecodeError:
        return {"error": "Model returned invalid JSON", "raw": raw}

    # Normalise the structured recommendation: strip whitespace, skip null/none.
    raw_rec = structured.get("recommendation") or ""
    recommendation = raw_rec.strip() if isinstance(raw_rec, str) else ""

    # Safeguard: if the model returned nothing usable, inject the default.
    if not recommendation:
        recommendation = "STOP_LOSS_PCT to 1.5%"

    result = {
        "analysis":              structured.get("analysis", ""),
        "win_rate_assessment":   structured.get("win_rate_assessment", ""),
        "biggest_issue":         structured.get("biggest_issue", ""),
        "suggested_improvement": structured.get("suggested_improvement", ""),
        "confidence":            structured.get("confidence", ""),
        "recommended_next_step": structured.get("recommended_next_step", ""),
        "recommendation":        recommendation,
        "model":                 MODEL,
        "trades_analyzed":       min(len(trades), MAX_TRADES),
        "tokens": {
            "prompt":     usage.get("prompt_tokens"),
            "completion": usage.get("completion_tokens"),
            "total":      usage.get("total_tokens"),
        },
    }

    # Cache the successful result
    _cache = {
        "result": result,
        "cached_at": datetime.now(timezone.utc).isoformat(),
    }

    return result
