# app/belfort_broker.py
#
# Thin Alpaca paper order client for THE ABODE.
#
# Submits limit orders to the Alpaca paper trading API.
# This module is strictly paper-only — it will refuse to submit if the
# configured base URL is not the paper endpoint.
#
# Safety constraints:
#   - Only paper API allowed (URL check on every call)
#   - Long-only paper orders (buy + sell to close; no shorting)
#   - No margin, no options, no fractional shares
#   - No retry logic — all failures are logged immediately
#   - Returns a structured result dict, never raises
#
# Configuration (from .env):
#   ALPACA_API_KEY    — same key used for market data
#   ALPACA_API_SECRET — same secret used for market data
#   APCA_API_BASE_URL — must contain "paper-api.alpaca.markets"
#
# Public API:
#   submit_paper_order(symbol, qty, limit_price, side="buy", extended_hours=False) → BrokerResult
#   fetch_paper_order(order_id) → PaperOrderStatus
#   fetch_paper_account_snapshot() → PaperAccountSnapshot
#   fetch_paper_positions() → PaperPositionsSnapshot
#   broker_status() → dict

from __future__ import annotations

import os
import pathlib
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

import requests as _http

_ROOT     = pathlib.Path(__file__).resolve().parent.parent
_ENV_FILE = _ROOT / ".env"

# ── Configuration ─────────────────────────────────────────────────────────────

def _load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for key in ("ALPACA_API_KEY", "ALPACA_API_SECRET", "APCA_API_BASE_URL"):
        val = os.getenv(key, "")
        if val:
            env[key] = val
    if _ENV_FILE.exists():
        for line in _ENV_FILE.read_text().splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                k = k.strip()
                if k in ("ALPACA_API_KEY", "ALPACA_API_SECRET", "APCA_API_BASE_URL"):
                    env.setdefault(k, v.strip())
    return env


_cfg        = _load_env()
_API_KEY    = _cfg.get("ALPACA_API_KEY", "")
_API_SECRET = _cfg.get("ALPACA_API_SECRET", "")
_BASE_URL   = _cfg.get("APCA_API_BASE_URL", "").rstrip("/")

# ── Safety check ──────────────────────────────────────────────────────────────

_PAPER_URL_MARKER = "paper-api.alpaca.markets"
_is_paper_url     = _PAPER_URL_MARKER in _BASE_URL


@dataclass
class BrokerResult:
    submitted:              bool
    paper_only:             bool   = True     # invariant
    broker_order_id:        str    = ""
    broker_client_order_id: str    = ""
    broker_status:          str    = ""
    broker_error:           str    = ""
    submission_error:       str    = ""
    raw_response:           dict   = None     # type: ignore[assignment]

    def __post_init__(self):
        if self.raw_response is None:
            self.raw_response = {}


@dataclass
class PaperOrderStatus:
    order_id:         str = ""
    client_order_id:  str = ""
    submitted:        bool = False
    status:           str = ""
    symbol:           str = ""
    side:             str = ""
    qty:              float = 0.0
    filled_qty:       float = 0.0
    limit_price:      float | None = None
    fill_price:       float | None = None
    updated_at:       str = ""
    broker_error:     str = ""
    submission_error: str = ""
    raw_response:     dict = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.raw_response is None:
            self.raw_response = {}


@dataclass
class PaperAccountSnapshot:
    available:        bool = False
    cash:             float = 0.0
    buying_power:     float = 0.0
    equity:           float = 0.0
    last_equity:      float = 0.0
    broker_error:     str = ""
    submission_error: str = ""
    raw_response:     dict = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.raw_response is None:
            self.raw_response = {}


@dataclass
class PaperPosition:
    symbol:         str = ""
    qty:            float = 0.0
    avg_cost:       float = 0.0
    market_value:   float | None = None
    unrealized_pnl: float | None = None
    side:           str = "long"
    raw_response:   dict = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.raw_response is None:
            self.raw_response = {}


