#!/usr/bin/env python3
"""
测试职业操盘手策略 - 新增策略验证脚本
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
    AllocationManager,
    list_strategies
)

def generate_test_data(days=300, start_price=100):
    """生成模拟股票数据"""
    dates = pd.date_range(end=datetime.now(), periods=days, freq='D')

    np.random.seed(42)
    returns = np.random.randn(days) * 0.02
    prices = [start_price]
    for r in returns[1:]:
        prices.append(prices[-1] * (1 + r))

    df = pd.DataFrame({
        'date': dates,
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

def test_sentiment_cycle():
    """测试情绪周期策略"""
    print("\n" + "="*60)
    print("📊 情绪周期策略测试")
    print("="*60)

    df = generate_test_data(days=300)
    strategy = SentimentCycleStrategy()
    result = strategy.generate_signals(df)

    signals = result[result['signal'] != 0]
    print(f"\n✅ 策略生成信号数: {len(signals)}")
    print(f"📈 买入信号: {len(signals[signals['signal'] == 1])}")
    print(f"📉 卖出信号: {len(signals[signals['signal'] == -1])}")
    print(f"📋 策略描述: {strategy.get_info()['description']}")

def test_sector_rotation():
    """测试行业轮动策略"""
    print("\n" + "="*60)
    print("🔄 行业轮动策略测试")
    print("="*60)

    df = generate_test_data(days=200)
    strategy = SectorRotationStrategy()
    result = strategy.generate_signals(df)

    signals = result[result['signal'] != 0]
    print(f"\n✅ 策略生成信号数: {len(signals)}")
    print(f"📈 买入信号: {len(signals[signals['signal'] == 1])}")
    print(f"📉 卖出信号: {len(signals[signals['signal'] == -1])}")

def test_prosperity():
    """测试景气度投资策略"""
    print("\n" + "="*60)
    print("📈 景气度投资策略测试")
    print("="*60)

    df = generate_test_data(days=300)
    strategy = ProsperityInvestmentStrategy()
    result = strategy.generate_signals(df)

    signals = result[result['signal'] != 0]
    print(f"\n✅ 策略生成信号数: {len(signals)}")
    print(f"📈 买入信号: {len(signals[signals['signal'] == 1])}")
    print(f"📉 卖出信号: {len(signals[signals['signal'] == -1])}")

def test_band_operation():
    """测试波段操作策略"""
    print("\n" + "="*60)
    print("🌊 波段操作策略测试")
    print("="*60)

    df = generate_test_data(days=300)
    strategy = BandOperationStrategy()
    result = strategy.generate_signals(df)

    signals = result[result['signal'] != 0]
    print(f"\n✅ 策略生成信号数: {len(signals)}")
    print(f"📈 买入信号: {len(signals[signals['signal'] == 1])}")
    print(f"📉 卖出信号: {len(signals[signals['signal'] == -1])}")

def test_value_investment():
    """测试价值投资策略"""
    print("\n" + "="*60)
    print("💎 价值投资策略测试")
    print("="*60)

    df = generate_test_data(days=500)
    strategy = ValueInvestmentStrategy()
    result = strategy.generate_signals(df)

    signals = result[result['signal'] != 0]
    print(f"\n✅ 策略生成信号数: {len(signals)}")
    print(f"📈 买入信号: {len(signals[signals['signal'] == 1])}")
    print(f"📉 卖出信号: {len(signals[signals['signal'] == -1])}")

def test_dragon_head():
    """测试龙头战法"""
    print("\n" + "="*60)
    print("🐉 龙头战法测试")
    print("="*60)

    df = generate_test_data(days=200)
    strategy = DragonHeadStrategy()
    result = strategy.generate_signals(df)

    signals = result[result['signal'] != 0]
    print(f"\n✅ 策略生成信号数: {len(signals)}")
    print(f"📈 买入信号: {len(signals[signals['signal'] == 1])}")
    print(f"📉 卖出信号: {len(signals[signals['signal'] == -1])}")

def test_allocation_manager():
    """测试资产配置管理器"""
    print("\n" + "="*60)
    print("💰 资产配置管理器测试")
    print("="*60)

    allocator = AllocationManager()

    print("\n📊 目标资产配置:")
    allocation = allocator.get_allocation()
    for key, info in allocation.items():
        print(f"  {info['name']}: {info['pct']*100:.0f}%")
        print(f"    描述: {info['description']}")
        if 'examples' in info:
            print(f"    示例: {', '.join(info['examples'])}")

    print("\n⚠️ 风险控制参数:")
    risk_control = allocator.get_risk_control()
    for key, value in risk_control.items():
        if key != 'warnings':
            if isinstance(value, float):
                print(f"  {key}: {value*100:.0f}%" if value < 1 else f"  {key}: {value}")
            else:
                print(f"  {key}: {value}")

    print("\n🚨 风控警告:")
    for warning in risk_control['warnings']:
        print(f"  • {warning}")

    print("\n🔄 再平衡建议示例:")
    mock_allocation = {
        'conservative': 0.5,
        'aggressive': 0.2,
        'index': 0.15,
        'cash': 0.15
    }
    recommendations = allocator.recommend_rebalance(mock_allocation)
    if recommendations:
        for category, rec in recommendations.items():
            print(f"  {category}: {rec['action']} {rec['diff']} - {rec['reason']}")
    else:
        print("  无需再平衡")

def main():
    print("\n" + "="*60)
    print("🎯 职业操盘手策略测试套件")
    print("="*60)

    try:
        test_sentiment_cycle()
        test_sector_rotation()
        test_prosperity()
        test_band_operation()
        test_value_investment()
        test_dragon_head()
        test_allocation_manager()

        print("\n" + "="*60)
        print("✅ 所有职业操盘手策略测试完成!")
        print("="*60)

        print("\n📋 所有可用策略列表:")
        all_strategies = list_strategies()
        print(f"\n总计 {len(all_strategies)} 个策略:")
        for i, strat in enumerate(all_strategies, 1):
            print(f"  {i:2d}. {strat['name']} ({strat['key']})")

    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
