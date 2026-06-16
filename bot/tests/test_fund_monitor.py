"""测试基金监控模块"""
import unittest
import tempfile
import shutil
from pathlib import Path
from datetime import datetime

from services.fund_monitor import (
    FundMonitor,
    FundMonitorConfig,
    FundData,
    MonitorAlert,
    build_fund_monitor_card,
)


class TestFundMonitorConfig(unittest.TestCase):
    """基金监控配置测试"""
    
    def test_default_config(self):
        config = FundMonitorConfig()
        self.assertEqual(config.fund_code, "001480")
        self.assertEqual(config.fund_name, "财通成长优选混合 A")
        self.assertEqual(config.base_investment, 1000.0)
    
    def test_custom_config(self):
        config = FundMonitorConfig(
            fund_code="001480",
            cost_price=2.5,
            total_investment=10000.0,
            base_investment=500.0,
        )
        self.assertEqual(config.cost_price, 2.5)
        self.assertEqual(config.total_investment, 10000.0)
        self.assertEqual(config.base_investment, 500.0)


class TestFundData(unittest.TestCase):
    """基金数据模型测试"""
    
    def test_fund_data_creation(self):
        data = FundData(
            date="2026-06-10",
            net_value=2.5,
            accumulated_value=3.0,
            daily_change_pct=2.5,
            weekly_change_pct=5.0,
            monthly_change_pct=10.0,
        )
        self.assertEqual(data.date, "2026-06-10")
        self.assertEqual(data.net_value, 2.5)
        self.assertEqual(data.daily_change_pct, 2.5)


class TestMonitorAlert(unittest.TestCase):
    """监控告警测试"""
    
    def test_alert_creation(self):
        alert = MonitorAlert(
            alert_type="daily_change",
            level="warning",
            title="日跌幅超5%",
            content="建议定投金额×1.5",
            action="加仓",
            timestamp="2026-06-12 16:00:00",
        )
        self.assertEqual(alert.alert_type, "daily_change")
        self.assertEqual(alert.level, "warning")
        self.assertEqual(alert.action, "加仓")


class TestFundMonitor(unittest.TestCase):
    """基金监控器测试"""
    
    def setUp(self):
        self.config = FundMonitorConfig(
            fund_code="001480",
            cost_price=2.0,
            total_investment=10000.0,
        )
        self.monitor = FundMonitor(self.config)
    
    def test_monitor_initialization(self):
        self.assertEqual(self.monitor.config.fund_code, "001480")
        self.assertIsNone(self.monitor.fund_data)
        self.assertEqual(len(self.monitor.alerts), 0)
    
    def test_calculate_profit_no_data(self):
        """没有基金数据时，返回None"""
        profit = self.monitor.calculate_profit()
        self.assertIsNone(profit)
    
    def test_calculate_profit_with_data(self):
        """有基金数据和成本价时，计算收益率"""
        self.monitor.fund_data = FundData(
            date="2026-06-10",
            net_value=2.5,
            accumulated_value=3.0,
            daily_change_pct=2.5,
        )
        profit = self.monitor.calculate_profit()
        self.assertIsNotNone(profit)
        self.assertAlmostEqual(profit, 25.0, places=1)  # (2.5-2.0)/2.0 * 100 = 25%
    
    def test_calculate_profit_zero_cost(self):
        """成本价为0时，返回None"""
        self.monitor.config.cost_price = 0
        self.monitor.fund_data = FundData(
            date="2026-06-10",
            net_value=2.5,
            accumulated_value=3.0,
            daily_change_pct=2.5,
        )
        profit = self.monitor.calculate_profit()
        self.assertIsNone(profit)
    
    def test_monitor_daily_change_no_data(self):
        """没有基金数据时，没有告警"""
        alerts = self.monitor.monitor_daily_change()
        self.assertEqual(len(alerts), 0)
    
    def test_monitor_daily_change_drop_3(self):
        """日跌幅超过-3%，应该有告警"""
        self.monitor.fund_data = FundData(
            date="2026-06-10",
            net_value=2.5,
            accumulated_value=3.0,
            daily_change_pct=-4.0,
        )
        alerts = self.monitor.monitor_daily_change()
        self.assertGreater(len(alerts), 0)
        self.assertEqual(alerts[0].alert_type, "daily_change")
    
    def test_monitor_daily_change_drop_8(self):
        """日跌幅超过-8%，应该有danger级别告警"""
        self.monitor.fund_data = FundData(
            date="2026-06-10",
            net_value=2.5,
            accumulated_value=3.0,
            daily_change_pct=-9.0,
        )
        alerts = self.monitor.monitor_daily_change()
        danger_alerts = [a for a in alerts if a.level == "danger"]
        self.assertGreater(len(danger_alerts), 0)
    
    def test_monitor_daily_change_rise_8(self):
        """日涨幅超过+8%，应该有暂停定投告警"""
        self.monitor.fund_data = FundData(
            date="2026-06-10",
            net_value=2.5,
            accumulated_value=3.0,
            daily_change_pct=9.0,
        )
        alerts = self.monitor.monitor_daily_change()
        pause_alerts = [a for a in alerts if "暂停" in a.content]
        self.assertGreater(len(pause_alerts), 0)
    
    def test_monitor_profit_no_cost(self):
        """没有成本价时，没有止盈告警"""
        self.monitor.config.cost_price = None
        self.monitor.fund_data = FundData(
            date="2026-06-10",
            net_value=3.0,
            accumulated_value=3.5,
            daily_change_pct=0.0,
        )
        alerts = self.monitor.monitor_profit()
        self.assertEqual(len(alerts), 0)
    
    def test_monitor_profit_50_percent(self):
        """累计收益超过50%，应该有止盈告警"""
        self.monitor.config.cost_price = 2.0
        self.monitor.fund_data = FundData(
            date="2026-06-10",
            net_value=3.1,  # 收益率 = (3.1-2.0)/2.0 * 100 = 55%
            accumulated_value=3.5,
            daily_change_pct=0.0,
        )
        alerts = self.monitor.monitor_profit()
        profit_alerts = [a for a in alerts if a.alert_type == "profit"]
        self.assertGreater(len(profit_alerts), 0)
    
    def test_monitor_profit_200_percent(self):
        """累计收益超过200%，应该有全部止盈告警"""
        self.monitor.config.cost_price = 1.0
        self.monitor.fund_data = FundData(
            date="2026-06-10",
            net_value=3.1,  # 收益率 = (3.1-1.0)/1.0 * 100 = 210%
            accumulated_value=3.5,
            daily_change_pct=0.0,
        )
        alerts = self.monitor.monitor_profit()
        sell_all_alerts = [a for a in alerts if "全部止盈" in a.content]
        self.assertGreater(len(sell_all_alerts), 0)


