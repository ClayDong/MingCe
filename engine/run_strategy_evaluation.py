"""策略回测评估脚本 — 跑全部策略并统计胜率/夏普/最大回撤。

用法:
    cd engine
    python run_strategy_evaluation.py [--symbols SH600519,SZ002594] [--days 365]

输出:
    - 控制台表格：每策略的胜率/夏普/最大回撤/总收益
    - JSON 报告：docs/reviews/strategy-backtest-report.json
    - Markdown 报告：docs/reviews/strategy-backtest-report.md
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import numpy as np
from loguru import logger

# 确保能 import qlib_vnpy_platform
sys.path.insert(0, str(Path(__file__).parent))

from qlib_vnpy_platform.core.strategies import list_strategies, get_strategy
from qlib_vnpy_platform.core.backtest import BacktestEngine
from qlib_vnpy_platform.core.regime_detector import MarketRegimeDetector


def fetch_stock_data(symbol: str, days: int = 365) -> pd.DataFrame:
    """获取股票历史数据（新浪 + 腾讯回退）"""
    import json as _json
    import urllib.request
    import ssl
    from datetime import date, timedelta

    end = date.today()
    start = end - timedelta(days=days)

    # 转换代码格式
    if symbol.startswith("SZ"):
        sina_symbol = f"sz{symbol[2:]}"
    elif symbol.startswith("SH"):
        sina_symbol = f"sh{symbol[2:]}"
    elif symbol.startswith("BJ"):
        sina_symbol = f"bj{symbol[2:]}"
    else:
        sina_symbol = f"sh{symbol}" if symbol.startswith("6") else f"sz{symbol}"

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    df = pd.DataFrame()

    # 源1: 新浪
    try:
        url = (
            f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
            f"CN_MarketData.getKLineData?symbol={sina_symbol}"
            f"&scale=240&ma=5&datalen={min(days, 1024)}"
        )
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
            "Referer": "https://finance.sina.com.cn/",
        })
        resp = urllib.request.urlopen(req, timeout=15, context=ctx)
        raw = resp.read().decode("utf-8")
        records = _json.loads(raw)
        if records and isinstance(records, list):
            rows = [{
                "date": r["day"], "open": float(r["open"]), "close": float(r["close"]),
                "high": float(r["high"]), "low": float(r["low"]),
                "volume": float(r.get("volume", 0)),
            } for r in records]
            if rows:
                df = pd.DataFrame(rows)
                df["date"] = pd.to_datetime(df["date"])
                df = df.sort_values("date")
                df["symbol"] = symbol
                logger.info(f"✅ {symbol}: 新浪获取 {len(df)} 行")
                return df
    except Exception as e:
        logger.debug(f"新浪失败 {symbol}: {e}")

    # 源2: 腾讯
    try:
        tenc_symbol = sina_symbol
        end_str = end.strftime("%Y%m%d")
        start_str = start.strftime("%Y%m%d")
        url = f"https://web.ifzg.gtimg.cn/appstock/app/fqkline/get?param={tenc_symbol},day,{start_str},{end_str},365,qfq"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=15, context=ctx)
        raw = resp.read().decode("utf-8")
        data = _json.loads(raw)
        kline = data.get("data", {}).get(tenc_symbol, {}).get("day", [])
        if kline:
            rows = [{
                "date": item[0], "open": float(item[1]), "close": float(item[2]),
                "high": float(item[3]), "low": float(item[4]), "volume": float(item[5]),
            } for item in kline]
            df = pd.DataFrame(rows)
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date")
            df["symbol"] = symbol
            logger.info(f"✅ {symbol}: 腾讯获取 {len(df)} 行")
    except Exception as e:
        logger.debug(f"腾讯失败 {symbol}: {e}")

    return df


def evaluate_strategy(strategy, df: pd.DataFrame, engine: BacktestEngine) -> dict:
    """评估单个策略"""
    try:
        result = engine.run(df, strategy, symbol=df["symbol"].iloc[0] if "symbol" in df.columns else "UNKNOWN")
        if "error" in result:
            return {"strategy": strategy.name, "error": result["error"]}

        metrics = result.get("metrics", {})
        return {
            "strategy": strategy.name,
            "strategy_key": getattr(strategy, "key", ""),
            "total_return_pct": round(metrics.get("total_return", 0) * 100, 2),
            "win_rate_pct": round(metrics.get("win_rate", 0), 2),
            "sharpe_ratio": round(metrics.get("sharpe_ratio", 0), 3),
            "max_drawdown_pct": round(metrics.get("max_drawdown", 0), 2),
            "profit_factor": round(metrics.get("profit_factor", 0), 2),
            "total_trades": metrics.get("total_trades", 0),
            "avg_holding_days": round(metrics.get("avg_holding_days", 0), 1),
        }
    except Exception as e:
        return {"strategy": strategy.name, "error": str(e)}


def run_evaluation(symbols: list[str], days: int = 365) -> dict:
    """跑全部策略 × 全部股票的回测"""
    engine = BacktestEngine(initial_capital=100000)
    detector = MarketRegimeDetector()

    all_results = {}
    regime_info = {}

    for symbol in symbols:
        logger.info(f"\n{'='*60}\n回测 {symbol}\n{'='*60}")
        df = fetch_stock_data(symbol, days)
        if df.empty:
            logger.warning(f"❌ {symbol} 无数据，跳过")
            continue

        # 市场状态检测
        regime = detector.detect(df)
        regime_info[symbol] = regime
        logger.info(f"市场状态: {regime['regime']} - {regime['reason']}")

        # 跑全部策略
        symbol_results = []
        for strat_info in list_strategies():
            try:
                strategy = get_strategy(strat_info["key"])
                eval_result = evaluate_strategy(strategy, df, engine)
                eval_result["symbol"] = symbol
                eval_result["regime_match"] = strat_info["key"] in regime.get("recommended_strategies", [])
                symbol_results.append(eval_result)
                if "error" not in eval_result:
                    logger.info(
                        f"  {strategy.name}: 收益={eval_result['total_return_pct']}% "
                        f"胜率={eval_result['win_rate_pct']}% "
                        f"夏普={eval_result['sharpe_ratio']} "
                        f"回撤={eval_result['max_drawdown_pct']}%"
                    )
            except Exception as e:
                logger.error(f"  {strat_info.get('name', 'unknown')} 失败: {e}")
                symbol_results.append({
                    "strategy": strat_info.get("name", ""),
                    "strategy_key": strat_info.get("key", ""),
                    "symbol": symbol,
                    "error": str(e),
                })

        all_results[symbol] = symbol_results

    return {"results": all_results, "regime_info": regime_info, "evaluated_at": datetime.now().isoformat()}


def generate_report(eval_data: dict, output_dir: Path) -> tuple[Path, Path]:
    """生成 JSON + Markdown 报告"""
    output_dir.mkdir(parents=True, exist_ok=True)

    # JSON 报告
    json_path = output_dir / "strategy-backtest-report.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(eval_data, f, ensure_ascii=False, indent=2, default=str)

    # Markdown 报告
    md_path = output_dir / "strategy-backtest-report.md"
    lines = [
        "# 策略回测评估报告",
        "",
        f"> **评估时间**: {eval_data['evaluated_at']}",
        f"> **评估范围**: {len(eval_data['results'])} 只股票 × 全部策略",
        "",
        "## 一、市场状态检测",
        "",
        "| 股票 | 市场状态 | 趋势强度 | 波动率 | 推荐策略类型 |",
        "|:-----|:--------:|:--------:|:------:|:------------|",
    ]

    for symbol, regime in eval_data.get("regime_info", {}).items():
        lines.append(
            f"| {symbol} | {regime.get('regime', '-')} | "
            f"{regime.get('trend_strength', 0)} | "
            f"{regime.get('volatility', 0)} | "
            f"{', '.join(regime.get('recommended_strategies', [])[:3])} |"
        )

    lines.extend(["", "## 二、策略表现汇总", ""])

    for symbol, results in eval_data["results"].items():
        lines.append(f"### {symbol}")
        lines.append("")
        lines.append("| 策略 | 总收益% | 胜率% | 夏普 | 最大回撤% | 盈亏比 | 交易次数 | 状态匹配 |")
        lines.append("|:-----|:-------:|:-----:|:----:|:---------:|:------:|:--------:|:--------:|")

        # 按夏普排序
        valid_results = [r for r in results if "error" not in r]
        valid_results.sort(key=lambda x: x.get("sharpe_ratio", 0), reverse=True)

        for r in valid_results:
            regime_match = "✅" if r.get("regime_match") else "❌"
            lines.append(
                f"| {r['strategy']} | {r['total_return_pct']} | {r['win_rate_pct']} | "
                f"{r['sharpe_ratio']} | {r['max_drawdown_pct']} | {r['profit_factor']} | "
                f"{r['total_trades']} | {regime_match} |"
            )

        # 错误的策略
        errors = [r for r in results if "error" in r]
        if errors:
            lines.append("")
            lines.append("**失败的策略:**")
            for r in errors:
                lines.append(f"- {r['strategy']}: {r['error']}")

        lines.append("")

    # 总结
    lines.extend([
        "## 三、关键发现",
        "",
        "1. **高夏普策略**（夏普>1）: 适合实盘参考",
        "2. **高胜率策略**（胜率>55%）: 适合稳健配置",
        "3. **低回撤策略**（回撤<10%）: 适合风险敏感型",
        "4. **状态匹配策略**: 与当前市场状态匹配，优先考虑",
        "",
        "## 四、使用建议",
        "",
        "- 信号融合时，按夏普比率动态加权（夏普越高权重越大）",
        "- 剔除夏普<0 或 胜率<40% 的策略",
        "- 市场状态变化时，切换推荐策略组",
        "",
        "---",
        f"*报告由明策策略评估系统自动生成 · {eval_data['evaluated_at']}*",
    ])

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return json_path, md_path


def main():
    parser = argparse.ArgumentParser(description="策略回测评估")
    parser.add_argument("--symbols", default="SH600519,SZ002594,SZ300750",
                        help="股票代码，逗号分隔")
    parser.add_argument("--days", type=int, default=365, help="回测天数")
    parser.add_argument("--output", default=str(Path(__file__).parent.parent / "docs" / "reviews"),
                        help="输出目录")
    args = parser.parse_args()

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    logger.info(f"开始策略回测评估: {symbols}, 天数={args.days}")

    eval_data = run_evaluation(symbols, args.days)

    output_dir = Path(args.output)
    json_path, md_path = generate_report(eval_data, output_dir)

    logger.info(f"\n✅ 评估完成!")
    logger.info(f"📄 JSON 报告: {json_path}")
    logger.info(f"📄 Markdown 报告: {md_path}")

    # 打印汇总
    print("\n" + "="*80)
    print("策略回测评估汇总")
    print("="*80)
    for symbol, results in eval_data["results"].items():
        print(f"\n【{symbol}】")
        valid = [r for r in results if "error" not in r]
        valid.sort(key=lambda x: x.get("sharpe_ratio", 0), reverse=True)
        print(f"{'策略':<20} {'收益%':>8} {'胜率%':>8} {'夏普':>8} {'回撤%':>8} {'匹配':>6}")
        print("-" * 70)
        for r in valid[:10]:  # Top 10
            match = "✅" if r.get("regime_match") else "❌"
            print(f"{r['strategy']:<20} {r['total_return_pct']:>8} "
                  f"{r['win_rate_pct']:>8} {r['sharpe_ratio']:>8} "
                  f"{r['max_drawdown_pct']:>8} {match:>6}")


if __name__ == "__main__":
    main()
