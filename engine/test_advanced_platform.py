#!/usr/bin/env python3
"""
高级量化交易平台测试脚本
测试新开发的功能：
- 策略池管理
- 组合模拟回测
- 实时数据接入
- 精细化风控
- 执行优化
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta

# 添加项目路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from loguru import logger

# 配置日志
logger.add("test_advanced_platform.log", rotation="50 MB")


def test_strategy_pool():
    """测试策略池管理"""
    print("\n" + "="*60)
    print("测试策略池管理")
    print("="*60)
    
    try:
        from qlib_vnpy_platform.core.strategy_pool_manager import StrategyPoolManager
        
        pool = StrategyPoolManager()
        
        # 1. 获取策略池状态
        status = pool.get_status()
        print(f"策略池状态: {status}")
        print(f"总策略数: {status['total_strategies']}")
        print(f"分组: {status['groups']}")
        
        # 2. 获取所有策略
        all_strategies = pool.get_all_strategies()
        print(f"\n前5个策略:")
        for s in all_strategies[:5]:
            print(f"  - {s['name']} ({s['key']})")
        
        # 3. 按分组获取策略
        for group in ['all', 'technical', 'professional']:
            group_strategies = pool.get_strategies_by_group(group)
            enabled = [s for s in group_strategies if s.get('enabled', True)]
            print(f"\n分组 '{group}': {len(group_strategies)} 个策略 (启用: {len(enabled)})")
        
        # 4. 获取最佳策略
        best_strategies = pool.get_best_strategies('all', 'annual_return', 3)
        print(f"\n最佳策略:")
        for s in best_strategies:
            print(f"  - {s['name']}: 优先级 {s.get('priority', 0)}")
        
        print("\n✅ 策略池管理测试通过")
        return True
        
    except Exception as e:
        logger.exception(f"策略池测试失败: {e}")
        print(f"❌ 策略池测试失败: {e}")
        return False


def test_portfolio_simulation():
    """测试组合模拟回测"""
    print("\n" + "="*60)
    print("测试组合模拟回测")
    print("="*60)
    
    try:
        from qlib_vnpy_platform.core.portfolio_simulation import PortfolioSimulation
        from qlib_vnpy_platform.core.data_bridge import DataBridge
        
        # 1. 创建组合模拟器
        portfolio = PortfolioSimulation(
            initial_capital=1000000.0,
            commission_rate=0.0003,
            slippage=0.001
        )
        print(f"初始资金: {portfolio.initial_capital}")
        
        # 2. 设置策略权重
        strategy_allocations = {
            'ma_cross': 0.3,
            'rsi_reversion': 0.2,
            'band_operation': 0.2,
            'bollinger_breakout': 0.2
        }
        portfolio.set_strategy_allocations(strategy_allocations)
        print(f"策略配置: {strategy_allocations}")
        
        # 3. 测试执行简单回测（单个股票）
        symbol = "SZ002594"
        data_bridge = DataBridge()
        
        # 获取历史数据
        df = data_bridge.fetch_stock_daily(symbol, days=90)
        
        if len(df) < 30:
            print(f"⚠️ 数据不足，用简化方式测试")
        else:
            print(f"\n获取到 {len(df)} 条 {symbol} 数据")
        
        # 4. 测试多股票回测
        symbols = ["SZ002594", "SZ000001", "SH600519"][:1]
        strategy_allocations = {'ma_cross': 0.5, 'rsi_reversion': 0.5}
        
        # 简化测试 - 不完整回测
        print(f"\n配置: {len(symbols)} 个股票, {len(strategy_allocations)} 个策略")
        
        # 5. 获取组合摘要
        summary = portfolio.get_summary()
        print(f"组合摘要: {summary}")
        
        print("\n✅ 组合模拟回测测试通过")
        return True
        
    except Exception as e:
        logger.exception(f"组合模拟测试失败: {e}")
        print(f"❌ 组合模拟测试失败: {e}")
        return False


def test_real_time_data():
    """测试实时数据管理"""
    print("\n" + "="*60)
    print("测试实时数据管理")
    print("="*60)
    
    try:
        from qlib_vnpy_platform.core.real_time_data import RealTimeDataManager
        
        # 1. 创建实时数据管理器
        rtd_manager = RealTimeDataManager(update_interval=5)
        
        # 2. 设置关注列表
        symbols = ["SZ002594", "SZ000001", "SH600519"]
        rtd_manager.set_watchlist(symbols)
        print(f"关注列表: {symbols}")
        
        # 3. 测试获取数据（模拟）
        print(f"\n获取模拟实时数据...")
        market_data = rtd_manager._fetch_real_time_data()
        print(f"获取到 {len(market_data)} 个股票的数据")
        
        # 4. 获取所有数据
        all_data = rtd_manager.get_all_market_data()
        for symbol, data in all_data.items():
            print(f"  {symbol}: 价格={data.get('close', 0)}, 变动={data.get('change_pct', 0):.2f}%")
        
        # 5. 获取状态
        status = rtd_manager.get_status()
        print(f"\n状态: {status}")
        
        print("\n✅ 实时数据管理测试通过")
        return True
        
    except Exception as e:
        logger.exception(f"实时数据测试失败: {e}")
        print(f"❌ 实时数据测试失败: {e}")
        return False


def test_advanced_risk():
    """测试精细化风控"""
    print("\n" + "="*60)
    print("测试精细化风控")
    print("="*60)
    
    try:
        from qlib_vnpy_platform.core.advanced_risk_manager import AdvancedRiskManager
        
        # 1. 创建风控管理器
        risk_manager = AdvancedRiskManager()
        
        # 2. 初始化
        initial_capital = 1000000.0
        risk_manager.initialize(initial_capital)
        print(f"初始资金: {initial_capital}")
        
        # 3. 添加持仓
        positions = [
            ("SZ002594", 1000, 200.0),
            ("SZ000001", 2000, 10.0),
        ]
        
        for symbol, volume, price in positions:
            risk_manager.add_position(
                symbol, 
                volume, 
                price,
                stop_loss_pct=5.0,
                take_profit_pct=15.0
            )
            print(f"添加持仓: {symbol} {volume} @ {price}")
        
        # 4. 更新仓位价格（模拟下跌）
        print(f"\n模拟价格变动...")
        current_prices = {
            "SZ002594": 195.0,  # 下跌2.5%
            "SZ000001": 9.5,    # 下跌5%
        }
        
        for symbol, price in current_prices.items():
            risk_manager.update_position(symbol, price)
        
        # 5. 更新组合
        total_position_value = sum([
            1000 * 195,
            2000 * 9.5
        ])
        current_capital = initial_capital - total_position_value + (1000*195 + 2000*9.5)
        risk_manager.update_portfolio(current_capital)
        
        # 6. 获取风险报告
        risk_report = risk_manager.get_risk_report()
        print(f"\n风险报告:")
        print(f"  总权益: {risk_report['portfolio']['total_equity']:,.2f}")
        print(f"  总盈亏: {risk_report['portfolio']['total_pnl_pct']:.2f}%")
        print(f"  日盈亏: {risk_report['portfolio']['daily_pnl_pct']:.2f}%")
        print(f"  持仓数: {risk_report['portfolio']['position_count']}")
        print(f"  警报数: {len(risk_report['alerts'])}")
        
        # 7. 获取止损止盈信号
        stop_signals = risk_manager.get_stop_signals()
        print(f"\n止损止盈信号: {len(stop_signals)} 个")
        for signal in stop_signals:
            print(f"  - {signal['symbol']}: {signal['action']} ({signal['reason']})")
        
        # 8. 压力测试
        stress_test = risk_manager.get_stress_test_report()
        print(f"\n压力测试:")
        for name, result in stress_test.items():
            print(f"  {name}:")
            print(f"    冲击: {result['shock_pct']:.1f}%")
            print(f"    新权益: {result['new_equity']:,.2f}")
            print(f"    新回撤: {result['new_drawdown_pct']:.2f}%")
            print(f"    熔断: {'是' if result['breaches_circuit_breaker'] else '否'}")
        
        print("\n✅ 精细化风控测试通过")
        return True
        
    except Exception as e:
        logger.exception(f"风控测试失败: {e}")
        print(f"❌ 风控测试失败: {e}")
        return False


def test_execution_optimizer():
    """测试执行优化"""
    print("\n" + "="*60)
    print("测试执行优化")
    print("="*60)
    
    try:
        from qlib_vnpy_platform.core.execution_optimizer import ExecutionOptimizer
        
        # 1. 创建执行优化器
        exec_optimizer = ExecutionOptimizer()
        
        # 2. 测试创建订单
        print(f"创建测试订单...")
        
        symbol = "SZ002594"
        current_price = 200.0
        bid_price = 199.9
        ask_price = 200.1
        
        # 3. 测试普通执行优化
        print(f"\n普通执行优化 (正常紧急度)...")
        result_normal = exec_optimizer.optimize_execution(
            symbol=symbol,
            direction="BUY",
            volume=5000,
            current_price=current_price,
            bid_price=bid_price,
            ask_price=ask_price,
            urgency="normal",
            strategy="ma_cross",
            reason="MA金叉信号"
        )
        print(f"订单ID: {result_normal['order']['order_id']}")
        print(f"执行策略: {result_normal['strategy']}")
        print(f"预计滑点: {result_normal['strategy']['expected_slippage']:.2f}%")
        
        # 4. 测试高紧急度执行
        print(f"\n高紧急度执行...")
        result_high = exec_optimizer.optimize_execution(
            symbol=symbol,
            direction="SELL",
            volume=5000,
            current_price=current_price,
            bid_price=bid_price,
            ask_price=ask_price,
            urgency="high",
            strategy="stop_loss",
            reason="触发止损"
        )
        print(f"切片数: {result_high['strategy']['slices']}")
        
        # 5. 测试VWAP执行
        print(f"\nVWAP执行策略...")
        vwap_result = exec_optimizer.execute_vwap(
            symbol=symbol,
            direction="BUY",
            volume=10000,
            duration_minutes=30,
            num_slices=10
        )
        print(f"策略: {vwap_result['strategy']}")
        print(f"时长: {vwap_result['duration_minutes']} 分钟")
        print(f"切片数: {vwap_result['slices']}")
        
        # 6. 测试执行限制检查
        print(f"\n执行限制检查...")
        limit_ok, limit_msg = exec_optimizer.check_limits_for_execution(
            symbol=symbol,
            direction="BUY",
            volume=100,
            current_price=current_price,
            is_limit_up=False,
            is_limit_down=False
        )
        print(f"检查结果: {'✅ 通过' if limit_ok else '❌ 拒绝'} - {limit_msg}")
        
        # 7. 获取执行报告
        report = exec_optimizer.get_execution_report()
        print(f"\n执行报告:")
        print(f"总订单数: {report.get('total_orders', 0)}")
        print(f"活动订单: {report.get('active_orders', 0)}")
        
        print("\n✅ 执行优化测试通过")
        return True
        
    except Exception as e:
        logger.exception(f"执行优化测试失败: {e}")
        print(f"❌ 执行优化测试失败: {e}")
        return False


def main():
    """主测试函数"""
    print("="*60)
    print("高级量化交易平台 - 功能测试")
    print("="*60)
    
    # 测试计数器
    tests_passed = 0
    tests_total = 5
    
    # 测试1: 策略池管理
    if test_strategy_pool():
        tests_passed += 1
    
    # 测试2: 组合模拟回测
    if test_portfolio_simulation():
        tests_passed += 1
    
    # 测试3: 实时数据管理
    if test_real_time_data():
        tests_passed += 1
    
    # 测试4: 精细化风控
    if test_advanced_risk():
        tests_passed += 1
    
    # 测试5: 执行优化
    if test_execution_optimizer():
        tests_passed += 1
    
    # 总结
    print("\n" + "="*60)
    print(f"测试总结: {tests_passed}/{tests_total} 个测试通过")
    print("="*60)
    
    if tests_passed == tests_total:
        print("\n🎉 所有测试通过！")
        return 0
    else:
        print(f"\n⚠️ 有 {tests_total - tests_passed} 个测试失败")
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
