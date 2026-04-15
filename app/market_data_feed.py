# app/market_data_feed.py
#
# Market data feed connector for THE ABODE.
#
# Provides L1 quotes (bid/ask/last) and basic trade events.
# Every event carries a `data_lane` field — never silently assumes consolidated.
#
# Data lane:
#   IEX_ONLY        — single-venue Investors Exchange feed (free Alpaca tier)
#   SIP_CONSOLIDATED — consolidated tape from all U.S. exchanges (paid tier)
#   UNKNOWN          — lane could not be determined; treat estimates as indicative
#
# Configuration (from .env):
#   ALPACA_API_KEY    — Alpaca API key
#   ALPACA_API_SECRET — Alpaca API secret
#   ALPACA_DATA_FEED  — "iex" (default) or "sip"
#
# Graceful degradation:
#   If no API key is configured, get_quote() returns a QuoteEvent with
#   source="simulated" and is_live=False, so the rest of the system still
#   functions (for testing / paper sim without live feed).
#
# Public API:
#   get_quote(symbol)    → QuoteEvent
#   get_recent_bars(symbol, timeframe="5Min", limit=32) → list[dict]
#   get_multi_symbol_bar_context(symbols, intraday_timeframe="10Min", intraday_limit=24) → dict[str, dict]
#   feed_status()        → FeedStatus
#   DATA_LANE            — current lane constant (module-level)

from __future__ import annotations

import json
import os
import pathlib
import threading
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Literal

import requests as _http

_ROOT     = pathlib.Path(__file__).resolve().parent.parent
_ENV_FILE = _ROOT / ".env"

DataLane = Literal["IEX_ONLY", "SIP_CONSOLIDATED", "UNKNOWN"]

# Alpaca data API endpoint
_ALPACA_DATA_URL = "https://data.alpaca.markets/v2"

# ── Configuration ─────────────────────────────────────────────────────────────

def _load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    # OS environment takes priority
    for key in ("ALPACA_API_KEY", "ALPACA_API_SECRET", "ALPACA_DATA_FEED"):
        val = os.getenv(key, "")
        if val:
            env[key] = val
    # Fill from .env file for any missing keys
    if _ENV_FILE.exists():
        for line in _ENV_FILE.read_text().splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                if k.strip() in ("ALPACA_API_KEY", "ALPACA_API_SECRET", "ALPACA_DATA_FEED"):
                    env.setdefault(k.strip(), v.strip())
    return env


_cfg = _load_env()
_API_KEY    = _cfg.get("ALPACA_API_KEY", "")
_API_SECRET = _cfg.get("ALPACA_API_SECRET", "")
_FEED_PARAM = _cfg.get("ALPACA_DATA_FEED", "iex").lower()

# Resolve the data lane constant
DATA_LANE: DataLane = (
    "SIP_CONSOLIDATED" if _FEED_PARAM == "sip"
    else "IEX_ONLY" if _FEED_PARAM in ("iex", "")
    else "UNKNOWN"
)

# ── Result dataclasses ────────────────────────────────────────────────────────

@dataclass
class QuoteEvent:
    symbol:       str
    bid:          float | None      # best bid price
    ask:          float | None      # best ask price
    bid_size:     float | None      # shares at bid
    ask_size:     float | None      # shares at ask
    last:         float | None      # last trade price
    last_size:    float | None      # last trade size
    spread:       float | None      # ask - bid (None if either missing)
    spread_pct:   float | None      # spread / midpoint (None if no midpoint)
    midpoint:     float | None      # (bid + ask) / 2
    data_lane:    DataLane          # IEX_ONLY or SIP_CONSOLIDATED
    timestamp:    str               # ISO UTC
    is_live:      bool              # False when simulated / no API key
    source:       str               # "alpaca" | "simulated"
    conditions:   list[str]         # quote condition codes (empty list if none)

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def extended_hours_warning(self) -> str:
        from app.market_time import session_type, session_summary
        stype = session_type()
        if stype in ("pre_market", "after_hours"):
            return (
                f"Extended hours ({stype}): wider spreads and lower liquidity expected. "
                "Fill quality may degrade significantly."
            )
        return ""


