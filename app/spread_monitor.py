# app/spread_monitor.py
#
# Spread and liquidity monitor for THE ABODE.
#
# Tracks per-symbol bid/ask spread metrics across market sessions.
# Persists daily summaries to data/market_observations/YYYY-MM-DD.jsonl.
#
# Key rule: extended-hours spread data is ALWAYS annotated with a warning.
# If data_lane is IEX_ONLY, that disclaimer is always attached.
#
# Public API:
#   record_quote(quote)              → ObservationRecord
#   get_daily_summary(symbol, date)  → dict
#   get_all_summaries(date)          → dict[symbol → dict]
#   get_status()                     → dict

from __future__ import annotations

import json
import pathlib
import threading
from collections import defaultdict
from dataclasses import dataclass, asdict
from datetime import date, datetime, timezone
from typing import Any

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_OBS  = _ROOT / "data" / "market_observations"

_lock = threading.Lock()

# In-memory accumulator: {symbol: {session_type: [spread_pct, ...]}}
_intraday: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))


@dataclass
class ObservationRecord:
    symbol:        str
    session_type:  str
    bid:           float | None
    ask:           float | None
    spread:        float | None
    spread_pct:    float | None
    midpoint:      float | None
    data_lane:     str
    timestamp_utc: str
    is_live:       bool
    extended_hours_warning: str

    def to_dict(self) -> dict:
        return asdict(self)


def record_quote(quote: Any) -> ObservationRecord:
    """
    Record a QuoteEvent from the market data feed.
    Accumulates spread data in-memory and appends to the daily JSONL.
    Returns the observation record.
    """
    from app.market_time import session_type as get_session_type

    stype = get_session_type()
    ext_warn = (
        "Extended hours: wider spreads and lower liquidity expected."
        if stype in ("pre_market", "after_hours") else ""
    )
    data_lane_disclaimer = _lane_disclaimer(getattr(quote, "data_lane", "UNKNOWN"))

    rec = ObservationRecord(
        symbol        = quote.symbol,
        session_type  = stype,
        bid           = quote.bid,
        ask           = quote.ask,
        spread        = quote.spread,
        spread_pct    = quote.spread_pct,
        midpoint      = quote.midpoint,
        data_lane     = getattr(quote, "data_lane", "UNKNOWN"),
        timestamp_utc = getattr(quote, "timestamp", datetime.now(timezone.utc).isoformat()),
        is_live       = getattr(quote, "is_live", False),
        extended_hours_warning = ext_warn + (" " + data_lane_disclaimer if data_lane_disclaimer else ""),
    )

    # Accumulate for summary stats
    if quote.spread_pct is not None:
        with _lock:
            _intraday[quote.symbol][stype].append(quote.spread_pct)

    # Append to daily JSONL
    _write_observation(rec)
    return rec


def _lane_disclaimer(data_lane: str) -> str:
    if data_lane == "IEX_ONLY":
        return "IEX-only: spread may not reflect consolidated market."
    if data_lane == "UNKNOWN":
        return "Data lane unknown."
    return ""


def _write_observation(rec: ObservationRecord) -> None:
    try:
        _OBS.mkdir(parents=True, exist_ok=True)
        path = _OBS / f"{date.today().isoformat()}.jsonl"
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec.to_dict()) + "\n")
    except Exception:
        pass


def get_daily_summary(symbol: str, day: str | None = None) -> dict:
    """
    Return spread statistics for a symbol for the given date (default: today).
    Stats are broken down by session type.
    """
    day = day or date.today().isoformat()
    path = _OBS / f"{day}.jsonl"

    by_session: dict[str, list[float]] = defaultdict(list)
    data_lanes: set[str] = set()
    total = 0

    if path.exists():
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if r.get("symbol", "").upper() != symbol.upper():
                    continue
                sp = r.get("spread_pct")
                if sp is not None:
                    by_session[r.get("session_type", "unknown")].append(sp)
                    total += 1
                dl = r.get("data_lane", "UNKNOWN")
                if dl:
                    data_lanes.add(dl)
        except Exception:
            pass

    sessions_summary = {}
    for stype, spreads in by_session.items():
        avg = sum(spreads) / len(spreads)
        sessions_summary[stype] = {
            "observations":  len(spreads),
            "avg_spread_pct": round(avg * 100, 4),     # as percentage
            "min_spread_pct": round(min(spreads) * 100, 4),
            "max_spread_pct": round(max(spreads) * 100, 4),
            "extended_hours_warning": (
                "Extended hours data: spreads are typically wider; not representative of regular session."
                if stype in ("pre_market", "after_hours") else ""
            ),
        }

    lanes = sorted(data_lanes)
    return {
        "symbol":          symbol.upper(),
        "date":            day,
        "total_observations": total,
        "sessions":        sessions_summary,
        "data_lanes":      lanes,
        "data_lane_disclaimer": (
            "IEX-only: data is from a single exchange, not the consolidated market. "
            "Spreads may not reflect NBBO."
            if "IEX_ONLY" in data_lanes else ""
        ),
    }


def get_all_summaries(day: str | None = None) -> dict[str, dict]:
    """Return spread summaries for all symbols observed on the given date."""
    day = day or date.today().isoformat()
    path = _OBS / f"{day}.jsonl"
    symbols: set[str] = set()

    if path.exists():
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                    sym = r.get("symbol", "").upper()
                    if sym:
                        symbols.add(sym)
                except Exception:
                    continue
        except Exception:
            pass

    return {sym: get_daily_summary(sym, day) for sym in sorted(symbols)}


def get_status() -> dict:
    """Current in-memory accumulation status."""
    with _lock:
        counts = {
            sym: {stype: len(spreads) for stype, spreads in stypes.items()}
            for sym, stypes in _intraday.items()
        }
    return {
        "intraday_observation_counts": counts,
        "data_dir": str(_OBS),
        "today": date.today().isoformat(),
    }
