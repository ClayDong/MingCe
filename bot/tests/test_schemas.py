"""测试数据模型 + report_generator 工具函数"""
import unittest
from datetime import date
from models.schemas import (
    IndexData, MarketOverview, MacroData, NorthFlowData,
    AlertItem, DailyReportData,
)
from services.report_generator import _is_trading_day, _build_market_summary_v2


class TestIndexData(unittest.TestCase):
    def test_create(self):
        idx = IndexData(name="上证指数", value=3500.0, change_pct=1.5)
        self.assertEqual(idx.name, "上证指数")
        self.assertEqual(idx.value, 3500.0)

    def test_with_volume(self):
        idx = IndexData(name="深证成指", value=12000.0, change_pct=-0.5, volume="5000亿")
        self.assertEqual(idx.volume, "5000亿")


class TestMarketOverview(unittest.TestCase):
    def test_defaults(self):
        m = MarketOverview()
        self.assertEqual(m.indices, [])
        self.assertEqual(m.up_count, 0)

    def test_with_data(self):
        m = MarketOverview(
            indices=[IndexData(name="上证指数", value=3500.0, change_pct=1.0)],
            up_count=2000, down_count=1500, total_volume="10000亿",
        )
        self.assertEqual(len(m.indices), 1)
        self.assertEqual(m.up_count, 2000)


class TestDailyReportData(unittest.TestCase):
    def test_defaults(self):
        r = DailyReportData()
        self.assertEqual(r.report_date, "")
        self.assertEqual(r.version, "close")
        self.assertIsInstance(r.market, MarketOverview)

    def test_with_data(self):
        r = DailyReportData(
            report_date="2026-06-04",
            alerts=[AlertItem(alert_type="index", title="测试", content="测试内容")],
        )
        self.assertEqual(len(r.alerts), 1)


class TestAlertItem(unittest.TestCase):
    def test_default_level(self):
        a = AlertItem(alert_type="index", title="测试", content="测试内容")
        self.assertEqual(a.level, "info")

    def test_custom_level(self):
        a = AlertItem(alert_type="index", title="测试", content="测试内容", level="danger")
        self.assertEqual(a.level, "danger")


class TestIsTradingDay(unittest.TestCase):
    def test_returns_bool(self):
        result = _is_trading_day()
        self.assertIsInstance(result, bool)


class TestBuildMarketSummaryV2(unittest.TestCase):
    def test_empty_data(self):
        result = _build_market_summary_v2({})
        self.assertIn("版本", result) or self.assertIn("A股核心", result)

    def test_with_indices(self):
        data = {
            "report_date": "2026-06-04", "version": "close",
            "market": {
                "indices": [{"name": "上证指数", "value": 3500.0, "change_pct": 1.0}],
                "up_count": 2000, "down_count": 1000, "total_volume": "10000亿",
            },
            "north_flow": {"net_flow": 60.0},
            "leading": {}, "macro": {}, "global_macro": {},
            "crypto": {}, "futures": {}, "monetary": {}, "comparison": {}, "bse": {},
        }
        result = _build_market_summary_v2(data)
        self.assertIn("上证指数", result)
        self.assertIn("3500", result)

    def test_with_global_macro(self):
        data = {
            "report_date": "2026-06-04", "version": "test",
            "market": {"indices": [], "up_count": 0, "down_count": 0, "total_volume": ""},
            "north_flow": {}, "leading": {}, "macro": {}, "bse": {},
            "global_macro": {"brent_oil": "75.50", "gold": "2000.00"},
            "crypto": {}, "futures": {}, "monetary": {}, "comparison": {},
        }
        result = _build_market_summary_v2(data)
        self.assertIn("黄金", result)


if __name__ == "__main__":
    unittest.main()