@dataclass
class PaperPositionsSnapshot:
    available:        bool = False
    positions:        list[PaperPosition] = None  # type: ignore[assignment]
    broker_error:     str = ""
    submission_error: str = ""
    raw_response:     list | dict = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.positions is None:
            self.positions = []
        if self.raw_response is None:
            self.raw_response = []


def _headers() -> dict[str, str]:
    return {
        "APCA-API-KEY-ID":     _API_KEY,
        "APCA-API-SECRET-KEY": _API_SECRET,
        "Content-Type":        "application/json",
    }


def _safe_float(value: object) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


# ── Order submission ──────────────────────────────────────────────────────────

def submit_paper_order(
    symbol:      str,
    qty:         int,
    limit_price: float,
    side:        str = "buy",
    extended_hours: bool = False,
) -> BrokerResult:
    """
    Submit a paper long-only limit order to Alpaca.

    Supports:
      - buy
      - sell (to close an existing long position)
    Does not support shorting.
    Returns a BrokerResult — never raises.

    Args:
        symbol:      Ticker, e.g. "SPY"
        qty:         Whole shares only (no fractional)
        limit_price: Limit price in USD
        extended_hours: Mark the order as extended-hours eligible

    Returns BrokerResult with submitted=True on success, False on any failure.
    """
    now_str = datetime.now(timezone.utc).isoformat()

    # ── Safety gates ─────────────────────────────────────────────────────────
    if not _is_paper_url:
        return BrokerResult(
            submitted        = False,
            submission_error = (
                f"Broker URL is not a paper endpoint: {_BASE_URL!r}. "
                "Paper execution is blocked — only paper-api.alpaca.markets is allowed."
            ),
        )

    if not (_API_KEY and _API_SECRET):
        return BrokerResult(
            submitted        = False,
            submission_error = "No Alpaca credentials configured — cannot submit paper order.",
        )

    if qty <= 0:
        return BrokerResult(
            submitted        = False,
            submission_error = f"Invalid qty={qty} — must be a positive integer.",
        )

    if limit_price <= 0:
        return BrokerResult(
            submitted        = False,
            submission_error = f"Invalid limit_price={limit_price} — must be positive.",
        )

    side = str(side or "buy").strip().lower()
    if side not in ("buy", "sell"):
        return BrokerResult(
            submitted        = False,
            submission_error = f"Invalid side={side!r} — must be 'buy' or 'sell'.",
        )

    # ── Build order ───────────────────────────────────────────────────────────
    client_order_id = f"belfort-paper-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:6]}"
    order_payload = {
        "symbol":          symbol.upper(),
        "qty":             str(qty),
        "side":            side,
        "type":            "limit",
        "time_in_force":   "day",
        "limit_price":     f"{limit_price:.4f}",
        "client_order_id": client_order_id,
    }
    if extended_hours:
        order_payload["extended_hours"] = True

    # ── Submit ────────────────────────────────────────────────────────────────
    try:
        resp = _http.post(
            f"{_BASE_URL}/orders",
            headers=_headers(),
            json=order_payload,
            timeout=10,
        )
        raw = {}
        try:
            raw = resp.json()
        except Exception:
            raw = {"raw_text": resp.text[:200]}

        if resp.status_code in (200, 201):
            return BrokerResult(
                submitted              = True,
                broker_order_id        = raw.get("id", ""),
                broker_client_order_id = raw.get("client_order_id", client_order_id),
                broker_status          = raw.get("status", "submitted"),
                raw_response           = raw,
            )
        else:
            broker_err = raw.get("message", raw.get("error", resp.text[:200]))
            return BrokerResult(
                submitted        = False,
                broker_error     = f"HTTP {resp.status_code}: {broker_err}",
                raw_response     = raw,
            )

    except _http.exceptions.Timeout:
        return BrokerResult(
            submitted        = False,
            submission_error = "Broker request timed out (10s).",
        )
    except _http.exceptions.RequestException as exc:
        return BrokerResult(
            submitted        = False,
            submission_error = f"Request error: {exc}",
        )
    except Exception as exc:
        return BrokerResult(
            submitted        = False,
            submission_error = f"Unexpected error during order submission: {exc}",
        )


