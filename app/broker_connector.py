# app/broker_connector.py
#
# Broker-agnostic connector for THE ABODE.
#
# Provides a unified interface for order lifecycle, positions, and account state.
# The environment (PAPER or LIVE) is locked at module load time — it cannot be
# changed per-call. Routing to live when paper is configured is impossible.
#
# Supported brokers:
#   alpaca   — Alpaca Markets (paper and live)
#
# Configuration (.env):
#   ALPACA_API_KEY       — required
#   ALPACA_API_SECRET    — required
#   ALPACA_ENVIRONMENT   — "paper" (default) or "live"
#   ALPACA_BROKER        — "alpaca" (default; only option currently)
#
# Graceful degradation:
#   If no credentials are configured, all calls return stub responses
#   indicating the broker is unavailable. The system continues running
#   (useful for unit tests and simulation without real broker access).
#
# Public API:
#   get_connector()  → AlpacaConnector | None
#   OrderAck, CancelAck, OrderStatus, Position, AccountState — result types

from __future__ import annotations

import json
import os
import pathlib
import threading
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Any, Literal

import requests as _http

_ROOT     = pathlib.Path(__file__).resolve().parent.parent
_ENV_FILE = _ROOT / ".env"

EnvironmentType = Literal["paper", "live"]

_ALPACA_PAPER_URL = "https://paper-api.alpaca.markets"
_ALPACA_LIVE_URL  = "https://api.alpaca.markets"


# ── Config loading ────────────────────────────────────────────────────────────

def _load_cfg() -> dict[str, str]:
    cfg: dict[str, str] = {}
    for key in ("ALPACA_API_KEY", "ALPACA_API_SECRET", "ALPACA_ENVIRONMENT", "ALPACA_BROKER"):
        val = os.getenv(key, "")
        if val:
            cfg[key] = val
    if _ENV_FILE.exists():
        for line in _ENV_FILE.read_text().splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                if k.strip() in ("ALPACA_API_KEY", "ALPACA_API_SECRET", "ALPACA_ENVIRONMENT", "ALPACA_BROKER"):
                    cfg.setdefault(k.strip(), v.strip())
    return cfg


_cfg = _load_cfg()
_ENVIRONMENT: EnvironmentType = (
    "live" if _cfg.get("ALPACA_ENVIRONMENT", "paper").lower() == "live"
    else "paper"
)
_API_KEY    = _cfg.get("ALPACA_API_KEY", "")
_API_SECRET = _cfg.get("ALPACA_API_SECRET", "")


# ── Result types ──────────────────────────────────────────────────────────────

@dataclass
class OrderAck:
    order_id:    str
    status:      str          # "accepted" | "rejected" | "error"
    broker_ref:  str          # broker's internal order ID
    message:     str          # plain text
    raw:         dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CancelAck:
    order_id:    str
    success:     bool
    message:     str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class OrderStatus:
    order_id:    str
    symbol:      str
    side:        str          # "buy" | "sell"
    qty:         float
    filled_qty:  float
    order_type:  str
    status:      str          # broker status string
    limit_price: float | None
    fill_price:  float | None  # avg fill price if any
    created_at:  str
    updated_at:  str
    raw:         dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    def is_final(self) -> bool:
        return self.status in ("filled", "cancelled", "expired", "rejected")


@dataclass
class Position:
    symbol:    str
    qty:       float
    avg_cost:  float
    side:      str      # "long" | "short"
    market_value: float | None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AccountState:
    cash:          float
    buying_power:  float
    equity:        float
    environment:   EnvironmentType

    def to_dict(self) -> dict:
        return asdict(self)


# ── Connector ─────────────────────────────────────────────────────────────────

