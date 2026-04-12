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
#   - Only buy side supported (no shorting)
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
#   submit_paper_order(symbol, qty, limit_price) → BrokerResult
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


# ── Order submission ──────────────────────────────────────────────────────────

def submit_paper_order(
    symbol:      str,
    qty:         int,
    limit_price: float,
) -> BrokerResult:
    """
    Submit a paper buy limit order to Alpaca.

    Only buy orders are supported in this block (no shorting).
    Returns a BrokerResult — never raises.

    Args:
        symbol:      Ticker, e.g. "SPY"
        qty:         Whole shares only (no fractional)
        limit_price: Limit price in USD

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

    # ── Build order ───────────────────────────────────────────────────────────
    client_order_id = f"belfort-paper-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:6]}"
    order_payload = {
        "symbol":          symbol.upper(),
        "qty":             str(qty),
        "side":            "buy",
        "type":            "limit",
        "time_in_force":   "day",
        "limit_price":     f"{limit_price:.4f}",
        "client_order_id": client_order_id,
    }

    # ── Submit ────────────────────────────────────────────────────────────────
    try:
        resp = _http.post(
            f"{_BASE_URL}/orders",
            headers={
                "APCA-API-KEY-ID":     _API_KEY,
                "APCA-API-SECRET-KEY": _API_SECRET,
                "Content-Type":        "application/json",
            },
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


def broker_status() -> dict:
    """Return current broker configuration state (no credentials exposed)."""
    return {
        "paper_only":          True,
        "is_paper_url":        _is_paper_url,
        "base_url_configured": bool(_BASE_URL),
        "has_credentials":     bool(_API_KEY and _API_SECRET),
        "url_marker":          _PAPER_URL_MARKER,
    }
