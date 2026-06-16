#!/usr/bin/env python3
"""
全自动每日策略 + 舆情分析报告
每天16:30自动运行，直接发送到飞书群
集成LLM智能分析

所有飞书发送统一使用中转API (http://localhost:8000/api/send_message)
"""
import sys
import time
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

from daily_strategy_trade_report import DailyStrategyTradeReport
from qlib_vnpy_platform.core.sentiment_analyzer import SentimentSystem
from qlib_vnpy_platform.core.llm_analyzer import LLManalyzer
from qlib_vnpy_platform.strategy_monitor_pkg import FeishuOutput


def generate_full_report_and_send():
    """生成完整报告并发送到飞书"""
    print("=" * 70)
    print(f"🤖 开始每日自动化分析 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    # 统一使用 FeishuOutput
    feishu = FeishuOutput()

    try:
        # 1. 生成策略交易报告（generate_daily_report 内部已自动发送）
        print("\n📊 [1/4] 生成策略交易报告...")
        strategy_report = DailyStrategyTradeReport()
        strategy_msg, strategy_data = strategy_report.generate_daily_report()
        print("   ✅ 策略报告已生成并发送")

        # 2. 生成舆情分析报告
        print("📰 [2/4] 生成舆情分析报告...")
        sentiment_system = SentimentSystem()
        sentiment_report = sentiment_system.run_daily_analysis()
        sentiment_msg = sentiment_system.report_generator.format_report_for_feishu(sentiment_report)

        # 3. LLM智能分析
        print("🧠 [3/4] LLM智能分析...")
        llm_analyzer = LLManalyzer()
        llm_msg = ""

        if llm_analyzer.is_available():
            news_text = ""
            if sentiment_report and sentiment_report.get('analyzed_news'):
                news_list = sentiment_report['analyzed_news'][:3]
                news_text = "\n\n".join(
                    [f"{news.get('title', '')}\n{news.get('content', '')[:300]}..."
                     for news in news_list]
                )

            llm_result = llm_analyzer.generate_strategy_advice(
                symbol="SZ002594",
                backtest_results=strategy_data.get('backtest_results', []),
                regime={
                    'regime': 'BULL' if strategy_data.get('change_pct', 0) > 0 else 'BEAR',
                    'trend_strength': abs(strategy_data.get('change_pct', 0)) / 5.0,
                    'volatility': 0.1
                }
            )
            llm_msg = format_llm_daily_report(llm_result)
        else:
            print("   → LLM不可用，跳过智能分析")

        # 4. 统一发送（使用 FeishuOutput 中转API）
        print("📤 [4/4] 发送报告到飞书...")

        time.sleep(2)

        # 发送舆情报告
        if sentiment_msg:
            print("   → 发送舆情报告...")
            feishu.send_message(sentiment_msg)
        else:
            print("   → 舆情报告为空，跳过")

        # 发送LLM分析报告
        if llm_msg:
            time.sleep(2)
            print("   → 发送LLM智能分析报告...")
            feishu.send_message(llm_msg)

        print("\n" + "=" * 70)
        print("✅ 所有报告生成并发送完成！")
        print("=" * 70)

    except Exception as e:
        print(f"\n❌ 自动化分析失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

    return True


def format_llm_daily_report(llm_result):
    """格式化LLM每日分析报告"""
    lines = []
    lines.append(f"🤖 **LLM每日智能分析报告**")
    lines.append(f"📅 {datetime.now().strftime('%Y年%m月%d日')}")
    lines.append("")
    lines.append("━" * 35)

    rec_strategy = llm_result.get('recommended_strategy', '无')
    lines.append(f"🎯 **今日推荐策略:** {rec_strategy}")
    lines.append("")

    entry = llm_result.get('entry_condition', '')
    if entry:
        lines.append(f"📈 **入场条件:**")
        lines.append(f"   {entry}")
        lines.append("")

    exit_cond = llm_result.get('exit_condition', '')
    if exit_cond:
        lines.append(f"📉 **出场条件:**")
        lines.append(f"   {exit_cond}")
        lines.append("")

    position = llm_result.get('position_size', '')
    if position:
        lines.append(f"⚖️ **建议仓位:** {position}")
        lines.append("")

    confidence = llm_result.get('confidence', 0)
    try:
        confidence = float(confidence)
    except (ValueError, TypeError):
        confidence = 0
    from qlib_vnpy_platform.strategy_monitor_pkg import ReportFormatter
    bar = ReportFormatter.strength_bar(confidence, filled='▓', empty='░')
    lines.append(f"🎯 **置信度:** {bar} {confidence:.2f}")
    lines.append("")

    risk = llm_result.get('risk_warning', '')
    if risk:
        lines.append(f"⚠️ **风险提示:**")
        lines.append(f"   {risk}")
        lines.append("")

    reasoning = llm_result.get('reasoning', '')
    if reasoning:
        lines.append(f"💡 **分析理由:**")
        lines.append(f"   {reasoning}")
        lines.append("")

    lines.append("━" * 35)
    lines.append("*以上分析由AI生成，仅供参考，不构成投资建议*")

    return "\n".join(lines)


if __name__ == "__main__":
    generate_full_report_and_send()
