"""决策引擎 — 融合 News 宏观数据与 MakingMoney 策略信号。

核心流程：
1. 从 PortfolioManager 获取自选股 + 持仓
2. 获取个股历史数据（使用 akshare）
3. 运行 MakingMoney 策略库
4. 结合 News 宏观信号
5. 输出综合买卖建议

供 Feishu Bot 和日报系统调用。
"""

import sys
import os
import json
import time
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, date, timedelta
from typing import Optional
from loguru import logger

# MakingMoney 导入
_MAKINGMONEY_PATH = Path(os.environ.get("MAKINGMONEY_DIR", Path(__file__).resolve().parent.parent.parent))
if str(_MAKINGMONEY_PATH) not in sys.path:
    sys.path.insert(0, str(_MAKINGMONEY_PATH))

try:
    from qlib_vnpy_platform.core.strategies import get_strategy, STRATEGY_REGISTRY
    from qlib_vnpy_platform.core.regime_detector import MarketRegimeDetector, StrategySelector
    from qlib_vnpy_platform.core.backtest import BacktestEngine

    _MAKINGMONEY_AVAILABLE = True
    _ALL_STRATEGY_KEYS = list(STRATEGY_REGISTRY.keys())
    logger.info(f"✅ MakingMoney 策略引擎加载: {len(_ALL_STRATEGY_KEYS)} 个策略")
except ImportError as e:
    _MAKINGMONEY_AVAILABLE = False
    _ALL_STRATEGY_KEYS = []
    logger.warning(f"⚠️ MakingMoney 不可用: {e}")


# ═══ 个股数据获取 ═══

def _symbol_to_sina(symbol: str) -> str:
    """将 SZ002594 格式转为新浪格式 sh600519 / sz002594"""
    if symbol.startswith("SZ"):
        return f"sz{symbol[2:]}"
    elif symbol.startswith("SH"):
        return f"sh{symbol[2:]}"
    elif symbol.startswith("BJ"):
        return f"bj{symbol[2:]}"
    else:
        if symbol.startswith("6"):
            return f"sh{symbol}"
        return f"sz{symbol}"


def _symbol_to_tencent(symbol: str) -> str:
    """将 SZ002594 格式转为腾讯格式 sz002594 / sh600519"""
    return _symbol_to_sina(symbol)


def fetch_stock_data(symbol: str, days: int = 365) -> pd.DataFrame:
    """获取个股历史数据（新浪财经 API）。"""
    import json, urllib.request, ssl
    from datetime import date, timedelta

    end = date.today()
    start = end - timedelta(days=days)
    sina_symbol = _symbol_to_sina(symbol)

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    df = pd.DataFrame()

    # ── 源1: 新浪日K线 API ──
    try:
        url = (
            f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
            f"CN_MarketData.getKLineData?symbol={sina_symbol}"
            f"&scale=240&ma=5&datalen={min(days, 1024)}"
        )
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Referer": "https://finance.sina.com.cn/",
        })
        resp = urllib.request.urlopen(req, timeout=15, context=ctx)
        raw = resp.read().decode("utf-8")
        records = json.loads(raw)
        if records and isinstance(records, list):
            rows = []
            for r in records:
                rows.append({
                    "date": r["day"],
                    "open": float(r["open"]),
                    "close": float(r["close"]),
                    "high": float(r["high"]),
                    "low": float(r["low"]),
                    "volume": float(r.get("volume", 0)),
                })
            if rows:
                df = pd.DataFrame(rows)
                df["date"] = pd.to_datetime(df["date"])
                df = df.sort_values("date")
                df["symbol"] = symbol
    except Exception as e:
        logger.debug(f"新浪API失败 {symbol}: {e}")

    # ── 源2: 腾讯日K线 API (备用) ──
    if df.empty:
        try:
            end_str = end.strftime("%Y%m%d")
            start_str = start.strftime("%Y%m%d")
            tenc_symbol = _symbol_to_tencent(symbol)
            url = f"https://web.ifzg.gtimg.cn/appstock/app/fqkline/get?param={tenc_symbol},day,{start_str},{end_str},365,qfq"
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            })
            resp = urllib.request.urlopen(req, timeout=15, context=ctx)
            raw = resp.read().decode("utf-8")
            data = json.loads(raw)
            kline = data.get("data", {}).get(tenc_symbol, {}).get("day", [])
            if kline:
                rows = []
                for item in kline:
                    rows.append({
                        "date": item[0],
                        "open": float(item[1]),
                        "close": float(item[2]),
                        "high": float(item[3]),
                        "low": float(item[4]),
                        "volume": float(item[5]),
                    })
                if rows:
                    df = pd.DataFrame(rows)
                    df["date"] = pd.to_datetime(df["date"])
                    df = df.sort_values("date")
                    df["symbol"] = symbol
        except Exception as e:
            logger.debug(f"腾讯API失败 {symbol}: {e}")

    if df.empty:
        logger.warning(f"❌ {symbol}: 新浪/腾讯均不可用")
        return df

    logger.info(f"✅ {symbol}: {len(df)} 行数据 ({start} ~ {end})")
    return df


