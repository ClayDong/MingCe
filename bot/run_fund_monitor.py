#!/usr/bin/env python3
"""基金监控启动脚本 — 每日运行基金监控并发送飞书通知。

使用方法：
    python run_fund_monitor.py [--config config.json]
"""

import asyncio
import json
import argparse
from datetime import datetime
from typing import Optional
from loguru import logger
from pathlib import Path

from services.fund_monitor import FundMonitor, FundMonitorConfig, build_fund_monitor_card
from services.feishu_service import send_card_message, get_tenant_token
from config.settings import get_settings

settings = get_settings()


async def run_fund_monitor(config_path: Optional[str] = None):
    """运行基金监控并发送飞书通知"""
    
    logger.info("Starting fund monitor...")
    
    # 加载配置
    config = FundMonitorConfig()
    if config_path and Path(config_path).exists():
        try:
            with open(config_path, "r") as f:
                config_data = json.load(f)
                config = FundMonitorConfig(**config_data)
                logger.info(f"Loaded config from {config_path}")
        except Exception as e:
            logger.warning(f"Failed to load config: {e}, using default config")
    
    # 创建监控器
    monitor = FundMonitor(config)
    
    # 运行监控
    result = monitor.run_monitor()
    
    if result.get("status") != "success":
        logger.error(f"Monitor failed: {result.get('message', 'Unknown error')}")
        return
    
    # 保存监控结果到本地文件
    output_dir = Path("data/fund_monitor")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    date_str = result.get("date", datetime.now().strftime("%Y-%m-%d"))
    output_file = output_dir / f"monitor_{date_str}.json"
    
    try:
        with open(output_file, "w") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        logger.info(f"Monitor result saved to {output_file}")
    except Exception as e:
        logger.warning(f"Failed to save monitor result: {e}")
    
    # 发送飞书通知
    if settings.FEISHU_CHAT_ID:
        try:
            # 获取飞书 token
            await get_tenant_token()
            
            # 构建飞书卡片
            card = build_fund_monitor_card(result)
            
            # 发送卡片消息
            success = await send_card_message(settings.FEISHU_CHAT_ID, card)
            
            if success:
                logger.info("Fund monitor notification sent to Feishu")
            else:
                logger.warning("Failed to send fund monitor notification")
        except Exception as e:
            logger.error(f"Failed to send Feishu notification: {e}")
    else:
        logger.warning("No FEISHU_CHAT_ID configured, skip sending notification")
    
    # 打印监控摘要
    print("\n" + "="*60)
    print(f"基金监控报告 - {result.get('date', '')}")
    print("="*60)
    print(f"基金名称：{result.get('fund_name', '')} ({result.get('fund_code', '')})")
    print(f"单位净值：{result.get('net_value', 0):.4f}")
    print(f"日涨跌幅：{result.get('daily_change_pct', 0):+.2f}%")
    
    if result.get("weekly_change_pct"):
        print(f"近1周涨跌：{result.get('weekly_change_pct', 0):+.2f}%")
    if result.get("monthly_change_pct"):
        print(f"近1月涨跌：{result.get('monthly_change_pct', 0):+.2f}%")
    if result.get("quarterly_change_pct"):
        print(f"近3月涨跌：{result.get('quarterly_change_pct', 0):+.2f}%")
    if result.get("yearly_change_pct"):
        print(f"近1年涨跌：{result.get('yearly_change_pct', 0):+.2f}%")
    
    if result.get("profit_pct"):
        print(f"累计收益：{result.get('profit_pct', 0):+.2f}%")
    if result.get("drawdown_pct"):
        print(f"当前回撤：{result.get('drawdown_pct', 0):+.2f}%")
    if result.get("volatility"):
        print(f"波动率：{result.get('volatility', 0):.2f}%")
    
    alerts = result.get("alerts", [])
    if alerts:
        print(f"\n告警数量：{len(alerts)}")
        for alert in alerts[:5]:
            level = alert.get("level", "info")
            icon = {"danger": "🔴", "warning": "🟡", "info": "🟢"}.get(level, "⚪")
            print(f"{icon} {alert.get('title', '')}: {alert.get('content', '')}")
            if alert.get("action"):
                print(f"   👉 建议：{alert.get('action', '')}")
    
    print("="*60)
    print(f"数据更新：{result.get('timestamp', '')}")
    print("="*60 + "\n")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="运行基金监控并发送飞书通知")
    parser.add_argument("--config", type=str, help="配置文件路径（JSON格式）")
    args = parser.parse_args()
    
    asyncio.run(run_fund_monitor(args.config))


if __name__ == "__main__":
    main()