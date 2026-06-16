import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from qlib_vnpy_platform.config import load_config
from qlib_vnpy_platform.core.main_engine import TradingEngine


def test_trading_engine_init():
    load_config()
    engine = TradingEngine(load_persistence=False)
    account = engine.account
    assert account["total_capital"] == 1000000, "Initial capital should be 1M"
    assert account["cash"] == 1000000, "Initial cash should be 1M"
    print(f"[PASS] Trading engine init test: capital={account['total_capital']}")


def test_buy_order():
    load_config()
    engine = TradingEngine(load_persistence=False)

    order = {
        "symbol": "SZ000001",
        "direction": "BUY",
        "volume": 1000,
        "price": 12.5,
    }
    result = engine.execute_order(order)
    assert result["status"] == "FILLED", f"Buy should be filled: {result}"

    positions = engine.get_positions()
    assert "SZ000001" in positions, "Should have SZ000001 position"
    assert positions["SZ000001"]["volume"] == 1000, "Volume should be 1000"

    account = engine.account
    assert account["cash"] < 1000000, "Cash should decrease after buy"
    print(f"[PASS] Buy order test: volume={positions['SZ000001']['volume']}, "
          f"cash={account['cash']:.2f}")


def test_sell_order():
    load_config()
    engine = TradingEngine(load_persistence=False)

    buy_order = {
        "symbol": "SZ000001",
        "direction": "BUY",
        "volume": 1000,
        "price": 12.0,
    }
    engine.execute_order(buy_order)

    sell_order = {
        "symbol": "SZ000001",
        "direction": "SELL",
        "volume": 500,
        "price": 13.0,
    }
    result = engine.execute_order(sell_order)
    assert result["status"] == "FILLED", f"Sell should be filled: {result}"

    positions = engine.get_positions()
    assert positions["SZ000001"]["volume"] == 500, "Remaining volume should be 500"

    trades = engine.get_trades()
    assert len(trades) >= 2, "Should have at least 2 trades"
    print(f"[PASS] Sell order test: remaining={positions['SZ000001']['volume']}, "
          f"trades={len(trades)}")


def test_insufficient_funds():
    load_config()
    engine = TradingEngine(load_persistence=False)

    order = {
        "symbol": "SZ000001",
        "direction": "BUY",
        "volume": 1000000,
        "price": 12.5,
    }
    result = engine.execute_order(order)
    assert result["status"] == "FILLED", "Should auto-adjust volume"
    positions = engine.get_positions()
    if "SZ000001" in positions:
        assert positions["SZ000001"]["volume"] < 1000000, "Volume should be adjusted down"
        print(f"[PASS] Insufficient funds test: adjusted to {positions['SZ000001']['volume']}")
    else:
        print("[PASS] Insufficient funds test: order rejected")


def test_sell_no_position():
    load_config()
    engine = TradingEngine(load_persistence=False)

    order = {
        "symbol": "SH600000",
        "direction": "SELL",
        "volume": 1000,
        "price": 10.0,
    }
    result = engine.execute_order(order)
    assert result["status"] == "FAILED", "Should fail to sell with no position"
    print(f"[PASS] Sell no position test: {result['reason']}")


def test_hold_order():
    load_config()
    engine = TradingEngine(load_persistence=False)

    order = {
        "symbol": "SZ000001",
        "direction": "HOLD",
        "volume": 0,
        "price": 12.5,
    }
    result = engine.execute_order(order)
    assert result["status"] == "SKIPPED", "HOLD should be skipped"
    print("[PASS] Hold order test")


if __name__ == "__main__":
    test_trading_engine_init()
    test_buy_order()
    test_sell_order()
    test_insufficient_funds()
    test_sell_no_position()
    test_hold_order()
    print("\n=== All TradingEngine tests passed ===")
