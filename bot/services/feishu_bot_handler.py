"""飞书 Bot 指令处理器 — 融合持仓/信号/日报。

支持飞书群里 @机器人 执行以下指令：
  关注/取消关注 <股票名>  — 管理自选股
  持仓 <股票名> <数量>股 <价格>元 — 添加/更新持仓
  移除持仓 <股票名>
  我的组合 — 查看持仓和信号概览
  信号 <股票名> — 查看单只股票的技术信号
  分析 <股票名> — 综合宏观+技术分析

⚠️ 注意：飞书事件回调是同步的，但 portfolio_manager 是 async。
    使用 _run_async() 工具桥接 async/sync 边界。
"""

import asyncio
import re
from loguru import logger

from services.portfolio_manager import (
    parse_feishu_command, resolve_symbol,
)


def _run_async(coro):
    """在同步上下文中运行 async 协程。

    飞书事件回调是同步的，但 portfolio_manager 已改为 async def。
    此函数通过获取运行中的事件循环或创建新循环来执行协程。
    """
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    if loop.is_running():
        # 已在事件循环中 — 使用 run_coroutine_threadsafe
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result(timeout=30)
    else:
        return loop.run_until_complete(coro)


# ── 懒加载导入（异步） ──
def _get_watchlist():
    from services.portfolio_manager import get_watchlist
    return _run_async(get_watchlist())


def _get_holdings():
    from services.portfolio_manager import get_holdings
    return _run_async(get_holdings())


def _add_watchlist(symbol, name):
    from services.portfolio_manager import add_watchlist
    return _run_async(add_watchlist(symbol, name))


def _remove_watchlist(symbol):
    from services.portfolio_manager import remove_watchlist
    return _run_async(remove_watchlist(symbol))


def _add_holding(symbol, name, shares, price):
    from services.portfolio_manager import add_holding
    return _run_async(add_holding(symbol, name, shares, price))


def _remove_holding(symbol):
    from services.portfolio_manager import remove_holding
    return _run_async(remove_holding(symbol))


def _get_portfolio_summary():
    from services.decision_engine import get_portfolio_summary
    return get_portfolio_summary()


def _analyze_stock(symbol, name):
    from services.decision_engine import analyze_stock
    return analyze_stock(symbol, name)


# ═══ 主入口 ═══


def handle_command(text: str) -> str:
    """处理飞书指令，返回回复文本。"""
    cmd = parse_feishu_command(text)
    action = cmd["action"]
    args = cmd["args"]

    logger.info(f"Feishu command: {action} args='{args}'")

    handlers = {
        "add_watchlist": lambda: _handle_add_watchlist(args),
        "remove_watchlist": lambda: _handle_remove_watchlist(args),
        "add_holding": lambda: _handle_add_holding(args),
        "remove_holding": lambda: _handle_remove_holding(args),
        "portfolio_summary": _handle_portfolio_summary,
        "stock_signals": lambda: _handle_stock_signals(args),
    }

    handler = handlers.get(action)
    if handler:
        return handler()

    return (
        "🤖 **可用指令：**\n\n"
        "📌 **自选股**\n"
        "`关注 比亚迪` — 加入自选股\n"
        "`取消关注 比亚迪` — 移除自选股\n\n"
        "💰 **持仓**\n"
        "`持仓 比亚迪 100股 280元` — 记录持仓\n"
        "`移除持仓 比亚迪` — 删除持仓\n\n"
        "📊 **分析**\n"
        "`我的组合` — 查看持仓概览+信号\n"
        "`信号 比亚迪` — 查看单只股票技术信号\n"
        "`分析 比亚迪` — 综合宏观+技术分析"
    )


# ═══ 指令处理器 ═══


def _handle_add_watchlist(args: str) -> str:
    if not args:
        return "请指定股票名称，如 `关注 比亚迪`"
    symbol, name = resolve_symbol(args)
    result = _add_watchlist(symbol, name)
    if result["success"]:
        watchlist = _get_watchlist()
        return f"✅ 已添加 **{name}** ({symbol}) 到自选股\n📋 当前共 {len(watchlist)} 只自选股"
    return f"❌ 添加失败: {result.get('error', '未知错误')}"


