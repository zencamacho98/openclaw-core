from __future__ import annotations

import json
import pathlib
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

import requests as _http

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_CACHE_FILE = _ROOT / "data" / "belfort" / "company_profiles.json"
_PROFILE_URL = "https://finviz.com/quote.ashx"
_UA = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/123.0 Safari/537.36"
    )
}


def _read_cache() -> dict[str, dict]:
    if not _CACHE_FILE.exists():
        return {}
    try:
        raw = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return {str(k).upper(): dict(v) for k, v in raw.items() if isinstance(v, dict)}
    except Exception:
        pass
    return {}


def _write_cache(cache: dict[str, dict]) -> None:
    try:
        _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_FILE.write_text(json.dumps(cache, indent=2, sort_keys=True), encoding="utf-8")
    except Exception:
        pass


def _parse_number(value: object) -> float | None:
    raw = str(value or "").strip().replace(",", "")
    if not raw or raw in {"-", "N/A"}:
        return None
    mult = 1.0
    suffix = raw[-1].upper()
    if suffix in {"K", "M", "B", "T"}:
        raw = raw[:-1]
        mult = {
            "K": 1_000.0,
            "M": 1_000_000.0,
            "B": 1_000_000_000.0,
            "T": 1_000_000_000_000.0,
        }[suffix]
    try:
        return float(raw) * mult
    except (TypeError, ValueError):
        return None


def _extract_snapshot_value(html: str, label: str) -> str:
    pattern = re.compile(
        rf">{re.escape(label)}</div></td><td[^>]*><div class=\"snapshot-td-content\">(?:<a [^>]*>)?<b>([^<]+)</b>",
        re.IGNORECASE,
    )
    match = pattern.search(html)
    return match.group(1).strip() if match else ""


def _market_cap_bucket(market_cap_usd: float | None) -> str:
    if not market_cap_usd or market_cap_usd <= 0:
        return "market cap unknown"
    if market_cap_usd < 300_000_000:
        return "micro-cap"
    if market_cap_usd < 2_000_000_000:
        return "small-cap"
    if market_cap_usd < 10_000_000_000:
        return "mid-cap"
    if market_cap_usd < 200_000_000_000:
        return "large-cap"
    return "mega-cap"


def _float_bucket(float_shares: float | None) -> str:
    if not float_shares or float_shares <= 0:
        return "float unknown"
    if float_shares < 15_000_000:
        return "ultra-low float"
    if float_shares < 50_000_000:
        return "low float"
    if float_shares < 200_000_000:
        return "medium float"
    if float_shares < 1_000_000_000:
        return "high float"
    return "very high float"


def _fetch_profile(symbol: str) -> dict:
    try:
        resp = _http.get(
            _PROFILE_URL,
            params={"t": symbol.upper(), "p": "d"},
            headers=_UA,
            timeout=8,
        )
        resp.raise_for_status()
        html = resp.text
    except Exception:
        return {
            "symbol": symbol.upper(),
            "source": "finviz",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "market_cap_usd": None,
            "float_shares": None,
            "avg_volume": None,
            "market_cap_bucket": "market cap unknown",
            "float_bucket": "float unknown",
        }

    market_cap_usd = _parse_number(_extract_snapshot_value(html, "Market Cap"))
    float_shares = _parse_number(_extract_snapshot_value(html, "Shs Float"))
    avg_volume = _parse_number(_extract_snapshot_value(html, "Avg Volume"))
    return {
        "symbol": symbol.upper(),
        "source": "finviz",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "market_cap_usd": market_cap_usd,
        "float_shares": float_shares,
        "avg_volume": avg_volume,
        "market_cap_bucket": _market_cap_bucket(market_cap_usd),
        "float_bucket": _float_bucket(float_shares),
    }


def get_company_profiles(symbols: list[str], max_age_hours: int = 24) -> dict[str, dict]:
    """
    Return cached company-structure profiles for the requested symbols.

    Profiles are refreshed lazily and cached on disk so Belfort's scanner can
    use float and market-cap context without hitting the remote source on every
    refresh tick.
    """
    wanted = [str(sym or "").upper().strip() for sym in symbols if str(sym or "").strip()]
    if not wanted:
        return {}

    cache = _read_cache()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    stale: list[str] = []
    for symbol in wanted:
        entry = cache.get(symbol)
        if not entry:
            stale.append(symbol)
            continue
        try:
            updated = datetime.fromisoformat(str(entry.get("updated_at", "")).replace("Z", "+00:00"))
            if updated < cutoff:
                stale.append(symbol)
        except Exception:
            stale.append(symbol)

    if stale:
        workers = min(6, len(stale))
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            futures = {pool.submit(_fetch_profile, symbol): symbol for symbol in stale}
            for fut in as_completed(futures):
                symbol = futures[fut]
                try:
                    cache[symbol] = fut.result()
                except Exception:
                    cache.setdefault(symbol, {
                        "symbol": symbol,
                        "source": "finviz",
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                        "market_cap_usd": None,
                        "float_shares": None,
                        "avg_volume": None,
                        "market_cap_bucket": "market cap unknown",
                        "float_bucket": "float unknown",
                    })
        _write_cache(cache)

    return {
        symbol: cache.get(symbol, {
            "symbol": symbol,
            "source": "finviz",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "market_cap_usd": None,
            "float_shares": None,
            "avg_volume": None,
            "market_cap_bucket": "market cap unknown",
            "float_bucket": "float unknown",
        })
        for symbol in wanted
    }
