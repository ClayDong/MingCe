#!/usr/bin/env python3
"""
实盘模拟交易系统
基于优化后的策略进行实时模拟交易
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from collections import defaultdict
import json

class SimulatedBroker:
    """模拟券商"""
    def __init__(self, initial_capital=1000000, commission_rate=0.0003):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.commission_rate = commission_rate
        self.positions = {}  # {stock_code: {'shares': int, 'avg_cost': float}}
        self.trades = []
        self.equity_curve = []
    
    def buy(self, stock_code, price, shares, date):
        """买入"""
        cost = shares * price
        commission = cost * self.commission_rate
        total_cost = cost + commission
        
        if total_cost > self.cash:
            return False, "资金不足"
        
        if stock_code not in self.positions:
            self.positions[stock_code] = {'shares': 0, 'avg_cost': 0}
        
        old_shares = self.positions[stock_code]['shares']
        old_cost = old_shares * self.positions[stock_code]['avg_cost']
        new_shares = old_shares + shares
        new_cost = (old_cost + cost) / new_shares
        
        self.positions[stock_code]['shares'] = new_shares
        self.positions[stock_code]['avg_cost'] = new_cost
        self.cash -= total_cost
        
        self.trades.append({
            'date': date,
            'stock_code': stock_code,
            'action': 'BUY',
            'price': price,
            'shares': shares,
            'cost': cost,
            'commission': commission
        })
        
        return True, f"买入成功: {stock_code} {shares}股 @{price:.2f}"
    
    def sell(self, stock_code, price, shares, date):
        """卖出"""
        if stock_code not in self.positions or self.positions[stock_code]['shares'] < shares:
            return False, "持仓不足"
        
        proceeds = shares * price
        commission = proceeds * self.commission_rate
        net_proceeds = proceeds - commission
        
        self.positions[stock_code]['shares'] -= shares
        self.cash += net_proceeds
        
        if self.positions[stock_code]['shares'] == 0:
            del self.positions[stock_code]
        
        self.trades.append({
            'date': date,
            'stock_code': stock_code,
            'action': 'SELL',
            'price': price,
            'shares': shares,
            'proceeds': proceeds,
            'commission': commission,
            'profit': net_proceeds - shares * self.positions.get(stock_code, {}).get('avg_cost', price) if stock_code in self.positions else 0
        })
        
        return True, f"卖出成功: {stock_code} {shares}股 @{price:.2f}"
    
    def get_position_value(self, prices):
        """获取持仓市值"""
        total = 0
        for stock_code, pos in self.positions.items():
            price = prices.get(stock_code, pos['avg_cost'])
            total += pos['shares'] * price
        return total
    
    def get_total_value(self, prices):
        """获取总资产"""
        return self.cash + self.get_position_value(prices)
    
    def record_equity(self, date, prices):
        """记录资产曲线"""
        total_value = self.get_total_value(prices)
        self.equity_curve.append({
            'date': date,
            'cash': self.cash,
            'position_value': self.get_position_value(prices),
            'total_value': total_value,
            'return': (total_value - self.initial_capital) / self.initial_capital * 100
        })

class StrategySimulator:
    """策略模拟器"""
    def __init__(self, broker, strategy, params):
        self.broker = broker
        self.strategy = strategy
        self.params = params
        self.current_position = 0
    
    def run(self, data, stock_code):
        """运行模拟"""
        strategy = self.broker.strategy.get_strategy(self.strategy, self.params)
        result = strategy.generate_signals(data.copy())
        
        for i in range(len(result)):
            date = result.iloc[i]['date']
            price = result.iloc[i]['close']
            signal = result.iloc[i]['signal']
            signal_strength = result.iloc[i]['signal_strength']
            
            if signal == 1 and self.current_position == 0:
                max_shares = int(self.broker.cash * 0.95 / price)
                if max_shares > 0:
                    success, msg = self.broker.buy(stock_code, price, max_shares, date)
                    if success:
                        self.current_position = max_shares
                        print(f"  📈 {date.strftime('%Y-%m-%d')}: {msg}")
            
            elif signal == -1 and self.current_position > 0:
                success, msg = self.broker.sell(stock_code, price, self.current_position, date)
                if success:
                    print(f"  📉 {date.strftime('%Y-%m-%d')}: {msg}")
                    self.current_position = 0
            
            self.broker.record_equity(date, {stock_code: price})
        
        return self.broker

def generate_simulated_data(days=30, stock_code='SZ002594'):
    """生成模拟实时数据"""
    dates = pd.date_range(end=datetime.now(), periods=days, freq='D')
    np.random.seed(42)
    
    base_price = 100
    prices = [base_price]
    for i in range(days - 1):
        change = np.random.randn() * 2
        prices.append(prices[-1] * (1 + change / 100))
    
    df = pd.DataFrame({
        'date': dates,
        'stock_code': stock_code,
        'open': prices,
        'high': [p * (1 + abs(np.random.randn() * 0.01)) for p in prices],
        'low': [p * (1 - abs(np.random.randn() * 0.01)) for p in prices],
        'close': prices,
        'volume': [np.random.randint(1000000, 5000000) for _ in range(days)],
        'pe': [15 + np.random.randn() * 5 for _ in range(days)],
        'pb': [1.5 + np.random.randn() * 0.5 for _ in range(days)],
        'roe': [0.15 + np.random.randn() * 0.05 for _ in range(days)],
        'dividend_yield': [0.025 + np.random.randn() * 0.01 for _ in range(days)]
    })
    
    return df

def main():
    print("\n" + "="*70)
    print("🎯 实盘模拟交易系统")
    print("="*70)
    
    stock_code = 'SZ002594'
    print(f"\n📊 股票: {stock_code}")
    print(f"📅 模拟周期: 最近30天")
    
    data = generate_simulated_data(days=30, stock_code=stock_code)
    print(f"   数据条数: {len(data)}")
    print(f"   起始价格: {data['close'].iloc[0]:.2f}")
    print(f"   最新价格: {data['close'].iloc[-1]:.2f}")
    
    initial_capital = 1000000
    
    strategies_to_simulate = [
        {
            'name': 'prosperity',
            'display_name': '景气度投资',
            'params': {
                'growth_window': 40,
                'min_growth_rate': 0.1,
                'volume_confirm': True,
                'volume_threshold': 1.2
            }
        },
        {
            'name': 'sector_rotation',
            'display_name': '行业轮动',
            'params': {
                'lookback': 60,
                'momentum_window': 30,
                'value_threshold': 0.25,
                'momentum_threshold': 0.08
            }
        },
        {
            'name': 'band_operation',
            'display_name': '波段操作',
            'params': {
                'band_window': 30,
                'buy_band_pct': 0.4,
                'sell_band_pct': 0.6,
                'min_hold_days': 7,
                'max_hold_days': 40
            }
        }
    ]
    
    all_results = []
    
    for strategy_info in strategies_to_simulate:
        print(f"\n{'='*70}")
        print(f"📈 模拟策略: {strategy_info['display_name']}")
        print('='*70)
        
        broker = SimulatedBroker(initial_capital=initial_capital)
        broker.strategy = __import__('qlib_vnpy_platform.core.strategies', fromlist=[''])
        
        simulator = StrategySimulator(broker, strategy_info['name'], strategy_info['params'])
        broker = simulator.run(data, stock_code)
        
        equity_df = pd.DataFrame(broker.equity_curve)
        total_return = (equity_df['total_value'].iloc[-1] - initial_capital) / initial_capital * 100
        
        print(f"\n📊 模拟结果:")
        print(f"   初始资金: {initial_capital:,.2f}")
        print(f"   最终价值: {equity_df['total_value'].iloc[-1]:,.2f}")
        print(f"   总收益: {total_return:.2f}%")
        print(f"   交易次数: {len(broker.trades)}")
        
        if broker.trades:
            print(f"\n📋 交易记录:")
            for trade in broker.trades:
                print(f"   {trade['date'].strftime('%Y-%m-%d')} {trade['action']}: "
                      f"{trade['stock_code']} {trade['shares']}股 @{trade['price']:.2f}")
        
        all_results.append({
            'strategy_name': strategy_info['display_name'],
            'strategy_key': strategy_info['name'],
            'params': strategy_info['params'],
            'total_return': total_return,
            'final_value': equity_df['total_value'].iloc[-1],
            'trade_count': len(broker.trades),
            'equity_curve': equity_df,
            'trades': broker.trades
        })
        
        output_file = f'/tmp/simulation_{strategy_info["name"]}.json'
        with open(output_file, 'w') as f:
            json.dump({
                'strategy': strategy_info['display_name'],
                'total_return': total_return,
                'final_value': equity_df['total_value'].iloc[-1],
                'trades': broker.trades,
                'equity_curve': equity_df.to_dict('records')
            }, f, indent=2, default=str)
        print(f"\n💾 模拟数据已保存: {output_file}")
    
    print(f"\n{'='*70}")
    print("📈 实盘模拟汇总")
    print('='*70)
    
    results_df = pd.DataFrame([{
        '策略名称': r['strategy_name'],
        '总收益(%)': r['total_return'],
        '最终价值': r['final_value'],
        '交易次数': r['trade_count']
    } for r in all_results])
    
    results_df = results_df.sort_values('总收益(%)', ascending=False)
    print(results_df.to_string(index=False))
    
    best_strategy = max(all_results, key=lambda x: x['total_return'])
    print(f"\n🏆 最佳策略: {best_strategy['strategy_name']}")
    print(f"   总收益: {best_strategy['total_return']:.2f}%")
    print(f"   交易次数: {best_strategy['trade_count']}")

if __name__ == "__main__":
    main()
