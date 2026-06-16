#!/usr/bin/env python3
"""信号路由模块测试"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from qlib_vnpy_platform.config import load_config
from qlib_vnpy_platform.core.signal_router import SignalRouter
from loguru import logger


def test_fuse_signals():
    logger.info("=" * 60)
    logger.info("测试信号融合功能")
    logger.info("=" * 60)
    
    load_config()
    router = SignalRouter()
    
    test_cases = [
        {
            "name": "强买入信号",
            "qlib_pred": 0.8,
            "llm_result": {
                "signal": "BUY",
                "confidence": 0.9,
                "reason": "技术面和基本面都很好"
            },
            "expected_direction": "BUY"
        },
        {
            "name": "强卖出信号",
            "qlib_pred": 0.2,
            "llm_result": {
                "signal": "SELL",
                "confidence": 0.9,
                "reason": "技术面和基本面都很差"
            },
            "expected_direction": "SELL"
        },
        {
            "name": "中性信号",
            "qlib_pred": 0.5,
            "llm_result": {
                "signal": "HOLD",
                "confidence": 0.5,
                "reason": "观望"
            },
            "expected_direction": "HOLD"
        }
    ]
    
    all_passed = True
    for test_case in test_cases:
        logger.info(f"\n测试用例: {test_case['name']}")
        result = router.fuse_signals(
            symbol="SZ002594",
            qlib_pred=test_case["qlib_pred"],
            llm_result=test_case["llm_result"],
            current_price=250.0
        )
        logger.info(f"结果: {result['direction']}, 得分: {result['score']:.4f}, 置信度: {result['confidence']:.4f}")
        
        if result["direction"] == test_case["expected_direction"]:
            logger.info(f"✓ {test_case['name']} 通过")
        else:
            logger.error(f"✗ {test_case['name']} 失败: 期望 {test_case['expected_direction']}, 实际 {result['direction']}")
            all_passed = False
    
    logger.info(f"\n{'所有测试通过' if all_passed else '有测试失败'}")
    return all_passed


def test_signal_to_order():
    logger.info("\n" + "=" * 60)
    logger.info("测试信号转订单功能")
    logger.info("=" * 60)
    
    load_config()
    router = SignalRouter()
    
    account = {
        "total_capital": 1000000.0,
        "cash": 500000.0,
        "position_value": 500000.0
    }
    
    signal = {
        "symbol": "SZ002594",
        "direction": "BUY",
        "score": 0.8,
        "confidence": 0.9,
        "current_price": 250.0
    }
    
    order = router.signal_to_order(signal, account)
    logger.info(f"信号转订单结果: {order}")
    
    assert order["symbol"] == "SZ002594"
    assert order["direction"] == "BUY"
    assert order["volume"] > 0
    assert order["price"] == 250.0
    
    logger.info("✓ 信号转订单测试通过")
    return True


if __name__ == "__main__":
    success1 = test_fuse_signals()
    success2 = test_signal_to_order()
    
    if success1 and success2:
        print("\n=== 所有 SignalRouter 测试通过 ===")
        sys.exit(0)
    else:
        print("\n=== 部分 SignalRouter 测试失败 ===")
        sys.exit(1)
