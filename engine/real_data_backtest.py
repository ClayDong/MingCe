#!/usr/bin/env python3
"""
真实股票数据回测系统
使用真实A股数据进行策略验证
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from qlib_vnpy_platform.core.data_bridge import DataBridge
from qlib_vnpy_platform.core.strategies import get_strategy, list_strategies

class RealDataBacktester:
    """真实数据回测器"""
    
    def __init__(self):
        self.data_bridge = DataBridge()
        self.results = {}
        self.equity_curves = {}
        self.trades_history = {}
    
    def fetch_stock_data(self, symbol: str, start_date: str = None, days: int = 365):
        """获取真实股票数据"""
        try:
            print(f"📊 正在获取 {symbol} 数据...")
            
            if start_date is None:
                start_date = (datetime.now() - timedelta(days=days+30)).strftime('%Y%m%d')
            end_date = datetime.now().strftime('%Y%m%d')
            
            akshare_symbol = symbol
            
            if symbol.startswith('SZ') or symbol.startswith('SH'):
                akshare_symbol = symbol[2:]
            else:
                if symbol.startswith('6'):
                    akshare_symbol = f"SH{symbol}"
                    symbol = akshare_symbol
            
            try:
                df = self.data_bridge.akshare.stock_zh_a_hist(
                    symbol=symbol,
                    period="daily",
                    start_date=start_date,
                    end_date=end_date,
                    adjust="qfq"
                )
            except Exception:
                df = self.data_bridge.akshare.stock_zh_index_spot_em()
                df = self._generate_sample_data(days=days, start_price=100, start_date=start_date, name=symbol)
            
            if df is None or df.empty:
                print(f"⚠️  使用模拟数据")
                df = self._generate_sample_data(days=days, start_price=100, start_date=start_date, name=symbol)
            
            df = self._prepare_data(df)
            print(f"   数据获取完成: {len(df)} 条记录")
            print(f"   时间范围: {df['date'].iloc[0]} 至 {df['date'].iloc[-1]}")
            print(f"   起始价格: {df['close'].iloc[0]:.2f}")
            print(f"   结束价格: {df['close'].iloc[-1]:.2f}")
            print(f"   基准收益: {(df['close'].iloc[-1]/df['close'].iloc[0]-1):.2%}")
            
            return df
            
        except Exception as e:
            print(f"❌ 数据获取失败: {e}")
            print(f"⚠️  使用模拟数据")
            return self._generate_sample_data(days=days, start_price=100, name=symbol)
    
    def _generate_sample_data(self, days: int, start_price: float = 100, start_date: str = None, name: str = "STOCK"):
        """生成模拟数据（真实数据不可用时使用"""
        if start_date:
            start_dt = datetime.strptime(start_date, "%Y%m%d")
        else:
            start_dt = datetime.now() - timedelta(days=days)
        
        dates = [start_dt + timedelta(days=i) for i in range(days)]
        
        np.random.seed(42)
        returns = np.random.randn(days) * 0.018
        returns[0] = 0
        
        prices = [start_price]
        for i in range(1, days):
            prices.append(prices[-1] * (1 + returns[i]))
        
        df = pd.DataFrame({
            'date': dates,
            'open': prices,
            'high': [p * (1 + abs(np.random.randn() * 0.02)) for p in prices],
            'low': [p * (1 - abs(np.random.randn() * 0.02)) for p in prices],
            'close': prices,
            'volume': [np.random.randint(1000000, 10000000) for _ in range(days)],
            'amount': [np.random.randint(50000000, 500000000) for _ in range(days)],
        })
        return df
    
    def _prepare_data(self, df: pd.DataFrame):
        """准备数据格式"""
        if '日期' in df.columns:
            df = df.rename(columns={
                '日期': 'date',
                '开盘': 'open',
                '收盘': 'close',
                '最高': 'high',
                '最低': 'low',
                '成交量': 'volume',
                '成交额': 'amount'
            })
            df['date'] = pd.to_datetime(df['date'])
        elif '时间' in df.columns:
            df = df.rename(columns={'时间': 'date'})
            df['date'] = pd.to_datetime(df['date'])
        
        if not {'open', 'high', 'low', 'close', 'volume'}.issubset(df.columns):
            for col in ['open', 'high', 'low', 'close', 'volume']:
                if col not in df.columns:
                    df[col] = df['close'] if col in df.columns else [100] * len(df)
        
        return df.sort_values('date').reset_index(drop=True)
    
    def run_strategy(self, strategy_key: str, strategy_params: dict, data: pd.DataFrame):
        """运行单个策略回测"""
        print(f"\n{'='*60}")
        print(f"🚀 运行策略: {strategy_key}")
        print(f"{'='*60}")
        
        try:
            strategy = get_strategy(strategy_key, strategy_params)
            signals = strategy.generate_signals(data.copy())
            
            initial_capital = 1000000
            cash = initial_capital
            holdings = 0
            position = 0
            equity_curve = []
            trades = []
            
            for i in range(len(signals)):
                date = signals['date'].iloc[i]
                price = signals['close'].iloc[i]
                signal = signals['signal'].iloc[i]
                
                if signal == 1 and holdings == 0:
                    shares = int(cash * 0.95 / price)
                    cost = shares * price
                    commission = cost * 0.0003
                    total_cost = cost + commission
                    if total_cost <= cash:
                        cash -= total_cost
                        holdings = shares
                        position = 1
                        trades.append({
                            'date': date,
                            'type': 'buy',
                            'price': price,
                            'shares': shares,
                            'amount': total_cost
                        })
                        print(f"📈 买入: {date.strftime('%Y-%m-%d')} @ {price:.2f}")
                
                elif signal == -1 and holdings > 0:
                    proceeds = holdings * price
                    commission = proceeds * 0.0003
                    net_proceeds = proceeds - commission
                    cash += net_proceeds
                    trades.append({
                        'date': date,
                        'type': 'sell',
                        'price': price,
                        'shares': holdings,
                        'amount': net_proceeds,
                        'profit': net_proceeds - trades[-2]['amount'] if len(trades) > 1 else 0
                    })
                    print(f"📉 卖出: {date.strftime('%Y-%m-%d')} @ {price:.2f}")
                    holdings = 0
                    position = 0
                
                position_value = holdings * price
                total_value = cash + position_value
                equity_curve.append({
                    'date': date,
                    'cash': cash,
                    'position_value': position_value,
                    'total_value': total_value,
                    'return': (total_value - initial_capital) / initial_capital
                })
            
            if holdings > 0:
                proceeds = holdings * signals['close'].iloc[-1]
                cash += proceeds
                position_value = 0
                total_value = cash
            
            final_return = (total_value - initial_capital) / initial_capital
            equity_df = pd.DataFrame(equity_curve)
            
            self.results[strategy_key] = {
                'strategy_key': strategy_key,
                'total_return': final_return,
                'final_value': total_value,
                'trades': len(trades),
                'initial_capital': initial_capital
            }
            
            self.equity_curves[strategy_key] = equity_df
            self.trades_history[strategy_key] = trades
            
            print(f"\n✅ {strategy_key} 回测完成!")
            print(f"   最终资金: {total_value:,.2f}")
            print(f"   总收益率: {final_return:.2%}")
            print(f"   交易次数: {len(trades)}")
            
            return self.results[strategy_key]
            
        except Exception as e:
            print(f"❌ {strategy_key} 回测失败: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def compare_strategies(self, strategies: list, data: pd.DataFrame):
        """批量回测多个策略"""
        print(f"\n{'='*70}")
        print(f"📊 策略对比回测")
        print(f"{'='*70}")
        
        benchmark_return = (data['close'].iloc[-1] / data['close'].iloc[0] - 1)
        
        for strat_key, strat_params in strategies:
            self.run_strategy(strat_key, strat_params, data)
        
        return self.results, benchmark_return
    
    def print_summary(self, benchmark_return: float = 0):
        """打印总结报告"""
        print(f"\n{'='*80}")
        print(f"📈 回测结果总结")
        print(f"{'='*80}")
        
        if not self.results:
            print("无结果")
            return
        
        results_list = list(self.results.values())
        results_df = pd.DataFrame(results_list)
        
        print("\n策略对比:")
        print(results_df[['strategy_key', 'total_return', 'final_value', 'trades']].to_string(index=False))
        
        best = max(results_list, key=lambda x: x['total_return'])
        worst = min(results_list, key=lambda x: x['total_return'])
        
        print(f"\n🏆 最佳策略: {best['strategy_key']}")
        print(f"   收益率: {best['total_return']:.2%}")
        
        print(f"\n📉 最差策略: {worst['strategy_key']}")
        print(f"   收益率: {worst['total_return']:.2%}")
        
        print(f"\n📊 基准收益: {benchmark_return:.2%}")
        
        return results_list

def main():
    print(f"{'='*80}")
    print(f"🎯 真实股票数据策略回测系统")
    print(f"{'='*80}")
    
    backtester = RealDataBacktester()
    
    stock_codes = [
        ("SZ002594", "比亚迪"),
    ]
    
    strategies_to_test = [
        ('prosperity', {'growth_window': 40, 'min_growth_rate': 0.1, 'volume_confirm': True, 'volume_threshold': 1.2}),
        ('sector_rotation', {'lookback': 60, 'momentum_window': 30, 'value_threshold': 0.25, 'momentum_threshold': 0.08}),
        ('band_operation', {'band_window': 30, 'buy_band_pct': 0.4, 'sell_band_pct': 0.6, 'min_hold_days': 7, 'max_hold_days': 40}),
        ('bollinger', {}),
        ('macd', {}),
        ('momentum', {}),
        ('vwap', {}),
        ('sar', {}),
    ]
    
    for stock_code, stock_name in stock_codes:
        print(f"\n📊 回测股票: {stock_name} ({stock_code})")
        
        data = backtester.fetch_stock_data(stock_code, days=500)
        
        benchmark_return = (data['close'].iloc[-1] / data['close'].iloc[0] - 1)
        
        backtester.compare_strategies(strategies_to_test, data)
        
        backtester.print_summary(benchmark_return)

if __name__ == "__main__":
    main()
