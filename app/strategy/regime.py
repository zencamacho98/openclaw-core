# app/strategy/regime.py
#
# Market regime detector using the Kaufman Efficiency Ratio (ER).
#
# Intuition:
#   A trending market moves directionally — net displacement is large relative
#   to the sum of all individual moves.
#   A ranging market oscillates — many moves cancel out, so net displacement
#   is small relative to total path length.
#
#   ER = net_displacement / total_path_length
#   ER → 1.0  : perfectly trending (straight-line move)
#   ER → 0.0  : perfectly ranging (random walk around a mean)
#
# Interpretation:
#   ER >= REGIME_THRESHOLD → TRENDING  → use MA crossover
#   ER <  REGIME_THRESHOLD → RANGING   → use mean reversion

from app.strategy.config import get_config

TRENDING = "trending"
RANGING  = "ranging"


def detect(prices: list[float]) -> str:
    """
    Classify recent price action as 'trending' or 'ranging'.

    Defaults to RANGING when data is insufficient — fewer trades is the
    safer default while the system is warming up.
    """
    cfg       = get_config()
    window    = int(cfg.get("REGIME_WINDOW", 20))
    threshold = float(cfg.get("REGIME_THRESHOLD", 0.3))

    if len(prices) < window + 1:
        return RANGING

    recent     = prices[-(window + 1):]
    net_move   = abs(recent[-1] - recent[0])
    total_path = sum(abs(recent[i] - recent[i - 1]) for i in range(1, len(recent)))

    if total_path == 0.0:
        return RANGING

    er = net_move / total_path
    return TRENDING if er >= threshold else RANGING


def efficiency_ratio(prices: list[float]) -> float | None:
    """
    Return the raw Efficiency Ratio for the price series, or None if too short.
    Useful for monitoring and experiment analysis.
    """
    cfg    = get_config()
    window = int(cfg.get("REGIME_WINDOW", 20))

    if len(prices) < window + 1:
        return None

    recent     = prices[-(window + 1):]
    net_move   = abs(recent[-1] - recent[0])
    total_path = sum(abs(recent[i] - recent[i - 1]) for i in range(1, len(recent)))

    if total_path == 0.0:
        return 0.0

    return round(net_move / total_path, 4)
