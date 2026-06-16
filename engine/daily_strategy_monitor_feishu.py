#!/usr/bin/env python3
"""
每日策略监控报告生成器 - 飞书通知版
每天收盘后自动生成策略操作建议和盈亏报告，并通过飞书发送
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from datetime import datetime

from qlib_vnpy_platform.strategy_monitor_pkg import BaseMonitor, ReportFormatter, FeishuOutput


class DailyStrategyMonitorFeishu(BaseMonitor):
    """每日策略监控器（飞书输出版）"""

    def __init__(self):
        super().__init__()
        self.feishu = FeishuOutput()

    def generate_feishu_message(self, symbol='SZ002594', stock_name='比亚迪'):
        """生成飞书消息内容并发送"""
        data = self.fetch_latest_data(symbol)
        if data is None or data.empty:
            print("❌ 无法获取数据")
            return None

        change, change_pct, latest_price, latest_date = self.compute_change(data)

        results, signals = self.run_strategy_analysis(data)
        buy_signals, sell_signals, hold_signals = self.classify_signals(results)

        # 使用统一的格式化工具生成飞书消息
        message = ReportFormatter.format_feishu_daily_header(
            stock_name, symbol, latest_date, latest_price, change, change_pct
        )
        message += ReportFormatter.format_feishu_signals(buy_signals, sell_signals, hold_signals)

        # 保存报告
        report = {
            'date': latest_date,
            'symbol': symbol,
            'stock_name': stock_name,
            'latest_price': float(latest_price),
            'change': float(change),
            'change_pct': float(change_pct),
            'total_strategies': len(results),
            'buy_signals': len(buy_signals),
            'sell_signals': len(sell_signals),
            'hold_signals': len(hold_signals),
            'message': message,
        }
        self.save_report(report)

        return message


def main():
    monitor = DailyStrategyMonitorFeishu()
    message = monitor.generate_feishu_message()

    if message:
        print("\n📤 飞书消息内容预览:")
        print("=" * 80)
        print(message)
        print("=" * 80)

        # ★ 关键修复：通过中转API发送到飞书
        print("\n📤 正在发送到飞书...")
        success = monitor.feishu.send_message(message)
        if success:
            print("✅ 报告已生成并成功发送到飞书！")
        else:
            print("⚠️ 报告已生成，但飞书发送失败（请检查中转API是否运行）")
    else:
        print("❌ 报告生成失败")


if __name__ == "__main__":
    main()
