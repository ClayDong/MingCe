
import sys
from pathlib import Path

# 添加项目路径
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from loguru import logger

# 导入策略模块
from qlib_vnpy_platform.core.strategies import get_strategy, STRATEGY_REGISTRY
from qlib_vnpy_platform.core.data_bridge import DataBridge


def generate_test_data(days=100):
    """生成模拟测试数据"""
    np.random.seed(42)
    
    dates = pd.date_range(end=datetime.now(), periods=days, freq='D')
    base_price = 100.0
    
    # 生成带趋势和波动的价格数据
    returns = np.random.normal(0.001, 0.02, days)
    prices = base_price * (1 + returns).cumprod()
    
    # 生成OHLCV数据
    high = prices * (1 + np.random.uniform(0, 0.03, days))
    low = prices * (1 - np.random.uniform(0, 0.03, days))
    open_ = prices * (1 + np.random.uniform(-0.01, 0.01, days))
    close = prices
    volume = np.random.randint(1000000, 10000000, days)
    
    df = pd.DataFrame({
        'date': dates,
        'open': open_,
        'high': high,
        'low': low,
        'close': close,
        'volume': volume
    })
    
    # 再生成一些特殊形态的数据，确保能触发信号
    # 1. 上升趋势数据
    df_trend_up = df.iloc[:30].copy()
    df_trend_up['close'] = df_trend_up['close'] * (1 + np.linspace(0, 0.15, 30))
    df_trend_up['high'] = df_trend_up['high'] * (1 + np.linspace(0, 0.15, 30))
    df_trend_up['low'] = df_trend_up['low'] * (1 + np.linspace(0, 0.15, 30))
    df_trend_up['open'] = df_trend_up['open'] * (1 + np.linspace(0, 0.15, 30))
    
    # 2. 下降趋势数据
    df_trend_down = df.iloc[30:60].copy()
    df_trend_down['close'] = df_trend_down['close'] * (1 - np.linspace(0, 0.15, 30))
    df_trend_down['high'] = df_trend_down['high'] * (1 - np.linspace(0, 0.15, 30))
    df_trend_down['low'] = df_trend_down['low'] * (1 - np.linspace(0, 0.15, 30))
    df_trend_down['open'] = df_trend_down['open'] * (1 - np.linspace(0, 0.15, 30))
    
    # 3. 震荡数据
    df_range = df.iloc[60:].copy()
    
    return pd.concat([df_trend_up, df_trend_down, df_range], ignore_index=True)


def test_strategy(strategy_key):
    """测试单个策略"""
    print(f"\n{'='*80}")
    print(f"  测试策略: {strategy_key}")
    print(f"{'='*80}")
    
    try:
        # 获取策略实例
        strategy = get_strategy(strategy_key)
        if not strategy:
            print(f"❌ 无法找到策略: {strategy_key}")
            return {
                'strategy': strategy_key,
                'status': 'failed',
                'error': '策略不存在'
            }
        
        print(f"✅ 策略名称: {strategy.name}")
        print(f"✅ 策略参数: {strategy.params}")
        
        # 生成测试数据
        df = generate_test_data(days=150)
        print(f"✅ 测试数据已生成，共 {len(df)} 条记录")
        
        # 运行策略生成信号
        result_df = strategy.generate_signals(df.copy())
        
        # 统计信号
        buy_signals = (result_df['signal'] == 1).sum()
        sell_signals = (result_df['signal'] == -1).sum()
        hold_signals = (result_df['signal'] == 0).sum()
        total_signals = buy_signals + sell_signals
        
        print(f"\n📊 信号统计:")
        print(f"   买入信号: {buy_signals}")
        print(f"   卖出信号: {sell_signals}")
        print(f"   无信号:   {hold_signals}")
        print(f"   总信号:   {total_signals}")
        
        # 检查结果列
        required_columns = ['signal', 'signal_strength']
        missing_columns = [col for col in required_columns if col not in result_df.columns]
        
        if missing_columns:
            print(f"❌ 缺少必要列: {missing_columns}")
            return {
                'strategy': strategy_key,
                'name': strategy.name,
                'status': 'failed',
                'error': f'缺少列: {missing_columns}'
            }
        
        # 展示最近的信号
        recent_signals = result_df[result_df['signal'] != 0].tail(5)
        if len(recent_signals) > 0:
            print(f"\n📈 最近的信号:")
            for _, row in recent_signals.iterrows():
                signal_text = "买入" if row['signal'] == 1 else "卖出"
                print(f"   {row['date'].date()}: {signal_text} (置信度: {row['signal_strength']:.2%})")
        else:
            print(f"\n⚠️  当前没有触发信号 (数据可能不符合触发条件)")
        
        # 获取策略信息
        info = strategy.get_info()
        print(f"\n📋 策略信息:")
        print(f"   描述: {info.get('description', '')}")
        
        status = 'passed' if total_signals > 0 else 'passed_no_signals'
        
        return {
            'strategy': strategy_key,
            'name': strategy.name,
            'status': status,
            'buy_signals': buy_signals,
            'sell_signals': sell_signals,
            'total_signals': total_signals,
            'info': info
        }
        
    except Exception as e:
        logger.error(f"策略测试失败: {e}")
        return {
            'strategy': strategy_key,
            'name': strategy_key,
            'status': 'failed',
            'error': str(e)
        }


def main():
    """主测试函数"""
    print("="*80)
    print("  🧪 策略全面测试")
    print("="*80)
    
    # 获取所有策略
    print(f"\n📋 已注册策略 ({len(STRATEGY_REGISTRY)}个):")
    for key in STRATEGY_REGISTRY.keys():
        print(f"   - {key}")
    
    # 逐个测试
    results = []
    for strategy_key in STRATEGY_REGISTRY.keys():
        result = test_strategy(strategy_key)
        results.append(result)
    
    # 生成总结报告
    print(f"\n\n{'='*80}")
    print("  📊 测试总结报告")
    print(f"{'='*80}\n")
    
    # 统计
    total = len(results)
    passed = sum(1 for r in results if r['status'] in ['passed', 'passed_no_signals'])
    failed = sum(1 for r in results if r['status'] == 'failed')
    with_signals = sum(1 for r in results if r.get('total_signals', 0) > 0)
    
    print(f"总策略数: {total}")
    print(f"✅ 通过: {passed}")
    print(f"❌ 失败: {failed}")
    print(f"📈 有信号: {with_signals}")
    
    print(f"\n{'策略名':<20} {'状态':<15} {'买入':<8} {'卖出':<8} {'总信号':<8}")
    print("-"*80)
    
    for result in results:
        name = result.get('name', result.get('strategy', 'Unknown'))[:18]
        status_icon = "✅" if result['status'] != 'failed' else "❌"
        status_text = "通过" if result['status'] != 'failed' else "失败"
        buy = result.get('buy_signals', 0)
        sell = result.get('sell_signals', 0)
        total = result.get('total_signals', 0)
        
        print(f"{name:<20} {status_icon} {status_text:<10} {buy:<8} {sell:<8} {total:<8}")
    
    print("\n" + "="*80)
    print("  测试完成!")
    print("="*80)
    
    return results


if __name__ == "__main__":
    main()
