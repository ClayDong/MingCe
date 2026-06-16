#!/usr/bin/env python3
"""
策略组合回测 - 测试职业操盘手推荐的配置方案
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
import numpy as np
from datetime import datetime
from qlib_vnpy_platform.core.strategies import (
    SentimentCycleStrategy,
    SectorRotationStrategy,
    ProsperityInvestmentStrategy,
    BandOperationStrategy,
    ValueInvestmentStrategy,
    BollingerStrategy,
    MACDStrategy,
    MomentumStrategy,
    get_strategy
)

def generate_market_data(days=365, start_price=100, trend='sideways'):
    """生成不同市场环境的数据"""
    dates = pd.date_range(end=datetime.now(), periods=days, freq='D')
    np.random.seed(42)
    
    base_volatility = 0.015
    
    if trend == 'up':
        trend_factor = np.linspace(0, 0.5, days)
    elif trend == 'down':
        trend_factor = np.linspace(0, -0.5, days)
    else:
        trend_factor = np.zeros(days)
    
    returns = np.random.randn(days) * base_volatility + trend_factor / days
    
    prices = [start_price]
    for i, r in enumerate(returns[1:], 1):
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

def run_strategy(strategy_name, params, data):
    """运行单个策略"""
    strategy = get_strategy(strategy_name, params)
    result = strategy.generate_signals(data.copy())
    return result

def run_portfolio(strategy_allocations, data, initial_capital=1000000):
    """运行组合策略"""
    portfolio = {}
    equity_curve = []
    total_value = initial_capital
    
    for strategy_name, allocation in strategy_allocations.items():
        capital = initial_capital * allocation
        result = run_strategy(strategy_name, {}, data)
        
        cash = capital
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
        portfolio[strategy_name] = {
            'allocation': allocation,
            'initial': capital,
            'final': final_value,
            'return': (final_value - capital) / capital * 100
        }
        total_value += (final_value - capital)
    
    return portfolio, total_value

def main():
    print("\n" + "="*70)
    print("🎯 策略组合回测")
    print("="*70)
    
    market_scenarios = [
        {'name': '震荡市', 'trend': 'sideways'},
        {'name': '牛市', 'trend': 'up'},
        {'name': '熊市', 'trend': 'down'}
    ]
    
    portfolio_configs = [
        {
            'name': '稳健长线组合',
            'description': '机构策略为主，适合长期投资',
            'allocation': {
                'value_investment': 0.5,
                'sector_rotation': 0.3,
                'bollinger': 0.2
            }
        },
        {
            'name': '平衡中线组合',
            'description': '私募策略为主，兼顾稳健与进攻',
            'allocation': {
                'prosperity': 0.3,
                'band_operation': 0.25,
                'sector_rotation': 0.2,
                'macd': 0.25
            }
        },
        {
            'name': '进取短线组合',
            'description': '游资策略为主，高风险高收益',
            'allocation': {
                'momentum': 0.3,
                'sentiment_cycle': 0.2,
                'dragon_head': 0.1,
                'bollinger': 0.4
            }
        },
        {
            'name': '大师兄组合',
            'description': '顶级操盘手配置：70%稳+20%攻+10%现金',
            'allocation': {
                'value_investment': 0.35,
                'sector_rotation': 0.2,
                'prosperity': 0.15,
                'momentum': 0.1,
                'bollinger': 0.2
            }
        }
    ]
    
    all_results = []
    
    for scenario in market_scenarios:
        print(f"\n📊 市场场景: {scenario['name']}")
        data = generate_market_data(days=365, trend=scenario['trend'])
        benchmark_return = (data['close'].iloc[-1] / data['close'].iloc[0] - 1) * 100
        
        for portfolio in portfolio_configs:
            portfolio_result, final_value = run_portfolio(portfolio['allocation'], data)
            total_return = (final_value - 1000000) / 1000000 * 100
            
            all_results.append({
                '市场场景': scenario['name'],
                '组合名称': portfolio['name'],
                '总收益(%)': total_return,
                '基准收益(%)': benchmark_return,
                '超额收益(%)': total_return - benchmark_return
            })
            
            print(f"  • {portfolio['name']}: {total_return:.2f}% (基准: {benchmark_return:.2f}%)")
    
    print("\n" + "="*70)
    print("📈 组合回测结果汇总")
    print("="*70)
    
    results_df = pd.DataFrame(all_results)
    results_df = results_df.sort_values('超额收益(%)', ascending=False)
    print(results_df.to_string(index=False, float_format='%.2f'))
    
    best_portfolio = results_df.iloc[0]
    print(f"\n🏆 最佳组合: {best_portfolio['组合名称']}")
    print(f"   市场场景: {best_portfolio['市场场景']}")
    print(f"   总收益: {best_portfolio['总收益(%)']:.2f}%")
    print(f"   超额收益: {best_portfolio['超额收益(%)']:.2f}%")

if __name__ == "__main__":
    main()
