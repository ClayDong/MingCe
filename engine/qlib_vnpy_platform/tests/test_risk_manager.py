#!/usr/bin/env python3
"""风险管理模块测试"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from qlib_vnpy_platform.config import load_config
from qlib_vnpy_platform.core.risk_manager import RiskManager
from loguru import logger


def test_single_position_limit():
    logger.info("=" * 60)
    logger.info("测试单股持仓限制")
    logger.info("=" * 60)
    
    load_config()
    rm = RiskManager()
    
    account = {
        "total_capital": 1000000.0,
        "cash": 500000.0
    }
    portfolio = {
        "positions": {}
    }
    
    order = {
        "symbol": "SZ002594",
        "direction": "BUY",
        "volume": 2000,
        "price": 250.0,
        "confidence": 0.9
    }
    
    result = rm.check_order(order, account, portfolio)
    logger.info(f"检查结果: {result}")
    
    assert result["approved"] is False or result.get("adjusted_volume") < 2000
    logger.info("✓ 单股持仓限制测试通过")
    return True


def test_daily_loss_circuit_breaker():
    logger.info("\n" + "=" * 60)
    logger.info("测试日亏损熔断")
    logger.info("=" * 60)
    
    load_config()
    rm = RiskManager()
    
    from datetime import datetime
    today = datetime.now().date()
    
    rm._last_reset_date = today  # 告诉它今天已经重置过了
    rm._circuit_breaker_active = True
    account = {
        "total_capital": 900000.0,
        "cash": 500000.0
    }
    portfolio = {
        "positions": {}
    }
    
    order = {
        "symbol": "SZ002594",
        "direction": "BUY",
        "volume": 100,
        "price": 250.0,
        "confidence": 0.9
    }
    
    result = rm.check_order(order, account, portfolio)
    logger.info(f"检查结果: {result}")
    
    assert result["approved"] is False
    assert "熔断" in result["reason"]
    logger.info("✓ 日亏损熔断测试通过")
    
    rm._circuit_breaker_active = False
    return True


def test_low_confidence_rejection():
    logger.info("\n" + "=" * 60)
    logger.info("测试低置信度拒绝")
    logger.info("=" * 60)
    
    load_config()
    rm = RiskManager()
    
    account = {
        "total_capital": 1000000.0,
        "cash": 500000.0
    }
    portfolio = {
        "positions": {}
    }
    
    order = {
        "symbol": "SZ002594",
        "direction": "BUY",
        "volume": 100,
        "price": 250.0,
        "confidence": 0.3
    }
    
    result = rm.check_order(order, account, portfolio)
    logger.info(f"检查结果: {result}")
    
    assert result["approved"] is False
    assert "置信度" in result["reason"]
    logger.info("✓ 低置信度拒绝测试通过")
    return True


def test_sell_restriction_t1():
    logger.info("\n" + "=" * 60)
    logger.info("测试T+1卖出限制")
    logger.info("=" * 60)
    
    load_config()
    rm = RiskManager()
    
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")
    
    portfolio = {
        "positions": {
            "SZ002594": {
                "volume": 100,
                "avg_cost": 250.0,
                "buy_date": today
            }
        }
    }
    
    result = rm.check_sell_restriction("SZ002594", "SELL", portfolio)
    logger.info(f"检查结果: {result}")
    
    assert result["approved"] is False
    assert "T+1" in result["reason"]
    logger.info("✓ T+1卖出限制测试通过")
    return True


def test_get_risk_status():
    logger.info("\n" + "=" * 60)
    logger.info("测试风险状态获取")
    logger.info("=" * 60)
    
    load_config()
    rm = RiskManager()
    
    account = {
        "total_capital": 1000000.0,
        "cash": 500000.0
    }
    
    status = rm.get_risk_status(account)
    logger.info(f"风险状态: {status}")
    
    assert "circuit_breaker_active" in status
    assert "daily_pnl" in status
    assert "risk_level" in status
    logger.info("✓ 风险状态获取测试通过")
    return True


if __name__ == "__main__":
    success1 = test_single_position_limit()
    success2 = test_daily_loss_circuit_breaker()
    success3 = test_low_confidence_rejection()
    success4 = test_sell_restriction_t1()
    success5 = test_get_risk_status()
    
    if success1 and success2 and success3 and success4 and success5:
        print("\n=== 所有 RiskManager 测试通过 ===")
        sys.exit(0)
    else:
        print("\n=== 部分 RiskManager 测试失败 ===")
        sys.exit(1)
