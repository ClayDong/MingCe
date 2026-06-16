#!/usr/bin/env python3
"""QLib+VNPY Web 面板 — 主入口"""

import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime
from loguru import logger
from qlib_vnpy_platform.config import load_config
from qlib_vnpy_platform.core.main_engine import MainEngine
from qlib_vnpy_platform.core.feishu_notifier import send_markdown
from web_app_pkg import create_app

# Module-level convenience for import access (e.g. tests, gunicorn)
app = create_app()


def send_startup_notification(engine):
    """发送系统启动通知到飞书"""
    try:
        now = datetime.now()
        status = engine.get_status()
        account = status["account"]
        watch_list = status.get("watch_list", [])

        message = (
            f"✅ **量化交易系统已启动**\n"
            f"🕒 **启动时间**: {now.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"📊 **监控股票**: {', '.join(watch_list) if watch_list else '无'}\n"
            f"💰 **总资产**: {account['total_capital']:,.2f}\n"
            f"💸 **可用资金**: {account['cash']:,.2f}\n"
            f"📉 **总盈亏**: {account['total_pnl']:,.2f} ({account['total_pnl_pct']:.2%})\n"
            f"\n"
            f"📝 **日报将在每日 15:10 自动发送**\n"
            f"🔔 如需手动发送日报，请运行: python send_daily_report.py"
        )

        success = send_markdown(message)
        if success:
            logger.info("✅ 启动通知已发送到飞书")
        else:
            logger.warning("⚠️ 启动通知发送失败")
    except Exception as e:
        logger.error(f"发送启动通知失败: {e}")


def main():
    parser = argparse.ArgumentParser(description="QLib+VNPY Web 面板")
    parser.add_argument("-H", "--host", default="0.0.0.0", help="Web服务地址 (默认: 0.0.0.0)")
    parser.add_argument("-p", "--port", type=int, default=5000, help="Web服务端口 (默认: 5000)")
    parser.add_argument("--debug", action="store_true", help="启用调试模式")
    parser.add_argument("--no-auto", action="store_true", help="不自动启动调度器")
    args = parser.parse_args()

    load_config()
    engine = MainEngine()
    from web_app_pkg.helpers import _set_engine
    _set_engine(engine)

    # 启动调度器
    if not args.no_auto:
        engine.scheduler.configure(
            watch_list=list(engine._watch_list),
            scan_interval=300,
            auto_trade=False,
        )
        engine.scheduler.start()
        engine._running = True
        logger.info("调度器已自动启动 (--no-auto 参数可关闭)")

        # 发送启动通知
        send_startup_notification(engine)

    logger.info(f"Web 面板启动于 http://{args.host}:{args.port}")
    logger.info("📝 每日 15:10 将自动发送交易日报到飞书")
    logger.info("📝 如需手动发送日报: python send_daily_report.py")
    app.run(host=args.host, port=args.port, debug=args.debug, threaded=True)


if __name__ == "__main__":
    main()