def calc_technical_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """计算技术指标（MA, RSI, MACD, Bollinger 等）。"""
    if df.empty:
        return df

    df = df.copy()
    
    # 均线
    for period in [5, 10, 20, 30, 60]:
        df[f"ma_{period}"] = df["close"].rolling(window=period).mean()

    # 均线距离（价格偏离度）
    df["ma_distance"] = (df["close"] / df["ma_20"] - 1) * 100

    # RSI
    delta = df["close"].diff()
    gain = delta.where(delta > 0, 0).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss.replace(0, np.nan)
    df["rsi"] = 100 - (100 / (1 + rs))

    # MACD
    ema12 = df["close"].ewm(span=12).mean()
    ema26 = df["close"].ewm(span=26).mean()
    df["macd"] = ema12 - ema26
    df["macd_signal"] = df["macd"].ewm(span=9).mean()
    df["macd_hist"] = df["macd"] - df["macd_signal"]

    # Bollinger Bands
    df["boll_mid"] = df["close"].rolling(window=20).mean()
    df["boll_std"] = df["close"].rolling(window=20).std()
    df["boll_upper"] = df["boll_mid"] + 2 * df["boll_std"]
    df["boll_lower"] = df["boll_mid"] - 2 * df["boll_std"]
    df["boll_width"] = (df["boll_upper"] - df["boll_lower"]) / df["boll_mid"]

    # ATR
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["close"].shift(1)).abs(),
        (df["low"] - df["close"].shift(1)).abs(),
    ], axis=1).max(axis=1)
    df["atr"] = tr.rolling(window=14).mean()
    df["atr_pct"] = df["atr"] / df["close"] * 100

    # 成交量指标
    df["volume_ma_5"] = df["volume"].rolling(window=5).mean()
    df["volume_ratio"] = df["volume"] / df["volume_ma_5"]
    df["obv"] = (np.sign(df["close"].diff()) * df["volume"]).fillna(0).cumsum()

    return df


# ═══ 策略信号生成 ═══

def generate_signals(df: pd.DataFrame) -> list[dict]:
    """对单只股票运行所有策略，返回信号列表。"""
    if not _MAKINGMONEY_AVAILABLE or df.empty or len(df) < 30:
        # 降级：使用本地技术指标生成信号
        return _generate_fallback_signals(df)

    signals = []
    
    # 市场状态检测
    detector = MarketRegimeDetector()
    regime = detector.detect(df)
    
    # 运行所有策略
    all_strategies = [get_strategy(key) for key in _ALL_STRATEGY_KEYS if get_strategy(key)]
    engine = BacktestEngine()
    results = engine.run_multiple(df, all_strategies, df.get("symbol", "UNKNOWN"))
    
    # 策略选择器
    selector = StrategySelector()
    top_picks = selector.select_best(df, results, top_n=5)
    
    for r in results:
        if "error" in r:
            continue
        ls = r.get("latest_signals", {})
        signal_val = ls.get("signal", 0) if ls else 0
        if signal_val != 0:
            signals.append({
                "strategy": r["strategy"]["name"],
                "strategy_key": r["strategy"].get("key", ""),
                "signal": signal_val,
                "action": "买入" if signal_val > 0 else ("卖出" if signal_val < 0 else "持有"),
                "price": ls.get("close", df.iloc[-1]["close"]) if ls else df.iloc[-1]["close"],
                "signal_strength": ls.get("signal_strength", 0.5) if ls else 0.5,
            })

    return {
        "regime": regime,
        "top_picks": top_picks,
        "signals": signals,
    }