def _handle_remove_watchlist(args: str) -> str:
    if not args:
        return "请指定股票名称，如 `取消关注 比亚迪`"
    symbol, name = resolve_symbol(args)
    result = _remove_watchlist(symbol)
    if result["success"]:
        return f"✅ 已移除 **{name}** ({symbol})"
    return f"❌ 移除失败"


def _handle_add_holding(args: str) -> str:
    """解析 '比亚迪 100股 280元' → 添加持仓"""
    if not args:
        return "格式：`持仓 比亚迪 100股 280元`"

    m = re.match(r'(\S+)\s+(\d+\.?\d*)\s*股\s+(\d+\.?\d*)\s*元', args)
    if not m:
        return "格式错误，正确格式：`持仓 比亚迪 100股 280元`"

    name_raw = m.group(1)
    shares = float(m.group(2))
    price = float(m.group(3))

    symbol, name = resolve_symbol(name_raw)
    result = _add_holding(symbol, name, shares, price)
    if result["success"]:
        total_cost = shares * price
        return (
            f"✅ 持仓已记录\n"
            f"**{name}** ({symbol})\n"
            f"📈 {shares:.0f}股 × {price:.2f}元 = **{total_cost:,.0f}元**"
        )
    return f"❌ 记录失败: {result.get('error', '')}"


def _handle_remove_holding(args: str) -> str:
    if not args:
        return "请指定股票，如 `移除持仓 比亚迪`"
    symbol, name = resolve_symbol(args)
    result = _remove_holding(symbol)
    if result["success"]:
        return f"✅ 已移除 **{name}** 的持仓记录"
    return "❌ 移除失败"


def _handle_portfolio_summary() -> str:
    """生成组合概览文本（异步桥接）。"""
    watchlist = _get_watchlist()
    holdings = _get_holdings()

    if not holdings and not watchlist:
        return "📭 还没有持仓和自选股\n\n可用指令：\n`关注 比亚迪` — 添加自选股\n`持仓 比亚迪 100股 280元` — 记录持仓"

    # 分析所有持仓
    summary = _get_portfolio_summary()
    text_parts = ["## 📊 我的投资组合\n"]

    # 总览
    text_parts.append(
        f"💰 **总投入**: {summary['total_investment']:,.0f}元  "
        f"| **当前市值**: {summary['total_current']:,.0f}元\n"
        f"📈 **总盈亏**: **{'🟢' if summary['total_pnl'] >= 0 else '🔴'} {summary['total_pnl']:+,.0f}元"
        f" ({summary['total_pnl_pct']:+.2f}%)**\n"
        f"⚠️ **集中度**: {summary['concentration_pct']:.0f}% (单股最大占比)\n"
    )

    # 各股分析
    for a in summary.get("stock_analyses", []):
        h = a.get("holding")
        if h:
            icon = "🟢" if h["pnl_pct"] >= 0 else "🔴"
            risk_icon = {"低": "✅", "中": "⚠️", "高": "🔴"}.get(
                a.get("risk", {}).get("vol_risk", "中"), "⚠️"
            )
            text_parts.append(
                f"\n{icon} **{a['name']}** ({a['symbol']})\n"
                f"   当前: {h['current']:.2f} | 成本: {h['cost']:.2f} | "
                f"盈亏: {h['pnl_pct']:+.2f}% ({h['pnl_amount']:+,.0f}元)\n"
                f"   RSI: {a['risk']['rsi']:.0f} | "
                f"波动: {risk_icon}{a['risk']['vol_risk']} | "
                f"支撑: {a['levels']['support']:.0f} | "
                f"阻力: {a['levels']['resistance']:.0f}"
            )

            active_signals = [s for s in a.get("signals", []) if s.get("signal") != 0]
            if active_signals:
                for s in active_signals[:3]:
                    sig_icon = "🟢" if s["signal"] > 0 else "🔴"
                    text_parts.append(f"   {sig_icon} {s['action']} ({s['strategy']})")

    # 自选股（无持仓）
    watchlist_without_holdings = [
        w for w in watchlist
        if not any(h["symbol"] == w["symbol"] for h in holdings)
    ]
    if watchlist_without_holdings:
        text_parts.append(f"\n📋 **关注中** ({len(watchlist_without_holdings)}只)")
        for w in watchlist_without_holdings[:5]:
            text_parts.append(f"   👁️ {w['name']} ({w['symbol']})")

    return "\n".join(text_parts)


