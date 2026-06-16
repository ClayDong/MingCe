#!/usr/bin/env python3
"""
报告格式化工具
提供控制台文本格式和飞书 Markdown 格式的字符串生成
"""

from datetime import datetime


class ReportFormatter:
    """报告格式化工具"""

    # ------------------------------------------------------------------ #
    #  通用工具
    # ------------------------------------------------------------------ #

    @staticmethod
    def strength_bar(value, total=10, filled='█', empty='░'):
        """生成强度进度条"""
        filled_count = min(int(value * total), total)
        return filled * filled_count + empty * (total - filled_count)

    @staticmethod
    def separator(char='=', width=80):
        return char * width

    # ------------------------------------------------------------------ #
    #  控制台报告
    # ------------------------------------------------------------------ #

    @classmethod
    def format_console_daily_header(cls, stock_name, symbol, latest_date, latest_price, change, change_pct):
        """生成控制台报告头部"""
        lines = []
        lines.append(f"\n{cls.separator()}")
        lines.append(f"📊 {datetime.now().strftime('%Y-%m-%d')} 每日策略监控报告")
        lines.append(cls.separator())
        lines.append(f"\n📈 {stock_name} ({symbol}) 最新行情")
        lines.append(f"   日期: {latest_date}")
        lines.append(f"   最新价: {latest_price:.2f} 元")
        if change != 0:
            lines.append(f"   涨跌额: {change:+.2f} 元")
            lines.append(f"   涨跌幅: {change_pct:+.2f}%")
        return "\n".join(lines)

    @classmethod
    def format_console_signals(cls, buy_signals, sell_signals, hold_signals):
        """生成控制台信号汇总"""
        lines = []
        lines.append(f"\n{cls.separator()}")
        lines.append(f"🎯 策略信号汇总")
        lines.append(cls.separator())

        # 买入
        lines.append(f"\n🟢 买入信号 ({len(buy_signals)} 个策略):")
        if buy_signals:
            for key, signal in buy_signals.items():
                bar = cls.strength_bar(signal['signal_strength'], filled='█', empty='')
                lines.append(f"   • {signal['strategy_name']:12s} | 信号强度: {signal['signal_strength']:.2f} {bar}")
        else:
            lines.append("   暂无买入信号")

        # 卖出
        lines.append(f"\n🔴 卖出信号 ({len(sell_signals)} 个策略):")
        if sell_signals:
            for key, signal in sell_signals.items():
                bar = cls.strength_bar(signal['signal_strength'], filled='█', empty='')
                lines.append(f"   • {signal['strategy_name']:12s} | 信号强度: {signal['signal_strength']:.2f} {bar}")
        else:
            lines.append("   暂无卖出信号")

        # 持有（只显示前5个）
        lines.append(f"\n🟡 持有信号 ({len(hold_signals)} 个策略):")
        if hold_signals:
            for key, signal in list(hold_signals.items())[:5]:
                lines.append(f"   • {signal['strategy_name']:12s}")
            if len(hold_signals) > 5:
                lines.append(f"   ... 等共 {len(hold_signals)} 个策略")
        else:
            lines.append("   暂无持有信号")

        return "\n".join(lines)

    @classmethod
    def format_console_summary(cls, report):
        """生成通知摘要（文本版）"""
        if not report:
            return "无法生成报告"

        summary = f"""
📊 每日策略监控报告 - {report['date']}

{report['stock_name']} ({report['symbol']})
💰 最新价格: {report['latest_price']:.2f} 元

🎯 策略信号汇总:
🟢 买入信号: {report['buy_signals']} 个策略
🔴 卖出信号: {report['sell_signals']} 个策略
🟡 持有信号: {report['hold_signals']} 个策略

"""
        if report['buy_signals'] > 0:
            summary += f"✅ 推荐买入: {', '.join(report['recommendations']['buy'][:3])}"
            if report['buy_signals'] > 3:
                summary += f" 等{report['buy_signals']}个策略"

        if report['sell_signals'] > 0:
            summary += f"\n⚠️ 建议关注: {', '.join(report['recommendations']['sell'][:3])}"
            if report['sell_signals'] > 3:
                summary += f" 等{report['sell_signals']}个策略"

        return summary

    # ------------------------------------------------------------------ #
    #  飞书 Markdown 报告
    # ------------------------------------------------------------------ #

    @classmethod
    def format_feishu_daily_header(cls, stock_name, symbol, latest_date, latest_price, change, change_pct):
        """飞书每日报告头部"""
        return f"""📊 **每日策略监控报告**
📅 **{latest_date}**

━━━━━━━━━━━━━━━━━
**{stock_name}** ({symbol})
💰 最新价: **{latest_price:.2f}** 元
📈 涨跌额: **{change:+.2f}** 元
📉 涨跌幅: **{change_pct:+.2f}%**
━━━━━━━━━━━━━━━━━

🎯 **策略信号汇总**
"""

    @classmethod
    def format_feishu_signals(cls, buy_signals, sell_signals, hold_signals):
        """飞书信号汇总（买入/卖出/持有）"""
        message = ""

        # 买入
        message += f"\n🟢 **买入信号: {len(buy_signals)} 个策略**\n"
        if buy_signals:
            sorted_buys = sorted(buy_signals.items(), key=lambda x: x[1]['signal_strength'], reverse=True)
            for key, signal in sorted_buys:
                bar = cls.strength_bar(signal['signal_strength'], filled='▓', empty='░')
                message += f"• {signal['strategy_name']} {bar} {signal['signal_strength']:.0%}\n"
        else:
            message += "• 暂无买入信号\n"

        # 卖出
        message += f"\n🔴 **卖出信号: {len(sell_signals)} 个策略**\n"
        if sell_signals:
            sorted_sells = sorted(sell_signals.items(), key=lambda x: x[1]['signal_strength'], reverse=True)
            for key, signal in sorted_sells:
                bar = cls.strength_bar(signal['signal_strength'], filled='▓', empty='░')
                message += f"• {signal['strategy_name']} {bar} {signal['signal_strength']:.0%}\n"
        else:
            message += "• 暂无卖出信号\n"

        # 持有
        message += f"\n🟡 **持有信号: {len(hold_signals)} 个策略**\n"
        hold_list = [v['strategy_name'] for v in hold_signals.values()]
        message += "• " + "、".join(hold_list[:8])
        if len(hold_list) > 8:
            message += f" 等{len(hold_list)}个策略"

        message += f"\n━━━━━━━━━━━━━━━━━\n"

        # 重点关注
        if len(buy_signals) > 0:
            top_buy = sorted(buy_signals.items(), key=lambda x: x[1]['signal_strength'], reverse=True)[0]
            message += f"\n✅ **重点关注**: {top_buy[1]['strategy_name']} (信号强度: {top_buy[1]['signal_strength']:.0%})"

        if len(sell_signals) > 0:
            top_sell = sorted(sell_signals.items(), key=lambda x: x[1]['signal_strength'], reverse=True)[0]
            message += f"\n⚠️ **注意风险**: {top_sell[1]['strategy_name']} (信号强度: {top_sell[1]['signal_strength']:.0%})"

        return message

    @classmethod
    def format_feishu_trade_report(cls, date, stock_name, symbol, price, change, change_pct,
                                   buy_actions, sell_actions, performance):
        """格式化交易报告飞书消息"""
        message = f"""📊 **每日策略交易报告**
📅 **{date}**

━━━━━━━━━━━━━━━━━
**{stock_name}** ({symbol})
💰 最新价: **{price:.2f}** 元
📈 涨跌额: **{change:+.2f}** 元
📉 涨跌幅: **{change_pct:+.2f}%**
━━━━━━━━━━━━━━━━━

🎯 **今日操作信号**

🟢 **买入操作: {len(buy_actions)} 个策略**
"""
        if buy_actions:
            for action in buy_actions:
                bar = cls.strength_bar(action['signal_strength'], filled='▓', empty='░')
                message += f"• {action['strategy']} {bar} {action['signal_strength']:.0%}\n"
        else:
            message += "• 暂无买入信号\n"

        message += f"\n🔴 **卖出操作: {len(sell_actions)} 个策略**\n"
        if sell_actions:
            for action in sell_actions:
                message += f"• {action['action']}\n"
        else:
            message += "• 暂无卖出信号\n"

        message += "\n━━━━━━━━━━━━━━━━━\n"
        message += f"📈 **全部策略收益排名（共{len(performance)}个）**\n"

        for i, perf in enumerate(performance, 1):
            emoji = "🟢" if perf['pnl_pct'] >= 0 else "🔴"
            message += f"{emoji} {i:2d}. {perf['strategy']:<12s} 收益:{perf['pnl_pct']:+6.2f}%  状态:{perf['position']}  交易:{perf['total_trades']}次  胜率:{perf['win_rate']:.0%}\n"

        holding = [p for p in performance if p['position'] == '持仓']
        message += "\n━━━━━━━━━━━━━━━━━\n"
        message += f"📋 **持仓策略详情（共{len(holding)}个）**\n"

        if holding:
            for perf in holding:
                if perf['shares'] > 0:
                    message += f"• {perf['strategy']}: {perf['shares']}股 @ {perf['avg_price']:.2f}元\n"
                else:
                    message += f"• {perf['strategy']}: 空仓\n"
        else:
            message += "• 暂无持仓策略\n"

        message += "\n━━━━━━━━━━━━━━━━━\n"
        message += "⚠️ **注意**: 本报告仅供模拟跟踪，不构成投资建议"

        return message
