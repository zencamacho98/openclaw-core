from __future__ import annotations

import json
import os
import pathlib
from datetime import datetime, timezone

import requests as _http

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_SCANNER_SNAPSHOT = _ROOT / "data" / "belfort" / "scanner_snapshot.json"
_ENV_FILE = _ROOT / ".env"
_NEWS_URL = "https://data.alpaca.markets/v1beta1/news"

_CACHE: dict[str, object] = {"written_at": None, "snapshot": None}

_SEED_UNIVERSE = {
    "benchmarks": ["SPY", "QQQ", "IWM"],
    "liquid_leaders": ["AAPL", "MSFT", "NVDA", "AMD", "TSLA", "META", "AMZN", "GOOGL", "PLTR", "SMCI", "APP", "HOOD", "AFRM"],
    "lower_price_watch": ["SOFI", "RKLB", "IONQ", "SOUN", "ACHR", "QBTS", "LCID", "HIMS", "ASTS", "LUNR", "RGTI", "TEM"],
}
_PAPER_LIQUID_UNIVERSE = set(_SEED_UNIVERSE["benchmarks"] + _SEED_UNIVERSE["liquid_leaders"])

_POSITIVE_KEYWORDS = (
    "earnings", "guidance", "beat", "contract", "approval",
    "partnership", "launch", "revenue", "profit", "buyback",
)
_NEGATIVE_KEYWORDS = (
    "offering", "dilution", "lawsuit", "bankruptcy", "miss",
    "guidance cut", "secondary", "warning",
)
_CATALYST_PATTERNS = (
    ("financing / dilution risk", ("offering", "dilution", "secondary", "atm", "reverse split")),
    ("earnings / numbers", ("earnings", "guidance", "revenue", "profit", "beat", "miss")),
    ("business catalyst", ("contract", "partnership", "approval", "launch", "buyback", "order")),
    ("headline risk", ("lawsuit", "bankruptcy", "guidance cut", "warning", "fraud")),
)
_RISK_FLAG_PATTERNS = (
    ("dilution risk", ("offering", "dilution", "secondary", "atm")),
    ("reverse split risk", ("reverse split",)),
    ("earnings miss risk", ("miss", "guidance cut")),
    ("headline risk", ("lawsuit", "bankruptcy", "warning", "fraud")),
)


def _load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for key in ("ALPACA_API_KEY", "ALPACA_API_SECRET"):
        val = os.getenv(key, "")
        if val:
            env[key] = val
    if _ENV_FILE.exists():
        for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                if k.strip() in ("ALPACA_API_KEY", "ALPACA_API_SECRET"):
                    env.setdefault(k.strip(), v.strip())
    return env


