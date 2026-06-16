#!/usr/bin/env python3
import sys
import os
import json
import argparse
import pandas as pd
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from qlib_vnpy_platform.config import load_config
from qlib_vnpy_platform.core.main_engine import MainEngine


def cmd_analyze(engine, args):
    symbols = args.symbols.split(",") if args.symbols else []
    if not symbols:
        print("Error: Please specify symbols with -s, e.g. -s SZ000001,SH600000")
        return

    for symbol in symbols:
        print(f"\n{'='*60}")
        print(f"  Analyzing: {symbol}")
        print(f"{'='*60}")

        result = engine.analyze_stock(
            symbol=symbol,
            use_llm=not args.no_llm,
            use_qlib=not args.no_qlib,
        )

        md = result.get("market_data", {})
        if md:
            print(f"\n  [Market Data]")
            print(f"    Price: {md.get('price', 'N/A')}")
            print(f"    Change: {md.get('change_pct', 'N/A')}%")
            print(f"    Volume: {md.get('volume', 'N/A')}")
            if md.get("ma5"):
                print(f"    MA5: {md['ma5']:.2f}")
            if md.get("ma20"):
                print(f"    MA20: {md['ma20']:.2f}")
            if md.get("rsi"):
                print(f"    RSI: {md['rsi']:.2f}")

        qlib_pred = result.get("qlib_pred")
        if qlib_pred is not None:
            print(f"\n  [QLib Prediction]")
            print(f"    Score: {qlib_pred:.4f}")
            direction = "看涨" if qlib_pred > 0.6 else ("看跌" if qlib_pred < 0.4 else "中性")
            print(f"    Direction: {direction}")

        llm = result.get("llm_result")
        if llm:
            print(f"\n  [LLM Analysis]")
            print(f"    Signal: {llm.get('signal', 'N/A')}")
            print(f"    Confidence: {llm.get('confidence', 0):.2f}")
            print(f"    Risk Level: {llm.get('risk_level', 'N/A')}")
            print(f"    Reason: {llm.get('reason', 'N/A')}")
            if llm.get("target_price"):
                print(f"    Target: {llm['target_price']}")
            if llm.get("stop_loss"):
                print(f"    Stop Loss: {llm['stop_loss']}")
            if llm.get("key_factors"):
                print(f"    Key Factors: {', '.join(llm['key_factors'])}")

        signal = result.get("signal")
        if signal:
            print(f"\n  [Final Signal]")
            print(f"    Direction: {signal['direction']}")
            print(f"    Score: {signal['score']:.4f}")
            print(f"    Confidence: {signal['confidence']:.4f}")

        risk = result.get("risk_check")
        if risk:
            print(f"\n  [Risk Check]")
            print(f"    Approved: {risk.get('approved', 'N/A')}")
            if risk.get("reason"):
                print(f"    Reason: {risk['reason']}")

        trade = result.get("trade_result")
        if trade and trade.get("status") == "FILLED":
            t = trade["trade"]
            print(f"\n  [Trade Executed]")
            print(f"    {t['direction']} {t['symbol']} {t['volume']}@{t['price']:.2f}")
            print(f"    Commission: {t['commission']:.2f}")

        print()


def cmd_status(engine, args):
    status = engine.get_status()
    print(f"\n{'='*60}")
    print(f"  Platform Status")
    print(f"{'='*60}")
    print(f"\n  [Account]")
    print(f"    Total Capital: {status['account']['total_capital']:,.2f}")
    print(f"    Cash: {status['account']['cash']:,.2f}")
    print(f"    Position Value: {status['account']['position_value']:,.2f}")
    print(f"    Total P&L: {status['account']['total_pnl']:,.2f} ({status['account']['total_pnl_pct']:.2%})")

    positions = status.get("positions", {})
    if positions:
        print(f"\n  [Positions]")
        for sym, pos in positions.items():
            pnl = (pos["current_price"] - pos["avg_cost"]) * pos["volume"]
            print(f"    {sym}: {pos['volume']} shares @ {pos['avg_cost']:.2f}, "
                  f"current={pos['current_price']:.2f}, P&L={pnl:+,.2f}")

    risk = status.get("risk_status", {})
    print(f"\n  [Risk Status]")
    print(f"    Risk Level: {risk.get('risk_level', 'N/A')}")
    print(f"    Circuit Breaker: {'ACTIVE' if risk.get('circuit_breaker_active') else 'Inactive'}")
    print(f"    Daily P&L: {risk.get('daily_pnl', 0):,.2f}")

    trades = status.get("recent_trades", [])
    if trades:
        print(f"\n  [Recent Trades]")
        for t in trades[-5:]:
            print(f"    {t['timestamp'][:19]} {t['direction']} {t['symbol']} "
                  f"{t['volume']}@{t['price']:.2f}")

    llm = status.get("llm_stats", {})
    print(f"\n  [LLM Stats]")
    print(f"    Total Calls: {llm.get('total_calls', 0)}")
    print(f"    Total Tokens: {llm.get('total_tokens', 0)}")

    print(f"\n  [Watch List] {status.get('watch_list', [])}")
    print()


