from __future__ import annotations

from unittest.mock import patch


def test_monitor_chart_returns_bars_and_change():
    from app.routes.monitor import chart

    bars = [
        {"t": "2026-04-14T09:30:00Z", "open": 100.0, "high": 101.0, "low": 99.5, "close": 100.5, "volume": 1000},
        {"t": "2026-04-14T09:35:00Z", "open": 100.5, "high": 101.5, "low": 100.2, "close": 101.2, "volume": 1200},
    ]
    with patch("app.market_data_feed.get_recent_bars", return_value=bars):
        result = chart(symbol="spy", timeframe="5Min", limit=2)
    assert result["symbol"] == "SPY"
    assert result["timeframe"] == "5Min"
    assert result["bar_count"] == 2
    assert result["last_close"] == 101.2
    assert result["change"] == 0.7