class AlpacaConnector:
    """
    Alpaca broker connector.

    Environment is locked at construction time.
    All methods return structured result types — never raw dicts from caller's
    perspective. Never raises on network errors; errors are embedded in results.
    """

    def __init__(self, environment: EnvironmentType, api_key: str, api_secret: str) -> None:
        # Hard lock: if paper is configured, live URL is never used.
        if environment not in ("paper", "live"):
            raise ValueError(f"Invalid environment: {environment!r}")
        self._env    = environment
        self._key    = api_key
        self._secret = api_secret
        self._base   = _ALPACA_PAPER_URL if environment == "paper" else _ALPACA_LIVE_URL

    @property
    def environment(self) -> EnvironmentType:
        return self._env

    def _headers(self) -> dict[str, str]:
        return {
            "APCA-API-KEY-ID":    self._key,
            "APCA-API-SECRET-KEY": self._secret,
            "Content-Type":       "application/json",
        }

    def _get(self, path: str, params: dict | None = None) -> dict:
        try:
            resp = _http.get(
                f"{self._base}{path}",
                headers=self._headers(),
                params=params,
                timeout=10,
            )
            resp.raise_for_status()
            return resp.json()
        except _http.exceptions.HTTPError as exc:
            return {"error": f"HTTP {exc.response.status_code}: {exc.response.text[:200]}"}
        except Exception as exc:
            return {"error": str(exc)}

    def _post(self, path: str, body: dict) -> dict:
        try:
            resp = _http.post(
                f"{self._base}{path}",
                headers=self._headers(),
                json=body,
                timeout=10,
            )
            resp.raise_for_status()
            return resp.json()
        except _http.exceptions.HTTPError as exc:
            return {"error": f"HTTP {exc.response.status_code}: {exc.response.text[:200]}"}
        except Exception as exc:
            return {"error": str(exc)}

    def _delete(self, path: str) -> dict:
        try:
            resp = _http.delete(
                f"{self._base}{path}",
                headers=self._headers(),
                timeout=10,
            )
            # 204 No Content is success for cancels
            if resp.status_code == 204:
                return {"ok": True}
            resp.raise_for_status()
            return resp.json() if resp.content else {"ok": True}
        except _http.exceptions.HTTPError as exc:
            return {"error": f"HTTP {exc.response.status_code}: {exc.response.text[:200]}"}
        except Exception as exc:
            return {"error": str(exc)}

    # ── Order lifecycle ────────────────────────────────────────────────────────

    def place_order(
        self,
        symbol:           str,
        side:             str,
        qty:              float,
        order_type:       str,
        limit_price:      float | None = None,
        extended_hours:   bool = False,
        time_in_force:    str = "day",
    ) -> OrderAck:
        """
        Place an order. Returns OrderAck regardless of broker response.
        The caller must check ack.status — "rejected" and "error" are valid.
        """
        body: dict[str, Any] = {
            "symbol":         symbol.upper(),
            "qty":            str(int(qty)),
            "side":           side.lower(),
            "type":           order_type.lower(),
            "time_in_force":  time_in_force,
        }
        if order_type.lower() == "limit" and limit_price is not None:
            body["limit_price"] = str(round(limit_price, 2))
        if extended_hours:
            body["extended_hours"] = True

        raw = self._post("/v2/orders", body)

        if "error" in raw:
            return OrderAck(
                order_id   = "",
                status     = "error",
                broker_ref = "",
                message    = raw["error"],
                raw        = raw,
            )

        status = raw.get("status", "unknown")
        return OrderAck(
            order_id   = raw.get("client_order_id", raw.get("id", "")),
            status     = "rejected" if status == "rejected" else "accepted",
            broker_ref = raw.get("id", ""),
            message    = f"Order {status}",
            raw        = raw,
        )

    def cancel_order(self, order_id: str) -> CancelAck:
        raw = self._delete(f"/v2/orders/{order_id}")
        if "error" in raw:
            return CancelAck(order_id=order_id, success=False, message=raw["error"])
        return CancelAck(order_id=order_id, success=True, message="Cancelled")

    def get_order(self, order_id: str) -> OrderStatus | None:
        raw = self._get(f"/v2/orders/{order_id}")
        if "error" in raw or not raw:
            return None
        return _parse_order(raw)

    def get_open_orders(self) -> list[dict]:
        """Return raw open orders from broker. For kill switch use."""
        raw = self._get("/v2/orders", params={"status": "open"})
        if isinstance(raw, list):
            return raw
        return []

    def cancel_all_orders(self) -> int:
        """Cancel all open orders. Returns number of cancel attempts."""
        orders = self.get_open_orders()
        cancelled = 0
        for o in orders:
            oid = o.get("id", "")
            if oid:
                ack = self.cancel_order(oid)
                if ack.success:
                    cancelled += 1
        return cancelled

    # ── Positions and account ─────────────────────────────────────────────────

    def get_positions(self) -> list[Position]:
        raw = self._get("/v2/positions")
        if not isinstance(raw, list):
            return []
        return [_parse_position(p) for p in raw]

    def get_account(self) -> AccountState:
        raw = self._get("/v2/account")
        if "error" in raw:
            return AccountState(cash=0.0, buying_power=0.0, equity=0.0, environment=self._env)
        return AccountState(
            cash         = float(raw.get("cash", 0.0)),
            buying_power = float(raw.get("buying_power", 0.0)),
            equity       = float(raw.get("equity", 0.0)),
            environment  = self._env,
        )


def _parse_order(raw: dict) -> OrderStatus:
    return OrderStatus(
        order_id    = raw.get("client_order_id", raw.get("id", "")),
        symbol      = raw.get("symbol", ""),
        side        = raw.get("side", ""),
        qty         = float(raw.get("qty", 0.0)),
        filled_qty  = float(raw.get("filled_qty", 0.0)),
        order_type  = raw.get("type", ""),
        status      = raw.get("status", ""),
        limit_price = _safe_float(raw.get("limit_price")),
        fill_price  = _safe_float(raw.get("filled_avg_price")),
        created_at  = raw.get("created_at", ""),
        updated_at  = raw.get("updated_at", ""),
        raw         = raw,
    )


def _parse_position(raw: dict) -> Position:
    return Position(
        symbol      = raw.get("symbol", ""),
        qty         = float(raw.get("qty", 0.0)),
        avg_cost    = float(raw.get("avg_entry_price", 0.0)),
        side        = raw.get("side", "long"),
        market_value = _safe_float(raw.get("market_value")),
    )


def _safe_float(v: object) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


# ── Singleton connector ───────────────────────────────────────────────────────

_connector: AlpacaConnector | None = None
_connector_lock = threading.Lock()


def get_connector() -> AlpacaConnector | None:
    """
    Return the shared connector instance, or None if no credentials are set.
    Environment is locked to whatever was in config at startup.
    """
    global _connector
    if _connector is not None:
        return _connector
    with _connector_lock:
        if _connector is None:
            if not (_API_KEY and _API_SECRET):
                return None
            _connector = AlpacaConnector(_ENVIRONMENT, _API_KEY, _API_SECRET)
    return _connector


def connector_status() -> dict:
    """Status summary for Peter / dashboard."""
    c = get_connector()
    if c is None:
        return {
            "available":    False,
            "environment":  None,
            "message":      "No broker credentials configured. Paper sim only.",
        }
    return {
        "available":    True,
        "environment":  c.environment,
        "broker":       "alpaca",
        "base_url":     _ALPACA_PAPER_URL if c.environment == "paper" else _ALPACA_LIVE_URL,
        "message":      f"Alpaca connector ready ({c.environment}).",
    }
