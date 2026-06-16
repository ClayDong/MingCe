#!/usr/bin/env python3
"""测试交易记录持久化功能"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime
from qlib_vnpy_platform.config import load_config
from qlib_vnpy_platform.core.main_engine import TradingEngine
from loguru import logger


def test_persistence():
    logger.info("=" * 60)
    logger.info("开始测试交易记录持久化功能")
    logger.info("=" * 60)

    load_config()
    engine = TradingEngine()
    
    logger.info(f"初始现金: {engine._cash}")
    logger.info(f"初始持仓: {engine._positions}")
    
    test_order = {
        "symbol": "SZ002594",
        "direction": "BUY",
        "volume": 100,
        "price": 250.0
    }
    
    logger.info(f"执行测试订单: {test_order}")
    result = engine.execute_order(test_order)
    logger.info(f"执行结果: {result}")
    
    if result.get("status") == "FILLED":
        logger.info("✓ 交易执行成功")
        logger.info(f"当前现金: {engine._cash}")
        logger.info(f"当前持仓: {engine._positions}")
        logger.info(f"交易记录数: {len(engine._trades)}")
    
    logger.info("=" * 60)
    logger.info("重新初始化引擎，检查数据是否正确加载")
    logger.info("=" * 60)
    
    del engine
    engine2 = TradingEngine()
    logger.info(f"重新加载后现金: {engine2._cash}")
    logger.info(f"重新加载后持仓: {engine2._positions}")
    logger.info(f"重新加载后交易记录数: {len(engine2._trades)}")
    
    logger.info("=" * 60)
    logger.info("测试完成")
    logger.info("=" * 60)
    
    return True


if __name__ == "__main__":
    test_persistence()
