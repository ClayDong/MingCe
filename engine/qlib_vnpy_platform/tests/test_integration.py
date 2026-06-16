import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from qlib_vnpy_platform.config import load_config
from qlib_vnpy_platform.core.main_engine import MainEngine


def test_main_engine_init():
    load_config()
    engine = MainEngine()
    status = engine.get_status()
    assert "account" in status, "Should have account"
    assert "risk_status" in status, "Should have risk_status"
    assert "watch_list" in status, "Should have watch_list"
    print(f"[PASS] MainEngine init test: capital={status['account']['total_capital']}")


def test_add_remove_stock():
    load_config()
    engine = MainEngine()
    engine.add_stock("SZ000001")
    engine.add_stock("SH600000")
    assert "SZ000001" in engine._watch_list, "SZ000001 should be in watch list"
    assert "SH600000" in engine._watch_list, "SH600000 should be in watch list"

    engine.remove_stock("SH600000")
    assert "SH600000" not in engine._watch_list, "SH600000 should be removed"
    print("[PASS] Add/remove stock test")


def test_full_analysis():
    load_config()
    engine = MainEngine()
    engine.add_stock("SZ000001")

    result = engine.analyze_stock("SZ000001", use_llm=True, use_qlib=True)
    assert result is not None, "Result should not be None"
    assert "symbol" in result, "Should have symbol"
    assert "signal" in result, "Should have signal"
    assert result["signal"]["direction"] in ["BUY", "SELL", "HOLD"], \
        f"Invalid direction: {result['signal']['direction']}"

    print(f"[PASS] Full analysis test for {result['symbol']}:")
    print(f"  Direction: {result['signal']['direction']}")
    print(f"  Score: {result['signal']['score']:.4f}")
    print(f"  Confidence: {result['signal']['confidence']:.4f}")
    if result.get("qlib_pred") is not None:
        print(f"  QLib pred: {result['qlib_pred']:.4f}")
    if result.get("llm_result"):
        print(f"  LLM signal: {result['llm_result'].get('signal')}")
        print(f"  LLM reason: {result['llm_result'].get('reason', '')[:100]}")
    if result.get("risk_check"):
        print(f"  Risk approved: {result['risk_check'].get('approved')}")


if __name__ == "__main__":
    test_main_engine_init()
    test_add_remove_stock()
    test_full_analysis()
    print("\n=== All MainEngine integration tests passed ===")