def _generate_fallback_signals(df: pd.DataFrame) -> dict:
    """降级：当 MakingMoney 不可用时使用本地计算。"""
    if df.empty or len(df) < 30:
        return {"regime": {"regime": "unknown"}, "top_picks": [], "signals": []}

    df = calc_technical_indicators(df)
    latest = df.iloc[-1]
    signals = []

    # RSI 信号
    rsi = latest.get("rsi", 50)
    if rsi < 30:
        signals.append({"strategy": "RSI超卖", "strategy_key": "rsi", "signal": 1, "action": "买入（超卖）", "price": latest["close"], "signal_strength": max(0, (30 - rsi) / 30)})
    elif rsi > 70:
        signals.append({"strategy": "RSI超买", "strategy_key": "rsi", "signal": -1, "action": "卖出（超买）", "price": latest["close"], "signal_strength": max(0, (rsi - 70) / 30)})

    # MACD 信号
    macd = latest.get("macd", 0)
    macd_signal = latest.get("macd_signal", 0)
    prev_macd = df.iloc[-2].get("macd", 0) if len(df) >= 2 else 0
    prev_macd_signal = df.iloc[-2].get("macd_signal", 0) if len(df) >= 2 else 0
    
    if prev_macd <= prev_macd_signal and macd > macd_signal:
        signals.append({"strategy": "MACD金叉", "strategy_key": "macd", "signal": 1, "action": "买入（MACD金叉）", "price": latest["close"], "signal_strength": 0.7})
    elif prev_macd >= prev_macd_signal and macd < macd_signal:
        signals.append({"strategy": "MACD死叉", "strategy_key": "macd", "signal": -1, "action": "卖出（MACD死叉）", "price": latest["close"], "signal_strength": 0.7})

    # 均线信号
    ma5 = latest.get("ma_5", 0)
    ma20 = latest.get("ma_20", 0)
    prev_ma5 = df.iloc[-2].get("ma_5", 0) if len(df) >= 2 else 0
    prev_ma20 = df.iloc[-2].get("ma_20", 0) if len(df) >= 2 else 0
    
    if prev_ma5 <= prev_ma20 and ma5 > ma20:
        signals.append({"strategy": "MA5金叉MA20", "strategy_key": "ma_cross", "signal": 1, "action": "买入（均线金叉）", "price": latest["close"], "signal_strength": 0.6})
    elif prev_ma5 >= prev_ma20 and ma5 < ma20:
        signals.append({"strategy": "MA5死叉MA20", "strategy_key": "ma_cross", "signal": -1, "action": "卖出（均线死叉）", "price": latest["close"], "signal_strength": 0.6})

    # Bollinger 信号
    if latest.get("close", 0) < latest.get("boll_lower", 0):
        signals.append({"strategy": "布林带下轨", "strategy_key": "bollinger", "signal": 1, "action": "买入（下轨支撑）", "price": latest["close"], "signal_strength": 0.5})
    elif latest.get("close", 0) > latest.get("boll_upper", 0):
        signals.append({"strategy": "布林带上轨", "strategy_key": "bollinger", "signal": -1, "action": "卖出（上轨压力）", "price": latest["close"], "signal_strength": 0.5})

    # 量价信号
    vol_ratio = latest.get("volume_ratio", 1)
    pct = latest.get("pct_change", 0)
    if vol_ratio > 2 and pct > 3:
        signals.append({"strategy": "放量突破", "strategy_key": "volume_breakout", "signal": 1, "action": "买入（放量突破）", "price": latest["close"], "signal_strength": 0.8})
    elif vol_ratio > 2 and pct < -3:
        signals.append({"strategy": "放量下跌", "strategy_key": "volume_breakout", "signal": -1, "action": "卖出（放量下跌）", "price": latest["close"], "signal_strength": 0.8})

    # 市场状态
    regime_type = "trending"
    if rsi > 70:
        regime_type = "overbought"
    elif rsi < 30:
        regime_type = "oversold"
    
    regime = {
        "regime": regime_type,
        "trend_strength": abs(float(df["ma_distance"].iloc[-1] if "ma_distance" in df.columns else 0)) / 10,
        "volatility": float(df["close"].pct_change().std()),
    }

    return {
        "regime": regime,
        "top_picks": [],
        "signals": signals,
    }