def _safe_float(value: object) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _read_snapshot() -> dict | None:
    if not _SCANNER_SNAPSHOT.exists():
        return None
    try:
        return json.loads(_SCANNER_SNAPSHOT.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_snapshot(snapshot: dict) -> None:
    try:
        _SCANNER_SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
        _SCANNER_SNAPSHOT.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    except Exception:
        pass


def _article_time(article: dict) -> str:
    return str(article.get("updated_at") or article.get("created_at") or "")


def _keyword_bias(text: str) -> int:
    lower = text.lower()
    score = 0
    for word in _POSITIVE_KEYWORDS:
        if word in lower:
            score += 1
    for word in _NEGATIVE_KEYWORDS:
        if word in lower:
            score -= 1
    return score


def fetch_latest_news(limit: int = 12) -> list[dict]:
    cfg = _load_env()
    key = cfg.get("ALPACA_API_KEY", "")
    secret = cfg.get("ALPACA_API_SECRET", "")
    if not (key and secret):
        return []
    try:
        resp = _http.get(
            _NEWS_URL,
            headers={
                "APCA-API-KEY-ID": key,
                "APCA-API-SECRET-KEY": secret,
            },
            params={"limit": limit, "include_content": "false"},
            timeout=8,
        )
        resp.raise_for_status()
        raw = resp.json()
        articles = raw.get("news") if isinstance(raw, dict) else raw
        if not isinstance(articles, list):
            return []
        cleaned = []
        for art in articles[:limit]:
            symbols = [str(sym).upper() for sym in (art.get("symbols") or []) if str(sym).strip()]
            cleaned.append({
                "headline": str(art.get("headline", "")),
                "summary": str(art.get("summary", "")),
                "symbols": symbols,
                "url": str(art.get("url", "")),
                "updated_at": _article_time(art),
                "sentiment_bias": _keyword_bias(" ".join([str(art.get("headline", "")), str(art.get("summary", ""))])),
                "source": str(art.get("source", "")),
            })
        return cleaned
    except Exception:
        return []


def _news_by_symbol(articles: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for art in articles:
        for sym in art.get("symbols", []):
            bucket = out.setdefault(sym, {
                "count": 0,
                "bias": 0,
                "latest_headline": "",
                "latest_at": "",
                "headline_url": "",
            })
            bucket["count"] += 1
            bucket["bias"] += int(art.get("sentiment_bias", 0) or 0)
            if not bucket["latest_at"] or str(art.get("updated_at", "")) > str(bucket["latest_at"]):
                bucket["latest_at"] = art.get("updated_at", "")
                bucket["latest_headline"] = art.get("headline", "")
                bucket["headline_url"] = art.get("url", "")
    return out


def _candidate_symbols(news_map: dict[str, dict]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for group in (_SEED_UNIVERSE["benchmarks"], _SEED_UNIVERSE["liquid_leaders"], _SEED_UNIVERSE["lower_price_watch"], list(news_map.keys())):
        for sym in group:
            sym = str(sym).upper()
            if sym and sym not in seen:
                seen.add(sym)
                ordered.append(sym)
    return ordered[:40]


def _history_map(snapshot: dict | None) -> dict[str, list[dict]]:
    if not snapshot:
        return {}
    history = snapshot.get("history")
    if isinstance(history, dict):
        return {str(sym).upper(): list(rows) for sym, rows in history.items() if isinstance(rows, list)}
    return {}


def _roll_history(rows: list[dict], *, ts: str, mid: float | None) -> list[dict]:
    if mid is None or mid <= 0:
        return rows[-11:]
    nxt = [r for r in rows[-11:] if isinstance(r, dict)]
    nxt.append({"t": ts, "mid": round(mid, 6)})
    return nxt[-12:]


def _tape_delta_pct(rows: list[dict]) -> float | None:
    mids = [_safe_float(r.get("mid")) for r in rows if isinstance(r, dict)]
    mids = [m for m in mids if m and m > 0]
    if len(mids) < 2:
        return None
    start, end = mids[0], mids[-1]
    if not start:
        return None
    return round((end - start) / start, 4)


def _range_expansion_pct(rows: list[dict]) -> float | None:
    mids = [_safe_float(r.get("mid")) for r in rows if isinstance(r, dict)]
    mids = [m for m in mids if m and m > 0]
    if len(mids) < 3:
        return None
    low = min(mids)
    high = max(mids)
    if not low:
        return None
    return round((high - low) / low, 4)


def _price_bucket(symbol: str, mid: float | None) -> str:
    symbol = str(symbol).upper()
    if symbol in _SEED_UNIVERSE["benchmarks"]:
        return "benchmark"
    if symbol in _SEED_UNIVERSE["liquid_leaders"]:
        return "liquid leader"
    if mid is not None and mid <= 25:
        return "lower-price momentum watch"
    return "general watch"


def _human_money(value: float | None) -> str:
    if value is None or value <= 0:
        return "unknown"
    if value >= 1_000_000_000_000:
        return f"${value / 1_000_000_000_000:.2f}T"
    if value >= 1_000_000_000:
        return f"${value / 1_000_000_000:.2f}B"
    if value >= 1_000_000:
        return f"${value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"${value / 1_000:.0f}K"
    return f"${value:.0f}"


def _human_shares(value: float | None) -> str:
    if value is None or value <= 0:
        return "unknown"
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f}B"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value / 1_000:.0f}K"
    return f"{value:.0f}"


def _volatility_profile(candidate: dict) -> str:
    tape_delta = abs(_safe_float(candidate.get("tape_delta_pct")) or 0.0)
    range_pct = _safe_float(candidate.get("range_expansion_pct")) or 0.0
    gap_pct = abs(_safe_float(candidate.get("gap_pct")) or 0.0)
    float_bucket = str(candidate.get("float_bucket", "float unknown"))
    price_bucket = str(candidate.get("price_bucket", "general watch"))
    if "ultra-low float" in float_bucket:
        return "very high volatility"
    if tape_delta >= 0.08 or range_pct >= 0.08 or gap_pct >= 0.12:
        return "very high volatility"
    if "low float" in float_bucket or price_bucket == "lower-price momentum watch" or tape_delta >= 0.04 or range_pct >= 0.04 or gap_pct >= 0.05:
        return "high volatility"
    if tape_delta >= 0.015 or range_pct >= 0.02:
        return "moderate volatility"
    return "steady volatility"


def _tradeability(candidate: dict) -> str:
    spread_pct = _safe_float(candidate.get("spread_pct"))
    lane = str(candidate.get("data_lane", "UNKNOWN"))
    if spread_pct is None:
        return "quote quality unclear"
    if spread_pct > 0.02:
        return "hard to trade cleanly"
    if spread_pct > 0.01:
        return "trade carefully"
    if lane == "UNKNOWN":
        return "tradeable but feed is limited"
    if spread_pct <= 0.002:
        return "clean book"
    return "acceptable book"


def _structure_label(candidate: dict) -> str:
    market_cap_bucket = str(candidate.get("market_cap_bucket", "market cap unknown"))
    float_bucket = str(candidate.get("float_bucket", "float unknown"))
    market_cap_usd = _safe_float(candidate.get("market_cap_usd"))
    float_shares = _safe_float(candidate.get("float_shares"))
    parts = [market_cap_bucket, float_bucket]
    if market_cap_usd:
        parts.append(_human_money(market_cap_usd) + " market cap")
    if float_shares:
        parts.append(_human_shares(float_shares) + " float")
    return " · ".join(parts)


def _flow_label(candidate: dict) -> str:
    rel_volume = _safe_float(candidate.get("relative_volume"))
    gap_pct = _safe_float(candidate.get("gap_pct"))
    float_turnover_pct = _safe_float(candidate.get("float_turnover_pct"))
    parts: list[str] = []
    if rel_volume is not None:
        if rel_volume >= 3:
            parts.append(f"{rel_volume:.1f}x relative volume")
        elif rel_volume >= 1:
            parts.append(f"{rel_volume:.1f}x relative volume")
        else:
            parts.append(f"{rel_volume:.1f}x relative volume")
    if gap_pct is not None:
        parts.append(f"{gap_pct * 100:+.1f}% gap")
    if float_turnover_pct is not None:
        parts.append(f"{float_turnover_pct * 100:.2f}% float turnover")
    return " · ".join(parts)


def _preopen_opportunity_score(candidate: dict) -> float:
    """
    Score how attractive a symbol looks for pre-open / opening-drive attention.

    This is not a prediction score. It is a ranking helper that favors names with:
    - meaningful gap context
    - strong relative volume
    - enough float turnover to matter
    - relative strength versus SPY
    - acceptable spread / quote quality
    - fresh catalysts
    """
    score = 0.0
    gap_pct = abs(_safe_float(candidate.get("gap_pct")) or 0.0)
    rel_vol = _safe_float(candidate.get("relative_volume")) or 0.0
    float_turn = _safe_float(candidate.get("float_turnover_pct")) or 0.0
    rel_vs_spy = _safe_float(candidate.get("relative_strength_vs_spy_pct")) or 0.0
    spread_pct = _safe_float(candidate.get("spread_pct"))
    news_count = int(candidate.get("news_count", 0) or 0)
    risk_flags = list(candidate.get("risk_flags") or [])
    data_lane = str(candidate.get("data_lane", "UNKNOWN"))
    session = str(candidate.get("scanner_session", "unknown"))

    if rel_vol >= 4.0:
        score += 3.0
    elif rel_vol >= 2.0:
        score += 2.0
    elif rel_vol >= 1.0:
        score += 1.0
    elif rel_vol < 0.6:
        score -= 1.0

    if 0.02 <= gap_pct <= 0.12:
        score += 2.25
    elif 0.01 <= gap_pct < 0.02:
        score += 1.0
    elif gap_pct >= 0.18:
        score -= 1.0

    if float_turn >= 0.01:
        score += 2.0
    elif float_turn >= 0.003:
        score += 1.0
    elif float_turn < 0.0005:
        score -= 0.75

    if rel_vs_spy >= 0.01:
        score += 1.75
    elif rel_vs_spy >= 0.004:
        score += 0.9
    elif rel_vs_spy <= -0.01:
        score -= 0.9

    if spread_pct is not None:
        if spread_pct <= 0.002:
            score += 1.0
        elif spread_pct <= 0.006:
            score += 0.5
        elif spread_pct > 0.02:
            score -= 2.0

    score += min(news_count, 3) * 0.4
    score -= min(len(risk_flags), 3) * 0.6
    if data_lane == "UNKNOWN":
        score -= 0.5

    # Session-aware weighting:
    # - pre-market favors gap + flow more heavily
    # - regular session favors sustained relative strength
    # - after-hours is tradable but less trustworthy for opening-drive ranking
    if session == "pre_market":
        if gap_pct >= 0.015:
            score += 1.0
        if rel_vol >= 1.5:
            score += 0.75
    elif session == "regular":
        if rel_vs_spy >= 0.004:
            score += 0.6
        if float_turn >= 0.003:
            score += 0.35
    elif session == "after_hours":
        score -= 0.35

    return round(score, 2)


def _catalyst_summary(candidate: dict) -> str:
    headline = str(candidate.get("latest_headline", "")).strip()
    count = int(candidate.get("news_count", 0) or 0)
    bias = int(candidate.get("news_bias", 0) or 0)
    if count <= 0:
        return "no fresh company catalyst"
    if headline:
        prefix = "positive catalyst" if bias > 0 else "negative catalyst" if bias < 0 else "fresh catalyst"
        return f"{prefix}: {headline[:84]}"
    return f"{count} fresh catalyst headline(s)"


def _catalyst_type(candidate: dict) -> str:
    text = " ".join([
        str(candidate.get("latest_headline", "")),
        str(candidate.get("catalyst_summary", "")),
    ]).lower()
    if not text.strip() or int(candidate.get("news_count", 0) or 0) <= 0:
        return "no fresh catalyst"
    for label, patterns in _CATALYST_PATTERNS:
        if any(term in text for term in patterns):
            return label
    return "headline catalyst"


def _risk_flags(candidate: dict) -> list[str]:
    text = " ".join([
        str(candidate.get("latest_headline", "")),
        str(candidate.get("catalyst_summary", "")),
    ]).lower()
    if not text.strip():
        return []
    flags: list[str] = []
    for label, patterns in _RISK_FLAG_PATTERNS:
        if any(term in text for term in patterns):
            flags.append(label)
    return flags


def _relative_strength_label(symbol: str, relative_vs_spy: float | None) -> str:
    symbol = str(symbol).upper()
    if symbol == "SPY":
        return "broad tape baseline"
    if symbol == "QQQ":
        return "tech tape baseline"
    if symbol == "IWM":
        return "small-cap tape baseline"
    if relative_vs_spy is None:
        return "relative strength unclear"
    if relative_vs_spy >= 0.01:
        return "leading SPY"
    if relative_vs_spy >= 0.004:
        return "slightly stronger than SPY"
    if relative_vs_spy <= -0.01:
        return "lagging SPY"
    if relative_vs_spy <= -0.004:
        return "slightly weaker than SPY"
    return "moving with SPY"


def _quote_score(candidate: dict) -> float:
    score = 0.0
    mid = _safe_float(candidate.get("mid"))
    spread_pct = _safe_float(candidate.get("spread_pct"))
    tape_delta = _safe_float(candidate.get("tape_delta_pct"))
    range_pct = _safe_float(candidate.get("range_expansion_pct"))
    relative_vs_spy = _safe_float(candidate.get("relative_strength_vs_spy_pct"))
    news_count = int(candidate.get("news_count", 0) or 0)
    news_bias = int(candidate.get("news_bias", 0) or 0)
    is_live = bool(candidate.get("is_live"))
    risk_flags = list(candidate.get("risk_flags") or [])
    market_cap_usd = _safe_float(candidate.get("market_cap_usd"))
    float_shares = _safe_float(candidate.get("float_shares"))
    avg_volume = _safe_float(candidate.get("avg_volume"))
    relative_volume = _safe_float(candidate.get("relative_volume"))
    gap_pct = _safe_float(candidate.get("gap_pct"))
    float_turnover_pct = _safe_float(candidate.get("float_turnover_pct"))

    if mid and mid > 0:
        score += 1.5
        if 2 <= mid <= 25:
            score += 1.5
        elif mid < 2:
            score -= 1.0
        elif mid > 200:
            score -= 0.5

    if spread_pct is not None:
        if spread_pct <= 0.002:
            score += 2.0
        elif spread_pct <= 0.006:
            score += 1.0
        elif spread_pct > 0.02:
            score -= 3.0
        elif spread_pct > 0.01:
            score -= 1.5

    if tape_delta is not None:
        if tape_delta > 0:
            score += min(tape_delta * 140, 5.0)
        else:
            score += max(tape_delta * 80, -2.0)

    if range_pct is not None:
        if range_pct >= 0.02:
            score += 1.5
        elif range_pct >= 0.01:
            score += 0.75

    if relative_vs_spy is not None:
        if relative_vs_spy > 0:
            score += min(relative_vs_spy * 180, 2.5)
        else:
            score += max(relative_vs_spy * 120, -1.75)

    score += min(news_count * 1.5, 6.0)
    score += max(min(news_bias, 3), -3) * 0.75
    score -= min(len(risk_flags) * 0.85, 2.55)
    if market_cap_usd is not None:
        if 300_000_000 <= market_cap_usd < 2_000_000_000:
            score += 1.25
        elif 2_000_000_000 <= market_cap_usd < 10_000_000_000:
            score += 0.75
        elif market_cap_usd < 150_000_000:
            score -= 1.0
        elif market_cap_usd > 300_000_000_000:
            score -= 0.4
    if float_shares is not None:
        if 15_000_000 <= float_shares < 50_000_000:
            score += 1.5
        elif 50_000_000 <= float_shares < 200_000_000:
            score += 0.9
        elif float_shares < 10_000_000:
            score -= 1.25
        elif float_shares > 2_000_000_000:
            score -= 0.35
    if avg_volume is not None:
        if avg_volume >= 10_000_000:
            score += 1.0
        elif avg_volume >= 2_000_000:
            score += 0.6
        elif avg_volume < 500_000:
            score -= 1.1
    if relative_volume is not None:
        if relative_volume >= 3.0:
            score += 2.25
        elif relative_volume >= 1.5:
            score += 1.5
        elif relative_volume >= 1.0:
            score += 0.75
        elif relative_volume < 0.5:
            score -= 1.25
    if gap_pct is not None:
        if 0.02 <= gap_pct <= 0.12:
            score += 1.5
        elif 0.005 <= gap_pct < 0.02:
            score += 0.65
        elif gap_pct >= 0.18:
            score -= 1.25
        elif gap_pct <= -0.04:
            score -= 0.6
    if float_turnover_pct is not None:
        if float_turnover_pct >= 0.01:
            score += 1.5
        elif float_turnover_pct >= 0.003:
            score += 0.75
        elif float_turnover_pct < 0.0005:
            score -= 0.75
    if not is_live:
        score -= 1.5
    return round(score, 2)


def _strategy_fit(candidate: dict) -> str:
    score = float(candidate.get("score", 0.0) or 0.0)
    spread_pct = _safe_float(candidate.get("spread_pct"))
    tape_delta = _safe_float(candidate.get("tape_delta_pct")) or 0.0
    range_pct = _safe_float(candidate.get("range_expansion_pct")) or 0.0
    relative_vs_spy = _safe_float(candidate.get("relative_strength_vs_spy_pct")) or 0.0
    news_count = int(candidate.get("news_count", 0) or 0)
    news_bias = int(candidate.get("news_bias", 0) or 0)
    catalyst_type = str(candidate.get("catalyst_type", ""))
    risk_flags = list(candidate.get("risk_flags") or [])
    relative_volume = _safe_float(candidate.get("relative_volume")) or 0.0
    gap_pct = _safe_float(candidate.get("gap_pct")) or 0.0
    float_turnover_pct = _safe_float(candidate.get("float_turnover_pct")) or 0.0
    if spread_pct is not None and spread_pct > 0.02:
        return "avoid — spread too wide"
    if "dilution risk" in risk_flags and tape_delta > 0:
        return "dilution squeeze watch"
    if gap_pct >= 0.03 and relative_volume >= 1.5 and relative_vs_spy > 0.004:
        return "gap-and-go watch"
    if relative_volume >= 2.0 and float_turnover_pct >= 0.003 and relative_vs_spy > 0.004 and tape_delta > 0.008:
        return "volume leader watch"
    if news_count > 0 and abs(tape_delta) < 0.004:
        return "news setup watch"
    if catalyst_type == "business catalyst" and relative_vs_spy > 0.004 and tape_delta > 0.008:
        return "business catalyst momentum watch"
    if news_count > 0 and news_bias > 0 and relative_vs_spy > 0.004 and tape_delta > 0.01:
        return "news-backed momentum watch"
    if news_count > 0 and tape_delta < -0.01:
        return "news-fade watch"
    if score >= 6 and relative_vs_spy > 0.004 and tape_delta > 0.012 and range_pct >= 0.01:
        return "relative strength breakout watch"
    if score >= 6 and tape_delta > 0.012 and range_pct >= 0.01:
        return "trend continuation watch"
    if score >= 6 and tape_delta > 0:
        return "momentum watch"
    if relative_vs_spy <= -0.006 and tape_delta < 0:
        return "weak tape / fade watch"
    if abs(tape_delta) <= 0.004 and range_pct <= 0.008:
        return "mean reversion watch"
    if tape_delta < -0.01:
        return "fade / mean reversion watch"
    return "monitor only"


def _board_note(candidate: dict) -> str:
    mid = _safe_float(candidate.get("mid"))
    mid_text = _human_money(mid) if mid is not None else "No live quote"
    relative_label = str(candidate.get("relative_strength_label", "relative strength unclear"))
    catalyst_summary = str(candidate.get("catalyst_summary", "no fresh company catalyst"))
    structure = _structure_label(candidate)
    flow = _flow_label(candidate)
    volatility = str(candidate.get("volatility_profile", "steady volatility"))
    tradeability = str(candidate.get("tradeability_reason") or _tradeability(candidate))
    setup = str(candidate.get("strategy_fit", "monitor only"))
    return (
        f"{mid_text}. {setup}. {volatility}. {structure}. "
        f"{flow}. "
        f"{tradeability}. {relative_label}. {catalyst_summary}"
    )


def _paper_tradeability(candidate: dict) -> tuple[bool, str, str]:
    from app.strategy.config import get_config

    cfg = get_config()
    symbol = str(candidate.get("symbol", "")).upper()
    spread_pct = _safe_float(candidate.get("spread_pct"))
    mid = _safe_float(candidate.get("mid"))
    data_lane = str(candidate.get("data_lane", "UNKNOWN"))
    is_live = bool(candidate.get("is_live"))
    risk_flags = list(candidate.get("risk_flags") or [])
    score = float(candidate.get("score", 0.0) or 0.0)
    tape_delta = abs(_safe_float(candidate.get("tape_delta_pct")) or 0.0)
    market_cap_usd = _safe_float(candidate.get("market_cap_usd"))
    float_shares = _safe_float(candidate.get("float_shares"))
    avg_volume = _safe_float(candidate.get("avg_volume"))
    relative_volume = _safe_float(candidate.get("relative_volume"))
    float_turnover_pct = _safe_float(candidate.get("float_turnover_pct"))
    min_market_cap = float(cfg.get("BELFORT_MIN_MARKET_CAP_USD", 300_000_000.0) or 300_000_000.0)
    min_float = float(cfg.get("BELFORT_MIN_FLOAT_SHARES", 15_000_000.0) or 15_000_000.0)
    min_avg_volume = float(cfg.get("BELFORT_MIN_AVG_VOLUME", 800_000.0) or 800_000.0)
    min_relative_volume = float(cfg.get("BELFORT_MIN_RELATIVE_VOLUME", 0.8) or 0.8)
    min_float_turnover = float(cfg.get("BELFORT_MIN_FLOAT_TURNOVER_PCT", 0.001) or 0.001)
    max_volatile_spread = float(cfg.get("BELFORT_MAX_VOLATILE_SPREAD_PCT", 0.015) or 0.015)
    max_volatile_tape = float(cfg.get("BELFORT_MAX_VOLATILE_TAPE_PCT", 0.18) or 0.18)

    in_expanded_dynamic_universe = (
        symbol not in _PAPER_LIQUID_UNIVERSE
        and mid is not None
        and mid >= 2.0
        and spread_pct is not None
        and spread_pct <= max_volatile_spread
        and score >= 2.25
        and tape_delta <= max_volatile_tape
        and market_cap_usd is not None
        and market_cap_usd >= min_market_cap
        and float_shares is not None
        and float_shares >= min_float
        and avg_volume is not None
        and avg_volume >= min_avg_volume
        and (relative_volume is not None and relative_volume >= min_relative_volume)
        and (float_turnover_pct is not None and float_turnover_pct >= min_float_turnover)
    )

    if symbol not in _PAPER_LIQUID_UNIVERSE and not in_expanded_dynamic_universe:
        if market_cap_usd is None or float_shares is None:
            return False, "watch_only", "Watch only for now — company structure data is still loading."
        if market_cap_usd < min_market_cap:
            return False, "watch_only", "Watch only for now — market cap is still too small for Belfort's current paper phase."
        if float_shares < min_float:
            return False, "watch_only", "Watch only for now — float is still too tight for Belfort's current paper phase."
        if avg_volume is not None and avg_volume < min_avg_volume:
            return False, "watch_only", "Watch only for now — average volume is still too thin for Belfort's paper lane."
        if relative_volume is not None and relative_volume < min_relative_volume:
            return False, "watch_only", "Watch only for now — relative volume is still too soft for Belfort's paper lane."
        if float_turnover_pct is not None and float_turnover_pct < min_float_turnover:
            return False, "watch_only", "Watch only for now — float turnover is still too low for Belfort's paper lane."
        return False, "watch_only", "Watch only for now — not yet clean enough for Belfort's paper lane."
    if not is_live or data_lane == "UNKNOWN":
        return False, "blocked", "Blocked for now — Belfort still needs a cleaner live quote."
    if mid is None or mid <= 0:
        return False, "blocked", "Blocked for now — no valid mid price yet."
    if spread_pct is None:
        return False, "blocked", "Blocked for now — spread quality is still unclear."
    if spread_pct > max_volatile_spread:
        return False, "blocked", "Blocked for now — spread is too wide for this paper phase."
    if any(flag in risk_flags for flag in ("dilution risk", "reverse split risk")):
        return False, "blocked", "Blocked for now — headline risk is too high for this paper phase."
    if tape_delta > max_volatile_tape:
        return False, "blocked", "Blocked for now — price action is too unstable for a fresh paper entry."
    if in_expanded_dynamic_universe:
        return True, "eligible", "Eligible for paper trading in Belfort's expanded liquid-volatility universe."
    return True, "eligible", "Eligible for paper trading in Belfort's liquid Phase 1 universe."


def refresh_scanner_snapshot(max_age_seconds: int = 45) -> dict:
    now = datetime.now(timezone.utc)
    cached = _CACHE.get("snapshot")
    written_at = str(_CACHE.get("written_at") or "")
    if cached and written_at:
        try:
            age = (now - datetime.fromisoformat(written_at)).total_seconds()
            if age <= max_age_seconds:
                return cached  # type: ignore[return-value]
        except Exception:
            pass

    previous = _read_snapshot()
    history = _history_map(previous)
    news = fetch_latest_news(limit=12)
    news_map = _news_by_symbol(news)
    symbols = _candidate_symbols(news_map)
    try:
        from app.market_data_feed import get_multi_symbol_bar_context
        bar_context = get_multi_symbol_bar_context(symbols, intraday_timeframe="10Min", intraday_limit=24)
    except Exception:
        bar_context = {}
    try:
        from app.market_time import session_type as _session_type
        scanner_session = str(_session_type() or "unknown")
    except Exception:
        scanner_session = "unknown"
    try:
        from app.company_profile_feed import get_company_profiles
        profile_map = get_company_profiles(symbols, max_age_hours=24)
    except Exception:
        profile_map = {}
    candidates = []
    timestamp = now.isoformat()

    from app.market_data_feed import get_quote

    for symbol in symbols:
        quote = get_quote(symbol)
        mid = _safe_float(getattr(quote, "midpoint", None))
        history[symbol] = _roll_history(history.get(symbol, []), ts=timestamp, mid=mid)
        tape_delta = _tape_delta_pct(history[symbol])
        range_pct = _range_expansion_pct(history[symbol])
        news_bucket = news_map.get(symbol, {})
        profile = profile_map.get(symbol, {})
        bar_ctx = bar_context.get(symbol, {})
        recent_volume = _safe_float(bar_ctx.get("recent_volume"))
        avg_volume = _safe_float(profile.get("avg_volume"))
        bar_count = int(bar_ctx.get("bar_count", 0) or 0)
        relative_volume = None
        if avg_volume and bar_count > 0:
            expected_recent_volume = avg_volume * min(bar_count, 39) / 39.0
            if expected_recent_volume > 0:
                relative_volume = round(recent_volume / expected_recent_volume, 3) if recent_volume is not None else None
        float_shares = _safe_float(profile.get("float_shares"))
        float_turnover_pct = None
        if recent_volume is not None and float_shares and float_shares > 0:
            float_turnover_pct = round(recent_volume / float_shares, 5)
        candidate = {
            "symbol": symbol,
            "last": _safe_float(getattr(quote, "last", None)),
            "mid": mid,
            "bid": _safe_float(getattr(quote, "bid", None)),
            "ask": _safe_float(getattr(quote, "ask", None)),
            "spread_pct": _safe_float(getattr(quote, "spread_pct", None)),
            "data_lane": str(getattr(quote, "data_lane", "UNKNOWN")),
            "is_live": bool(getattr(quote, "is_live", False)),
            "source": str(getattr(quote, "source", "")),
            "tape_delta_pct": tape_delta,
            "range_expansion_pct": range_pct,
            "news_count": int(news_bucket.get("count", 0) or 0),
            "news_bias": int(news_bucket.get("bias", 0) or 0),
            "latest_headline": str(news_bucket.get("latest_headline", "")),
            "latest_headline_at": str(news_bucket.get("latest_at", "")),
            "headline_url": str(news_bucket.get("headline_url", "")),
            "market_cap_usd": _safe_float(profile.get("market_cap_usd")),
            "market_cap_bucket": str(profile.get("market_cap_bucket", "market cap unknown")),
            "float_shares": float_shares,
            "float_bucket": str(profile.get("float_bucket", "float unknown")),
            "avg_volume": avg_volume,
            "recent_volume": recent_volume,
            "relative_volume": relative_volume,
            "float_turnover_pct": float_turnover_pct,
            "gap_pct": _safe_float(bar_ctx.get("gap_pct")),
            "intraday_change_pct": _safe_float(bar_ctx.get("intraday_change_pct")),
            "intraday_bar_count": bar_count,
            "scanner_session": scanner_session,
        }
        candidates.append(candidate)

    benchmark_map = {str(item.get("symbol", "")).upper(): item for item in candidates}
    spy_delta = _safe_float((benchmark_map.get("SPY") or {}).get("tape_delta_pct"))
    for candidate in candidates:
        symbol = str(candidate.get("symbol", "")).upper()
        tape_delta = _safe_float(candidate.get("tape_delta_pct"))
        relative_vs_spy = None
        if symbol not in _SEED_UNIVERSE["benchmarks"] and tape_delta is not None and spy_delta is not None:
            relative_vs_spy = round(tape_delta - spy_delta, 4)
        candidate["relative_strength_vs_spy_pct"] = relative_vs_spy
        candidate["relative_strength_label"] = _relative_strength_label(symbol, relative_vs_spy)
        candidate["price_bucket"] = _price_bucket(symbol, _safe_float(candidate.get("mid")))
        candidate["catalyst_summary"] = _catalyst_summary(candidate)
        candidate["catalyst_type"] = _catalyst_type(candidate)
        candidate["risk_flags"] = _risk_flags(candidate)
        candidate["structure_label"] = _structure_label(candidate)
        candidate["volatility_profile"] = _volatility_profile(candidate)
        candidate["tradeability"] = _tradeability(candidate)
        candidate["score"] = _quote_score(candidate)
        candidate["opportunity_score"] = _preopen_opportunity_score(candidate)
        candidate["strategy_fit"] = _strategy_fit(candidate)
        paper_eligible, tradeability_label, tradeability_reason = _paper_tradeability(candidate)
        candidate["paper_eligible"] = paper_eligible
        candidate["tradeability_label"] = tradeability_label
        candidate["tradeability_reason"] = tradeability_reason
        candidate["board_note"] = _board_note(candidate)

    candidates.sort(
        key=lambda item: (
            float(item.get("score", 0.0) or 0.0),
            float(item.get("opportunity_score", 0.0) or 0.0),
            int(item.get("news_count", 0) or 0),
        ),
        reverse=True,
    )
    non_bench = [c for c in candidates if c["symbol"] not in _SEED_UNIVERSE["benchmarks"]]
    lower_price_watch = [c for c in candidates if (_safe_float(c.get("mid")) or 999) <= 25][:6]
    top_candidates = non_bench[:6] or candidates[:6]
    focus = top_candidates[0] if top_candidates else {"symbol": "SPY", "strategy_fit": "monitor only", "score": 0.0}
    paper_eligible_candidates = [c for c in candidates if c.get("paper_eligible")]
    paper_focus = paper_eligible_candidates[0] if paper_eligible_candidates else None
    relative_volume_leaders = sorted(
        [c for c in candidates if _safe_float(c.get("relative_volume")) is not None],
        key=lambda item: float(item.get("relative_volume", 0.0) or 0.0),
        reverse=True,
    )[:5]
    gap_leaders = sorted(
        [c for c in candidates if _safe_float(c.get("gap_pct")) is not None],
        key=lambda item: abs(float(item.get("gap_pct", 0.0) or 0.0)),
        reverse=True,
    )[:5]
    preopen_leaders = sorted(
        candidates,
        key=lambda item: (
            float(item.get("opportunity_score", 0.0) or 0.0),
            float(item.get("score", 0.0) or 0.0),
        ),
        reverse=True,
    )[:6]

    snapshot = {
        "written_at": timestamp,
        "focus_symbol": focus.get("symbol", "SPY"),
        "focus_reason": (
            f"{focus.get('symbol', 'SPY')} leads the board with score {focus.get('score', 0)} "
            f"and opening-drive score {focus.get('opportunity_score', 0)} "
            f"with setup bias '{focus.get('strategy_fit', 'monitor only')}'. "
            f"{focus.get('relative_strength_label', 'relative strength unclear')}. "
            f"{focus.get('tradeability', 'tradeability unclear')}. "
            f"{focus.get('catalyst_summary', '')}"
        ),
        "paper_eligible_focus_symbol": (paper_focus or {}).get("symbol", ""),
        "paper_eligible_focus_reason": (
            ""
            if not paper_focus else
            f"{paper_focus.get('symbol', 'SPY')} is Belfort's current paper-eligible name. "
            f"{paper_focus.get('tradeability_reason', '')}"
        ),
        "paper_eligible_count": len(paper_eligible_candidates),
        "scanner_note": (
            "Belfort now ranks a freer market board using quote quality, short tape momentum, range expansion, "
            "relative strength versus SPY, catalysts, float, market cap, average volume, relative volume, and gap context. Paper eligibility is still stricter than research ranking."
        ),
        "selection_framework": [
            "quote quality",
            "tape momentum",
            "range expansion",
            "relative strength vs SPY",
            "fresh catalysts",
            "catalyst type / risk flags",
            "float",
            "market cap",
            "average volume",
            "relative volume",
            "gap context",
            "float turnover",
            "price bucket",
        ],
        "leaders": top_candidates,
        "relative_volume_leaders": relative_volume_leaders,
        "gap_leaders": gap_leaders,
        "preopen_leaders": preopen_leaders,
        "benchmarks": [c for c in candidates if c["symbol"] in _SEED_UNIVERSE["benchmarks"]][:3],
        "lower_price_watch": lower_price_watch,
        "catalysts": news[:6],
        "universe_size": len(candidates),
        "limitations": [
            "Scanner uses live quotes, Alpaca news, and cached company-structure data. It is a ranking engine, not a prediction oracle.",
            "Paper trading remains long-only and more selective than research ranking. Some volatile names can now become paper-eligible, but ultra-low-float and micro-cap names remain watch-only.",
            "If structure or intraday flow data is missing, Belfort falls back to watch-only rather than guessing.",
        ],
        "history": history,
    }
    _write_snapshot(snapshot)
    _CACHE["written_at"] = timestamp
    _CACHE["snapshot"] = snapshot
    return snapshot


def read_scanner_snapshot(max_age_seconds: int = 75) -> dict:
    snapshot = _read_snapshot()
    if not snapshot:
        return refresh_scanner_snapshot(max_age_seconds=0)
    written_at = str(snapshot.get("written_at", ""))
    if written_at:
        try:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(written_at)).total_seconds()
            if age <= max_age_seconds:
                return snapshot
        except Exception:
            pass
    return refresh_scanner_snapshot(max_age_seconds=0)


def lookup_candidate(symbol: str, max_age_seconds: int = 75) -> dict | None:
    symbol = str(symbol or "").upper().strip()
    if not symbol:
        return None
    try:
        snapshot = read_scanner_snapshot(max_age_seconds=max_age_seconds)
    except Exception:
        return None
    for bucket in ("leaders", "benchmarks", "lower_price_watch"):
        for item in snapshot.get(bucket, []) or []:
            if str(item.get("symbol", "")).upper() == symbol:
                return item
    return None


def get_focus_symbol(default: str = "SPY") -> str:
    try:
        snap = read_scanner_snapshot()
        symbol = str(snap.get("focus_symbol", "")).upper().strip()
        return symbol or default
    except Exception:
        return default


def get_paper_trade_symbol(default: str = "SPY") -> str:
    try:
        snap = read_scanner_snapshot()
        symbol = str(snap.get("paper_eligible_focus_symbol", "")).upper().strip()
        if symbol:
            return symbol
        return get_focus_symbol(default=default)
    except Exception:
        return default