@dataclass
class FeedStatus:
    connected:        bool
    data_lane:        DataLane
    has_credentials:  bool
    last_quote_at:    str | None      # ISO UTC of most recent successful quote
    request_count:    int
    error_count:      int
    last_error:       str

    def to_dict(self) -> dict:
        return asdict(self)

    def summary_line(self) -> str:
        lane_str = "IEX-only (not consolidated)" if self.data_lane == "IEX_ONLY" else self.data_lane
        if not self.has_credentials:
            return f"Feed: simulated (no credentials). Lane would be: {lane_str}."
        status = "connected" if self.connected else "disconnected"
        return (
            f"Feed: {status}. Data lane: {lane_str}. "
            f"Requests: {self.request_count}, errors: {self.error_count}."
        )


# ── Internal state (module-level) ─────────────────────────────────────────────

_lock           = threading.Lock()
_last_quote_at: str | None = None
_request_count  = 0
_error_count    = 0
_last_error     = ""


def _record_success() -> None:
    global _last_quote_at, _request_count
    with _lock:
        _last_quote_at  = datetime.now(timezone.utc).isoformat()
        _request_count += 1


def _record_error(msg: str) -> None:
    global _error_count, _last_error
    with _lock:
        _error_count += 1
        _last_error   = msg


# ── Quote fetch ───────────────────────────────────────────────────────────────

def get_quote(symbol: str) -> QuoteEvent:
    """
    Fetch the current L1 quote for `symbol`.

    Returns a QuoteEvent with data_lane always set.
    If no credentials are configured, returns a simulated event.
    Never raises — errors degrade to simulated/None values.
    """
    ts = datetime.now(timezone.utc).isoformat()
    sym = symbol.upper()

    if not (_API_KEY and _API_SECRET):
        return _simulated_quote(sym, ts)

    try:
        resp = _http.get(
            f"{_ALPACA_DATA_URL}/stocks/{sym}/quotes/latest",
            headers={
                "APCA-API-KEY-ID":    _API_KEY,
                "APCA-API-SECRET-KEY": _API_SECRET,
            },
            params={"feed": _FEED_PARAM},
            timeout=8,
        )
        resp.raise_for_status()
        data  = resp.json()
        quote = data.get("quote", {})

        bid   = _f(quote.get("bp"))
        ask   = _f(quote.get("ap"))
        bid_sz = _f(quote.get("bs"))
        ask_sz = _f(quote.get("as"))
        last_resp = _get_last_trade(sym)
        last   = last_resp.get("price")
        last_sz = last_resp.get("size")

        mid    = (bid + ask) / 2 if (bid and ask) else None
        spread = (ask - bid) if (bid and ask) else None
        sp_pct = (spread / mid) if (spread is not None and mid) else None

        _record_success()
        return QuoteEvent(
            symbol    = sym,
            bid       = bid,
            ask       = ask,
            bid_size  = bid_sz,
            ask_size  = ask_sz,
            last      = last,
            last_size = last_sz,
            spread    = round(spread, 6) if spread is not None else None,
            spread_pct = round(sp_pct, 6) if sp_pct is not None else None,
            midpoint  = round(mid, 6) if mid is not None else None,
            data_lane = DATA_LANE,
            timestamp = ts,
            is_live   = True,
            source    = "alpaca",
            conditions = quote.get("c", []),
        )

    except _http.exceptions.RequestException as exc:
        _record_error(str(exc))
        return _error_quote(sym, ts, str(exc))
    except Exception as exc:
        _record_error(str(exc))
        return _error_quote(sym, ts, str(exc))