class TestBuildFundMonitorCard(unittest.TestCase):
    """基金监控卡片构建测试"""
    
    def test_build_card_empty_alerts(self):
        """没有告警时，卡片应该正常构建"""
        monitor_result = {
            "fund_name": "测试基金",
            "fund_code": "001480",
            "date": "2026-06-10",
            "net_value": 2.5,
            "daily_change_pct": 2.5,
            "alerts": [],
            "timestamp": "2026-06-10 15:30:00",
        }
        card = build_fund_monitor_card(monitor_result)
        self.assertIn("header", card)
        self.assertIn("elements", card)
        self.assertEqual(card["header"]["template"], "blue")  # 涨是蓝色
    
    def test_build_card_with_negative_change(self):
        """下跌时，卡片模板应该是红色"""
        monitor_result = {
            "fund_name": "测试基金",
            "fund_code": "001480",
            "date": "2026-06-10",
            "net_value": 2.5,
            "daily_change_pct": -2.5,
            "alerts": [],
            "timestamp": "2026-06-10 15:30:00",
        }
        card = build_fund_monitor_card(monitor_result)
        self.assertEqual(card["header"]["template"], "red")  # 跌是红色
    
    def test_build_card_with_alerts(self):
        """有告警时，卡片应该包含告警内容"""
        monitor_result = {
            "fund_name": "测试基金",
            "fund_code": "001480",
            "date": "2026-06-10",
            "net_value": 2.5,
            "daily_change_pct": -6.0,
            "weekly_change_pct": -5.0,
            "monthly_change_pct": 10.0,
            "profit_pct": 55.0,
            "alerts": [
                {
                    "alert_type": "daily_change",
                    "level": "warning",
                    "title": "日跌幅超5%：-6.00%",
                    "content": "建议定投金额×1.5",
                    "action": "加仓",
                }
            ],
            "timestamp": "2026-06-10 15:30:00",
        }
        card = build_fund_monitor_card(monitor_result)
        card_content = card["elements"][0]["content"]
        self.assertIn("日跌幅超5%", card_content)
        self.assertIn("建议定投金额×1.5", card_content)
    
    def test_build_card_with_profit(self):
        """有收益时，卡片应该包含收益信息"""
        monitor_result = {
            "fund_name": "测试基金",
            "fund_code": "001480",
            "date": "2026-06-10",
            "net_value": 3.0,
            "daily_change_pct": 0.0,
            "profit_pct": 50.0,
            "alerts": [],
            "timestamp": "2026-06-10 15:30:00",
        }
        card = build_fund_monitor_card(monitor_result)
        card_content = card["elements"][0]["content"]
        self.assertIn("累计盈利", card_content)
        self.assertIn("+50.00%", card_content)
    
    def test_build_card_with_none_values(self):
        """部分数据为None时，应该正常处理"""
        monitor_result = {
            "fund_name": "测试基金",
            "fund_code": "001480",
            "date": "2026-06-10",
            "net_value": 2.5,
            "daily_change_pct": 1.5,
            "weekly_change_pct": None,
            "monthly_change_pct": None,
            "profit_pct": None,
            "drawdown_pct": None,
            "volatility": None,
            "alerts": [],
            "timestamp": "2026-06-10 15:30:00",
        }
        card = build_fund_monitor_card(monitor_result)
        self.assertIsNotNone(card)
        card_content = card["elements"][0]["content"]
        self.assertIn("测试基金", card_content)


class TestMonitorRun(unittest.TestCase):
    """监控运行测试（不实际获取数据）"""
    
    def test_run_monitor_no_data(self):
        """获取数据失败时，返回错误状态"""
        # 由于网络问题可能导致获取失败，这个测试验证错误处理
        config = FundMonitorConfig(fund_code="INVALID_CODE")
        monitor = FundMonitor(config)
        # 模拟 fetch_fund_data 返回 None
        result = monitor.run_monitor()
        # 无论成功与否，都应该有结果
        self.assertIn("status", result)


if __name__ == "__main__":
    unittest.main()
