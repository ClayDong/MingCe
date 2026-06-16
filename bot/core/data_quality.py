"""数据质量保障模块

提供完整的数据质量验证、监控、告警和审计功能。
"""
import time
import hashlib
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, field
from enum import Enum
import numpy as np

from loguru import logger
from config.settings import get_settings

settings = get_settings()


class DataQualityLevel(Enum):
    """数据质量等级"""
    EXCELLENT = "excellent"
    GOOD = "good"
    ACCEPTABLE = "acceptable"
    WARNING = "warning"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class DataSourceHealth(Enum):
    """数据源健康状态"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass
class DataQualityMetrics:
    """数据质量指标"""
    completeness: float = 1.0  # 完整性 0-1
    accuracy: float = 1.0  # 准确性 0-1
    consistency: float = 1.0  # 一致性 0-1
    timeliness: float = 1.0  # 时效性 0-1
    validity: float = 1.0  # 有效性 0-1
    
    @property
    def overall_score(self) -> float:
        """综合评分"""
        weights = [0.25, 0.25, 0.2, 0.15, 0.15]
        scores = [self.completeness, self.accuracy, self.consistency, 
                  self.timeliness, self.validity]
        return sum(w * s for w, s in zip(weights, scores))
    
    @property
    def level(self) -> DataQualityLevel:
        """数据质量等级"""
        score = self.overall_score
        if score >= 0.95:
            return DataQualityLevel.EXCELLENT
        elif score >= 0.85:
            return DataQualityLevel.GOOD
        elif score >= 0.7:
            return DataQualityLevel.ACCEPTABLE
        elif score >= 0.5:
            return DataQualityLevel.WARNING
        elif score > 0:
            return DataQualityLevel.CRITICAL
        return DataQualityLevel.UNKNOWN


@dataclass
class DataQualityReport:
    """数据质量报告"""
    module_name: str
    timestamp: float = field(default_factory=time.time)
    metrics: DataQualityMetrics = field(default_factory=DataQualityMetrics)
    issues: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    source_health: Dict[str, DataSourceHealth] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "module_name": self.module_name,
            "timestamp": self.timestamp,
            "datetime": datetime.fromtimestamp(self.timestamp).isoformat(),
            "metrics": {
                "completeness": self.metrics.completeness,
                "accuracy": self.metrics.accuracy,
                "consistency": self.metrics.consistency,
                "timeliness": self.metrics.timeliness,
                "validity": self.metrics.validity,
                "overall_score": self.metrics.overall_score,
                "level": self.metrics.level.value
            },
            "issues": self.issues,
            "recommendations": self.recommendations,
            "source_health": {k: v.value for k, v in self.source_health.items()}
        }


class DataQualityValidator:
    """数据质量验证器"""
    
    # 指数历史正常值范围（基于经验）
    INDEX_NORMAL_RANGES = {
        "上证指数": (2500, 5000),
        "深证成指": (8000, 18000),
        "创业板指": (1500, 4500),
        "科创50": (800, 2500),
        "北证50": (800, 2000),
        "北证指数": (800, 2000)
    }
    
    # 涨跌幅合理范围（±20%）
    CHANGE_PCT_NORMAL_RANGE = (-20, 20)
    
    def __init__(self):
        self.history_cache: Dict[str, List[Tuple[float, float]]] = {}
        self.max_history_size = 30
    
    def validate_index_value(
        self, 
        value: float, 
        name: str, 
        check_range: bool = True
    ) -> Tuple[bool, List[str]]:
        """验证指数值
        
        Args:
            value: 指数值
            name: 指数名称
            check_range: 是否检查历史范围
            
        Returns:
            (是否可用, 问题列表) - 只有严重问题才返回不可用，警告问题返回可用但带警告
        """
        issues = []
        is_usable = True
        
        if value is None:
            issues.append(f"{name}: 指数值为空")
            return False, issues
        
        if not isinstance(value, (int, float)):
            issues.append(f"{name}: 指数值类型无效 ({type(value).__name__})")
            return False, issues

        if isinstance(value, float) and (np.isnan(value) or np.isinf(value)):
            issues.append(f"{name}: 指数值无效 ({value})")
            return False, issues
        
        if value <= 0:
            issues.append(f"{name}: 指数值异常（<=0）")
            return False, issues
        
        if value < settings.MIN_INDEX_VALUE_THRESHOLD:
            issues.append(f"{name}: 指数值低于最小阈值 {settings.MIN_INDEX_VALUE_THRESHOLD}")
            return False, issues
        
        if check_range and name in self.INDEX_NORMAL_RANGES:
            min_val, max_val = self.INDEX_NORMAL_RANGES[name]
            if value < min_val or value > max_val:
                issues.append(f"{name}: 指数值超出历史范围 [{min_val}, {max_val}]")
                # 超出历史范围只是警告，数据仍然可用
        
        return is_usable, issues
    
    def validate_change_pct(self, change_pct: float, name: str = "") -> Tuple[bool, List[str]]:
        """验证涨跌幅
        
        Args:
            change_pct: 涨跌幅
            name: 名称
            
        Returns:
            (是否可用, 问题列表) - 只有严重问题才返回不可用，警告问题返回可用但带警告
        """
        issues = []
        is_usable = True
        
        if change_pct is None:
            return is_usable, issues
        
        if isinstance(change_pct, float) and (np.isnan(change_pct) or np.isinf(change_pct)):
            issues.append(f"{name}: 涨跌幅无效 ({change_pct})")
            return False, issues
        
        min_chg, max_chg = self.CHANGE_PCT_NORMAL_RANGE
        if change_pct < min_chg or change_pct > max_chg:
            issues.append(f"{name}: 涨跌幅异常 [{change_pct:.2f}%]，正常范围 [{min_chg}%, {max_chg}%]")
            # 异常涨跌幅只是警告，数据仍然可用
        
        return is_usable, issues
    
    def validate_volume(self, volume: float, name: str = "") -> Tuple[bool, List[str]]:
        """验证成交额
        
        Args:
            volume: 成交额（亿元）
            name: 名称
            
        Returns:
            (是否有效, 问题列表)
        """
        issues = []
        
        if volume is None:
            return True, issues
        
        if isinstance(volume, float) and (np.isnan(volume) or np.isinf(volume)):
            issues.append(f"{name}: 成交额无效 ({volume})")
            return False, issues
        
        if volume < 0:
            issues.append(f"{name}: 成交额异常（<0）")
            return False, issues
        
        return len(issues) == 0, issues
    
    def validate_north_flow(self, net_flow: Optional[float], 
                           sh_flow: Optional[float] = None,
                           sz_flow: Optional[float] = None) -> Tuple[bool, List[str]]:
        """验证北向资金
        
        Args:
            net_flow: 净流（亿）
            sh_flow: 沪股通（亿）
            sz_flow: 深股通（亿）
            
        Returns:
            (是否可用, 问题列表) - 只有严重问题才返回不可用，警告问题返回可用但带警告
        """
        issues = []
        is_usable = True
        
        if net_flow is not None:
            if isinstance(net_flow, float) and (np.isnan(net_flow) or np.isinf(net_flow)):
                issues.append(f"北向资金净流无效 ({net_flow})")
                is_usable = False
            
            if abs(net_flow) > 300:
                issues.append(f"北向资金净流异常大 ({net_flow:.1f}亿)")
                # 异常大只是警告
        
        if sh_flow is not None and sz_flow is not None:
            if not np.isnan(sh_flow) and not np.isnan(sz_flow) and net_flow is not None and not np.isnan(net_flow):
                if abs(net_flow - (sh_flow + sz_flow)) > 0.1:
                    issues.append("北向资金数据不一致（净流 != 沪股通 + 深股通）")
                    # 不一致只是警告
        
        return is_usable, issues
    
    def check_data_completeness(self, data: Dict[str, Any], 
                                required_fields: List[str]) -> Tuple[float, List[str]]:
        """检查数据完整性
        
        Args:
            data: 数据字典
            required_fields: 必填字段列表
            
        Returns:
            (完整性评分 0-1, 缺失字段列表)
        """
        missing = []
        for field in required_fields:
            if field not in data:
                missing.append(field)
            else:
                val = data[field]
                if val is None or (isinstance(val, float) and np.isnan(val)):
                    missing.append(field)
        
        completeness = 1.0 - (len(missing) / len(required_fields)) if required_fields else 1.0
        return max(0, completeness), missing
    
    def validate_historical_consistency(
        self, 
        name: str, 
        value: float, 
        change_pct: float
    ) -> Tuple[bool, List[str]]:
        """验证历史一致性
        
        与历史数据对比，检测异常波动
        
        Args:
            name: 名称
            value: 当前值
            change_pct: 涨跌幅
            
        Returns:
            (是否可用, 问题列表) - 异常只是警告，数据仍然可用
        """
        issues = []
        is_usable = True
        
        if name not in self.history_cache:
            self.history_cache[name] = []
        
        history = self.history_cache[name]
        
        if len(history) >= 5:
            values = [v for v, _ in history]
            mean_val = np.mean(values)
            std_val = np.std(values)
            
            if std_val > 0:
                z_score = abs(value - mean_val) / std_val
                if z_score > 3:
                    issues.append(f"{name}: 指数值异常偏离历史均值 {z_score:.1f}个标准差")
            
            changes = [c for _, c in history]
            if changes:
                avg_chg = np.mean(changes)
                if abs(change_pct - avg_chg) > 5:
                    issues.append(f"{name}: 涨跌幅异常偏离历史平均")
        
        history.append((value, change_pct))
        if len(history) > self.max_history_size:
            history.pop(0)
        
        return is_usable, issues


class DataSourceMonitor:
    """数据源监控器"""
    
    def __init__(self):
        self.source_stats: Dict[str, Dict[str, Any]] = {}
        self.failure_threshold = 3
    
    def record_success(self, source_name: str):
        """记录成功"""
        if source_name not in self.source_stats:
            self._init_source(source_name)
        
        stats = self.source_stats[source_name]
        stats["success_count"] += 1
        stats["consecutive_failures"] = 0
        stats["last_success"] = time.time()
        logger.debug(f"DataSource {source_name}: success recorded")
    
    def record_failure(self, source_name: str, error: str = ""):
        """记录失败"""
        if source_name not in self.source_stats:
            self._init_source(source_name)
        
        stats = self.source_stats[source_name]
        stats["failure_count"] += 1
        stats["consecutive_failures"] += 1
        stats["last_failure"] = time.time()
        stats["last_error"] = error
        logger.warning(f"DataSource {source_name}: failure recorded ({error})")
    
    def _init_source(self, source_name: str):
        self.source_stats[source_name] = {
            "success_count": 0,
            "failure_count": 0,
            "consecutive_failures": 0,
            "last_success": None,
            "last_failure": None,
            "last_error": None
        }
    
    def get_health(self, source_name: str) -> DataSourceHealth:
        """获取数据源健康状态"""
        if source_name not in self.source_stats:
            return DataSourceHealth.UNKNOWN
        
        stats = self.source_stats[source_name]
        
        if stats["consecutive_failures"] >= self.failure_threshold:
            return DataSourceHealth.FAILED
        
        if stats["failure_count"] > stats["success_count"] * 0.3:
            return DataSourceHealth.DEGRADED
        
        return DataSourceHealth.HEALTHY
    
    def should_skip(self, source_name: str) -> bool:
        """是否应该跳过该数据源（熔断器模式）"""
        health = self.get_health(source_name)
        return health == DataSourceHealth.FAILED
    
    def reset(self, source_name: Optional[str] = None):
        """重置统计"""
        if source_name:
            if source_name in self.source_stats:
                self._init_source(source_name)
        else:
            self.source_stats.clear()


# 全局单例
_validator = DataQualityValidator()
_monitor = DataSourceMonitor()


def get_validator() -> DataQualityValidator:
    """获取数据质量验证器"""
    return _validator


def get_monitor() -> DataSourceMonitor:
    """获取数据源监控器"""
    return _monitor


def generate_quality_report(module_name: str, 
                           data: Dict[str, Any],
                           issues: List[str]) -> DataQualityReport:
    """生成数据质量报告
    
    Args:
        module_name: 模块名称
        data: 数据
        issues: 已知问题列表
        
    Returns:
        数据质量报告
    """
    report = DataQualityReport(
        module_name=module_name,
        issues=issues.copy()
    )
    
    # 评估完整性
    completeness = 1.0
    if issues:
        completeness = max(0, 1.0 - len(issues) * 0.1)
    report.metrics.completeness = completeness
    
    # 评估准确性
    accuracy = 1.0
    if any("异常" in i or "无效" in i for i in issues):
        accuracy = 0.7
    report.metrics.accuracy = accuracy
    
    # 评估一致性
    report.metrics.consistency = 1.0
    
    # 评估时效性
    report.metrics.timeliness = 1.0
    
    # 评估有效性
    validity = 1.0
    if any("无效" in i or "异常" in i for i in issues):
        validity = 0.6
    report.metrics.validity = validity
    
    # 添加推荐
    if report.metrics.level in (DataQualityLevel.WARNING, DataQualityLevel.CRITICAL):
        report.recommendations.append("建议检查数据源连接")
        report.recommendations.append("考虑使用备用数据源")
    
    logger.info(f"DataQualityReport for {module_name}: "
                f"score={report.metrics.overall_score:.2f}, "
                f"level={report.metrics.level.value}")
    
    return report