def fetch_paper_order(order_id: str) -> PaperOrderStatus:
    """
    Fetch a paper order's latest broker status.

    Returns a PaperOrderStatus and never raises.
    """
    order_id = str(order_id or "").strip()
    if not order_id:
        return PaperOrderStatus(
            submitted=False,
            submission_error="order_id is required to fetch paper order status.",
        )

    if not _is_paper_url:
        return PaperOrderStatus(
            submitted=False,
            submission_error=(
                f"Broker URL is not a paper endpoint: {_BASE_URL!r}. "
                "Paper status lookup is blocked — only paper-api.alpaca.markets is allowed."
            ),
        )

    if not (_API_KEY and _API_SECRET):
        return PaperOrderStatus(
            submitted=False,
            submission_error="No Alpaca credentials configured — cannot fetch paper order status.",
        )

    try:
        resp = _http.get(
            f"{_BASE_URL}/orders/{order_id}",
            headers=_headers(),
            timeout=10,
        )
        raw = {}
        try:
            raw = resp.json()
        except Exception:
            raw = {"raw_text": resp.text[:200]}

        if resp.status_code not in (200, 201):
            broker_err = raw.get("message", raw.get("error", resp.text[:200]))
            return PaperOrderStatus(
                order_id=order_id,
                submitted=False,
                broker_error=f"HTTP {resp.status_code}: {broker_err}",
                raw_response=raw,
            )

        return PaperOrderStatus(
            order_id=raw.get("id", order_id),
            client_order_id=raw.get("client_order_id", ""),
            submitted=True,
            status=raw.get("status", ""),
            symbol=raw.get("symbol", ""),
            side=raw.get("side", ""),
            qty=_safe_float(raw.get("qty")) or 0.0,
            filled_qty=_safe_float(raw.get("filled_qty")) or 0.0,
            limit_price=_safe_float(raw.get("limit_price")),
            fill_price=_safe_float(raw.get("filled_avg_price")),
            updated_at=raw.get("updated_at", ""),
            raw_response=raw,
        )
    except _http.exceptions.Timeout:
        return PaperOrderStatus(
            order_id=order_id,
            submitted=False,
            submission_error="Paper order status request timed out (10s).",
        )
    except _http.exceptions.RequestException as exc:
        return PaperOrderStatus(
            order_id=order_id,
            submitted=False,
            submission_error=f"Request error: {exc}",
        )
    except Exception as exc:
        return PaperOrderStatus(
            order_id=order_id,
            submitted=False,
            submission_error=f"Unexpected error during paper status lookup: {exc}",
        )


def fetch_paper_account_snapshot() -> PaperAccountSnapshot:
    """
    Fetch the authoritative Alpaca paper account snapshot.

    Returns a PaperAccountSnapshot and never raises.
    """
    if not _is_paper_url:
        return PaperAccountSnapshot(
            available=False,
            submission_error=(
                f"Broker URL is not a paper endpoint: {_BASE_URL!r}. "
                "Paper account lookup is blocked — only paper-api.alpaca.markets is allowed."
            ),
        )

    if not (_API_KEY and _API_SECRET):
        return PaperAccountSnapshot(
            available=False,
            submission_error="No Alpaca credentials configured — cannot fetch paper account snapshot.",
        )

    try:
        resp = _http.get(
            f"{_BASE_URL}/account",
            headers=_headers(),
            timeout=10,
        )
        raw = {}
        try:
            raw = resp.json()
        except Exception:
            raw = {"raw_text": resp.text[:200]}

        if resp.status_code not in (200, 201):
            broker_err = raw.get("message", raw.get("error", resp.text[:200]))
            return PaperAccountSnapshot(
                available=False,
                broker_error=f"HTTP {resp.status_code}: {broker_err}",
                raw_response=raw,
            )

        return PaperAccountSnapshot(
            available=True,
            cash=_safe_float(raw.get("cash")) or 0.0,
            buying_power=_safe_float(raw.get("buying_power")) or 0.0,
            equity=_safe_float(raw.get("equity")) or 0.0,
            last_equity=_safe_float(raw.get("last_equity")) or 0.0,
            raw_response=raw,
        )
    except _http.exceptions.Timeout:
        return PaperAccountSnapshot(
            available=False,
            submission_error="Paper account request timed out (10s).",
        )
    except _http.exceptions.RequestException as exc:
        return PaperAccountSnapshot(
            available=False,
            submission_error=f"Request error: {exc}",
        )
    except Exception as exc:
        return PaperAccountSnapshot(
            available=False,
            submission_error=f"Unexpected error during paper account lookup: {exc}",
        )


