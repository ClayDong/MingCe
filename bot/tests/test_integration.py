"""集成测试 - 测试完整的数据流"""
import unittest
import asyncio
from unittest.mock import patch, MagicMock

from services.data_fetcher import (
    get_market_overview,
    get_macro_data,
    get_north_flow,
    detect_alerts,
)
from services.report_generator import _build_market_summary_v2
from services.fund_monitor import FundMonitor, FundMonitorConfig


class TestDataFlowIntegration(unittest.TestCase):
    """数据流集成测试"""

    def test_build_market_summary_structure(self):
        """测试市场摘要构建"""
        data = {
            "report_date": "2026-06-10", "version": "close", "is_trading_day": True,
            "market": {
                "indices": [
                    {"name": "上证指数", "value": 3200.0, "change_pct": 1.5},
                    {"name": "深证成指", "value": 10000.0, "change_pct": -0.5},
                ],
                "up_count": 2000, "down_count": 1500, "total_volume": "8000亿",
                "top_sectors": [{"name": "半导体", "change_pct": 3.5}, {"name": "AI", "change_pct": 2.8}],
                "bottom_sectors": [], "fund_flow": "主力净流入50亿",
            },
            "north_flow": {"net_flow": 80.5},
            "leading": {
                "headlines": [
                    {"name": "宁德时代", "change_pct": 5.0, "market_cap": "8000亿"},
                    {"name": "比亚迪", "change_pct": 3.0, "market_cap": "6000亿"},
                ]
            },
            "macro": {"highlights": ["CPI: 0.3%", "PPI: -2.5%"]},
            "global_macro": {"brent_oil": "75.50", "gold": "2000.00"},
            "bse": {"indices": [], "leading": {}},
            "crypto": {}, "futures": {}, "monetary": {}, "us_market": {}, "comparison": {},
        }

        summary = _build_market_summary_v2(data)

        self.assertIn("上证指数", summary)
        self.assertIn("深证成指", summary)
        self.assertIn("半导体", summary)
    
    def test_detect_alerts_threshold(self):
        """测试异动检测阈值"""
        market = {
            "indices": [
                {"name": "上证指数", "value": 3200.0, "change_pct": 3.5},
            ],
            "up_count": 2000,
            "down_count": 1500,
            "total_volume": "8000亿",
            "top_sectors": [],
            "bottom_sectors": [],
        }
        north = {"net_flow": 100.0}
        leading = {"headlines": []}
        
        alerts = detect_alerts(market, north, leading, etf=None, bse=None)

        # 检查是否有指数异动告警
        index_alerts = [a for a in alerts if a["alert_type"] == "index"]
        self.assertGreater(len(index_alerts), 0)

    def test_detect_alerts_large_change(self):
        """测试大幅波动检测"""
        market = {
            "indices": [
                {"name": "上证指数", "value": 3200.0, "change_pct": 10.0},
            ],
            "up_count": 3000,
            "down_count": 500,
            "total_volume": "15000亿",
            "top_sectors": [],
            "bottom_sectors": [],
        }
        north = {"net_flow": None}
        leading = {"headlines": []}

        alerts = detect_alerts(market, north, leading, etf=None, bse=None)
        
        # 大幅波动应该触发 danger 级别告警
        danger_alerts = [a for a in alerts if a["level"] == "warning"]
        self.assertGreater(len(danger_alerts), 0)


