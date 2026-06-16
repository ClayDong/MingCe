#!/usr/bin/env python3
"""
测试新增功能：飞书通知、系统监控
"""

import sys
from pathlib import Path
from loguru import logger

sys.path.insert(0, str(Path(__file__).parent))

from qlib_vnpy_platform.config import load_config
from qlib_vnpy_platform.core.feishu_notifier import get_notifier
from qlib_vnpy_platform.core.system_monitor import get_system_monitor
from qlib_vnpy_platform.core.data_quality_monitor import get_monitor_instance


def test_feishu_notifier():
    """测试飞书通知功能"""
    logger.info("=" * 60)
    logger.info("测试飞书通知功能")
    logger.info("=" * 60)
    
    try:
        notifier = get_notifier()
        
        # 发送测试消息
        test_message = (
            f"🔔 **系统测试消息**\n"
            f"🕐 {load_config()['llm']['model'] if 'llm' in load_config() else 'Test'}\n"
            f"\n"
            f"这是一条来自 MakingMoney 量化平台的测试消息。\n"
            f"飞书通知模块已正常工作。"
        )
        
        success = notifier.send_markdown(test_message)
        logger.info(f"✅ 飞书通知测试 {'成功' if success else '失败'}")
        return success
        
    except Exception as e:
        logger.error(f"❌ 测试失败: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def test_system_monitor():
    """测试系统监控功能"""
    logger.info("=" * 60)
    logger.info("测试系统监控功能")
    logger.info("=" * 60)
    
    try:
        monitor = get_system_monitor()
        
        # 检查系统健康
        health = monitor.check_system_health()
        logger.info(f"系统健康状态: {health}")
        
        # 打印摘要
        summary = monitor.get_status_summary()
        logger.info(f"\n{summary}")
        
        logger.info("✅ 系统监控测试成功")
        return True
        
    except Exception as e:
        logger.error(f"❌ 测试失败: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def test_data_quality_monitor():
    """测试数据质量监控功能"""
    logger.info("=" * 60)
    logger.info("测试数据质量监控功能")
    logger.info("=" * 60)
    
    try:
        monitor = get_monitor_instance()
        
        # 检查单个股票的数据质量
        logger.info("检查 SZ002594 的数据质量...")
        record = monitor.check_symbol_quality("SZ002594")
        logger.info(f"质量分数: {record.quality_score}/100")
        logger.info(f"通过: {record.passed}")
        if record.issues_summary:
            logger.warning(f"问题: {record.issues_summary}")
        
        # 获取质量摘要
        summary = monitor.get_quality_summary()
        logger.info(f"质量摘要: {summary}")
        
        logger.info("✅ 数据质量监控测试成功")
        return True
        
    except Exception as e:
        logger.error(f"❌ 测试失败: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def main():
    """主测试函数"""
    logger.info("开始测试新增功能...")
    
    results = {}
    
    # 测试飞书通知
    results["feishu_notifier"] = test_feishu_notifier()
    
    # 测试系统监控
    results["system_monitor"] = test_system_monitor()
    
    # 测试数据质量监控
    results["data_quality_monitor"] = test_data_quality_monitor()
    
    logger.info("\n" + "=" * 60)
    logger.info("测试结果汇总:")
    for name, success in results.items():
        status = "✅ 通过" if success else "❌ 失败"
        logger.info(f"  {name}: {status}")
    logger.info("=" * 60)
    
    all_success = all(results.values())
    if all_success:
        logger.info("🎉 所有测试通过！")
    else:
        logger.warning("部分测试失败")
    
    return 0 if all_success else 1


if __name__ == "__main__":
    sys.exit(main())