def _handle_stock_signals(args: str) -> str:
    """查看单只股票的技术信号。"""
    if not args:
        return "请指定股票，如 `信号 比亚迪`"

    symbol, name = resolve_symbol(args)
    analysis = _analyze_stock(symbol, name)

    if "error" in analysis:
        return f"❌ {analysis['error']}"

    text_parts = [f"## 📈 {analysis['name']} ({analysis['symbol']})\n"]

    current_price = analysis["price"]
    change = analysis.get("change_pct", 0)
    change_icon = "🟢" if change >= 0 else "🔴"

    text_parts.append(
        f"{change_icon} **{current_price:.2f}** ({change:+.2f}%)  "
        f"| 日期: {analysis['date']}\n"
    )

    # 市场状态
    regime = analysis.get("regime", {})
    regime_map = {
        "trending": "📈 趋势", "mean_reverting": "🔁 震荡",
        "volatile": "🌊 高波动", "neutral": "➖ 中性",
        "overbought": "🔴 超买", "oversold": "🟢 超卖",
    }
    regime_label = regime_map.get(regime.get("regime", ""), f"📊 {regime.get('regime', '未知')}")
    text_parts.append(f"📌 **市场状态**: {regime_label}\n")

    # 风险指标
    risk = analysis.get("risk", {})
    rsi = risk.get('rsi', 50)
    rsi_label = "🔴超买" if rsi > 70 else ("🟢超卖" if rsi < 30 else "➖正常")
    text_parts.append(
        f"**技术指标**\n"
        f"RSI: {rsi:.0f} {rsi_label}\n"
        f"波动率(ATR): {risk.get('atr_pct', 0):.2f}% | "
        f"风险等级: {risk.get('vol_risk', '中')}\n"
        f"价格距MA20: {risk.get('ma_distance', 0):+.2f}%\n"
    )

    # 关键价位
    levels = analysis.get("levels", {})
    text_parts.append(
        f"**关键价位**\n"
        f"🟢 支撑: {levels.get('support', 0):.0f}  "
        f"🔴 阻力: {levels.get('resistance', 0):.0f}\n"
        f"📉 MA20: {levels.get('ma_20', 0):.0f}  "
        f"📉 MA60: {levels.get('ma_60', 0):.0f}\n"
    )

    # 信号
    signals = analysis.get("signals", [])
    if signals:
        text_parts.append("**策略信号**\n")
        for s in signals[:5]:
            sig_icon = "🟢" if s["signal"] > 0 else "🔴"
            strength = s.get("signal_strength", 0.5)
            bar = "█" * int(strength * 10) + "░" * (10 - int(strength * 10))
            text_parts.append(f"{sig_icon} {s['action']} | 强度: {bar} ({strength:.0%})")
    else:
        text_parts.append("📭 当前无活跃信号")

    # 持仓信息
    holding = analysis.get("holding")
    if holding:
        pnl_icon = "🟢" if holding["pnl_pct"] >= 0 else "🔴"
        text_parts.append(
            f"\n**持仓**\n"
            f"📦 {holding['shares']:.0f}股 | 成本 {holding['cost']:.2f}\n"
            f"{pnl_icon} 盈亏: {holding['pnl_pct']:+.2f}% ({holding['pnl_amount']:+,.0f}元)"
        )
        if holding["pnl_pct"] < -10:
            text_parts.append(f"\n⚠️ **建议关注止损** — 已亏损超过10%")
        elif holding["pnl_pct"] > 30:
            text_parts.append(f"\n💡 **建议部分止盈** — 已有30%以上收益")

    return "\n".join(text_parts)
