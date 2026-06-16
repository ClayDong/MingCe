import sys
import os
import pytest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from qlib_vnpy_platform.config import load_config
from qlib_vnpy_platform.core.data_bridge import DataBridge


def test_symbol_conversion():
    load_config()
    bridge = DataBridge()

    assert bridge.akshare_to_qlib_symbol("000001") == "SZ000001", "SZ code conversion failed"
    assert bridge.akshare_to_qlib_symbol("600000") == "SH600000", "SH code conversion failed"
    assert bridge.akshare_to_qlib_symbol("SZ000001") == "SZ000001", "Already QLib format failed"

    assert bridge.qlib_to_akshare_symbol("SZ000001") == "000001", "QLib to AKShare failed"
    assert bridge.qlib_to_akshare_symbol("SH600000") == "600000", "QLib to AKShare SH failed"

    assert bridge.qlib_to_vnpy_symbol("SZ000001") == "000001.SZ", "QLib to VNPY SZ failed"
    assert bridge.qlib_to_vnpy_symbol("SH600000") == "600000.SH", "QLib to VNPY SH failed"

    assert bridge.vnpy_to_qlib_symbol("000001.SZ") == "SZ000001", "VNPY to QLib SZ failed"
    assert bridge.vnpy_to_qlib_symbol("600000.SH") == "SH600000", "VNPY to QLib SH failed"

    print("[PASS] Symbol conversion test")


@pytest.mark.online
def test_fetch_daily_data():
    load_config()
    bridge = DataBridge()

    df = bridge.fetch_stock_daily("SZ000001", days=60)
    assert not df.empty, "Daily data should not be empty"
    assert "open" in df.columns, "Should have open column"
    assert "close" in df.columns, "Should have close column"
    assert "high" in df.columns, "Should have high column"
    assert "low" in df.columns, "Should have low column"
    assert "volume" in df.columns, "Should have volume column"
    assert len(df) > 10, "Should have more than 10 records"
    print(f"[PASS] Fetch daily data test: {len(df)} records for SZ000001")


@pytest.mark.online
def test_fetch_realtime_data():
    load_config()
    bridge = DataBridge()

    data = bridge.fetch_stock_realtime("SZ000001")
    assert isinstance(data, dict), "Realtime data should be a dict"
    if data:
        assert "price" in data, "Should have price field"
        assert "change_pct" in data, "Should have change_pct field"
        print(f"[PASS] Fetch realtime data test: price={data.get('price')}, "
              f"change={data.get('change_pct')}%")
    else:
        print("[WARN] No realtime data (market may be closed)")


@pytest.mark.online
def test_technical_indicators():
    load_config()
    bridge = DataBridge()

    df = bridge.fetch_stock_daily("SZ000001", days=120)
    assert not df.empty, "Need data for technical indicators"

    df = bridge.calc_technical_indicators(df)
    assert "ma5" in df.columns, "Should have MA5"
    assert "ma20" in df.columns, "Should have MA20"
    assert "rsi" in df.columns, "Should have RSI"
    assert "macd" in df.columns, "Should have MACD"
    assert "boll_upper" in df.columns, "Should have Bollinger upper"
    assert "boll_lower" in df.columns, "Should have Bollinger lower"

    latest = df.iloc[-1]
    assert not df["ma5"].iloc[-1] != df["ma5"].iloc[-1], "MA5 should not be NaN at end"
    print(f"[PASS] Technical indicators test: MA5={latest['ma5']:.2f}, "
          f"RSI={latest['rsi']:.2f}")


def test_qlib_format_conversion():
    load_config()
    bridge = DataBridge()

    df = bridge.fetch_stock_daily("SZ000001", days=30)
    assert not df.empty, "Need data for QLib format conversion"

    qlib_df = bridge.to_qlib_format(df, "SZ000001")
    assert "instrument" in qlib_df.columns, "Should have instrument column"
    assert "$open" in qlib_df.columns, "Should have $open column"
    assert "$close" in qlib_df.columns, "Should have $close column"
    assert "$factor" in qlib_df.columns, "Should have $factor column"
    assert qlib_df["instrument"].iloc[0] == "SZ000001", "Instrument should be SZ000001"
    print(f"[PASS] QLib format conversion test: {len(qlib_df)} records")


if __name__ == "__main__":
    test_symbol_conversion()
    test_fetch_daily_data()
    test_fetch_realtime_data()
    test_technical_indicators()
    test_qlib_format_conversion()
    print("\n=== All DataBridge tests passed ===")