def cmd_watch(engine, args):
    symbols = args.symbols.split(",") if args.symbols else []
    for s in symbols:
        engine.add_stock(s)
    print(f"Watch list updated: {engine._watch_list}")


def cmd_data(engine, args):
    symbol = args.symbol
    days = args.days or 30

    df = engine.data_bridge.fetch_stock_daily(symbol, days=days)
    if df.empty:
        print(f"No data for {symbol}")
        return

    df = engine.data_bridge.calc_technical_indicators(df)

    print(f"\n  Historical Data: {symbol} (last {len(df)} days)")
    print(f"  {'Date':>12} {'Open':>8} {'High':>8} {'Low':>8} {'Close':>8} "
          f"{'Volume':>12} {'MA5':>8} {'RSI':>6}")
    print(f"  {'-'*80}")

    for _, row in df.tail(20).iterrows():
        ma5 = f"{row['ma5']:.2f}" if not pd.isna(row.get('ma5')) else "N/A"
        rsi = f"{row['rsi']:.1f}" if not pd.isna(row.get('rsi')) else "N/A"
        print(f"  {str(row['date'])[:10]:>12} {row['open']:>8.2f} {row['high']:>8.2f} "
              f"{row['low']:>8.2f} {row['close']:>8.2f} {row['volume']:>12,.0f} "
              f"{ma5:>8} {rsi:>6}")
    print()


def cmd_backtest(engine, args):
    symbol = args.symbol
    days = args.days or 365

    print(f"\n  Running backtest for {symbol} (last {days} days)...")
    df = engine.data_bridge.fetch_stock_daily(symbol, days=days)
    if df.empty:
        print(f"No data for {symbol}")
        return

    df = engine.data_bridge.calc_technical_indicators(df)

    capital = 1000000.0
    position = 0
    entry_price = 0
    trades = []
    total_pnl = 0

    for i in range(60, len(df)):
        row = df.iloc[i]
        prev_row = df.iloc[i-1]

        if pd.isna(row.get("ma5")) or pd.isna(row.get("ma20")):
            continue

        price = row["close"]

        if position == 0:
            if row["ma5"] > row["ma20"] and prev_row["ma5"] <= prev_row["ma20"]:
                shares = int(capital * 0.3 / price / 100) * 100
                if shares > 0:
                    cost = shares * price * 1.0003
                    capital -= cost
                    position = shares
                    entry_price = price
                    trades.append({"type": "BUY", "date": str(row["date"])[:10],
                                  "price": price, "volume": shares})
        else:
            if row["ma5"] < row["ma20"] and prev_row["ma5"] >= prev_row["ma20"]:
                revenue = position * price * 0.9997
                pnl = (price - entry_price) * position - position * price * 0.0006
                capital += revenue
                total_pnl += pnl
                trades.append({"type": "SELL", "date": str(row["date"])[:10],
                              "price": price, "volume": position, "pnl": pnl})
                position = 0
                entry_price = 0

    if position > 0:
        last_price = df.iloc[-1]["close"]
        capital += position * last_price * 0.9997
        position = 0

    total_return = (capital - 1000000) / 1000000

    print(f"\n  [Backtest Results] {symbol}")
    print(f"    Initial Capital: 1,000,000.00")
    print(f"    Final Capital: {capital:,.2f}")
    print(f"    Total Return: {total_return:.2%}")
    print(f"    Total Trades: {len(trades)}")
    print(f"    Winning Trades: {sum(1 for t in trades if t.get('pnl', 0) > 0)}")
    print(f"    Losing Trades: {sum(1 for t in trades if t.get('pnl', 0) < 0)}")

    if trades:
        print(f"\n  [Trade Details]")
        for t in trades[-10:]:
            pnl_str = f", P&L={t['pnl']:+,.2f}" if 'pnl' in t else ""
            print(f"    {t['date']} {t['type']} {t['volume']}@{t['price']:.2f}{pnl_str}")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="QLib+VNPY Quantitative Trading Platform",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    p_analyze = subparsers.add_parser("analyze", help="Analyze stocks")
    p_analyze.add_argument("-s", "--symbols", help="Stock symbols (comma separated)")
    p_analyze.add_argument("--no-llm", action="store_true", help="Skip LLM analysis")
    p_analyze.add_argument("--no-qlib", action="store_true", help="Skip QLib prediction")

    p_status = subparsers.add_parser("status", help="Show platform status")

    p_watch = subparsers.add_parser("watch", help="Manage watch list")
    p_watch.add_argument("-s", "--symbols", help="Stock symbols to add")

    p_data = subparsers.add_parser("data", help="Show stock data")
    p_data.add_argument("symbol", help="Stock symbol")
    p_data.add_argument("-d", "--days", type=int, help="Number of days")

    p_backtest = subparsers.add_parser("backtest", help="Run simple backtest")
    p_backtest.add_argument("symbol", help="Stock symbol")
    p_backtest.add_argument("-d", "--days", type=int, help="Number of days")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    load_config()
    engine = MainEngine()

    commands = {
        "analyze": cmd_analyze,
        "status": cmd_status,
        "watch": cmd_watch,
        "data": cmd_data,
        "backtest": cmd_backtest,
    }

    if args.command in commands:
        commands[args.command](engine, args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
