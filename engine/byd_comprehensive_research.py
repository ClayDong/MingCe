#!/usr/bin/env python3
"""
比亚迪股票(SZ002594)完整策略研究报告
使用全部27个策略进行深度分析
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import json
from qlib_vnpy_platform.core.data_bridge import DataBridge
from qlib_vnpy_platform.core.strategies import STRATEGY_REGISTRY, get_strategy

class BYDComprehensiveResearch:
    """比亚迪股票综合研究"""
    
    def __init__(self, symbol="SZ002594", stock_name="比亚迪"):
        self.symbol = symbol
        self.stock_name = stock_name
        self.data_bridge = DataBridge()
        self.all_results = {}
        self.best_strategies = []
        
    def fetch_data(self, days=500):
        """获取比亚迪股票数据"""
        print(f"\n{'='*80}")
        print(f"📊 获取 {self.stock_name} ({self.symbol}) 历史数据")
        print(f"{'='*80}")
        
        try:
            df = self.data_bridge.fetch_stock_daily(self.symbol, days=days)
            
            if df is None or df.empty:
                print(f"❌ 无法获取真实数据，使用模拟数据")
                df = self._generate_byd_simulation(days)
            else:
                if 'date' in df.columns:
                    df['date'] = pd.to_datetime(df['date'])
                
                numeric_cols = ['open', 'close', 'high', 'low', 'volume']
                for col in numeric_cols:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors='coerce')
                
                df = df.dropna(subset=['open', 'close', 'high', 'low'])
                df = df.sort_values('date').reset_index(drop=True)
            
            print(f"\n✅ 数据获取成功!")
            print(f"   📅 数据范围: {df['date'].iloc[0].strftime('%Y-%m-%d')} 至 {df['date'].iloc[-1].strftime('%Y-%m-%d')}")
            print(f"   📊 数据条数: {len(df)} 条")
            print(f"   💰 起始价格: {df['close'].iloc[0]:.2f} 元")
            print(f"   💰 结束价格: {df['close'].iloc[-1]:.2f} 元")
            print(f"   📈 期间涨跌: {((df['close'].iloc[-1]/df['close'].iloc[0])-1)*100:+.2f}%")
            
            benchmark_return = (df['close'].iloc[-1] / df['close'].iloc[0] - 1)
            print(f"   🎯 基准收益率: {benchmark_return:+.2%}")
            
            return df, benchmark_return
            
        except Exception as e:
            print(f"❌ 数据获取失败: {e}")
            df = self._generate_byd_simulation(days)
            return df, 0.0
    
    def _generate_byd_simulation(self, days):
        """生成比亚迪模拟数据（基于比亚迪历史特征）"""
        print(f"\n⚠️ 使用模拟数据进行回测")
        
        np.random.seed(42)
        
        base_price = 260
        volatility = 0.025
        drift = 0.0003
        
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        business_days = pd.bdate_range(start=start_date, end=end_date)
        n = len(business_days)
        
        returns = np.random.normal(drift, volatility, n)
        trend = np.linspace(0, 0.4 * np.random.choice([-1, 1]), n)
        cycle = 0.08 * np.sin(np.linspace(0, 6 * np.pi, n))
        returns = returns + trend / n + cycle / n
        
        prices = base_price * np.exp(np.cumsum(returns))
        
        df = pd.DataFrame({
            'date': business_days,
            'open': np.round(prices * (1 + np.random.uniform(-0.01, 0.01, n)), 2),
            'close': np.round(prices, 2),
            'high': np.round(prices * (1 + np.abs(np.random.normal(0, 0.008, n))), 2),
            'low': np.round(prices * (1 - np.abs(np.random.normal(0, 0.008, n))), 2),
            'volume': np.random.randint(3000000, 8000000, n).astype(int)
        })
        
        return df
    
    def run_single_strategy(self, strategy_key, strategy_params, data):
        """运行单个策略"""
        try:
            strategy = get_strategy(strategy_key, strategy_params)
            strategy_name = strategy.name
            
            signals = strategy.generate_signals(data.copy())
            
            initial_capital = 1000000
            cash = initial_capital
            holdings = 0
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
                    
                    if total_cost <= cash and shares > 0:
                        cash -= total_cost
                        holdings = shares
                        
                        trade = {
                            'date': date.strftime('%Y-%m-%d'),
                            'action': 'BUY',
                            'price': round(price, 2),
                            'shares': shares,
                            'amount': round(total_cost, 2)
                        }
                        trades.append(trade)
                
                elif signal == -1 and holdings > 0:
                    proceeds = holdings * price
                    commission = proceeds * 0.0003
                    net_proceeds = proceeds - commission
                    profit = net_proceeds - trades[-1]['amount'] if trades else 0
                    
                    trade = {
                        'date': date.strftime('%Y-%m-%d'),
                        'action': 'SELL',
                        'price': round(price, 2),
                        'shares': holdings,
                        'amount': round(net_proceeds, 2),
                        'profit': round(profit, 2)
                    }
                    trades.append(trade)
                    
                    cash += net_proceeds
                    holdings = 0
                
                position_value = holdings * price
                total_value = cash + position_value
                
                equity_curve.append({
                    'date': date,
                    'total_value': total_value,
                    'return': (total_value - initial_capital) / initial_capital
                })
            
            if holdings > 0:
                final_price = signals['close'].iloc[-1]
                proceeds = holdings * final_price
                cash += proceeds
                holdings = 0
            
            final_value = cash
            total_return = (final_value - initial_capital) / initial_capital
            
            return {
                'strategy_key': strategy_key,
                'strategy_name': strategy_name,
                'total_return': total_return,
                'final_value': final_value,
                'initial_capital': initial_capital,
                'trade_count': len(trades),
                'trades': trades,
                'equity_curve': equity_curve
            }
            
        except Exception as e:
            print(f"   ❌ 策略 {strategy_key} 执行失败: {e}")
            return None
    
    def run_all_strategies(self, data):
        """运行所有27个策略"""
        print(f"\n{'='*80}")
        print(f"🚀 开始运行全部27个策略")
        print(f"{'='*80}")
        
        strategies_to_run = [
            ('ma_cross', {}, '均线交叉策略'),
            ('rsi', {}, 'RSI超买超卖策略'),
            ('macd', {}, 'MACD金叉死叉策略'),
            ('bollinger', {}, '布林带突破策略'),
            ('momentum', {}, '动量策略'),
            ('kdj', {}, 'KDJ随机指标策略'),
            ('dual_thrust', {}, 'Dual Thrust策略'),
            ('turtle', {}, '海龟交易策略'),
            ('mean_reversion', {}, '均值回归策略'),
            ('ma_alignment', {}, '均线排列策略'),
            ('volume_breakout', {}, '成交量突破策略'),
            ('volatility_breakout', {}, '波动率突破策略'),
            ('trend_following', {}, '趋势跟随策略'),
            ('gap', {}, '跳空策略'),
            ('three_soldiers', {}, '三只乌鸦/红三兵策略'),
            ('support_resistance', {}, '支撑阻力策略'),
            ('obv', {}, 'OBV能量潮策略'),
            ('sentiment_cycle', {}, '情绪周期策略'),
            ('sector_rotation', {}, '行业轮动策略'),
            ('prosperity', {}, '景气度投资策略'),
            ('band_operation', {}, '波段操作策略'),
            ('value_investment', {}, '价值投资策略'),
            ('dragon_head', {}, '龙头战法策略'),
            ('macd_multitimeframe', {}, 'MACD多时间框架策略'),
            ('vwap', {}, 'VWAP成交量加权策略'),
            ('sar', {}, 'SAR抛物线策略'),
            ('mfi', {}, 'MFI资金流策略'),
        ]
        
        successful = 0
        failed = 0
        
        for i, (key, params, name) in enumerate(strategies_to_run, 1):
            print(f"\n[{i:2d}/27] 📈 {name} ({key})")
            
            result = self.run_single_strategy(key, params, data)
            
            if result:
                self.all_results[key] = result
                successful += 1
                
                return_str = f"{result['total_return']:+.2%}"
                trade_count = result['trade_count']
                print(f"   ✅ 收益率: {return_str:>10} | 交易次数: {trade_count:2d}")
            else:
                failed += 1
        
        print(f"\n{'='*80}")
        print(f"📊 策略执行完成: 成功 {successful} 个, 失败 {failed} 个")
        print(f"{'='*80}")
        
        return self.all_results
    
    def analyze_results(self, benchmark_return):
        """分析回测结果"""
        print(f"\n{'='*80}")
        print(f"🏆 策略表现排名分析")
        print(f"{'='*80}")
        
        if not self.all_results:
            print("❌ 没有可分析的结果")
            return
        
        results_list = []
        for key, result in self.all_results.items():
            results_list.append({
                '排名': 0,
                '策略名称': result['strategy_name'],
                '策略代码': key,
                '总收益率': result['total_return'],
                '最终资金': result['final_value'],
                '交易次数': result['trade_count'],
                '超额收益': result['total_return'] - benchmark_return
            })
        
        results_df = pd.DataFrame(results_list)
        results_df = results_df.sort_values('总收益率', ascending=False).reset_index(drop=True)
        results_df['排名'] = range(1, len(results_df) + 1)
        
        print(f"\n📊 收益率排名 (基准收益: {benchmark_return:+.2%}):\n")
        print(results_df[['排名', '策略名称', '总收益率', '交易次数', '超额收益']].to_string(index=False))
        
        best_5 = results_df.head(5)
        worst_5 = results_df.tail(5)
        
        print(f"\n🏅 TOP 5 最佳策略:")
        for idx, row in best_5.iterrows():
            print(f"   {row['排名']}. {row['策略名称']}: {row['总收益率']:+.2%} (交易 {row['交易次数']} 次)")
        
        print(f"\n📉 BOTTOM 5 最差策略:")
        for idx, row in worst_5.iterrows():
            print(f"   {row['排名']}. {row['策略名称']}: {row['总收益率']:+.2%} (交易 {row['交易次数']} 次)")
        
        profitable_strategies = results_df[results_df['总收益率'] > benchmark_return]
        print(f"\n✅ 跑赢基准的策略: {len(profitable_strategies)}/{len(results_df)} 个")
        
        return results_df, best_5
    
    def generate_detailed_report(self, benchmark_return):
        """生成详细分析报告"""
        print(f"\n{'='*80}")
        print(f"📝 比亚迪股票策略深度分析报告")
        print(f"{'='*80}")
        
        print(f"\n📌 股票基本信息:")
        print(f"   股票名称: {self.stock_name}")
        print(f"   股票代码: {self.symbol}")
        print(f"   分析日期: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"   基准收益: {benchmark_return:+.2%}")
        
        if not self.all_results:
            print("\n❌ 没有回测数据")
            return
        
        results_df, best_5 = self.analyze_results(benchmark_return)
        
        print(f"\n{'='*80}")
        print(f"💡 策略选择建议")
        print(f"{'='*80}")
        
        if len(best_5) > 0:
            best_strategy = best_5.iloc[0]
            print(f"\n🥇 推荐最佳策略: {best_strategy['策略名称']}")
            print(f"   - 总收益率: {best_strategy['总收益率']:+.2%}")
            print(f"   - 超额收益: {best_strategy['超额收益']:+.2%}")
            print(f"   - 交易次数: {best_strategy['交易次数']} 次")
            
            if best_strategy['策略代码'] in self.all_results:
                trades = self.all_results[best_strategy['策略代码']]['trades']
                if trades:
                    print(f"\n📋 详细交易记录:")
                    for i, trade in enumerate(trades[:10], 1):
                        profit_info = f" | 盈利: {trade.get('profit', 0):.2f}" if 'profit' in trade and trade['action'] == 'SELL' else ""
                        print(f"   {i:2d}. {trade['date']} | {trade['action']:4s} | 价格: {trade['price']:8.2f} | 数量: {trade['shares']:6d}{profit_info}")
                    
                    if len(trades) > 10:
                        print(f"   ... (共 {len(trades)} 笔交易)")
        
        print(f"\n{'='*80}")
        print(f"🎯 投资建议总结")
        print(f"{'='*80}")
        
        winning_strategies = results_df[results_df['总收益率'] > 0]
        print(f"\n✅ 盈利策略数量: {len(winning_strategies)}/{len(results_df)}")
        
        if len(winning_strategies) > 0:
            avg_win_return = winning_strategies['总收益率'].mean()
            print(f"   盈利策略平均收益率: {avg_win_return:+.2%}")
        
        losing_strategies = results_df[results_df['总收益率'] < 0]
        if len(losing_strategies) > 0:
            avg_loss_return = losing_strategies['总收益率'].mean()
            print(f"   亏损策略平均收益率: {avg_loss_return:+.2%}")
        
        print(f"\n💼 风险提示:")
        print(f"   - 以上结果基于历史数据回测,不代表未来收益")
        print(f"   - 实际交易需考虑手续费、滑点等因素")
        print(f"   - 建议结合基本面分析和市场环境综合决策")
        
        print(f"\n{'='*80}")
        
        return results_df

def main():
    print(f"\n{'#'*80}")
    print(f"#")
    print(f"#  🎯 比亚迪股票 (SZ002594) 量化策略深度研究报告")
    print(f"#  使用全部27个策略进行全面回测分析")
    print(f"#")
    print(f"{'#'*80}")
    
    researcher = BYDComprehensiveResearch("SZ002594", "比亚迪")
    
    data, benchmark_return = researcher.fetch_data(days=500)
    
    researcher.run_all_strategies(data)
    
    results_df = researcher.generate_detailed_report(benchmark_return)
    
    print(f"\n\n📁 完整排名数据:")
    if results_df is not None:
        print(results_df.to_string(index=False))
    
    print(f"\n{'='*80}")
    print(f"✅ 研究报告生成完成!")
    print(f"{'='*80}")

if __name__ == "__main__":
    main()
