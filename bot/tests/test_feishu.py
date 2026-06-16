"""测试飞书消息构建功能和 detect_alerts。"""
import unittest
from services.feishu_service import (
    _fmt_pct, _truncate, _is_chat_id_valid,
    build_detail_card, build_alert_card,
)
from services.data_fetcher import detect_alerts


class TestFmtPct(unittest.TestCase):
    def test_positive(self): self.assertEqual(_fmt_pct(3.14), "+3.14%")
    def test_negative(self): self.assertEqual(_fmt_pct(-0.5), "-0.50%")
    def test_zero(self): self.assertEqual(_fmt_pct(0.0), "+0.00%")
    def test_none(self): self.assertEqual(_fmt_pct(None), "--")
    def test_nan(self): self.assertEqual(_fmt_pct(float("nan")), "--")


class TestTruncate(unittest.TestCase):
    def test_short(self): self.assertEqual(_truncate("hello", 10), "hello")
    def test_long(self): self.assertEqual(_truncate("hello world", 5), "hello...")
    def test_exact(self): self.assertEqual(_truncate("hello", 5), "hello")


class TestChatIdValid(unittest.TestCase):
    def test_valid(self): self.assertTrue(_is_chat_id_valid("oc_abc123"))
    def test_empty(self): self.assertFalse(_is_chat_id_valid(""))
    def test_invalid_prefix(self): self.assertFalse(_is_chat_id_valid("invalid_id"))
    def test_none(self): self.assertFalse(_is_chat_id_valid(""))


class TestBuildSummaryCard(unittest.TestCase):
    def setUp(self):
        self.base = {
            "report_date": "2026-06-04", "version": "test",
            "market": {"indices": [], "up_count": 0, "down_count": 0, "total_volume": "",
                       "top_sectors": [], "bottom_sectors": [], "fund_flow": ""},
            "north_flow": {}, "alerts": [], "master_commentary": "",
            "global_macro": {}, "macro": {}, "etf": {}, "leading": {}, "bse": {},
            "us_market": {}, "crypto": {}, "futures": {}, "monetary": {}, "comparison": {},
        }

    def test_basic(self):
        card = build_detail_card(self.base)
        self.assertIn("日报", str(card))

    def test_with_indices(self):
        data = dict(self.base)
        data["market"]["indices"] = [{"name": "上证指数", "value": 3500, "change_pct": 1.5}]
        data["market"]["up_count"] = 2000
        self.assertIn("上证指数", str(build_detail_card(data)))

    def test_with_global_macro(self):
        data = dict(self.base)
        data["global_macro"] = {"brent_oil": "75.50", "gold": "2000.00"}
        content = str(build_detail_card(data))
        self.assertIn("布伦特", content) or self.assertIn("🛢️", content)


class TestBuildDetailCard(unittest.TestCase):
    def setUp(self):
        self.base = {
            "report_date": "2026-06-04", "version": "test",
            "market": {"indices": [], "up_count": 0, "down_count": 0, "total_volume": "",
                       "top_sectors": [], "bottom_sectors": [], "fund_flow": ""},
            "macro": {}, "north_flow": {}, "etf": {}, "leading": {},
            "global_macro": {}, "master_commentary": "",
        }

    def test_basic(self):
        self.assertIn("详情", str(build_detail_card(self.base)))


class TestBuildAlertCard(unittest.TestCase):
    def test_empty(self):
        self.assertIn("暂无异动", str(build_alert_card([])))

    def test_with_alerts(self):
        alerts = [{"alert_type": "index", "title": "测试", "content": "内容", "level": "danger"}]
        self.assertIn("测试", str(build_alert_card(alerts)))


class TestDetectAlerts(unittest.TestCase):
    def test_with_etf_none(self):
        """etf=None 不应导致错误。"""
        alerts = detect_alerts(
            {"indices": [{"name": "上证指数", "change_pct": 3.0, "value": 3500}]},
            {"net_flow": None}, {"headlines": []}, etf=None,
        )
        self.assertGreaterEqual(len(alerts), 1)

    def test_with_etf_empty_dict(self):
        alerts = detect_alerts(
            {"indices": []}, {"net_flow": None}, {"headlines": []}, etf={},
        )
        self.assertEqual(len(alerts), 0)


if __name__ == "__main__":
    unittest.main()
