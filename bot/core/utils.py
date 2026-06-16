"""工具函数 — 重试装饰器、类型安全转换、格式化"""
import time
import functools
import math
import numpy as np
from typing import Callable, TypeVar

from loguru import logger

T = TypeVar("T")


def retry(max_retries: int = 3, delay: float = 1.0, backoff: float = 2.0):
    """同步重试装饰器。

    在函数执行失败时按指数退避策略重试。
    适用于同步 akshare 等可能因网络问题失败的数据获取。
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    if attempt < max_retries - 1:
                        wait = delay * (backoff ** attempt)
                        logger.warning(
                            f"{func.__name__} attempt {attempt+1}/{max_retries} "
                            f"failed: {e}, retry in {wait:.1f}s"
                        )
                        time.sleep(wait)
            logger.error(f"{func.__name__} failed after {max_retries} attempts: {last_error}")
            raise last_error
        return wrapper
    return decorator


def async_retry(max_retries: int = 3, delay: float = 1.0, backoff: float = 2.0):
    """异步重试装饰器。

    用法与 retry 相同，但适用于 async/await 函数。
    """
    import asyncio

    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    if attempt < max_retries - 1:
                        wait = delay * (backoff ** attempt)
                        logger.warning(
                            f"{func.__name__} attempt {attempt+1}/{max_retries} "
                            f"failed: {e}, retry in {wait:.1f}s"
                        )
                        await asyncio.sleep(wait)
            logger.error(f"{func.__name__} failed after {max_retries} attempts: {last_error}")
            raise last_error
        return wrapper
    return decorator


def safe_float(val, default=0.0) -> float:
    """安全地将各种格式的值转换为浮点数。

    支持: 数字、百分数字符串、带千分位的字符串。
    不支持转换时返回 default。
    """
    if val is None or val == "" or val == "-":
        return default
    try:
        s = str(val).replace(",", "").replace("%", "").strip()
        if s.lower() == "nan" or s.lower() == "inf":
            return default
        result = float(s)
        if np.isnan(result) or np.isinf(result):
            return default
        return result
    except (ValueError, TypeError):
        return default


def safe_str(val, default="") -> str:
    """安全地将值转为字符串并去除首尾空白。"""
    import math as _m
    if val is None:
        return default
    if isinstance(val, float) and (_m.isnan(val) or _m.isinf(val)):
        return default
    return str(val).strip()


def safe_pct(val) -> float:
    """安全获取涨跌幅数值，NaN/Inf/None 返回 0.0。"""
    if val is None:
        return 0.0
    try:
        v = float(val)
        if math.isnan(v) or math.isinf(v):
            return 0.0
        return v
    except (ValueError, TypeError):
        return 0.0


def format_pct(val: float) -> str:
    """格式化涨跌幅显示，如 +3.14% / -2.50% / 0.00%。"""
    if val is None or (isinstance(val, float) and (math.isnan(val) or math.isinf(val))):
        return "0.00%"
    if val > 0:
        return f"+{val:.2f}%"
    elif val < 0:
        return f"{val:.2f}%"
    return "0.00%"


def format_volume(val: float) -> str:
    """格式化成交额，自动单位转换：亿/万/元。

    - >= 1e8 → 亿
    - >= 1e4 → 万
    - < 1e4 → 原始值
    """
    if val is None or (isinstance(val, float) and (math.isnan(val) or math.isinf(val))):
        return "0"
    if val >= 1e8:
        return f"{val/1e8:.0f}亿"
    elif val >= 1e4:
        return f"{val/1e4:.0f}万"
    return f"{val:.0f}"


# ═══════════════════════════════════════════════════════════
# 全局错误处理工具
# ═══════════════════════════════════════════════════════════


class ServiceError(Exception):
    """服务级错误基类。"""
    def __init__(self, message: str, code: str = "UNKNOWN", detail: str = ""):
        self.message = message
        self.code = code
        self.detail = detail
        super().__init__(self.message)


class DataSourceError(ServiceError):
    """数据源错误。"""
    def __init__(self, message: str, source: str = ""):
        super().__init__(message, code="DATA_SOURCE_ERROR", detail=source)


class LLMServiceError(ServiceError):
    """LLM 服务错误。"""
    def __init__(self, message: str, model: str = ""):
        super().__init__(message, code="LLM_SERVICE_ERROR", detail=model)


class DatabaseError(ServiceError):
    """数据库错误。"""
    def __init__(self, message: str, operation: str = ""):
        super().__init__(message, code="DATABASE_ERROR", detail=operation)


class TaskCancelled(Exception):
    """任务取消（非错误，用于优雅终止）。"""
    pass


def safe_execute(func, *args, fallback=None, error_msg: str = "", **kwargs):
    """安全执行函数，失败时返回 fallback 值。

    Args:
        func: 要执行的函数
        fallback: 失败时的返回值
        error_msg: 错误日志前缀
        *args, **kwargs: 传递给 func 的参数

    Returns:
        func 执行结果或 fallback
    """
    try:
        return func(*args, **kwargs)
    except TaskCancelled:
        raise  # 任务取消不应吞掉
    except Exception as e:
        if error_msg:
            logger.warning(f"{error_msg}: {e}")
        return fallback


async def async_safe_execute(func, *args, fallback=None, error_msg: str = "", **kwargs):
    """安全异步执行函数，失败时返回 fallback 值。"""
    try:
        return await func(*args, **kwargs)
    except TaskCancelled:
        raise
    except Exception as e:
        if error_msg:
            logger.warning(f"{error_msg}: {e}")
        return fallback
