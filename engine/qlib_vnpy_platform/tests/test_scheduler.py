import sys
import os
import time
from datetime import datetime
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from qlib_vnpy_platform.config import load_config
from qlib_vnpy_platform.core.scheduler import Scheduler


class MockEngine:
    def __init__(self):
        self._watch_list = []
        self._analysis_count = 0

    def analyze_stock(self, symbol, use_llm=True, use_qlib=True):
        self._analysis_count += 1
        return {
            "symbol": symbol,
            "signal": {"direction": "HOLD", "score": 0.0, "confidence": 0.0},
            "risk_check": {"approved": False, "reason": "HOLD signal"},
        }

    def get_status(self):
        return {
            "account": {"total_capital": 1000000, "cash": 1000000, "position_value": 0,
                        "total_pnl": 0, "total_pnl_pct": 0},
            "risk_status": {"risk_level": "LOW", "daily_pnl": 0, "circuit_breaker_active": False},
            "positions": {},
            "recent_trades": [],
        }


def test_trading_time_weekday():
    scheduler = Scheduler(MockEngine())

    with patch("qlib_vnpy_platform.core.scheduler.datetime") as mock_dt:
        mock_dt.now.return_value = MagicMock(hour=10, minute=30)
        mock_dt.now.return_value.weekday.return_value = 2
        assert scheduler._is_trading_time() == True, "Wed 10:30 should be trading time"

        mock_dt.now.return_value = MagicMock(hour=14, minute=30)
        mock_dt.now.return_value.weekday.return_value = 2
        assert scheduler._is_trading_time() == True, "Wed 14:30 should be trading time"

        mock_dt.now.return_value = MagicMock(hour=12, minute=30)
        mock_dt.now.return_value.weekday.return_value = 2
        assert scheduler._is_trading_time() == False, "Wed 12:30 should not be trading time"

        mock_dt.now.return_value = MagicMock(hour=8, minute=30)
        mock_dt.now.return_value.weekday.return_value = 2
        assert scheduler._is_trading_time() == False, "Wed 08:30 should not be trading time"

        mock_dt.now.return_value = MagicMock(hour=10, minute=30)
        mock_dt.now.return_value.weekday.return_value = 5
        assert scheduler._is_trading_time() == False, "Sat should not be trading time"

    print("[PASS] Trading time check test")


def test_scheduler_configure():
    scheduler = Scheduler(MockEngine())
    scheduler.configure(
        watch_list=["SZ000001", "SH600000"],
        scan_interval=120,
        daily_report_time=(15, 30),
        auto_trade=True,
    )

    assert scheduler._watch_list == ["SZ000001", "SH600000"], "Watch list should be set"
    assert scheduler._scan_interval == 120, "Scan interval should be 120"
    assert scheduler._daily_report_time == (15, 30), "Report time should be set"
    assert scheduler._auto_trade == True, "Auto trade should be True"
    print("[PASS] Scheduler configure test")


def test_scheduler_start_stop():
    scheduler = Scheduler(MockEngine())
    scheduler.configure(watch_list=["SZ000001"], scan_interval=60)

    assert scheduler.is_running == False, "Should not be running initially"

    scheduler.start()
    assert scheduler.is_running == True, "Should be running after start"
    time.sleep(0.5)

    scheduler.stop()
    assert scheduler.is_running == False, "Should not be running after stop"
    print("[PASS] Scheduler start/stop test")


def test_scheduler_status():
    scheduler = Scheduler(MockEngine())
    scheduler.configure(watch_list=["SZ000001"], scan_interval=300, auto_trade=False)

    status = scheduler.status
    assert status["running"] == False, "Should not be running"
    assert status["watch_list"] == ["SZ000001"], f"Watch list should match, got {status['watch_list']}"
    assert status["scan_interval"] == 300, "Scan interval should match"
    assert status["scan_count"] == 0, "Scan count should be 0"
    assert status["auto_trade"] == False, "Auto trade should be False"
    print("[PASS] Scheduler status test")


def test_scan_interval_minimum():
    scheduler = Scheduler(MockEngine())
    scheduler.configure(scan_interval=10)
    assert scheduler._scan_interval == 60, "Scan interval should be clamped to 60"
    print("[PASS] Scan interval minimum test")


def test_daily_report():
    scheduler = Scheduler(MockEngine())
    report = scheduler._generate_daily_report()
    assert "每日交易报告" in report, "Report should contain title"
    assert "账户概览" in report, "Report should contain account section"
    assert "风控状态" in report, "Report should contain risk section"
    print("[PASS] Daily report test")


if __name__ == "__main__":
    load_config()

    test_trading_time_weekday()
    test_scheduler_configure()
    test_scheduler_start_stop()
    test_scheduler_status()
    test_scan_interval_minimum()
    test_daily_report()

    print("\n=== All Scheduler tests passed ===")
