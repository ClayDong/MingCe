"""
系统健康监控模块
提供系统健康状态检查、告警通知等功能
"""

import os
import time
from datetime import datetime
from loguru import logger
from typing import Dict, List, Optional
from pathlib import Path

# 尝试导入 psutil，如果失败则提供降级实现
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    logger.warning("psutil 模块未安装，系统监控功能将使用降级实现")

from qlib_vnpy_platform.config import get_config
from qlib_vnpy_platform.core.feishu_notifier import get_notifier


class SystemMonitor:
    """系统健康监控器"""

    def __init__(self):
        self.config = get_config().get("monitor", {})
        self.cpu_threshold = self.config.get("cpu_threshold", 80.0)  # 百分比
        self.memory_threshold = self.config.get("memory_threshold", 85.0)  # 百分比
        self.disk_threshold = self.config.get("disk_threshold", 90.0)  # 百分比
        
        self.last_alert_time = {}
        self.alert_cooldown = 3600  # 告警冷却时间（秒）
        
        self.notifier = get_notifier()
        logger.info("SystemMonitor initialized")
    
    def check_system_health(self) -> Dict:
        """检查系统健康状态"""
        health_status = {
            "timestamp": datetime.now().isoformat(),
            "cpu": self._check_cpu(),
            "memory": self._check_memory(),
            "disk": self._check_disk(),
            "process": self._check_process_count(),
        }
        
        # 检查并发送告警
        self._check_and_send_alerts(health_status)
        
        return health_status
    
    def _check_cpu(self) -> Dict:
        """检查 CPU 使用率"""
        if not PSUTIL_AVAILABLE:
            return {"usage": 0, "healthy": True, "warning": "psutil 不可用"}
        try:
            usage = psutil.cpu_percent(interval=1)
            return {
                "usage": usage,
                "healthy": usage < self.cpu_threshold,
                "threshold": self.cpu_threshold,
            }
        except Exception as e:
            logger.error(f"CPU check failed: {e}")
            return {"usage": 0, "healthy": True, "error": str(e)}
    
    def _check_memory(self) -> Dict:
        """检查内存使用率"""
        if not PSUTIL_AVAILABLE:
            return {"usage_percent": 0, "healthy": True, "warning": "psutil 不可用"}
        try:
            mem = psutil.virtual_memory()
            return {
                "used_gb": round(mem.used / (1024**3), 2),
                "total_gb": round(mem.total / (1024**3), 2),
                "usage_percent": mem.percent,
                "healthy": mem.percent < self.memory_threshold,
                "threshold": self.memory_threshold,
            }
        except Exception as e:
            logger.error(f"Memory check failed: {e}")
            return {"usage_percent": 0, "healthy": True, "error": str(e)}
    
    def _check_disk(self) -> Dict:
        """检查磁盘使用率"""
        if not PSUTIL_AVAILABLE:
            return {"usage_percent": 0, "healthy": True, "warning": "psutil 不可用"}
        try:
            path = Path.cwd()
            disk = psutil.disk_usage(str(path))
            return {
                "used_gb": round(disk.used / (1024**3), 2),
                "total_gb": round(disk.total / (1024**3), 2),
                "usage_percent": disk.percent,
                "healthy": disk.percent < self.disk_threshold,
                "threshold": self.disk_threshold,
            }
        except Exception as e:
            logger.error(f"Disk check failed: {e}")
            return {"usage_percent": 0, "healthy": True, "error": str(e)}
    
    def _check_process_count(self) -> Dict:
        """检查进程数量"""
        if not PSUTIL_AVAILABLE:
            return {"count": 0, "healthy": True, "warning": "psutil 不可用"}
        try:
            count = len(psutil.pids())
            return {
                "count": count,
                "healthy": count < 1000,  # 简单阈值
            }
        except Exception as e:
            logger.error(f"Process check failed: {e}")
            return {"count": 0, "healthy": True, "error": str(e)}
    
    def _check_and_send_alerts(self, health_status: Dict):
        """检查状态并发送告警"""
        now = time.time()
        
        # 检查 CPU
        if not health_status["cpu"]["healthy"]:
            self._send_alert_if_needed("cpu", 
                f"⚠️ 高 CPU 使用率: {health_status['cpu']['usage']}%", 
                "error")
        
        # 检查内存
        if not health_status["memory"]["healthy"]:
            self._send_alert_if_needed("memory", 
                f"⚠️ 高内存使用率: {health_status['memory']['usage_percent']}%", 
                "error")
        
        # 检查磁盘
        if not health_status["disk"]["healthy"]:
            self._send_alert_if_needed("disk", 
                f"⚠️ 高磁盘使用率: {health_status['disk']['usage_percent']}%", 
                "error")
    
    def _send_alert_if_needed(self, key: str, message: str, level: str = "warning"):
        """发送告警（带冷却）"""
        now = time.time()
        
        if key in self.last_alert_time:
            if now - self.last_alert_time[key] < self.alert_cooldown:
                logger.debug(f"Alert {key} on cooldown, skipping")
                return
        
        self.last_alert_time[key] = now
        
        # 发送告警
        try:
            self.notifier.send_alert("系统告警", message, level)
            logger.warning(f"Alert sent: {message}")
        except Exception as e:
            logger.error(f"Failed to send alert: {e}")
    
    def get_status_summary(self) -> str:
        """获取状态摘要"""
        health = self.check_system_health()
        
        lines = [
            f"**系统健康状态** {health['timestamp']}",
            f"",
            f"- CPU: {health['cpu']['usage']}% {'✅' if health['cpu']['healthy'] else '❌'}",
            f"- 内存: {health['memory'].get('usage_percent', 0)}% {'✅' if health['memory']['healthy'] else '❌'}",
            f"- 磁盘: {health['disk'].get('usage_percent', 0)}% {'✅' if health['disk']['healthy'] else '❌'}",
            f"- 进程数: {health['process']['count']}",
        ]
        
        return "\n".join(lines)


# 全局单例
_monitor_instance = None


def get_system_monitor() -> SystemMonitor:
    """获取监控器单例"""
    global _monitor_instance
    if _monitor_instance is None:
        _monitor_instance = SystemMonitor()
    return _monitor_instance


# 别名，保持向后兼容
get_monitor = get_system_monitor
