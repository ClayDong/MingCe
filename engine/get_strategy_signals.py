#!/usr/bin/env python3
"""
策略信号获取入口 — 供 market-daily-bot 通过 subprocess 调用。
输出纯 JSON 到 stdout，所有日志输出到 stderr。

用法:
  python get_strategy_signals.py SZ002594
  python get_strategy_signals.py SZ002594,SH600519,SZ300750
  python get_strategy_signals.py --list  # 列出所有自选股及其信号
"""
import sys
import json
from pathlib import Path

# 重定向 print 到 stderr（MakingMoney 内部会有大量 print）
_original_print = print
def _print_to_stderr(*args, **kwargs):
    kwargs.setdefault("file", sys.stderr)
    _original_print(*args, **kwargs)
builtins = __import__("builtins")
builtins.print = _print_to_stderr

# 确保可以从项目根目录导入
PROJECT_ROOT = str(Path(__file__).parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from datetime import datetime


def format_signals(symbol: str, stock_name: str = "") -> dict:
    """对单只股票运行策略分析，返回格式化信号"""
    from qlib_vnpy_platform.strategy_monitor_pkg import BaseMonitor

    monitor = BaseMonitor(symbol=symbol, stock_name=stock_name or symbol)
    data = monitor.fetch_latest_data(symbol=symbol, days=60)
    if data is None or data.empty:
        return {"symbol": symbol, "stock_name": stock_name or symbol, "error": "无法获取数据"}

    change, change_pct, latest_price, latest_date = monitor.compute_change(data)
    results, signals = monitor.run_strategy_analysis(data)
    buy_signals, sell_signals, hold_signals = monitor.classify_signals(results)

    return {
        "symbol": symbol,
        "stock_name": stock_name or symbol,
        "date": str(latest_date),
        "price": float(latest_price),
        "change": float(change),
        "change_pct": float(change_pct),
        "total_strategies": len(results),
        "buy_count": len(buy_signals),
        "sell_count": len(sell_signals),
        "hold_count": len(hold_signals),
        "buy_signals": list(buy_signals.values()),
        "sell_signals": list(sell_signals.values()),
        "hold_signals": list(hold_signals.values()),
        "all_signals": {k: {"strategy_name": v.get("strategy_name"), "action": v.get("action"), "signal_value": v.get("signal_value"), "signal_strength": v.get("signal_strength"), "price": v.get("price")} for k, v in results.items()},
    }


def list_all_signals() -> dict:
    """获取所有自选股的信号（从 database 读取自选股列表）"""
    symbols = []

    # 尝试加载 market-daily-bot 的自选股
    portfolio_db = Path(PROJECT_ROOT).parent / "news/market-daily-bot/data/portfolio.db"
    if portfolio_db.exists():
        try:
            import sqlite3
            conn = sqlite3.connect(str(portfolio_db))
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT symbol, name FROM watchlist WHERE active = 1"
            ).fetchall()
            symbols = [dict(r) for r in rows]
            conn.close()
        except Exception as e:
            sys.stderr.write(f"⚠️ 无法读取自选股数据库: {e}\n")

    if not symbols:
        # 默认自选股列表
        symbols = [
            {"symbol": "SZ002594", "name": "比亚迪"},
            {"symbol": "SH600519", "name": "贵州茅台"},
            {"symbol": "SZ300750", "name": "宁德时代"},
        ]

    results = {}
    for item in symbols:
        sym = item["symbol"]
        name = item["name"]
        results[sym] = format_signals(sym, name)

    return {
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "symbols": results,
        "total_symbols": len(symbols),
    }


def main():
    args = sys.argv[1:]

    if not args or args[0] == "--list":
        result = list_all_signals()
        # 纯 JSON 输出到 stdout（所有 print 已重定向到 stderr）
        sys.stdout.write(json.dumps(result, ensure_ascii=False))
        return

    # 单个或多个股票
    symbols_and_names = []
    for arg in args:
        if "," in arg:
            for s in arg.split(","):
                s = s.strip()
                if s:
                    symbols_and_names.append(s)
        else:
            symbols_and_names.append(arg)

    if len(symbols_and_names) == 1:
        result = format_signals(symbols_and_names[0])
    else:
        result = {"results": [format_signals(s) for s in symbols_and_names]}
    sys.stdout.write(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