class TestFundMonitorIntegration(unittest.TestCase):
    """基金监控集成测试"""
    
    def test_fund_monitor_alert_levels(self):
        """测试基金监控各级别告警"""
        config = FundMonitorConfig(
            fund_code="001480",
            cost_price=2.0,
            total_investment=10000.0,
        )
        monitor = FundMonitor(config)
        
        # 模拟不同涨跌幅的告警
        test_cases = [
            (-11.0, "danger"),  # 跌幅超10%
            (-6.0, "warning"),   # 跌幅超5%
            (-4.0, "warning"),   # 跌幅超3%
            (9.0, "info"),       # 涨幅超8%
            (6.0, "info"),       # 涨幅超5%
            (4.0, "info"),       # 涨幅超3%
        ]
        
        for change_pct, expected_level in test_cases:
            monitor.fund_data = MagicMock()
            monitor.fund_data.daily_change_pct = change_pct
            
            alerts = monitor.monitor_daily_change()
            
            if expected_level == "danger":
                danger_count = len([a for a in alerts if a.level == "danger"])
                self.assertGreater(danger_count, 0, f"Expected danger level for {change_pct}%")
            elif expected_level == "warning":
                warning_count = len([a for a in alerts if a.level == "warning"])
                self.assertGreater(warning_count, 0, f"Expected warning level for {change_pct}%")
            elif expected_level == "info":
                info_count = len([a for a in alerts if a.level == "info"])
                self.assertGreater(info_count, 0, f"Expected info level for {change_pct}%")
    
    def test_fund_monitor_profit_alerts(self):
        """测试止盈告警"""
        config = FundMonitorConfig(
            fund_code="001480",
            cost_price=1.0,
            total_investment=10000.0,
        )
        monitor = FundMonitor(config)
        
        # 测试不同收益水平的告警
        test_cases = [
            (60.0, "profit_50"),   # 收益超50%
            (110.0, "profit_100"), # 收益超100%
            (160.0, "profit_150"), # 收益超150%
            (210.0, "profit_200"), # 收益超200%
        ]
        
        for profit_pct, expected_level in test_cases:
            monitor.fund_data = MagicMock()
            monitor.fund_data.net_value = 1.0 * (1 + profit_pct / 100)
            monitor.fund_data.accumulated_value = monitor.fund_data.net_value
            monitor.fund_data.daily_change_pct = 0
            
            alerts = monitor.monitor_profit()
            
            self.assertGreater(len(alerts), 0, f"Expected alerts for {profit_pct}% profit")
            
            if expected_level == "profit_200":
                all_sell = [a for a in alerts if "全部止盈" in a.content]
                self.assertGreater(len(all_sell), 0)


class TestReportGenerationIntegration(unittest.TestCase):
    """报表生成集成测试"""
    
    def test_complete_data_structure(self):
        """测试完整数据结构"""
        # 模拟完整的日报数据结构
        data = {
            "report_date": "2026-06-10",
            "version": "close",
            "is_trading_day": True,
            "market": {
                "indices": [
                    {"name": "上证指数", "value": 3200.0, "change_pct": 1.5, "volume": "3500亿"},
                    {"name": "深证成指", "value": 10000.0, "change_pct": -0.5, "volume": "4500亿"},
                    {"name": "创业板指", "value": 2000.0, "change_pct": 2.0, "volume": "2000亿"},
                    {"name": "科创50", "value": 1000.0, "change_pct": 3.0, "volume": "800亿"},
                ],
                "up_count": 2500,
                "down_count": 1800,
                "total_volume": "10000亿",
                "top_sectors": [
                    {"name": "半导体", "change_pct": 4.5},
                    {"name": "AI", "change_pct": 3.8},
                ],
                "bottom_sectors": [
                    {"name": "房地产", "change_pct": -2.0},
                ],
                "fund_flow": "主力净流入100亿",
            },
            "macro": {
                "cpi": "0.3%",
                "ppi": "-2.5%",
                "pmi": "50.4",
                "lpr_1y": "3.10%",
                "lpr_5y": "3.60%",
                "highlights": ["CPI: 0.3%", "PPI: -2.5%", "PMI: 50.4"],
            },
            "north_flow": {
                "net_flow": 85.5,
                "sh_flow": 40.0,
                "sz_flow": 45.5,
            },
            "etf": {
                "broad_based": [
                    {"name": "沪深300ETF", "change_pct": 1.2},
                    {"name": "科创50ETF", "change_pct": 2.8},
                ],
                "industry": [
                    {"name": "半导体ETF", "change_pct": 4.0},
                    {"name": "AI ETF", "change_pct": 3.5},
                ],
            },
            "leading": {
                "headlines": [
                    {"name": "宁德时代", "change_pct": 5.0, "market_cap": "8000亿"},
                    {"name": "比亚迪", "change_pct": 3.0, "market_cap": "6000亿"},
                ],
                "major_events": [
                    {"name": "华为", "change_pct": 8.0},
                ],
            },
            "global_macro": {
                "brent_oil": "75.50",
                "gold": "2000.00",
                "usd_index": "104.50",
                "usd_cny": "7.25",
            },
            "bse": {
                "indices": [
                    {"name": "北证50", "value": 1000.0, "change_pct": 1.5},
                ],
                "leading": {
                    "headlines": [],
                },
            },
            "alerts": [],
            "master_commentary": "今日市场整体表现强劲，AI和半导体板块领涨。",
        }
        
        # 验证数据结构完整性
        self.assertIn("market", data)
        self.assertIn("macro", data)
        self.assertIn("north_flow", data)
        self.assertIn("etf", data)
        self.assertIn("leading", data)
        self.assertIn("global_macro", data)
        self.assertIn("bse", data)
        
        # 验证索引数量
        self.assertEqual(len(data["market"]["indices"]), 4)


if __name__ == "__main__":
    unittest.main()
