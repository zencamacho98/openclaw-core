import random
import time
from app.mock_trade_task import mock_trade_spy
from app.regime_trade_task import regime_trade_spy

def analyze_spy():
    print("[TASK] analyzing SPY...")
    time.sleep(2)

    price = round(random.uniform(500, 550), 2)
    signal = random.choice(["BUY", "SELL", "HOLD"])

    result = {
        "price": price,
        "signal": signal
    }

    print(f"[RESULT] SPY -> {result}")
    return result


TASK_MAP = {
    "analyze_spy":      analyze_spy,
    "mock_trade_spy":   mock_trade_spy,
    "regime_trade_spy": regime_trade_spy,
}