def fetch_paper_positions() -> PaperPositionsSnapshot:
    """
    Fetch the authoritative Alpaca paper positions.

    Returns a PaperPositionsSnapshot and never raises.
    """
    if not _is_paper_url:
        return PaperPositionsSnapshot(
            available=False,
            submission_error=(
                f"Broker URL is not a paper endpoint: {_BASE_URL!r}. "
                "Paper position lookup is blocked — only paper-api.alpaca.markets is allowed."
            ),
        )

    if not (_API_KEY and _API_SECRET):
        return PaperPositionsSnapshot(
            available=False,
            submission_error="No Alpaca credentials configured — cannot fetch paper positions.",
        )

    try:
        resp = _http.get(
            f"{_BASE_URL}/positions",
            headers=_headers(),
            timeout=10,
        )
        raw = []
        try:
            raw = resp.json()
        except Exception:
            raw = [{"raw_text": resp.text[:200]}]

        if resp.status_code not in (200, 201):
            broker_err = ""
            if isinstance(raw, dict):
                broker_err = raw.get("message", raw.get("error", resp.text[:200]))
            else:
                broker_err = resp.text[:200]
            return PaperPositionsSnapshot(
                available=False,
                broker_error=f"HTTP {resp.status_code}: {broker_err}",
                raw_response=raw,
            )

        if not isinstance(raw, list):
            return PaperPositionsSnapshot(
                available=False,
                broker_error="Broker returned an unexpected positions payload.",
                raw_response=raw,
            )

        positions = []
        for row in raw:
            if not isinstance(row, dict):
                continue
            positions.append(
                PaperPosition(
                    symbol=str(row.get("symbol", "")).upper(),
                    qty=_safe_float(row.get("qty")) or 0.0,
                    avg_cost=_safe_float(row.get("avg_entry_price")) or 0.0,
                    market_value=_safe_float(row.get("market_value")),
                    unrealized_pnl=_safe_float(row.get("unrealized_pl")),
                    side=str(row.get("side", "long") or "long"),
                    raw_response=row,
                )
            )

        return PaperPositionsSnapshot(
            available=True,
            positions=positions,
            raw_response=raw,
        )
    except _http.exceptions.Timeout:
        return PaperPositionsSnapshot(
            available=False,
            submission_error="Paper positions request timed out (10s).",
        )
    except _http.exceptions.RequestException as exc:
        return PaperPositionsSnapshot(
            available=False,
            submission_error=f"Request error: {exc}",
        )
    except Exception as exc:
        return PaperPositionsSnapshot(
            available=False,
            submission_error=f"Unexpected error during paper positions lookup: {exc}",
        )


def broker_status() -> dict:
    """Return current broker configuration state (no credentials exposed)."""
    return {
        "paper_only":          True,
        "is_paper_url":        _is_paper_url,
        "base_url_configured": bool(_BASE_URL),
        "has_credentials":     bool(_API_KEY and _API_SECRET),
        "url_marker":          _PAPER_URL_MARKER,
    }
