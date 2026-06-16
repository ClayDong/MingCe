"""
数据质量监控服务
提供完整的数据质量监控、告警、自动化处理功能
"""

import time
import threading
import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Callable
from loguru import logger
from dataclasses import dataclass, field
from queue import Queue, Empty

from qlib_vnpy_platform.core.data_bridge import DataBridge
from qlib_vnpy_platform.core.data_quality import DataQualityChecker
from qlib_vnpy_platform.core.feishu_notifier import get_notifier
from qlib_vnpy_platform.config import get_config, PROJECT_ROOT


@dataclass
class DataQualityRecord:
    """数据质量记录"""
    symbol: str
    timestamp: str
    quality_score: float
    checks: Dict[str, Any]
    issues_summary: List[str]
    passed: bool
    data_source: str
    cache_age_seconds: float


@dataclass
class AlertRule:
    """告警规则"""
    name: str
    condition: Callable[[DataQualityRecord], bool]
    alert_level: str  # info, warning, error, critical
    message_template: str
    cooldown_minutes: int = 60
    last_alert_time: Optional[datetime] = None


class DataQualityMonitor:
    """数据质量监控器"""
    
    def __init__(self, data_bridge: Optional[DataBridge] = None):
        self.config = get_config()
        self.data_bridge = data_bridge or DataBridge()
        self.checker = DataQualityChecker()
        self.notifier = get_notifier()
        
        # 监控配置
        self.check_interval_minutes = self.config.get("data_quality", {}).get("check_interval", 60)
        self.alert_threshold = self.config.get("data_quality", {}).get("alert_threshold", 70)
        self.stale_data_days = self.config.get("data_quality", {}).get("stale_data_days", 5)
        self.enable_feishu_alerts = self.config.get("data_quality", {}).get("enable_feishu_alerts", True)
        
        # 数据存储
        self.storage_dir = PROJECT_ROOT / "data" / "quality_monitor"
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        
        # 历史记录
        self.quality_history: List[DataQualityRecord] = []
        self.alert_history: List[Dict[str, Any]] = []
        
        # 告警规则
        self.alert_rules: List[AlertRule] = []
        
        # 线程管理
        self.is_running = False
        self.monitor_thread: Optional[threading.Thread] = None
        self.alert_queue: Queue = Queue()
        self.stop_event = threading.Event()
        
        # 初始化默认告警规则
        self._init_default_alert_rules()
        
        logger.info("DataQualityMonitor initialized")
    
    def _init_default_alert_rules(self):
        """初始化默认告警规则"""
        # 规则1: 低质量分数
        self.alert_rules.append(AlertRule(
            name="low_quality_score",
            condition=lambda r: r.quality_score < self.alert_threshold,
            alert_level="error",
            message_template="⚠️ 数据质量警告: {symbol} 质量分数仅 {score:.1f}/100，低于阈值 {threshold}!"
        ))
        
        # 规则2: 数据过期
        self.alert_rules.append(AlertRule(
            name="stale_data",
            condition=lambda r: any("stale" in issue.lower() for issue in r.issues_summary),
            alert_level="warning",
            message_template="⚠️ 数据过期警告: {symbol} 数据可能已过时"
        ))
        
        # 规则3: 检测失败
        self.alert_rules.append(AlertRule(
            name="check_failed",
            condition=lambda r: not r.passed,
            alert_level="error",
            message_template="❌ 数据质量检查失败: {symbol} - {issues}"
        ))
        
        # 规则4: 使用模拟数据
        self.alert_rules.append(AlertRule(
            name="simulated_data",
            condition=lambda r: "simulated" in r.data_source.lower(),
            alert_level="warning",
            message_template="⚠️ 模拟数据使用: {symbol} 当前使用模拟数据，请检查数据源"
        ))
    
    def check_symbol_quality(self, symbol: str) -> DataQualityRecord:
        """检查单个股票数据质量"""
        try:
            logger.info(f"Checking data quality for {symbol}")
            
            # 获取数据
            df = self.data_bridge.fetch_stock_daily(symbol)
            
            # 检查数据来源
            data_source = "primary"
            cache_age = 0.0
            
            # 运行质量检查
            result = self.checker.run_full_check(df, symbol)
            
            # 创建记录
            record = DataQualityRecord(
                symbol=symbol,
                timestamp=datetime.now().isoformat(),
                quality_score=result["quality_score"],
                checks=result["checks"],
                issues_summary=result["issues_summary"],
                passed=result["overall_passed"],
                data_source=data_source,
                cache_age_seconds=cache_age
            )
            
            # 保存记录
            self._save_record(record)
            
            # 检查告警
            self._check_alerts(record)
            
            logger.info(f"{symbol} quality check complete: {record.quality_score:.1f}/100")
            return record
            
        except Exception as e:
            logger.error(f"Error checking data quality for {symbol}: {e}")
            # 创建失败记录
            record = DataQualityRecord(
                symbol=symbol,
                timestamp=datetime.now().isoformat(),
                quality_score=0.0,
                checks={},
                issues_summary=[f"Error: {str(e)}"],
                passed=False,
                data_source="error",
                cache_age_seconds=0.0
            )
            self._save_record(record)
            return record
    
    def check_multiple_symbols(self, symbols: List[str]) -> Dict[str, DataQualityRecord]:
        """批量检查多个股票"""
        results = {}
        for symbol in symbols:
            if self.stop_event.is_set():
                break
            results[symbol] = self.check_symbol_quality(symbol)
        return results
    
    def _save_record(self, record: DataQualityRecord):
        """保存质量记录"""
        try:
            self.quality_history.append(record)
            
            # 限制内存中历史记录数量
            if len(self.quality_history) > 1000:
                self.quality_history = self.quality_history[-1000:]
            
            # 保存到文件
            self._save_record_to_file(record)
            
        except Exception as e:
            logger.error(f"Error saving quality record: {e}")
    
    def _save_record_to_file(self, record: DataQualityRecord):
        """保存记录到文件"""
        try:
            date_str = datetime.now().strftime("%Y-%m-%d")
            file_path = self.storage_dir / f"quality_{date_str}.json"
            
            records = []
            if file_path.exists():
                with open(file_path, 'r', encoding='utf-8') as f:
                    records = json.load(f)
            
            record_dict = {
                "symbol": record.symbol,
                "timestamp": record.timestamp,
                "quality_score": record.quality_score,
                "checks": record.checks,
                "issues_summary": record.issues_summary,
                "passed": record.passed,
                "data_source": record.data_source,
                "cache_age_seconds": record.cache_age_seconds
            }
            records.append(record_dict)
            
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(records, f, ensure_ascii=False, indent=2)
                
        except Exception as e:
            logger.error(f"Error saving record to file: {e}")
    
    def _check_alerts(self, record: DataQualityRecord):
        """检查并触发告警"""
        for rule in self.alert_rules:
            try:
                # 检查冷却时间
                if rule.last_alert_time:
                    time_since_alert = (datetime.now() - rule.last_alert_time).total_seconds()
                    if time_since_alert < rule.cooldown_minutes * 60:
                        continue
                
                # 检查规则条件
                if rule.condition(record):
                    self._trigger_alert(rule, record)
                    rule.last_alert_time = datetime.now()
                    
            except Exception as e:
                logger.error(f"Error checking alert rule {rule.name}: {e}")
    
    def _trigger_alert(self, rule: AlertRule, record: DataQualityRecord):
        """触发告警"""
        try:
            # 格式化消息
            issues = "; ".join(record.issues_summary[:3]) if record.issues_summary else "无详情"
            message = rule.message_template.format(
                symbol=record.symbol,
                score=record.quality_score,
                threshold=self.alert_threshold,
                issues=issues
            )
            
            # 创建告警
            alert = {
                "rule_name": rule.name,
                "alert_level": rule.alert_level,
                "symbol": record.symbol,
                "message": message,
                "timestamp": datetime.now().isoformat(),
                "quality_score": record.quality_score,
                "record": record.__dict__
            }
            
            # 记录告警历史
            self.alert_history.append(alert)
            if len(self.alert_history) > 1000:
                self.alert_history = self.alert_history[-1000:]
            
            # 放入告警队列
            self.alert_queue.put(alert)
            
            # 发送飞书通知
            if self.enable_feishu_alerts:
                try:
                    feishu_message = self._format_feishu_alert_message(alert)
                    self.notifier.send_alert(
                        title=f"数据质量{rule.alert_level.upper()}",
                        content=feishu_message,
                        level=rule.alert_level
                    )
                except Exception as e:
                    logger.error(f"Error sending feishu alert: {e}")
            
            # 记录日志
            if rule.alert_level == "critical":
                logger.critical(message)
            elif rule.alert_level == "error":
                logger.error(message)
            elif rule.alert_level == "warning":
                logger.warning(message)
            else:
                logger.info(message)
                
        except Exception as e:
            logger.error(f"Error triggering alert: {e}")
    
    def _format_feishu_alert_message(self, alert: Dict[str, Any]) -> str:
        """格式化飞书告警消息"""
        return (
            f"📊 **数据质量告警**\n\n"
            f"**股票**: {alert['symbol']}\n"
            f"**告警级别**: {alert['alert_level'].upper()}\n"
            f"**质量分数**: {alert['quality_score']:.1f}/100\n"
            f"**消息**: {alert['message']}\n"
            f"**时间**: {alert['timestamp']}\n"
        )
    
    def send_daily_quality_report(self) -> bool:
        """发送每日数据质量报告"""
        try:
            summary = self.get_quality_summary()
            
            if summary["total_checks"] == 0:
                return False
            
            report = (
                f"📊 **每日数据质量报告**\n\n"
                f"**总检查次数**: {summary['total_checks']}\n"
                f"**平均质量分数**: {summary['average_score']:.1f}/100\n"
                f"**通过率**: {summary['pass_rate']:.1%}\n"
                f"**告警次数**: {summary['alert_count']}\n"
            )
            
            if 'symbol_stats' in summary and summary['symbol_stats']:
                report += "\n**各股票统计**\n"
                for symbol, stats in summary['symbol_stats'].items():
                    report += (
                        f"- {symbol}: {stats['avg_score']:.1f}分, "
                        f"通过率 {stats['pass_rate']:.1%}\n"
                    )
            
            return self.notifier.send_daily_report(report)
        except Exception as e:
            logger.error(f"Error sending daily quality report: {e}")
            return False
    
    def get_quality_summary(self) -> Dict[str, Any]:
        """获取质量摘要"""
        if not self.quality_history:
            return {"total_checks": 0}
        
        recent_records = self.quality_history[-100:]  # 最近100条记录
        
        avg_score = sum(r.quality_score for r in recent_records) / len(recent_records)
        pass_rate = sum(1 for r in recent_records if r.passed) / len(recent_records)
        
        # 按股票统计
        symbol_stats = {}
        for record in recent_records:
            if record.symbol not in symbol_stats:
                symbol_stats[record.symbol] = {"checks": 0, "passes": 0, "avg_score": 0.0}
            symbol_stats[record.symbol]["checks"] += 1
            symbol_stats[record.symbol]["avg_score"] += record.quality_score
            if record.passed:
                symbol_stats[record.symbol]["passes"] += 1
        
        for symbol in symbol_stats:
            stats = symbol_stats[symbol]
            stats["avg_score"] /= stats["checks"]
            stats["pass_rate"] = stats["passes"] / stats["checks"]
        
        return {
            "total_checks": len(self.quality_history),
            "recent_checks": len(recent_records),
            "average_score": avg_score,
            "pass_rate": pass_rate,
            "symbol_stats": symbol_stats,
            "alert_count": len(self.alert_history),
            "last_check_time": self.quality_history[-1].timestamp if self.quality_history else None
        }
    
    def get_history_for_symbol(self, symbol: str, limit: int = 100) -> List[DataQualityRecord]:
        """获取指定股票的历史记录"""
        symbol_records = [r for r in self.quality_history if r.symbol == symbol]
        return symbol_records[-limit:]
    
    def start_monitoring(self, symbols: List[str], interval_minutes: Optional[int] = None):
        """启动监控"""
        if self.is_running:
            logger.warning("Monitor is already running")
            return
        
        interval = interval_minutes or self.check_interval_minutes
        
        logger.info(f"Starting data quality monitor for {len(symbols)} symbols, interval: {interval} minutes")
        
        self.is_running = True
        self.stop_event.clear()
        
        def monitor_loop():
            while not self.stop_event.is_set():
                try:
                    # 检查所有股票
                    self.check_multiple_symbols(symbols)
                    
                    # 等待下一次检查
                    for _ in range(interval * 60):
                        if self.stop_event.is_set():
                            break
                        time.sleep(1)
                        
                except Exception as e:
                    logger.error(f"Error in monitor loop: {e}")
                    time.sleep(60)  # 出错后短暂休息
        
        self.monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
        self.monitor_thread.start()
        
        logger.info("Data quality monitor started")
    
    def stop_monitoring(self):
        """停止监控"""
        logger.info("Stopping data quality monitor")
        
        self.is_running = False
        self.stop_event.set()
        
        if self.monitor_thread:
            self.monitor_thread.join(timeout=10)
        
        logger.info("Data quality monitor stopped")
    
    def add_alert_rule(self, rule: AlertRule):
        """添加自定义告警规则"""
        self.alert_rules.append(rule)
        logger.info(f"Added alert rule: {rule.name}")
    
    def get_pending_alerts(self) -> List[Dict[str, Any]]:
        """获取待处理的告警"""
        alerts = []
        while not self.alert_queue.empty():
            try:
                alerts.append(self.alert_queue.get_nowait())
            except Empty:
                break
        return alerts


# 全局单例
_monitor_instance: Optional[DataQualityMonitor] = None


def get_monitor_instance() -> DataQualityMonitor:
    """获取全局监控器实例"""
    global _monitor_instance
    if _monitor_instance is None:
        _monitor_instance = DataQualityMonitor()
    return _monitor_instance


def init_monitor():
    """初始化监控器"""
    global _monitor_instance
    _monitor_instance = DataQualityMonitor()
    return _monitor_instance
