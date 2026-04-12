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