def get_recent_bars(symbol: str, timeframe: str = "5Min", limit: int = 32) -> list[dict]:
    """
    Fetch recent OHLCV bars for a symbol.

    Returns a compact list of dicts suitable for direct UI rendering.
    Never raises; returns [] on any failure.
    """
    sym = str(symbol or "").upper().strip()
    if not sym:
        return []
    try:
        limit = max(8, min(int(limit or 32), 96))
    except (TypeError, ValueError):
        limit = 32
    timeframe = str(timeframe or "5Min").strip() or "5Min"

    if not (_API_KEY and _API_SECRET):
        return []

    try:
        resp = _http.get(
            f"{_ALPACA_DATA_URL}/stocks/bars",
            headers={
                "APCA-API-KEY-ID": _API_KEY,
                "APCA-API-SECRET-KEY": _API_SECRET,
            },
            params={
                "symbols": sym,
                "timeframe": timeframe,
                "limit": limit,
                "adjustment": "raw",
                "feed": _FEED_PARAM,
                "sort": "asc",
            },
            timeout=8,
        )
        resp.raise_for_status()
        payload = resp.json()
        raw_bars = ((payload.get("bars") or {}).get(sym) or [])
        out: list[dict] = []
        for bar in raw_bars:
            try:
                o = float(bar.get("o"))
                h = float(bar.get("h"))
                l = float(bar.get("l"))
                c = float(bar.get("c"))
                v = float(bar.get("v", 0) or 0)
            except (TypeError, ValueError):
                continue
            out.append({
                "t": str(bar.get("t", "")),
                "open": round(o, 6),
                "high": round(h, 6),
                "low": round(l, 6),
                "close": round(c, 6),
                "volume": round(v, 2),
            })
        return out
    except Exception as exc:
        _record_error(str(exc))
        return []


def get_multi_symbol_bar_context(
    symbols: list[str],
    intraday_timeframe: str = "10Min",
    intraday_limit: int = 24,
) -> dict[str, dict]:
    """
    Fetch compact intraday and daily bar context for multiple symbols.

    Returns:
        {
            "NVDA": {
                "intraday_bars": [...],
                "daily_bars": [...],
                "bar_count": 24,
                "recent_volume": 1234567.0,
                "intraday_open": 850.0,
                "intraday_last": 862.5,
                "intraday_change_pct": 0.0147,
                "prev_close": 842.1,
                "gap_pct": 0.0094,
            },
            ...
        }
    """
    unique_symbols: list[str] = []
    seen: set[str] = set()
    for raw in symbols or []:
        sym = str(raw or "").upper().strip()
        if sym and sym not in seen:
            seen.add(sym)
            unique_symbols.append(sym)
    if not unique_symbols or not (_API_KEY and _API_SECRET):
        return {}

    try:
        intraday_limit = max(8, min(int(intraday_limit or 24), 64))
    except (TypeError, ValueError):
        intraday_limit = 24

    out: dict[str, dict] = {}
    intraday_map = _fetch_multi_bars(unique_symbols, timeframe=intraday_timeframe, limit=intraday_limit)
    daily_map = _fetch_multi_bars(unique_symbols, timeframe="1Day", limit=2)
    for sym in unique_symbols:
        intraday = intraday_map.get(sym, [])
        daily = daily_map.get(sym, [])
        recent_volume = round(sum(float(bar.get("volume", 0.0) or 0.0) for bar in intraday), 2)
        intraday_open = _f((intraday[0] if intraday else {}).get("open"))
        intraday_last = _f((intraday[-1] if intraday else {}).get("close"))
        intraday_change_pct = None
        if intraday_open and intraday_last:
            intraday_change_pct = round((intraday_last - intraday_open) / intraday_open, 4)
        prev_close = None
        if len(daily) >= 2:
            prev_close = _f(daily[-2].get("close"))
        gap_pct = None
        if intraday_open and prev_close:
            gap_pct = round((intraday_open - prev_close) / prev_close, 4)
        out[sym] = {
            "intraday_bars": intraday,
            "daily_bars": daily,
            "bar_count": len(intraday),
            "recent_volume": recent_volume,
            "intraday_open": intraday_open,
            "intraday_last": intraday_last,
            "intraday_change_pct": intraday_change_pct,
            "prev_close": prev_close,
            "gap_pct": gap_pct,
        }
    return out


