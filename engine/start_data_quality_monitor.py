#!/usr/bin/env python3
"""
数据质量监控启动脚本
提供完整的监控、告警、可视化功能
"""

import sys
import os
import time
import signal
import atexit
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from loguru import logger

from qlib_vnpy_platform.config import get_config, load_config
from qlib_vnpy_platform.core.data_quality_monitor import (
    DataQualityMonitor,
    get_monitor_instance,
    init_monitor
)


# 配置日志
logger.remove()
logger.add(
    sys.stdout,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    level="INFO"
)
logger.add(
    "logs/quality_monitor_{time:YYYY-MM-DD}.log",
    rotation="50 MB",
    retention="30 days",
    level="DEBUG"
)


class QualityMonitorService:
    """数据质量监控服务"""
    
    def __init__(self):
        self.config = get_config()
        self.monitor: DataQualityMonitor = init_monitor()
        self.running = False
        
        # 注册退出处理
        atexit.register(self.cleanup)
        
        # 注册信号处理
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        logger.info("QualityMonitorService initialized")
    
    def _signal_handler(self, signum, frame):
        """信号处理"""
        logger.info(f"Received signal {signum}, shutting down...")
        self.stop()
    
    def start(self, monitor_all: bool = False):
        """启动监控"""
        if self.running:
            logger.warning("Service is already running")
            return
        
        logger.info("=" * 60)
        logger.info("Starting Data Quality Monitoring Service")
        logger.info("=" * 60)
        
        # 获取监控股票列表
        data_quality_config = self.config.get("data_quality", {})
        symbols = data_quality_config.get("monitor_symbols", ["SZ002594"])
        
        logger.info(f"Monitoring {len(symbols)} symbols: {', '.join(symbols)}")
        
        # 启动监控
        check_interval = data_quality_config.get("check_interval", 60)
        self.monitor.start_monitoring(symbols, check_interval)
        
        self.running = True
        
        # 运行控制台界面
        self._run_console_interface()
    
    def _run_console_interface(self):
        """运行控制台界面"""
        try:
            while self.running:
                # 清屏
                os.system('cls' if os.name == 'nt' else 'clear')
                
                # 打印头部
                print("=" * 80)
                print("          📊 数据质量监控系统 - Data Quality Monitor")
                print("=" * 80)
                print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                print()
                
                # 显示摘要
                summary = self.monitor.get_quality_summary()
                print("📈 数据质量摘要")
                print("-" * 40)
                print(f"  总检查数: {summary.get('total_checks', 0)}")
                print(f"  平均评分: {summary.get('average_score', 0):.1f}/100")
                print(f"  通过率: {summary.get('pass_rate', 0)*100:.1f}%")
                print(f"  告警数: {summary.get('alert_count', 0)}")
                if summary.get('last_check_time'):
                    print(f"  最后检查: {summary.get('last_check_time')}")
                print()
                
                # 显示各股票状态
                symbol_stats = summary.get('symbol_stats', {})
                if symbol_stats:
                    print("📋 各股票质量状态")
                    print("-" * 40)
                    for symbol, stats in symbol_stats.items():
                        score = stats.get('avg_score', 0)
                        pass_rate = stats.get('pass_rate', 0) * 100
                        status_emoji = "✅" if score >= 80 else ("⚠️" if score >= 60 else "❌")
                        print(f"  {status_emoji} {symbol:10s} | 评分: {score:5.1f} | 通过率: {pass_rate:5.1f}%")
                    print()
                
                # 显示待处理告警
                pending_alerts = self.monitor.get_pending_alerts()
                if pending_alerts:
                    print("🚨 待处理告警")
                    print("-" * 40)
                    for alert in pending_alerts[:5]:  # 只显示最近5条
                        level = alert.get('alert_level', 'info').upper()
                        level_color = {
                            'CRITICAL': '\033[91m',
                            'ERROR': '\033[91m',
                            'WARNING': '\033[93m',
                            'INFO': '\033[94m'
                        }.get(level, '\033[0m')
                        reset = '\033[0m'
                        print(f"  {level_color}{level:8s}{reset} | {alert.get('symbol')} | {alert.get('message')[:60]}...")
                    print()
                
                # 显示操作提示
                print("🔧 操作:")
                print("  [R] 立即运行一次检查")
                print("  [Q] 退出监控")
                print()
                
                # 等待输入
                print("等待输入... ", end='', flush=True)
                
                # 使用非阻塞输入
                try:
                    import select
                    rlist, _, _ = select.select([sys.stdin], [], [], 1)
                    if rlist:
                        user_input = sys.stdin.readline().strip().upper()
                        if user_input == 'Q':
                            self.stop()
                        elif user_input == 'R':
                            print("\n立即检查所有股票...")
                            data_quality_config = self.config.get("data_quality", {})
                            symbols = data_quality_config.get("monitor_symbols", ["SZ002594"])
                            self.monitor.check_multiple_symbols(symbols)
                            print("检查完成！")
                            time.sleep(1)
                except (ImportError, KeyboardInterrupt):
                    self.stop()
                
                time.sleep(1)
                
        except Exception as e:
            logger.error(f"Error in console interface: {e}")
            self.stop()
    
    def stop(self):
        """停止监控"""
        if not self.running:
            return
        
        logger.info("Stopping Data Quality Monitoring Service...")
        self.running = False
        self.monitor.stop_monitoring()
        
        # 打印最终统计
        summary = self.monitor.get_quality_summary()
        logger.info("=" * 60)
        logger.info("监控结束 - 最终统计")
        logger.info("=" * 60)
        logger.info(f"总检查数: {summary.get('total_checks', 0)}")
        logger.info(f"平均评分: {summary.get('average_score', 0):.1f}/100")
        logger.info(f"告警数: {summary.get('alert_count', 0)}")
        
        logger.info("Data Quality Monitoring Service stopped")
    
    def cleanup(self):
        """清理资源"""
        if self.running:
            self.stop()


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='数据质量监控服务')
    parser.add_argument('--check', '-c', action='store_true', help='仅运行一次检查然后退出')
    parser.add_argument('--symbol', '-s', type=str, help='检查指定的单个股票')
    parser.add_argument('--daemon', '-d', action='store_true', help='以守护进程方式运行')
    
    args = parser.parse_args()
    
    # 加载配置
    load_config()
    
    service = QualityMonitorService()
    
    if args.check:
        # 单次检查模式
        symbols = [args.symbol] if args.symbol else get_config().get("data_quality", {}).get("monitor_symbols", ["SZ002594"])
        logger.info(f"Running single check for {len(symbols)} symbols")
        results = service.monitor.check_multiple_symbols(symbols)
        
        # 打印结果
        print("\n" + "=" * 60)
        print("单次检查结果")
        print("=" * 60)
        
        for symbol, record in results.items():
            status_emoji = "✅" if record.passed else "❌"
            print(f"\n{status_emoji} {symbol}")
            print(f"  质量评分: {record.quality_score:.1f}/100")
            if record.issues_summary:
                print("  问题:")
                for issue in record.issues_summary:
                    print(f"    - {issue}")
        
        print("\n" + "=" * 60)
        
    elif args.daemon:
        # 守护进程模式
        logger.info("Starting in daemon mode")
        service.monitor.start_monitoring(
            get_config().get("data_quality", {}).get("monitor_symbols", ["SZ002594"])
        )
        
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            service.stop()
    else:
        # 交互模式
        service.start()


if __name__ == "__main__":
    main()
