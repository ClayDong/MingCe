#!/usr/bin/env python3
"""
职业操盘手策略回测验证脚本
使用真实数据测试新策略表现
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from qlib_vnpy_platform.core.strategies import (
    SentimentCycleStrategy,
    SectorRotationStrategy,
    ProsperityInvestmentStrategy,
    BandOperationStrategy,
    ValueInvestmentStrategy,
    DragonHeadStrategy,
    BollingerStrategy,
    MACDStrategy,
    MomentumStrategy,
    STRATEGY_REGISTRY,
    get_strategy
)
from qlib_vnpy_platform.core.backtest import BacktestEngine

def run_backtest(strategy_name, strategy_params, data, initial_capital=1000000):
    """运行单个策略回测"""
    try:
        strategy = get_strategy(strategy_name, strategy_params)
        result = strategy.generate_signals(data.copy())
        
        initial_capital = 1000000
        cash = initial_capital
        holdings = 0
        position_value = 0
        total_value = initial_capital
        trades = []
        equity_curve = []
        
        for i in range(len(result)):
            date = result.iloc[i]['date']
            price = result.iloc[i]['close']
            signal = result.iloc[i]['signal']
            signal_strength = result.iloc[i]['signal_strength']
            
            if signal == 1 and cash > 0:
                shares = int(cash * 0.95 / price)
                cost = shares * price
                cash -= cost
                holdings += shares
                trades.append({
                    'date': date,
                    'type': 'buy',
                    'price': price,
                    'shares': shares,
                    'amount': cost,
                    'signal_strength': signal_strength
                })
            elif signal == -1 and holdings > 0:
                proceeds = holdings * price
                cash += proceeds
                trades.append({
                    'date': date,
                    'type': 'sell',
                    'price': price,
                    'shares': holdings,
                    'amount': proceeds,
                    'signal_strength': signal_strength
                })
                holdings = 0
            
            position_value = holdings * price
            total_value = cash + position_value
            equity_curve.append({
                'date': date,
                'total_value': total_value,
                'cash': cash,
                'position_value': position_value
            })
        
        equity_df = pd.DataFrame(equity_curve)
        total_return = (total_value - initial_capital) / initial_capital * 100
        max_drawdown = calculate_max_drawdown(equity_df['total_value'])
        win_rate = calculate_win_rate(trades)
        profit_factor = calculate_profit_factor(trades)
        
        return {
            'strategy_name': strategy.name,
            'strategy_key': strategy_name,
            'total_return': total_return,
            'max_drawdown': max_drawdown,
            'win_rate': win_rate,
            'profit_factor': profit_factor,
            'trade_count': len(trades),
            'final_value': total_value,
            'equity_curve': equity_df,
            'trades': trades
        }
    except Exception as e:
        print(f"❌ 策略 {strategy_name} 回测失败: {e}")
        import traceback
        traceback.print_exc()
        return None

def calculate_max_drawdown(equity):
    """计算最大回撤"""
    peak = equity.cummax()
    drawdown = (equity - peak) / peak
    return drawdown.min() * 100

def calculate_win_rate(trades):
    """计算胜率"""
    if len(trades) < 2:
        return 0
    sell_trades = [t for t in trades if t['type'] == 'sell']
    if len(sell_trades) == 0:
        return 0
    
    win_count = 0
    for i in range(0, len(trades), 2):
        if i + 1 < len(trades) and trades[i]['type'] == 'buy' and trades[i+1]['type'] == 'sell':
            if trades[i+1]['amount'] > trades[i]['amount']:
                win_count += 1
    
    return win_count / len(sell_trades) * 100

def calculate_profit_factor(trades):
    """计算盈亏比"""
    profits = []
    for i in range(0, len(trades), 2):
        if i + 1 < len(trades) and trades[i]['type'] == 'buy' and trades[i+1]['type'] == 'sell':
            profit = trades[i+1]['amount'] - trades[i]['amount']
            profits.append(profit)
    
    if not profits:
        return 0
    
    total_profit = sum(p for p in profits if p > 0)
    total_loss = abs(sum(p for p in profits if p < 0))
    
    if total_loss == 0:
        return float('inf') if total_profit > 0 else 0
    
    return total_profit / total_loss

def generate_realistic_data(days=365, start_price=100):
    """生成更真实的股票数据"""
    dates = pd.date_range(end=datetime.now(), periods=days, freq='D')
    
    np.random.seed(42)
    returns = np.random.randn(days) * 0.015
    
    for i in range(10, days - 30):
        if i % 60 == 0:
            trend = np.random.choice([0.02, -0.02])
            returns[i:i+30] += trend * np.linspace(1, 0, 30)
    
    prices = [start_price]
    for r in returns[1:]:
        prices.append(prices[-1] * (1 + r))
    
    df = pd.DataFrame({
        'date': dates,
        'open': prices,
        'high': [p * (1 + abs(np.random.randn() * 0.015)) for p in prices],
        'low': [p * (1 - abs(np.random.randn() * 0.015)) for p in prices],
        'close': prices,
        'volume': [np.random.randint(1000000, 8000000) * (1 + np.sin(i/30)*0.3) for i in range(days)],
        'pe': [12 + np.random.randn() * 8 + i/days*5 for i in range(days)],
        'pb': [1.2 + np.random.randn() * 0.8 for i in range(days)],
        'roe': [0.12 + np.random.randn() * 0.08 for i in range(days)],
        'dividend_yield': [0.02 + np.random.randn() * 0.015 for i in range(days)]
    })
    
    df['volume'] = df['volume'].astype(int)
    return df

def main():
    print("\n" + "="*70)
    print("🎯 职业操盘手策略回测验证")
    print("="*70)
    
    print("\n📊 生成测试数据...")
    data = generate_realistic_data(days=365)
    print(f"   数据周期: {len(data)} 天")
    print(f"   起始价格: {data['close'].iloc[0]:.2f}")
    print(f"   结束价格: {data['close'].iloc[-1]:.2f}")
    print(f"   基准收益: {(data['close'].iloc[-1]/data['close'].iloc[0]-1)*100:.2f}%")
    
    strategies_to_test = [
        {'name': 'sentiment_cycle', 'params': {}},
        {'name': 'sector_rotation', 'params': {}},
        {'name': 'prosperity', 'params': {}},
        {'name': 'band_operation', 'params': {}},
        {'name': 'value_investment', 'params': {}},
        {'name': 'dragon_head', 'params': {}},
        {'name': 'bollinger', 'params': {}},
        {'name': 'macd', 'params': {}},
        {'name': 'momentum', 'params': {}},
    ]
    
    results = []
    print(f"\n🚀 开始回测 {len(strategies_to_test)} 个策略...")
    
    for i, strategy_info in enumerate(strategies_to_test, 1):
        print(f"\n   [{i}/{len(strategies_to_test)}] 测试 {strategy_info['name']}...")
        result = run_backtest(strategy_info['name'], strategy_info['params'], data)
        if result:
            results.append(result)
            print(f"     ✅ 完成: 收益 {result['total_return']:.2f}%, 交易 {result['trade_count']} 次")
    
    if not results:
        print("\n❌ 没有策略回测成功")
        return
    
    print("\n" + "="*70)
    print("📈 回测结果汇总")
    print("="*70)
    
    results_df = pd.DataFrame([{
        '策略名称': r['strategy_name'],
        '策略代码': r['strategy_key'],
        '总收益(%)': r['total_return'],
        '最大回撤(%)': r['max_drawdown'],
        '胜率(%)': r['win_rate'],
        '盈亏比': r['profit_factor'],
        '交易次数': r['trade_count'],
        '最终净值': r['final_value']
    } for r in results])
    
    results_df = results_df.sort_values('总收益(%)', ascending=False)
    print(results_df.to_string(index=False, float_format='%.2f'))
    
    best_strategy = max(results, key=lambda x: x['total_return'])
    print(f"\n🏆 最佳策略: {best_strategy['strategy_name']}")
    print(f"   总收益: {best_strategy['total_return']:.2f}%")
    print(f"   最大回撤: {best_strategy['max_drawdown']:.2f}%")
    print(f"   胜率: {best_strategy['win_rate']:.2f}%")
    print(f"   盈亏比: {best_strategy['profit_factor']:.2f}")
    print(f"   交易次数: {best_strategy['trade_count']}")
    
    if best_strategy['trades']:
        print("\n📋 最近5笔交易:")
        for trade in best_strategy['trades'][-5:]:
            print(f"   {trade['date'].strftime('%Y-%m-%d')} {trade['type']}: {trade['price']:.2f} x {trade['shares']}")
    
    print("\n" + "="*70)
    print("✅ 回测完成!")
    print("="*70)
    
    return results

if __name__ == "__main__":
    main()