def _fetch_multi_bars(symbols: list[str], *, timeframe: str, limit: int) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for chunk in _chunks(symbols, 20):
        try:
            resp = _http.get(
                f"{_ALPACA_DATA_URL}/stocks/bars",
                headers={
                    "APCA-API-KEY-ID": _API_KEY,
                    "APCA-API-SECRET-KEY": _API_SECRET,
                },
                params={
                    "symbols": ",".join(chunk),
                    "timeframe": timeframe,
                    "limit": limit,
                    "adjustment": "raw",
                    "feed": _FEED_PARAM,
                    "sort": "asc",
                },
                timeout=10,
            )
            resp.raise_for_status()
            payload = resp.json()
            raw_map = payload.get("bars") or {}
            if not isinstance(raw_map, dict):
                continue
            for sym in chunk:
                raw_bars = raw_map.get(sym) or []
                cleaned: list[dict] = []
                for bar in raw_bars:
                    try:
                        o = float(bar.get("o"))
                        h = float(bar.get("h"))
                        l = float(bar.get("l"))
                        c = float(bar.get("c"))
                        v = float(bar.get("v", 0) or 0)
                    except (TypeError, ValueError):
                        continue
                    cleaned.append({
                        "t": str(bar.get("t", "")),
                        "open": round(o, 6),
                        "high": round(h, 6),
                        "low": round(l, 6),
                        "close": round(c, 6),
                        "volume": round(v, 2),
                    })
                out[sym] = cleaned
        except Exception as exc:
            _record_error(str(exc))
            for sym in chunk:
                out.setdefault(sym, [])
    return out


def _chunks(items: list[str], size: int) -> list[list[str]]:
    if size <= 0:
        return [items]
    return [items[idx:idx + size] for idx in range(0, len(items), size)]


def _get_last_trade(symbol: str) -> dict:
    """Fetch latest trade for a symbol. Returns {} on any error."""
    try:
        resp = _http.get(
            f"{_ALPACA_DATA_URL}/stocks/{symbol}/trades/latest",
            headers={
                "APCA-API-KEY-ID":    _API_KEY,
                "APCA-API-SECRET-KEY": _API_SECRET,
            },
            params={"feed": _FEED_PARAM},
            timeout=5,
        )
        resp.raise_for_status()
        trade = resp.json().get("trade", {})
        return {"price": _f(trade.get("p")), "size": _f(trade.get("s"))}
    except Exception:
        return {}


def _f(v: object) -> float | None:
    """Safe float cast."""
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _simulated_quote(symbol: str, ts: str) -> QuoteEvent:
    """Return a placeholder event used when no live feed is available."""
    return QuoteEvent(
        symbol    = symbol,
        bid       = None, ask=None, bid_size=None, ask_size=None,
        last      = None, last_size=None,
        spread    = None, spread_pct=None, midpoint=None,
        data_lane = DATA_LANE,
        timestamp = ts,
        is_live   = False,
        source    = "simulated",
        conditions = [],
    )


def _error_quote(symbol: str, ts: str, error: str) -> QuoteEvent:
    q = _simulated_quote(symbol, ts)
    q.source = f"error: {error[:80]}"
    return q


# ── Status ─────────────────────────────────────────────────────────────────────

def feed_status() -> FeedStatus:
    with _lock:
        rq = _request_count
        ec = _error_count
        le = _last_error
        lq = _last_quote_at

    return FeedStatus(
        connected       = bool(_API_KEY and _API_SECRET and rq > 0 and ec < rq),
        data_lane       = DATA_LANE,
        has_credentials = bool(_API_KEY and _API_SECRET),
        last_quote_at   = lq,
        request_count   = rq,
        error_count     = ec,
        last_error      = le,
    )