# ═══ 综合决策 ═══

def analyze_stock(symbol: str, name: str = "", macro_data: dict = None) -> dict:
    """综合宏观+技术分析一只股票。"""
    df = fetch_stock_data(symbol)
    if df.empty:
        return {"symbol": symbol, "name": name, "error": "无法获取数据"}
    
    # 技术指标计算
    df = calc_technical_indicators(df)
    latest = df.iloc[-1]
    
    # 策略信号
    signal_result = generate_signals(df)
    
    # 持仓盈亏（如果有）
    from services.portfolio_manager import get_holdings
    holdings = get_holdings()
    holding = next((h for h in holdings if h["symbol"] == symbol), None)
    
    pnl_info = None
    if holding:
        current_price = float(latest["close"])
        cost = float(holding["cost_price"])
        pnl_pct = (current_price - cost) / cost * 100
        pnl_amount = (current_price - cost) * float(holding["shares"])
        pnl_info = {
            "shares": float(holding["shares"]),
            "cost": cost,
            "current": current_price,
            "pnl_pct": round(pnl_pct, 2),
            "pnl_amount": round(pnl_amount, 2),
        }
    
    # 风险判断
    atr_pct = float(latest.get("atr_pct", 0))
    # 波动率风险
    vol_risk = "高" if atr_pct > 4 else ("中" if atr_pct > 2.5 else "低")
    
    return {
        "symbol": symbol,
        "name": name or symbol,
        "date": str(latest.get("date", "")),
        "price": float(latest["close"]),
        "change_pct": float(latest.get("pct_change", 0)),
        "volume": float(latest.get("volume", 0)),
        "regime": signal_result.get("regime", {}),
        "signals": signal_result.get("signals", []),
        "top_picks": signal_result.get("top_picks", []),
        "holding": pnl_info,
        "risk": {
            "atr_pct": round(atr_pct, 2),
            "vol_risk": vol_risk,
            "ma_distance": round(float(latest.get("ma_distance", 0)), 2),
            "rsi": round(float(latest.get("rsi", 50)), 1),
            "boll_width": round(float(latest.get("boll_width", 0)), 3),
        },
        # 关键价位
        "levels": {
            "support": round(float(latest.get("boll_lower", 0)), 2),
            "resistance": round(float(latest.get("boll_upper", 0)), 2),
            "ma_20": round(float(latest.get("ma_20", 0)), 2),
            "ma_60": round(float(latest.get("ma_60", 0)), 2),
        },
        "macro_context": macro_data or {},
    }


def get_portfolio_summary(macro_data: dict = None) -> dict:
    """获取完整持仓概览（含每只持仓信号）。"""
    from services.portfolio_manager import get_holdings, get_watchlist
    
    holdings = get_holdings()
    watchlist = get_watchlist()
    
    total_investment = 0
    total_current = 0
    stock_analyses = []
    
    for h in holdings:
        analysis = analyze_stock(h["symbol"], h["name"], macro_data)
        stock_analyses.append(analysis)
        if analysis.get("holding"):
            total_investment += analysis["holding"]["cost"] * analysis["holding"]["shares"]
            total_current += analysis["holding"]["current"] * analysis["holding"]["shares"]
    
    total_pnl = total_current - total_investment
    total_pnl_pct = (total_pnl / total_investment * 100) if total_investment > 0 else 0
    
    # 计算风险集中度
    if stock_analyses:
        max_position = max(
            (a["holding"]["current"] * a["holding"]["shares"] for a in stock_analyses if a.get("holding")),
            default=0,
        )
        concentration = (max_position / total_current * 100) if total_current > 0 else 0
    else:
        concentration = 0
    
    return {
        "date": str(date.today()),
        "holdings_count": len(holdings),
        "watchlist_count": len(watchlist),
        "total_investment": round(total_investment, 2),
        "total_current": round(total_current, 2),
        "total_pnl": round(total_pnl, 2),
        "total_pnl_pct": round(total_pnl_pct, 2),
        "concentration_pct": round(concentration, 1),
        "stock_analyses": stock_analyses,
    }
