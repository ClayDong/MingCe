#!/usr/bin/env python3
"""
每日策略监控报告生成器 - 控制台版
每天收盘后自动生成策略操作建议和盈亏报告，输出到控制台
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from datetime import datetime

from qlib_vnpy_platform.strategy_monitor_pkg import BaseMonitor, ConsoleOutput, ReportFormatter


class DailyStrategyMonitor(BaseMonitor):
    """每日策略监控器（控制台输出版）"""

    def __init__(self):
        super().__init__()
        self.output = ConsoleOutput()

    def generate_report(self, symbol='SZ002594', stock_name='比亚迪'):
        """生成每日报告并输出到控制台"""
        data = self.fetch_latest_data(symbol)
        if data is None or data.empty:
            print("❌ 无法获取数据")
            return None

        change, change_pct, latest_price, latest_date = self.compute_change(data)

        # 头部
        print(ReportFormatter.format_console_daily_header(
            stock_name, symbol, latest_date, latest_price, change, change_pct
        ))

        # 策略分析
        results, signals = self.run_strategy_analysis(data)
        buy_signals, sell_signals, hold_signals = self.classify_signals(results)

        # 信号汇总
        print(ReportFormatter.format_console_signals(buy_signals, sell_signals, hold_signals))

        # 构建报告 dict
        report = {
            'date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'symbol': symbol,
            'stock_name': stock_name,
            'latest_price': float(latest_price),
            'total_strategies': len(results),
            'buy_signals': len(buy_signals),
            'sell_signals': len(sell_signals),
            'hold_signals': len(hold_signals),
            'recommendations': {
                'buy': [v['strategy_name'] for v in buy_signals.values()],
                'sell': [v['strategy_name'] for v in sell_signals.values()],
                'hold': [v['strategy_name'] for v in hold_signals.values()]
            },
            'detailed_signals': results
        }

        self.save_report(report)
        return report

    def get_summary_for_notification(self, report):
        """生成通知摘要"""
        return ReportFormatter.format_console_summary(report)


def main():
    monitor = DailyStrategyMonitor()
    report = monitor.generate_report()
    if report:
        summary = monitor.get_summary_for_notification(report)
        print(f"\n{ReportFormatter.separator()}")
        print("📤 报告摘要:")
        print(ReportFormatter.separator())
        print(summary)
    else:
        print("❌ 报告生成失败")


if __name__ == "__main__":
    main()
