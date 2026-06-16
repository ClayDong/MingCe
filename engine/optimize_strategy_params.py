#!/usr/bin/env python3
"""
策略参数优化脚本 - 使用网格搜索优化策略参数
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
import numpy as np
from datetime import datetime
from itertools import product
from qlib_vnpy_platform.core.strategies import get_strategy

def generate_bull_market_data(days=365, start_price=100):
    """生成牛市数据"""
    dates = pd.date_range(end=datetime.now(), periods=days, freq='D')
    np.random.seed(42)
    
    trend_factor = np.linspace(0, 0.5, days)
    returns = np.random.randn(days) * 0.015 + trend_factor / days
    
    prices = [start_price]
    for r in returns[1:]:
        prices.append(prices[-1] * (1 + r))
    
    df = pd.DataFrame({
        'date': dates,
        'open': prices,
        'high': [p * (1 + abs(np.random.randn() * 0.015)) for p in prices],
        'low': [p * (1 - abs(np.random.randn() * 0.015)) for p in prices],
        'close': prices,
        'volume': [np.random.randint(1000000, 8000000) for _ in range(days)],
        'pe': [15 + np.random.randn() * 5 for _ in range(days)],
        'pb': [1.5 + np.random.randn() * 0.5 for _ in range(days)],
        'roe': [0.15 + np.random.randn() * 0.05 for _ in range(days)],
        'dividend_yield': [0.025 + np.random.randn() * 0.01 for _ in range(days)]
    })
    
    return df

def run_backtest(strategy_name, params, data):
    """运行回测"""
    try:
        strategy = get_strategy(strategy_name, params)
        result = strategy.generate_signals(data.copy())
        
        initial_capital = 1000000
        cash = initial_capital
        holdings = 0
        
        for i in range(len(result)):
            price = result.iloc[i]['close']
            signal = result.iloc[i]['signal']
            
            if signal == 1 and cash > 0:
                shares = int(cash * 0.95 / price)
                cash -= shares * price
                holdings += shares
            elif signal == -1 and holdings > 0:
                cash += holdings * price
                holdings = 0
        
        final_value = cash + holdings * data['close'].iloc[-1]
        total_return = (final_value - initial_capital) / initial_capital * 100
        
        return total_return, len(result[result['signal'] != 0])
    except Exception as e:
        return None, 0

def grid_search(strategy_name, param_grid, data):
    """网格搜索最优参数"""
    param_names = list(param_grid.keys())
    param_values = list(param_grid.values())
    
    best_params = None
    best_return = -float('inf')
    all_results = []
    
    total_combinations = np.prod([len(v) for v in param_values])
    print(f"\n🔍 开始网格搜索: {total_combinations} 种参数组合")
    
    for i, combination in enumerate(product(*param_values), 1):
        params = dict(zip(param_names, combination))
        ret, trade_count = run_backtest(strategy_name, params, data)
        
        if ret is not None:
            all_results.append({
                'params': params,
                'return': ret,
                'trade_count': trade_count
            })
            
            if ret > best_return:
                best_return = ret
                best_params = params
                print(f"  [{i}/{total_combinations}] 新最优! 收益: {ret:.2f}%, 交易: {trade_count}")
    
    return best_params, best_return, all_results

def main():
    print("\n" + "="*70)
    print("🎯 策略参数优化 - 牛市市场")
    print("="*70)
    
    print("\n📊 生成牛市数据...")
    data = generate_bull_market_data(days=365)
    benchmark = (data['close'].iloc[-1] / data['close'].iloc[0] - 1) * 100
    print(f"   基准收益: {benchmark:.2f}%")
    
    strategies_to_optimize = [
        {
            'name': 'prosperity',
            'display_name': '景气度投资',
            'param_grid': {
                'growth_window': [20, 30, 40],
                'min_growth_rate': [0.1, 0.15, 0.2],
                'volume_confirm': [True, False],
                'volume_threshold': [1.2, 1.5, 2.0]
            }
        },
        {
            'name': 'sector_rotation',
            'display_name': '行业轮动',
            'param_grid': {
                'lookback': [40, 60, 80],
                'momentum_window': [15, 20, 30],
                'value_threshold': [0.25, 0.3, 0.4],
                'momentum_threshold': [0.08, 0.1, 0.15]
            }
        },
        {
            'name': 'sentiment_cycle',
            'display_name': '情绪周期',
            'param_grid': {
                'fear_period': [15, 20, 25],
                'greed_period': [8, 10, 15],
                'fear_threshold': [0.2, 0.3, 0.35],
                'greed_threshold': [0.7, 0.8, 0.85]
            }
        },
        {
            'name': 'band_operation',
            'display_name': '波段操作',
            'param_grid': {
                'band_window': [15, 20, 30],
                'buy_band_pct': [0.2, 0.3, 0.4],
                'sell_band_pct': [0.6, 0.7, 0.8],
                'min_hold_days': [3, 5, 7],
                'max_hold_days': [40, 60, 80]
            }
        }
    ]
    
    all_optimization_results = []
    
    for strategy_info in strategies_to_optimize:
        print(f"\n{'='*70}")
        print(f"📈 优化策略: {strategy_info['display_name']} ({strategy_info['name']})")
        print('='*70)
        
        best_params, best_return, all_results = grid_search(
            strategy_info['name'],
            strategy_info['param_grid'],
            data
        )
        
        if best_params:
            print(f"\n🏆 最佳参数:")
            for param, value in best_params.items():
                print(f"   • {param}: {value}")
            print(f"   • 收益: {best_return:.2f}%")
            print(f"   • 超额收益: {best_return - benchmark:.2f}%")
            
            all_optimization_results.append({
                'strategy_name': strategy_info['display_name'],
                'best_params': best_params,
                'best_return': best_return,
                'excess_return': best_return - benchmark
            })
            
            top_5 = sorted(all_results, key=lambda x: x['return'], reverse=True)[:5]
            print(f"\n📊 Top 5 参数组合:")
            for i, result in enumerate(top_5, 1):
                print(f"   {i}. 收益: {result['return']:.2f}%, 交易: {result['trade_count']}次")
                for param, value in result['params'].items():
                    print(f"      - {param}: {value}")
    
    print(f"\n{'='*70}")
    print("📈 优化结果汇总")
    print('='*70)
    
    for result in sorted(all_optimization_results, key=lambda x: x['excess_return'], reverse=True):
        print(f"\n{result['strategy_name']}:")
        print(f"   最佳收益: {result['best_return']:.2f}%")
        print(f"   超额收益: {result['excess_return']:.2f}%")
        print(f"   最佳参数:")
        for param, value in result['best_params'].items():
            print(f"      • {param}: {value}")
    
    best_overall = max(all_optimization_results, key=lambda x: x['excess_return'])
    print(f"\n🏆 总体最佳策略: {best_overall['strategy_name']}")
    print(f"   超额收益: {best_overall['excess_return']:.2f}%")

if __name__ == "__main__":
    main()
