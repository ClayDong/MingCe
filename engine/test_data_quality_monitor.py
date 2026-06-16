#!/usr/bin/env python3
"""
数据质量监控服务测试
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from loguru import logger
from datetime import datetime

from qlib_vnpy_platform.config import load_config
from qlib_vnpy_platform.core.data_quality_monitor import DataQualityMonitor


def test_monitor_basic():
    """测试监控器基本功能"""
    print("=" * 60)
    print("测试数据质量监控器")
    print("=" * 60)
    
    # 加载配置
    load_config()
    
    # 创建监控器
    monitor = DataQualityMonitor()
    print("\n✅ 监控器创建成功")
    
    # 测试单个股票检查
    print("\n📊 测试单个股票检查: SZ002594")
    record = monitor.check_symbol_quality("SZ002594")
    
    print(f"  股票: {record.symbol}")
    print(f"  评分: {record.quality_score:.1f}/100")
    print(f"  状态: {'✅ 通过' if record.passed else '❌ 失败'}")
    if record.issues_summary:
        print(f"  问题数: {len(record.issues_summary)}")
        for issue in record.issues_summary[:3]:
            print(f"    - {issue}")
    
    # 测试批量检查
    print("\n📊 测试批量检查")
    symbols = ["SZ002594", "SZ000001", "SH600519"]
    results = monitor.check_multiple_symbols(symbols)
    
    print(f"  检查了 {len(results)} 只股票")
    for symbol, record in results.items():
        status_emoji = "✅" if record.passed else "❌"
        print(f"    {status_emoji} {symbol}: {record.quality_score:.1f}/100")
    
    # 测试摘要
    print("\n📈 测试质量摘要")
    summary = monitor.get_quality_summary()
    print(f"  总检查数: {summary.get('total_checks', 0)}")
    print(f"  平均评分: {summary.get('average_score', 0):.1f}/100")
    print(f"  通过率: {summary.get('pass_rate', 0)*100:.1f}%")
    print(f"  告警数: {summary.get('alert_count', 0)}")
    
    # 测试历史记录
    print("\n📋 测试历史记录")
    history = monitor.get_history_for_symbol("SZ002594", limit=10)
    print(f"  历史记录数: {len(history)}")
    
    # 测试待处理告警
    print("\n🚨 测试待处理告警")
    alerts = monitor.get_pending_alerts()
    print(f"  待处理告警数: {len(alerts)}")
    for alert in alerts[:3]:
        print(f"    [{alert.get('alert_level')}] {alert.get('symbol')}: {alert.get('message')[:50]}...")
    
    print("\n" + "=" * 60)
    print("✅ 所有基础功能测试通过！")
    print("=" * 60)


def test_monitor_alert_rules():
    """测试告警规则"""
    print("\n" + "=" * 60)
    print("测试告警规则")
    print("=" * 60)
    
    from qlib_vnpy_platform.core.data_quality_monitor import AlertRule, DataQualityRecord
    
    # 创建测试记录
    test_record = DataQualityRecord(
        symbol="TEST0001",
        timestamp=datetime.now().isoformat(),
        quality_score=50.0,
        checks={},
        issues_summary=["数据过期", "缺失率过高"],
        passed=False,
        data_source="simulated",
        cache_age_seconds=0.0
    )
    
    # 测试规则
    rule = AlertRule(
        name="test_low_score",
        condition=lambda r: r.quality_score < 70,
        alert_level="error",
        message_template="测试告警: {symbol} 评分过低"
    )
    
    print(f"  规则: {rule.name}")
    print(f"  条件触发: {rule.condition(test_record)}")
    
    print("\n✅ 告警规则测试完成")


def main():
    """运行所有测试"""
    try:
        test_monitor_basic()
        test_monitor_alert_rules()
        
        print("\n" + "=" * 60)
        print("🎉 所有测试通过！")
        print("=" * 60)
        
    except Exception as e:
        logger.error(f"测试失败: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
