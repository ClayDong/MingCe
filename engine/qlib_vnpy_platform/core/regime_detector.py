import pandas as pd
import numpy as np
from loguru import logger
from qlib_vnpy_platform.core.strategies import get_strategy, STRATEGY_REGISTRY


class MarketRegimeDetector:
    TREND_STRATEGIES = ["ma_cross", "macd", "momentum", "turtle", "dual_thrust", "ma_alignment", "trend_following", "three_soldiers", "support_resistance", "volume_breakout"]
    MEAN_REVERSION_STRATEGIES = ["rsi", "bollinger", "mean_reversion", "kdj", "volatility_breakout", "gap", "obv"]
    ALL_STRATEGIES = list(STRATEGY_REGISTRY.keys())

    def detect(self, df: pd.DataFrame) -> dict:
        if df.empty or len(df) < 60:
            return {
                "regime": "unknown",
                "trend_strength": 0,
                "volatility": 0,
                "recommended_strategies": self.ALL_STRATEGIES,
                "reason": "数据不足，推荐所有策略",
            }

        df = df.copy()
        df["return"] = df["close"].pct_change()

        trend_strength = self._calc_trend_strength(df)
        volatility = self._calc_volatility(df)
        mean_reversion_score = self._calc_mean_reversion_score(df)

        if trend_strength > 0.6 and volatility < 0.03:
            regime = "trending"
            recommended = self.TREND_STRATEGIES
            reason = f"趋势市场（趋势强度={trend_strength:.2f}，波动率={volatility:.4f}），推荐趋势跟踪策略"
        elif mean_reversion_score > 0.6:
            regime = "mean_reverting"
            recommended = self.MEAN_REVERSION_STRATEGIES
            reason = f"震荡市场（均值回归得分={mean_reversion_score:.2f}），推荐均值回归策略"
        elif volatility > 0.03:
            regime = "volatile"
            recommended = ["bollinger", "turtle", "dual_thrust"]
            reason = f"高波动市场（波动率={volatility:.4f}），推荐波动率策略"
        else:
            regime = "neutral"
            recommended = self.ALL_STRATEGIES
            reason = "中性市场，推荐全面验证"

        return {
            "regime": regime,
            "trend_strength": round(trend_strength, 4),
            "volatility": round(volatility, 6),
            "mean_reversion_score": round(mean_reversion_score, 4),
            "recommended_strategies": recommended,
            "reason": reason,
        }

    def _calc_trend_strength(self, df: pd.DataFrame) -> float:
        if len(df) < 20:
            return 0.0

        ma5 = df["close"].rolling(5).mean()
        ma20 = df["close"].rolling(20).mean()
        ma60 = df["close"].rolling(60).mean() if len(df) >= 60 else ma20

        aligned = (ma5 > ma20).astype(int) + (ma20 > ma60).astype(int)
        trend_pct = aligned.mean() / 2.0

        adx = self._calc_adx(df, period=14)

        return (trend_pct + adx) / 2

    def _calc_adx(self, df: pd.DataFrame, period: int = 14) -> float:
        if len(df) < period * 2:
            return 0.0

        high = df["high"]
        low = df["low"]
        close = df["close"]

        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        plus_dm = high.diff()
        minus_dm = low.diff().abs()

        plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0)
        minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0)

        atr = tr.rolling(period).mean()
        plus_di = 100 * (plus_dm.rolling(period).mean() / atr.replace(0, np.inf))
        minus_di = 100 * (minus_dm.rolling(period).mean() / atr.replace(0, np.inf))

        dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.inf)
        adx = dx.rolling(period).mean()

        latest_adx = adx.iloc[-1] if not adx.empty else 0
        return min(latest_adx / 100, 1.0) if pd.notna(latest_adx) else 0.0

    def _calc_volatility(self, df: pd.DataFrame) -> float:
        if len(df) < 20:
            return 0.0

        returns = df["return"].dropna()
        if len(returns) < 20:
            return 0.0

        recent_vol = returns.tail(20).std()
        return recent_vol

    def _calc_mean_reversion_score(self, df: pd.DataFrame) -> float:
        if len(df) < 20:
            return 0.0

        returns = df["return"].dropna()
        if len(returns) < 20:
            return 0.0

        recent_returns = returns.tail(20)
        autocorr = recent_returns.autocorr(lag=1)
        if pd.isna(autocorr):
            return 0.0

        score = max(0, -autocorr)

        hurst = self._calc_hurst(df["close"].tail(100))
        if hurst < 0.5:
            score = max(score, (0.5 - hurst) * 2)

        return min(score, 1.0)

    def _calc_hurst(self, series: pd.Series) -> float:
        if len(series) < 100:
            return 0.5

        lags = range(2, min(20, len(series) // 2))
        tau = []
        lag_vals = []

        for lag in lags:
            diff = series.diff(lag).dropna()
            if len(diff) > 0 and diff.std() > 0:
                tau.append(np.log(diff.std()))
                lag_vals.append(np.log(lag))

        if len(tau) < 2:
            return 0.5

        try:
            poly = np.polyfit(lag_vals, tau, 1)
            return poly[0] / 2
        except Exception:
            return 0.5


class StrategySelector:
    def __init__(self):
        self.detector = MarketRegimeDetector()

    def select_best(self, df: pd.DataFrame, backtest_results: list,
                    top_n: int = 3) -> list:
        regime = self.detector.detect(df)
        recommended = regime["recommended_strategies"]

        filtered = []
        for r in backtest_results:
            if "error" in r:
                continue
            strategy_key = r["strategy"].get("key", "")
            m = r.get("metrics", {})

            score = self._calc_composite_score(m, strategy_key in recommended)

            filtered.append({
                "strategy": r["strategy"],
                "metrics": m,
                "regime_match": strategy_key in recommended,
                "composite_score": round(score, 4),
                "regime_info": regime,
            })

        filtered.sort(key=lambda x: x["composite_score"], reverse=True)
        return filtered[:top_n]

    def _calc_composite_score(self, metrics: dict, regime_match: bool) -> float:
        sharpe = metrics.get("sharpe_ratio", 0)
        total_return = metrics.get("total_return", 0)
        max_dd = metrics.get("max_drawdown", 100)
        win_rate = metrics.get("win_rate", 0)
        profit_factor = metrics.get("profit_factor", 0)

        sharpe_score = max(0, min(sharpe / 3, 1)) * 30
        return_score = max(0, min(total_return / 50, 1)) * 20
        dd_score = max(0, 1 - max_dd / 50) * 25
        win_score = (win_rate / 100) * 15
        pf_score = max(0, min(profit_factor / 3, 1)) * 10

        regime_bonus = 10 if regime_match else 0

        return sharpe_score + return_score + dd_score + win_score + pf_score + regime_bonus
