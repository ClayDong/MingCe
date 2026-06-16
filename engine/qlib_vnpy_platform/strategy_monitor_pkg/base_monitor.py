#!/usr/bin/env python3
"""
策略监控基类
封装所有策略监控共用的数据获取、策略分析、信号判断、报告保存逻辑
"""

import sys
import json
from pathlib import Path
from datetime import datetime

import pandas as pd
import numpy as np

# 允许从项目根目录导入
_project_root = str(Path(__file__).parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from qlib_vnpy_platform.core.data_bridge import DataBridge
from qlib_vnpy_platform.core.strategies import STRATEGY_REGISTRY, get_strategy


class BaseMonitor:
    """策略监控基类，封装所有监控文件共用的逻辑"""

    # 标准监控策略列表（daily_strategy_monitor / feishu 版共用）
    DEFAULT_STRATEGIES = [
        'ma_cross', 'rsi', 'macd', 'bollinger', 'momentum',
        'kdj', 'dual_thrust', 'turtle', 'mean_reversion',
        'sentiment_cycle', 'sector_rotation', 'prosperity',
        'band_operation', 'value_investment', 'dragon_head',
        'macd_multitimeframe', 'vwap', 'sar', 'mfi'
    ]

    def __init__(self, strategies_to_monitor=None, symbol='SZ002594', stock_name='比亚迪'):
        self.data_bridge = DataBridge()
        self.strategies_to_monitor = strategies_to_monitor or list(self.DEFAULT_STRATEGIES)
        self.symbol = symbol
        self.stock_name = stock_name

    # ------------------------------------------------------------------ #
    #  数据获取
    # ------------------------------------------------------------------ #

    def fetch_latest_data(self, symbol=None, days=30):
        """获取最新行情数据"""
        symbol = symbol or self.symbol
        try:
            df = self.data_bridge.fetch_stock_daily(symbol, days=days)
            if df is not None and not df.empty:
                if 'date' in df.columns:
                    df['date'] = pd.to_datetime(df['date'])
                numeric_cols = ['open', 'close', 'high', 'low', 'volume']
                for col in numeric_cols:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors='coerce')
                df = df.dropna(subset=['open', 'close', 'high', 'low'])
                df = df.sort_values('date').reset_index(drop=True)
                return df
        except Exception as e:
            print(f"❌ 数据获取失败: {e}")
        return None

    def fetch_latest_data_extended(self, symbol=None, days=100):
        """获取更多历史数据（trade_report 专用，>=30天）"""
        return self.fetch_latest_data(symbol=symbol, days=days)

    # ------------------------------------------------------------------ #
    #  策略分析
    # ------------------------------------------------------------------ #

    def run_strategy_analysis(self, data):
        """运行所有策略分析，返回 (results, signals)

        results: {strategy_key: {strategy_name, action, action_desc, signal_value, signal_strength, price, date}}
        signals: {strategy_key: ...}  — 仅包含非零信号的子集
        """
        results = {}
        signals = {}

        for strategy_key in self.strategies_to_monitor:
            try:
                strategy = get_strategy(strategy_key)
                strategy_name = strategy.name

                signals_df = strategy.generate_signals(data.copy())

                if len(signals_df) > 0:
                    latest_signal = signals_df.iloc[-1]

                    signal_value = latest_signal.get('signal', 0)
                    signal_strength = latest_signal.get('signal_strength', 0)

                    if signal_value == 1:
                        action = 'BUY 🟢'
                        action_desc = '建议买入'
                    elif signal_value == -1:
                        action = 'SELL 🔴'
                        action_desc = '建议卖出'
                    else:
                        action = 'HOLD 🟡'
                        action_desc = '继续持有'

                    price = latest_signal.get('close', 0)
                    date = latest_signal.get('date', '')

                    results[strategy_key] = {
                        'strategy_name': strategy_name,
                        'action': action,
                        'action_desc': action_desc,
                        'signal_value': int(signal_value),
                        'signal_strength': float(signal_strength),
                        'price': float(price),
                        'date': str(date)
                    }

                    if signal_value != 0:
                        signals[strategy_key] = results[strategy_key]

            except Exception as e:
                print(f"⚠️ 策略 {strategy_key} 分析失败: {e}")

        return results, signals

    def run_strategy_analysis_flat(self, data):
        """简化版策略分析，返回 {strategy_key: {strategy_name, signal, signal_strength, price, date}}
        trade_report 等场景使用，不生成 action/action_desc。
        """
        results = {}
        for strategy_key in self.strategies_to_monitor:
            try:
                strategy = get_strategy(strategy_key)
                strategy_name = strategy.name
                signals_df = strategy.generate_signals(data.copy())
                if len(signals_df) > 0:
                    latest_signal = signals_df.iloc[-1]
                    signal_value = latest_signal.get('signal', 0)
                    signal_strength = latest_signal.get('signal_strength', 0)
                    price = latest_signal.get('close', data['close'].iloc[-1])
                    date_val = latest_signal.get('date')
                    if isinstance(date_val, pd.Timestamp):
                        date_str = date_val.strftime('%Y-%m-%d')
                    else:
                        date_str = str(date_val) if date_val else ''
                    results[strategy_key] = {
                        'strategy_name': strategy_name,
                        'signal': int(signal_value),
                        'signal_strength': float(signal_strength),
                        'price': float(price),
                        'date': date_str,
                    }
            except Exception as e:
                print(f"⚠️ 策略 {strategy_key} 分析失败: {e}")
        return results

    # ------------------------------------------------------------------ #
    #  报告保存
    # ------------------------------------------------------------------ #

    def save_report(self, report, subdir='daily_reports', filename_prefix='daily_report'):
        """保存报告到 JSON 文件"""
        try:
            report_dir = Path(__file__).parent.parent / 'data' / subdir
            report_dir.mkdir(parents=True, exist_ok=True)

            today = datetime.now().strftime('%Y-%m-%d')
            report_file = report_dir / f'{filename_prefix}_{today}.json'

            with open(report_file, 'w', encoding='utf-8') as f:
                json.dump(report, f, ensure_ascii=False, indent=2)

            print(f"✅ 报告已保存: {report_file}")
        except Exception as e:
            print(f"❌ 报告保存失败: {e}")

    # ------------------------------------------------------------------ #
    #  信号分类辅助
    # ------------------------------------------------------------------ #

    @staticmethod
    def classify_signals(results):
        """按信号值分类结果"""
        buy_signals = {k: v for k, v in results.items() if v.get('signal_value', v.get('signal', 0)) == 1}
        sell_signals = {k: v for k, v in results.items() if v.get('signal_value', v.get('signal', 0)) == -1}
        hold_signals = {k: v for k, v in results.items() if v.get('signal_value', v.get('signal', 0)) == 0}
        return buy_signals, sell_signals, hold_signals

    @staticmethod
    def compute_change(data):
        """计算最新收盘价涨跌"""
        if data is None or len(data) < 2:
            return 0, 0, data['close'].iloc[-1] if data is not None else 0, ''
        latest_price = data['close'].iloc[-1]
        prev_price = data['close'].iloc[-2]
        change = latest_price - prev_price
        change_pct = (change / prev_price) * 100
        latest_date = data['date'].iloc[-1].strftime('%Y-%m-%d') if 'date' in data.columns else ''
        return change, change_pct, latest_price, latest_date
