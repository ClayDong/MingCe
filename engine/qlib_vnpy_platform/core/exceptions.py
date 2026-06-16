"""
统一异常处理模块
提供项目专用的异常类，便于错误分类和处理
"""

from typing import Optional, Dict, Any


class TradingPlatformError(Exception):
    """交易平台基础异常类"""
    
    def __init__(self, message: str, code: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.code = code or "UNKNOWN_ERROR"
        self.details = details or {}
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "error": self.__class__.__name__,
            "message": self.message,
            "code": self.code,
            "details": self.details
        }


class DataError(TradingPlatformError):
    """数据相关错误"""
    
    def __init__(self, message: str, symbol: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, code="DATA_ERROR", details=details)
        self.symbol = symbol


class DataSourceError(DataError):
    """数据源错误（获取失败、超时等）"""
    
    def __init__(self, message: str, source: str, symbol: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, symbol=symbol, details=details)
        self.source = source
        self.code = "DATA_SOURCE_ERROR"
        self.details = {"source": source, **(details or {})}


class DataParseError(DataError):
    """数据解析错误"""
    
    def __init__(self, message: str, symbol: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, symbol=symbol, details=details)
        self.code = "DATA_PARSE_ERROR"


class ConfigError(TradingPlatformError):
    """配置相关错误"""
    
    def __init__(self, message: str, config_key: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, code="CONFIG_ERROR", details=details)
        self.config_key = config_key
        if config_key:
            self.details = {"config_key": config_key, **(details or {})}


class TradingError(TradingPlatformError):
    """交易执行错误"""
    
    def __init__(self, message: str, symbol: Optional[str] = None, order_id: Optional[str] = None, 
                 details: Optional[Dict[str, Any]] = None):
        super().__init__(message, code="TRADING_ERROR", details=details)
        self.symbol = symbol
        self.order_id = order_id
        if symbol or order_id:
            self.details = {
                "symbol": symbol,
                "order_id": order_id,
                **(details or {})
            }


class RiskControlError(TradingError):
    """风控拦截错误"""
    
    def __init__(self, message: str, symbol: Optional[str] = None, reason: Optional[str] = None,
                 details: Optional[Dict[str, Any]] = None):
        super().__init__(message, symbol=symbol, details=details)
        self.code = "RISK_CONTROL_ERROR"
        self.reason = reason
        self.details = {
            "reason": reason,
            **(details or {})
        }


class InsufficientFundsError(TradingError):
    """资金不足错误"""
    
    def __init__(self, message: str, required: float, available: float, symbol: Optional[str] = None,
                 details: Optional[Dict[str, Any]] = None):
        super().__init__(message, symbol=symbol, details=details)
        self.code = "INSUFFICIENT_FUNDS"
        self.required = required
        self.available = available
        self.details = {
            "required": required,
            "available": available,
            **(details or {})
        }


class PositionLimitError(TradingError):
    """持仓限制错误"""
    
    def __init__(self, message: str, symbol: str, limit_type: str, 
                 current: float, limit: float, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, symbol=symbol, details=details)
        self.code = "POSITION_LIMIT_ERROR"
        self.limit_type = limit_type
        self.current = current
        self.limit = limit
        self.details = {
            "limit_type": limit_type,
            "current": current,
            "limit": limit,
            **(details or {})
        }


class LLMAError(TradingPlatformError):
    """LLM 分析错误"""
    
    def __init__(self, message: str, symbol: Optional[str] = None, 
                 api_error: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, code="LLM_ERROR", details=details)
        self.symbol = symbol
        self.api_error = api_error
        self.details = {
            "symbol": symbol,
            "api_error": api_error,
            **(details or {})
        }


class ValidationError(TradingPlatformError):
    """数据验证错误"""
    
    def __init__(self, message: str, field: Optional[str] = None, 
                 value: Optional[Any] = None, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, code="VALIDATION_ERROR", details=details)
        self.field = field
        self.value = value
        if field or value:
            self.details = {
                "field": field,
                "value": str(value),
                **(details or {})
            }


class PersistenceError(TradingPlatformError):
    """持久化错误"""
    
    def __init__(self, message: str, file_path: Optional[str] = None,
                 operation: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, code="PERSISTENCE_ERROR", details=details)
        self.file_path = file_path
        self.operation = operation
        self.details = {
            "file_path": file_path,
            "operation": operation,
            **(details or {})
        }


class SchedulerError(TradingPlatformError):
    """调度器错误"""
    
    def __init__(self, message: str, task_name: Optional[str] = None,
                 details: Optional[Dict[str, Any]] = None):
        super().__init__(message, code="SCHEDULER_ERROR", details=details)
        self.task_name = task_name
        if task_name:
            self.details = {"task_name": task_name, **(details or {})}
