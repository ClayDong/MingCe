#!/usr/bin/env python3
"""
每日策略交易跟踪报告生成器
严格按策略信号执行，记录每个策略的操作和盈亏情况
"""

import sys
import json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
import numpy as np
from datetime import datetime

from qlib_vnpy_platform.strategy_monitor_pkg import BaseMonitor, ReportFormatter, FeishuOutput


# ======================================================================
#  策略交易跟踪器（属于此文件的独特逻辑，保持原样）
# ======================================================================

class StrategyTradeTracker:
    """策略交易跟踪器"""

    def __init__(self, initial_capital=100000):
        self.initial_capital = initial_capital
        self.strategy_positions = {}
        self.strategy_trades = {}
        self.strategy_performance = {}

    def initialize_strategy(self, strategy_key):
        self.strategy_positions[strategy_key] = {
            'position': 0, 'shares': 0, 'avg_price': 0,
            'cash': self.initial_capital, 'total_value': self.initial_capital
        }
        self.strategy_trades[strategy_key] = []
        self.strategy_performance[strategy_key] = {
            'total_trades': 0, 'winning_trades': 0, 'losing_trades': 0,
            'total_pnl': 0, 'win_rate': 0, 'max_drawdown': 0
        }

    def execute_trade(self, strategy_key, signal, price, date):
        pos = self.strategy_positions[strategy_key]
        trades = self.strategy_trades[strategy_key]
        perf = self.strategy_performance[strategy_key]
        trade_result = None

        if signal == 1 and pos['position'] == 0:
            buy_amount = pos['cash'] * 0.95
            shares = int(buy_amount / price / 100) * 100
            if shares > 0:
                cost = shares * price
                commission = cost * 0.0003
                pos['shares'] = shares
                pos['avg_price'] = price
                pos['cash'] -= cost + commission
                pos['position'] = 1
                trade = {'date': date, 'action': 'BUY', 'shares': shares, 'price': price,
                         'amount': cost, 'commission': commission, 'signal_strength': 0}
                trades.append(trade)
                perf['total_trades'] += 1
                trade_result = f"🟢 买入 {shares}股 @{price:.2f}"

        elif signal == -1 and pos['position'] == 1:
            sell_shares = pos['shares']
            revenue = sell_shares * price
            pnl = revenue - (pos['shares'] * pos['avg_price'])
            commission = revenue * 0.0003
            stamp_tax = revenue * 0.0005
            pos['cash'] += revenue - commission - stamp_tax
            pos['total_value'] = pos['cash']
            pos['position'] = 0
            pos['shares'] = 0
            pos['avg_price'] = 0
            trade = {'date': date, 'action': 'SELL', 'shares': sell_shares, 'price': price,
                     'amount': revenue, 'pnl': pnl - commission - stamp_tax,
                     'commission': commission, 'stamp_tax': stamp_tax, 'signal_strength': 0}
            trades.append(trade)
            perf['total_trades'] += 1
            perf['total_pnl'] += pnl - commission - stamp_tax
            net_pnl = pnl - commission - stamp_tax
            if net_pnl > 0:
                perf['winning_trades'] += 1
            else:
                perf['losing_trades'] += 1
            if perf['winning_trades'] + perf['losing_trades'] > 0:
                perf['win_rate'] = perf['winning_trades'] / (perf['winning_trades'] + perf['losing_trades'])
            trade_result = f"🔴 卖出 {sell_shares}股 @{price:.2f}, 盈亏: {pnl-commission-stamp_tax:+.2f}"

        return trade_result

    def update_position_value(self, strategy_key, current_price):
        pos = self.strategy_positions[strategy_key]
        if pos['position'] == 1:
            pos['total_value'] = pos['cash'] + pos['shares'] * current_price
        else:
            pos['total_value'] = pos['cash']
        pnl = pos['total_value'] - self.initial_capital
        pos['pnl'] = pnl
        pos['pnl_pct'] = (pnl / self.initial_capital) * 100


# ======================================================================
#  每日策略交易报告
# ======================================================================

