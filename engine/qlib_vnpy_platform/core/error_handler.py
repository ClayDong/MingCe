"""
统一异常处理模块
提供全局异常处理器和日志记录
"""

import traceback
from typing import Optional, Callable, Any
from functools import wraps
from loguru import logger
from qlib_vnpy_platform.core.exceptions import TradingPlatformError


class ExceptionHandler:
    """全局异常处理器"""
    
    def __init__(self):
        self.error_count = {}
        self.last_error_time = {}
    
    def handle_exception(self, error: Exception, context: Optional[dict] = None) -> dict:
        """
        处理异常并返回标准化的错误响应
        
        Args:
            error: 异常对象
            context: 上下文信息
            
        Returns:
            标准化的错误字典
        """
        error_type = type(error).__name__
        self.error_count[error_type] = self.error_count.get(error_type, 0) + 1
        
        if isinstance(error, TradingPlatformError):
            response = error.to_dict()
            logger.error(f"[{error.code}] {error.message}", extra=error.details)
        else:
            response = {
                "error": error_type,
                "message": str(error),
                "code": "INTERNAL_ERROR",
                "details": {}
            }
            logger.exception(f"Unhandled exception: {error}")
        
        if context:
            response["context"] = context
            logger.debug(f"Context: {context}")
        
        return response
    
    def get_error_stats(self) -> dict:
        """获取错误统计信息"""
        return {
            "error_counts": self.error_count.copy(),
            "total_errors": sum(self.error_count.values())
        }
    
    def reset_stats(self):
        """重置统计信息"""
        self.error_count.clear()
        self.last_error_time.clear()


# 全局异常处理器实例
_global_handler = ExceptionHandler()


def handle_exception(error: Exception, context: Optional[dict] = None) -> dict:
    """全局异常处理入口"""
    return _global_handler.handle_exception(error, context)


def get_error_stats() -> dict:
    """获取全局错误统计"""
    return _global_handler.get_error_stats()


def reset_error_stats():
    """重置全局错误统计"""
    _global_handler.reset_stats()


def safe_execute(func: Optional[Callable] = None, default_return: Any = None,
                log_errors: bool = True, context: Optional[dict] = None):
    """
    安全执行装饰器
    捕获异常并返回默认值，而不是让异常传播
    
    Args:
        func: 要包装的函数（如果用作装饰器）
        default_return: 异常时返回的默认值
        log_errors: 是否记录错误
        context: 额外的上下文信息
        
    Usage:
        @safe_execute(default_return={})
        def get_data():
            ...
            
        @safe_execute(default_return=[], context={"module": "data"})
        def fetch_data():
            ...
    """
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            try:
                return f(*args, **kwargs)
            except Exception as e:
                if log_errors:
                    ctx = context or {}
                    ctx["function"] = f.__name__
                    handle_exception(e, ctx)
                return default_return
        return wrapper
    
    if func is None:
        return decorator
    else:
        return decorator(func)


def retry_on_error(max_retries: int = 3, delay: float = 1.0, 
                  exceptions: tuple = (Exception,)):
    """
    失败重试装饰器
    
    Args:
        max_retries: 最大重试次数
        delay: 重试间隔（秒）
        exceptions: 需要重试的异常类型元组
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        logger.warning(f"Attempt {attempt + 1} failed for {func.__name__}: {e}, retrying...")
                        import time
                        time.sleep(delay)
                    else:
                        logger.error(f"All {max_retries} attempts failed for {func.__name__}")
            
            if last_exception:
                raise last_exception
        return wrapper
    return decorator


class ErrorContext:
    """上下文管理器，用于包装可能出错的代码块"""
    
    def __init__(self, context_name: str, log_level: str = "error", 
                default_return: Any = None):
        self.context_name = context_name
        self.log_level = log_level
        self.default_return = default_return
        self.error = None
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self.error = exc_val
            logger.log(self.log_level.upper(), f"Error in {self.context_name}: {exc_val}")
            if exc_tb:
                logger.debug(f"Traceback: {''.join(traceback.format_tb(exc_tb))}")
            return True  # 抑制异常
        return False
    
    def get_error(self) -> Optional[Exception]:
        """获取发生的错误"""
        return self.error
    
    def has_error(self) -> bool:
        """是否有错误发生"""
        return self.error is not None
