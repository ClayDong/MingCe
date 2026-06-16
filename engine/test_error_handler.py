import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "qlib_vnpy_platform"))

from qlib_vnpy_platform.core.exceptions import (
    TradingPlatformError, DataError, DataSourceError, TradingError,
    RiskControlError, LLMAError, ConfigError, ValidationError
)
from qlib_vnpy_platform.core.error_handler import (
    safe_execute, retry_on_error, ErrorContext, 
    handle_exception, get_error_stats, reset_error_stats
)


def test_exception_hierarchy():
    """测试异常类层次结构"""
    print("=" * 60)
    print("测试异常类层次结构")
    print("=" * 60)
    
    # 测试 TradingPlatformError
    try:
        raise TradingPlatformError("基础异常", code="BASE_ERROR")
    except TradingPlatformError as e:
        print(f"✓ TradingPlatformError: {e.message}, code={e.code}")
        assert e.code == "BASE_ERROR"
    
    # 测试 DataSourceError
    try:
        raise DataSourceError("获取数据失败", source="akshare", symbol="SZ000001")
    except TradingPlatformError as e:
        print(f"✓ DataSourceError: {e.message}")
        assert isinstance(e, DataError)
        assert isinstance(e, TradingPlatformError)
    
    # 测试 RiskControlError
    try:
        raise RiskControlError("风控拦截", reason="亏损超限", symbol="SZ000001")
    except TradingPlatformError as e:
        print(f"✓ RiskControlError: {e.message}")
        assert isinstance(e, TradingError)
    
    # 测试 LLMAError
    try:
        raise LLMAError("LLM API调用失败", symbol="SZ000001", api_error="timeout")
    except TradingPlatformError as e:
        print(f"✓ LLMAError: {e.message}")
        assert e.code == "LLM_ERROR"
    
    print("\n✓ 所有异常类测试通过")


def test_safe_execute():
    """测试安全执行装饰器"""
    print("\n" + "=" * 60)
    print("测试 safe_execute 装饰器")
    print("=" * 60)
    
    reset_error_stats()
    
    @safe_execute(default_return="fallback", log_errors=True)
    def might_fail():
        raise ValueError("测试错误")
    
    result = might_fail()
    assert result == "fallback"
    print("✓ 安全执行装饰器正常工作")
    
    stats = get_error_stats()
    assert stats["error_counts"]["ValueError"] == 1
    print(f"✓ 错误统计正确: {stats}")


def test_error_context():
    """测试错误上下文管理器"""
    print("\n" + "=" * 60)
    print("测试 ErrorContext")
    print("=" * 60)
    
    with ErrorContext("test_operation") as ctx:
        print("执行正常操作")
    
    assert not ctx.has_error()
    print("✓ 无错误时正常")
    
    with ErrorContext("test_error", log_level="warning") as ctx:
        raise RuntimeError("测试错误")
    
    assert ctx.has_error()
    assert isinstance(ctx.get_error(), RuntimeError)
    print("✓ 有错误时正确捕获")


def test_handle_exception():
    """测试全局异常处理"""
    print("\n" + "=" * 60)
    print("测试全局异常处理")
    print("=" * 60)
    
    reset_error_stats()
    
    # 测试 TradingPlatformError
    error = TradingPlatformError("测试错误", code="TEST_CODE", details={"key": "value"})
    result = handle_exception(error, context={"module": "test"})
    
    assert result["error"] == "TradingPlatformError"
    assert result["code"] == "TEST_CODE"
    assert result["context"]["module"] == "test"
    print(f"✓ TradingPlatformError 处理: {result}")
    
    # 测试普通 Exception
    error2 = ValueError("普通错误")
    result2 = handle_exception(error2, context={"func": "test"})
    
    assert result2["code"] == "INTERNAL_ERROR"
    assert result2["context"]["func"] == "test"
    print(f"✓ 普通 Exception 处理: {result2}")


if __name__ == "__main__":
    test_exception_hierarchy()
    test_safe_execute()
    test_error_context()
    test_handle_exception()
    
    print("\n" + "=" * 60)
    print("✅ 所有异常处理测试通过！")
    print("=" * 60)
