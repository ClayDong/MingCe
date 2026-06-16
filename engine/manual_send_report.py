#!/usr/bin/env python3
"""
手动触发飞书日报
所有飞书发送统一使用中转API (http://localhost:8000/api/send_message)
"""

import sys
import os
import json
from datetime import datetime
from pathlib import Path
from loguru import logger

sys.path.insert(0, str(Path(__file__).parent))

from qlib_vnpy_platform.config import load_config
from qlib_vnpy_platform.core.main_engine import MainEngine
from qlib_vnpy_platform.strategy_monitor_pkg import FeishuOutput, ReportFormatter


def manual_send_daily_report():
    """手动触发日报发送"""
    logger.info("=" * 60)
    logger.info("手动触发每日交易报告")
    logger.info("=" * 60)

    try:
        # 1. 加载配置和引擎
        load_config()
        engine = MainEngine()

        # 2. 获取系统状态
        logger.info("正在获取系统状态...")
        status = engine.get_status()

        account = status["account"]
        risk = status["risk_status"]
        positions = status.get("positions", {})
        trades = status.get("recent_trades", [])

        # 3. 生成报告
        report_lines = [
            f"=== 每日交易报告 {datetime.now().strftime('%Y-%m-%d')} ===",
            f"",
            f"[账户概览]",
            f"  总资产: {account['total_capital']:,.2f}",
            f"  可用资金: {account['cash']:,.2f}",
            f"  持仓市值: {account['position_value']:,.2f}",
            f"  总盈亏: {account['total_pnl']:,.2f} ({account['total_pnl_pct']:.2%})",
            f"",
            f"[风控状态]",
            f"  风险等级: {risk['risk_level']}",
            f"  当日盈亏: {risk['daily_pnl']:,.2f}",
            f"  熔断状态: {'已触发' if risk.get('circuit_breaker_active') else '正常'}",
        ]

        if positions:
            report_lines.append(f"")
            report_lines.append(f"[持仓明细]")
            for sym, pos in positions.items():
                pnl = (pos["current_price"] - pos["avg_cost"]) * pos["volume"]
                report_lines.append(f"  {sym}: {pos['volume']}股 @ {pos['avg_cost']:.2f}, "
                                    f"现价={pos['current_price']:.2f}, 盈亏={pnl:+,.2f}")

        if trades:
            today_trades = [t for t in trades if t["timestamp"].startswith(datetime.now().strftime("%Y-%m-%d"))]
            if today_trades:
                report_lines.append(f"")
                report_lines.append(f"[今日交易] ({len(today_trades)}笔)")
                for t in today_trades:
                    report_lines.append(f"  {t['direction']} {t['symbol']} {t['volume']}@{t['price']:.2f}")

        report = "\n".join(report_lines)
        logger.info(f"\n报告生成完成:\n{report}")

        # 4. 构建飞书消息
        message_lines = [
            f"📊 **每日交易报告**",
            f"🕐 **{datetime.now().strftime('%Y-%m-%d %H:%M')}**",
            f"",
            f"---",
            f"",
        ]
        for line in report.split('\n'):
            if line.strip():
                message_lines.append(line)

        message = "\n".join(message_lines)

        # 5. 使用统一的 FeishuOutput 发送（中转API优先）
        logger.info("\n正在发送到飞书...")
        feishu = FeishuOutput()
        success = feishu.send_message(message)

        if success:
            logger.info("✅ 飞书日报发送成功! (via relay API)")
            return True
        else:
            logger.warning("中转API发送失败，尝试备用方式...")

            # Fallback to lark-cli
            lark_cli_path = None
            for p in [
                "/Users/dong/.nvm/versions/node/v24.14.0/bin/lark-cli",
                "/Users/dong/.nvm/versions/node/v22.22.3/bin/lark-cli",
                "/usr/local/bin/lark-cli",
            ]:
                if os.path.isfile(p) and os.access(p, os.X_OK):
                    lark_cli_path = p
                    break

            if lark_cli_path:
                import subprocess
                import shutil
                node_bin = os.path.dirname(lark_cli_path)
                node_env = os.environ.copy()
                node_env['PATH'] = node_bin + ':' + node_env.get('PATH', '')
                cmd = [lark_cli_path, "im", "+messages-send", "--chat-id", feishu.chat_id, "--markdown", message]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=node_env)
                if result.returncode == 0:
                    logger.info("✅ 飞书日报发送成功! (via lark-cli)")
                    return True
                else:
                    logger.error(f"lark-cli发送失败: {result.stderr}")
                    return False
            else:
                logger.error("❌ lark-cli未安装，无法发送")
                return False

    except Exception as e:
        logger.error(f"错误: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


if __name__ == "__main__":
    success = manual_send_daily_report()
    sys.exit(0 if success else 1)