class DailyStrategyTradeReport(BaseMonitor):
    """每日策略交易报告生成器"""

    TRADE_STRATEGIES = [
        'ma_cross', 'rsi', 'macd', 'bollinger', 'momentum',
        'kdj', 'dual_thrust', 'turtle', 'mean_reversion',
        'ma_alignment', 'volume_breakout', 'volatility_breakout',
        'trend_following', 'gap', 'three_soldiers',
        'support_resistance', 'obv',
        'sentiment_cycle', 'sector_rotation', 'prosperity_investment',
        'band_operation', 'value_investment', 'dragon_head',
        'macd_multitimeframe', 'vwap', 'sar', 'mfi',
        'sentiment_news', 'sentiment_contrarian',
    ]

    def __init__(self, feishu_chat_id=None):
        super().__init__(strategies_to_monitor=list(self.TRADE_STRATEGIES))
        self.tracker = StrategyTradeTracker(initial_capital=100000)
        self.feishu = FeishuOutput(chat_id=feishu_chat_id)
        self.trade_history_file = Path(__file__).parent / 'qlib_vnpy_platform/data/daily_reports/trade_history.json'
        self.load_history()

    # ---- 历史持久化 ---- #

    def load_history(self):
        if self.trade_history_file.exists():
            with open(self.trade_history_file, 'r', encoding='utf-8') as f:
                history = json.load(f)
            for k, v in history.get('positions', {}).items():
                self.tracker.strategy_positions[k] = v
            for k, v in history.get('trades', {}).items():
                self.tracker.strategy_trades[k] = v
            for k, v in history.get('performance', {}).items():
                self.tracker.strategy_performance[k] = v
            self.last_date = history.get('last_date', None)
        else:
            self.last_date = None

    def save_history(self):
        history = {
            'positions': self.tracker.strategy_positions,
            'trades': self.tracker.strategy_trades,
            'performance': self.tracker.strategy_performance,
            'last_date': datetime.now().strftime('%Y-%m-%d')
        }
        self.trade_history_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.trade_history_file, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=2)

    # ---- 报告生成 ---- #

    def generate_daily_report(self, symbol='SZ002594', stock_name='比亚迪'):
        """生成每日报告"""
        data = self.fetch_latest_data(symbol, days=100)
        if data is None or data.empty:
            return None, None

        latest_date = data['date'].iloc[-1].strftime('%Y-%m-%d')
        latest_price = data['close'].iloc[-1]

        change = 0
        change_pct = 0
        if len(data) >= 2:
            prev_price = data['close'].iloc[-2]
            change = latest_price - prev_price
            change_pct = (change / prev_price) * 100

        # 使用基类的简化版策略分析
        results = self.run_strategy_analysis_flat(data)

        daily_trades = []
        today_actions = []

        for strategy_key, signal_info in results.items():
            if strategy_key not in self.tracker.strategy_positions:
                self.tracker.initialize_strategy(strategy_key)

            trade_result = self.tracker.execute_trade(
                strategy_key,
                signal_info['signal'],
                signal_info['price'],
                signal_info['date']
            )

            self.tracker.update_position_value(strategy_key, latest_price)

            if trade_result:
                today_actions.append({
                    'strategy': signal_info['strategy_name'],
                    'action': trade_result,
                    'signal_strength': signal_info['signal_strength']
                })

        self.save_history()

        buy_actions = [a for a in today_actions if '买入' in a['action']]
        sell_actions = [a for a in today_actions if '卖出' in a['action']]

        performance_summary = []
        for strategy_key in self.strategies_to_monitor:
            if strategy_key in self.tracker.strategy_positions:
                pos = self.tracker.strategy_positions[strategy_key]
                perf = self.tracker.strategy_performance.get(strategy_key, {})
                strategy = self._get_strategy_safe(strategy_key)
                performance_summary.append({
                    'strategy': strategy.name if strategy else strategy_key,
                    'position': '持仓' if pos['position'] == 1 else '空仓',
                    'shares': pos['shares'],
                    'avg_price': pos['avg_price'],
                    'current_value': pos['total_value'],
                    'pnl': pos.get('pnl', 0),
                    'pnl_pct': pos.get('pnl_pct', 0),
                    'total_trades': perf.get('total_trades', 0),
                    'win_rate': perf.get('win_rate', 0)
                })

        performance_summary.sort(key=lambda x: x['pnl_pct'], reverse=True)

        # ★ 使用统一格式化工具
        message = ReportFormatter.format_feishu_trade_report(
            latest_date, stock_name, symbol, latest_price, change, change_pct,
            buy_actions, sell_actions, performance_summary
        )

        report = {
            'date': latest_date,
            'symbol': symbol,
            'stock_name': stock_name,
            'latest_price': float(latest_price),
            'change': float(change),
            'change_pct': float(change_pct),
            'today_actions': today_actions,
            'buy_count': len(buy_actions),
            'sell_count': len(sell_actions),
            'performance_summary': performance_summary,
            'message': message
        }

        self.save_report(report, filename_prefix='trade_report')

        # ★ 统一发送
        self._send_to_feishu(message)

        return message, report

    def _get_strategy_safe(self, key):
        """安全获取策略对象"""
        try:
            from qlib_vnpy_platform.core.strategies import get_strategy
            return get_strategy(key)
        except Exception:
            return None

    def _send_to_feishu(self, message):
        """发送到飞书（统一使用 FeishuOutput）"""
        if message:
            self.feishu.send_message(message)
        else:
            print("⚠️ 消息为空，跳过飞书发送")


def main():
    report_generator = DailyStrategyTradeReport()
    message, report = report_generator.generate_daily_report()

    if message:
        print("\n" + "=" * 80)
        print("📤 飞书消息内容预览:")
        print("=" * 80)
        print(message)
        print("=" * 80)
        print(f"\n✅ 今日共 {len(report['today_actions'])} 条操作指令")
        print(f"   买入: {report['buy_count']} 条")
        print(f"   卖出: {report['sell_count']} 条")
        print("\n✅ 报告生成完成！")
    else:
        print("❌ 报告生成失败")


if __name__ == "__main__":
    main()
