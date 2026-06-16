import pandas as pd
import numpy as np
from abc import ABC, abstractmethod
from datetime import datetime
from loguru import logger


class BaseStrategy(ABC):
    def __init__(self, name: str, params: dict = None):
        self.name = name
        self.params = params or {}
        self.key = ""
        self._signals = []

    @abstractmethod
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        pass

    def get_info(self) -> dict:
        return {
            "name": self.name,
            "params": self.params,
            "description": self.__doc__ or "",
        }

    def _add_signal_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        if "signal" not in df.columns:
            df["signal"] = 0
        if "signal_strength" not in df.columns:
            df["signal_strength"] = 0.0
        return df


class MACrossStrategy(BaseStrategy):
    """均线交叉策略：短期均线上穿长期均线买入，下穿卖出"""

    def __init__(self, short_window: int = 5, long_window: int = 20, **kwargs):
        params = {"short_window": short_window, "long_window": long_window}
        params.update(kwargs)
        super().__init__("MA交叉", params)
        self.short_window = short_window
        self.long_window = long_window

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self._add_signal_columns(df)
        if len(df) < self.long_window + 1:
            return df

        df["ma_short"] = df["close"].rolling(window=self.short_window).mean()
        df["ma_long"] = df["close"].rolling(window=self.long_window).mean()

        for i in range(self.long_window, len(df)):
            prev_diff = df["ma_short"].iloc[i - 1] - df["ma_long"].iloc[i - 1]
            curr_diff = df["ma_short"].iloc[i] - df["ma_long"].iloc[i]

            if prev_diff <= 0 and curr_diff > 0:
                df.iloc[i, df.columns.get_loc("signal")] = 1
                df.iloc[i, df.columns.get_loc("signal_strength")] = min(abs(curr_diff) / df["close"].iloc[i] * 100, 1.0)
            elif prev_diff >= 0 and curr_diff < 0:
                df.iloc[i, df.columns.get_loc("signal")] = -1
                df.iloc[i, df.columns.get_loc("signal_strength")] = min(abs(curr_diff) / df["close"].iloc[i] * 100, 1.0)

        return df


class RSIStrategy(BaseStrategy):
    """RSI超买超卖策略：RSI低于超卖线买入，高于超买线卖出"""

    def __init__(self, period: int = 14, oversold: float = 30, overbought: float = 70, **kwargs):
        params = {"period": period, "oversold": oversold, "overbought": overbought}
        params.update(kwargs)
        super().__init__("RSI超买超卖", params)
        self.period = period
        self.oversold = oversold
        self.overbought = overbought

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self._add_signal_columns(df)
        if len(df) < self.period + 1:
            return df

        delta = df["close"].diff()
        gain = delta.where(delta > 0, 0)
        loss = (-delta).where(delta < 0, 0)
        avg_gain = gain.ewm(alpha=1 / self.period, min_periods=self.period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1 / self.period, min_periods=self.period, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, np.inf)
        df["rsi"] = 100 - (100 / (1 + rs))

        for i in range(self.period, len(df)):
            rsi_val = df["rsi"].iloc[i]
            prev_rsi = df["rsi"].iloc[i - 1]

            if prev_rsi <= self.oversold and rsi_val > self.oversold:
                df.iloc[i, df.columns.get_loc("signal")] = 1
                df.iloc[i, df.columns.get_loc("signal_strength")] = (self.oversold + (50 - self.oversold) / 2 - rsi_val) / 50
            elif prev_rsi >= self.overbought and rsi_val < self.overbought:
                df.iloc[i, df.columns.get_loc("signal")] = -1
                df.iloc[i, df.columns.get_loc("signal_strength")] = (rsi_val - (50 + (self.overbought - 50) / 2)) / 50

            df.iloc[i, df.columns.get_loc("signal_strength")] = max(0, min(1, abs(df.iloc[i, df.columns.get_loc("signal_strength")])))

        return df


class MACDStrategy(BaseStrategy):
    """MACD策略：MACD金叉买入，死叉卖出"""

    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9, **kwargs):
        params = {"fast": fast, "slow": slow, "signal": signal}
        params.update(kwargs)
        super().__init__("MACD金叉死叉", params)
        self.fast = fast
        self.slow = slow
        self.signal_period = signal

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self._add_signal_columns(df)
        if len(df) < self.slow + self.signal_period:
            return df

        ema_fast = df["close"].ewm(span=self.fast, adjust=False).mean()
        ema_slow = df["close"].ewm(span=self.slow, adjust=False).mean()
        df["macd"] = ema_fast - ema_slow
        df["macd_signal"] = df["macd"].ewm(span=self.signal_period, adjust=False).mean()
        df["macd_hist"] = df["macd"] - df["macd_signal"]

        for i in range(self.slow, len(df)):
            prev_hist = df["macd_hist"].iloc[i - 1]
            curr_hist = df["macd_hist"].iloc[i]

            if prev_hist <= 0 and curr_hist > 0:
                df.iloc[i, df.columns.get_loc("signal")] = 1
                df.iloc[i, df.columns.get_loc("signal_strength")] = min(abs(curr_hist) / df["close"].iloc[i] * 10, 1.0)
            elif prev_hist >= 0 and curr_hist < 0:
                df.iloc[i, df.columns.get_loc("signal")] = -1
                df.iloc[i, df.columns.get_loc("signal_strength")] = min(abs(curr_hist) / df["close"].iloc[i] * 10, 1.0)

        return df


class BollingerStrategy(BaseStrategy):
    """布林带策略：价格触及下轨买入，触及上轨卖出"""

    def __init__(self, window: int = 20, num_std: float = 2.0, **kwargs):
        params = {"window": window, "num_std": num_std}
        params.update(kwargs)
        super().__init__("布林带突破", params)
        self.window = window
        self.num_std = num_std

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self._add_signal_columns(df)
        if len(df) < self.window:
            return df

        df["boll_mid"] = df["close"].rolling(window=self.window).mean()
        boll_std = df["close"].rolling(window=self.window).std()
        df["boll_upper"] = df["boll_mid"] + self.num_std * boll_std
        df["boll_lower"] = df["boll_mid"] - self.num_std * boll_std

        for i in range(self.window, len(df)):
            price = df["close"].iloc[i]
            prev_price = df["close"].iloc[i - 1]
            lower = df["boll_lower"].iloc[i]
            upper = df["boll_upper"].iloc[i]

            if prev_price <= lower and price > lower:
                df.iloc[i, df.columns.get_loc("signal")] = 1
                df.iloc[i, df.columns.get_loc("signal_strength")] = min((price - lower) / (boll_std.iloc[i] + 1e-8) * 0.5 + 0.5, 1.0)
            elif prev_price >= upper and price < upper:
                df.iloc[i, df.columns.get_loc("signal")] = -1
                df.iloc[i, df.columns.get_loc("signal_strength")] = min((upper - price) / (boll_std.iloc[i] + 1e-8) * 0.5 + 0.5, 1.0)

        return df


class MomentumStrategy(BaseStrategy):
    """动量策略：N日涨幅为正买入，为负卖出"""

    def __init__(self, lookback: int = 20, buy_threshold: float = 0.05, sell_threshold: float = -0.05, **kwargs):
        params = {"lookback": lookback, "buy_threshold": buy_threshold, "sell_threshold": sell_threshold}
        params.update(kwargs)
        super().__init__("动量策略", params)
        self.lookback = lookback
        self.buy_threshold = buy_threshold
        self.sell_threshold = sell_threshold

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self._add_signal_columns(df)
        if len(df) < self.lookback + 1:
            return df

        df["momentum"] = df["close"].pct_change(self.lookback)

        for i in range(self.lookback, len(df)):
            mom = df["momentum"].iloc[i]
            if mom > self.buy_threshold:
                df.iloc[i, df.columns.get_loc("signal")] = 1
                df.iloc[i, df.columns.get_loc("signal_strength")] = min(mom, 1.0)
            elif mom < self.sell_threshold:
                df.iloc[i, df.columns.get_loc("signal")] = -1
                df.iloc[i, df.columns.get_loc("signal_strength")] = min(abs(mom), 1.0)

        return df


class KDJStrategy(BaseStrategy):
    """KDJ策略：K线上穿D线且J<20买入，K线下穿D线且J>80卖出"""

    def __init__(self, n: int = 9, m1: int = 3, m2: int = 3, **kwargs):
        params = {"n": n, "m1": m1, "m2": m2}
        params.update(kwargs)
        super().__init__("KDJ金叉死叉", params)
        self.n = n
        self.m1 = m1
        self.m2 = m2

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self._add_signal_columns(df)
        if len(df) < self.n:
            return df

        low_min = df["low"].rolling(window=self.n).min()
        high_max = df["high"].rolling(window=self.n).max()
        rsv = (df["close"] - low_min) / (high_max - low_min).replace(0, np.inf) * 100

        df["K"] = rsv.ewm(alpha=1 / self.m1, min_periods=self.m1, adjust=False).mean()
        df["D"] = df["K"].ewm(alpha=1 / self.m2, min_periods=self.m2, adjust=False).mean()
        df["J"] = 3 * df["K"] - 2 * df["D"]

        for i in range(self.n, len(df)):
            prev_k = df["K"].iloc[i - 1]
            curr_k = df["K"].iloc[i]
            prev_d = df["D"].iloc[i - 1]
            curr_d = df["D"].iloc[i]
            j_val = df["J"].iloc[i]

            if prev_k <= prev_d and curr_k > curr_d and j_val < 20:
                df.iloc[i, df.columns.get_loc("signal")] = 1
                df.iloc[i, df.columns.get_loc("signal_strength")] = min((20 - j_val) / 20, 1.0)
            elif prev_k >= prev_d and curr_k < curr_d and j_val > 80:
                df.iloc[i, df.columns.get_loc("signal")] = -1
                df.iloc[i, df.columns.get_loc("signal_strength")] = min((j_val - 80) / 20, 1.0)

        return df


class DualThrustStrategy(BaseStrategy):
    """Dual Thrust策略：基于N日高低价范围突破"""

    def __init__(self, lookback: int = 4, k1: float = 0.5, k2: float = 0.5, **kwargs):
        params = {"lookback": lookback, "k1": k1, "k2": k2}
        params.update(kwargs)
        super().__init__("双轨突破(Dual Thrust)", params)
        self.lookback = lookback
        self.k1 = k1
        self.k2 = k2

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self._add_signal_columns(df)
        if len(df) < self.lookback + 1:
            return df

        df["hh"] = df["high"].rolling(window=self.lookback).max().shift(1)
        df["hc"] = df["close"].rolling(window=self.lookback).max().shift(1)
        df["lc"] = df["close"].rolling(window=self.lookback).min().shift(1)
        df["ll"] = df["low"].rolling(window=self.lookback).min().shift(1)

        df["range"] = pd.concat([df["hh"] - df["lc"], df["hc"] - df["ll"]], axis=1).max(axis=1)
        df["upper_bound"] = df["close"].shift(1) + self.k1 * df["range"]
        df["lower_bound"] = df["close"].shift(1) - self.k2 * df["range"]

        for i in range(self.lookback, len(df)):
            price = df["close"].iloc[i]
            upper = df["upper_bound"].iloc[i]
            lower = df["lower_bound"].iloc[i]

            if pd.notna(upper) and price > upper:
                df.iloc[i, df.columns.get_loc("signal")] = 1
                df.iloc[i, df.columns.get_loc("signal_strength")] = min((price - upper) / (df["range"].iloc[i] + 1e-8), 1.0)
            elif pd.notna(lower) and price < lower:
                df.iloc[i, df.columns.get_loc("signal")] = -1
                df.iloc[i, df.columns.get_loc("signal_strength")] = min((lower - price) / (df["range"].iloc[i] + 1e-8), 1.0)

        return df


class TurtleStrategy(BaseStrategy):
    """海龟交易策略：突破N日最高价买入，跌破M日最低价卖出"""

    def __init__(self, entry_window: int = 20, exit_window: int = 10, atr_period: int = 20, risk_pct: float = 0.02, **kwargs):
        params = {"entry_window": entry_window, "exit_window": exit_window, "atr_period": atr_period, "risk_pct": risk_pct}
        params.update(kwargs)
        super().__init__("海龟交易", params)
        self.entry_window = entry_window
        self.exit_window = exit_window
        self.atr_period = atr_period
        self.risk_pct = risk_pct

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self._add_signal_columns(df)
        if len(df) < max(self.entry_window, self.exit_window, self.atr_period) + 1:
            return df

        df["entry_high"] = df["high"].rolling(window=self.entry_window).max().shift(1)
        df["exit_low"] = df["low"].rolling(window=self.exit_window).min().shift(1)

        tr = pd.concat([
            df["high"] - df["low"],
            (df["high"] - df["close"].shift(1)).abs(),
            (df["low"] - df["close"].shift(1)).abs(),
        ], axis=1).max(axis=1)
        df["atr"] = tr.rolling(window=self.atr_period).mean()

        position = 0
        for i in range(max(self.entry_window, self.exit_window, self.atr_period), len(df)):
            price = df["close"].iloc[i]
            entry_high = df["entry_high"].iloc[i]
            exit_low = df["exit_low"].iloc[i]

            if position <= 0 and pd.notna(entry_high) and price > entry_high:
                df.iloc[i, df.columns.get_loc("signal")] = 1
                df.iloc[i, df.columns.get_loc("signal_strength")] = min((price - entry_high) / (df["atr"].iloc[i] + 1e-8), 1.0)
                position = 1
            elif position >= 0 and pd.notna(exit_low) and price < exit_low:
                df.iloc[i, df.columns.get_loc("signal")] = -1
                df.iloc[i, df.columns.get_loc("signal_strength")] = min((exit_low - price) / (df["atr"].iloc[i] + 1e-8), 1.0)
                position = -1

        return df


class MeanReversionStrategy(BaseStrategy):
    """均值回归策略：价格偏离均线超过阈值时反向操作"""

    def __init__(self, window: int = 20, entry_std: float = 2.0, exit_std: float = 0.5, **kwargs):
        params = {"window": window, "entry_std": entry_std, "exit_std": exit_std}
        params.update(kwargs)
        super().__init__("均值回归", params)
        self.window = window
        self.entry_std = entry_std
        self.exit_std = exit_std

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self._add_signal_columns(df)
        if len(df) < self.window:
            return df

        df["mean"] = df["close"].rolling(window=self.window).mean()
        df["std"] = df["close"].rolling(window=self.window).std()
        df["zscore"] = (df["close"] - df["mean"]) / df["std"].replace(0, np.inf)

        position = 0
        for i in range(self.window, len(df)):
            zscore = df["zscore"].iloc[i]

            if position <= 0 and zscore < -self.entry_std:
                df.iloc[i, df.columns.get_loc("signal")] = 1
                df.iloc[i, df.columns.get_loc("signal_strength")] = min(abs(zscore) / 4, 1.0)
                position = 1
            elif position >= 0 and zscore > self.entry_std:
                df.iloc[i, df.columns.get_loc("signal")] = -1
                df.iloc[i, df.columns.get_loc("signal_strength")] = min(abs(zscore) / 4, 1.0)
                position = -1
            elif position == 1 and zscore > -self.exit_std:
                df.iloc[i, df.columns.get_loc("signal")] = -1
                df.iloc[i, df.columns.get_loc("signal_strength")] = 0.3
                position = 0
            elif position == -1 and zscore < self.exit_std:
                df.iloc[i, df.columns.get_loc("signal")] = 1
                df.iloc[i, df.columns.get_loc("signal_strength")] = 0.3
                position = 0

        return df


class MAAlignmentStrategy(BaseStrategy):
    """均线多头排列策略：短中长期均线多头排列买入，空头排列卖出"""
    def __init__(self, short_window: int = 5, mid_window: int = 20, long_window: int = 60, **kwargs):
        params = {"short_window": short_window, "mid_window": mid_window, "long_window": long_window}
        super().__init__("均线多头排列", params)
        self.short_window = short_window
        self.mid_window = mid_window
        self.long_window = long_window

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self._add_signal_columns(df)
        df["ma_short"] = df["close"].rolling(window=self.short_window).mean()
        df["ma_mid"] = df["close"].rolling(window=self.mid_window).mean()
        df["ma_long"] = df["close"].rolling(window=self.long_window).mean()

        for i in range(1, len(df)):
            if pd.isna(df.iloc[i]["ma_long"]):
                continue
            prev = df.iloc[i - 1]
            curr = df.iloc[i]
            bullish = curr["ma_short"] > curr["ma_mid"] > curr["ma_long"]
            bearish = curr["ma_short"] < curr["ma_mid"] < curr["ma_long"]
            prev_bullish = prev["ma_short"] > prev["ma_mid"] > prev["ma_long"]
            prev_bearish = prev["ma_short"] < prev["ma_mid"] < prev["ma_long"]

            if bullish and not prev_bullish:
                df.iloc[i, df.columns.get_loc("signal")] = 1
                df.iloc[i, df.columns.get_loc("signal_strength")] = 0.8
            elif bearish and not prev_bearish:
                df.iloc[i, df.columns.get_loc("signal")] = -1
                df.iloc[i, df.columns.get_loc("signal_strength")] = 0.8
        return df


class VolumeBreakoutStrategy(BaseStrategy):
    """量价突破策略：放量突破近N日高点买入，缩量跌破低点卖出"""
    def __init__(self, lookback: int = 20, volume_ratio: float = 1.5, **kwargs):
        params = {"lookback": lookback, "volume_ratio": volume_ratio}
        super().__init__("量价突破", params)
        self.lookback = lookback
        self.volume_ratio = volume_ratio

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self._add_signal_columns(df)
        df["highest"] = df["high"].rolling(window=self.lookback).max().shift(1)
        df["lowest"] = df["low"].rolling(window=self.lookback).min().shift(1)
        df["avg_volume"] = df["volume"].rolling(window=self.lookback).mean().shift(1)
        df["vol_ratio"] = df["volume"] / df["avg_volume"].replace(0, 1)

        for i in range(self.lookback + 1, len(df)):
            curr = df.iloc[i]
            if curr["close"] > curr["highest"] and curr["vol_ratio"] > self.volume_ratio:
                df.iloc[i, df.columns.get_loc("signal")] = 1
                df.iloc[i, df.columns.get_loc("signal_strength")] = min(curr["vol_ratio"] / self.volume_ratio, 1.0)
            elif curr["close"] < curr["lowest"] and curr["vol_ratio"] > self.volume_ratio * 0.8:
                df.iloc[i, df.columns.get_loc("signal")] = -1
                df.iloc[i, df.columns.get_loc("signal_strength")] = min(curr["vol_ratio"] / self.volume_ratio, 1.0)
        return df


class VolatilityBreakoutStrategy(BaseStrategy):
    """波动率突破策略：价格突破布林带宽度的一定比例时交易"""
    def __init__(self, bb_window: int = 20, bb_std: float = 2.0, breakout_pct: float = 0.5, **kwargs):
        params = {"bb_window": bb_window, "bb_std": bb_std, "breakout_pct": breakout_pct}
        super().__init__("波动率突破", params)
        self.bb_window = bb_window
        self.bb_std = bb_std
        self.breakout_pct = breakout_pct

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self._add_signal_columns(df)
        df["bb_mid"] = df["close"].rolling(window=self.bb_window).mean()
        df["bb_std_val"] = df["close"].rolling(window=self.bb_window).std()
        df["bb_upper"] = df["bb_mid"] + self.bb_std * df["bb_std_val"]
        df["bb_lower"] = df["bb_mid"] - self.bb_std * df["bb_std_val"]
        df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / df["bb_mid"].replace(0, 1)

        for i in range(self.bb_window, len(df)):
            curr = df.iloc[i]
            prev = df.iloc[i - 1]
            if pd.isna(curr["bb_upper"]):
                continue
            upper_target = curr["bb_upper"] + (curr["bb_upper"] - curr["bb_lower"]) * self.breakout_pct
            lower_target = curr["bb_lower"] - (curr["bb_upper"] - curr["bb_lower"]) * self.breakout_pct

            if curr["close"] > upper_target and prev["close"] <= upper_target:
                df.iloc[i, df.columns.get_loc("signal")] = 1
                df.iloc[i, df.columns.get_loc("signal_strength")] = 0.7
            elif curr["close"] < lower_target and prev["close"] >= lower_target:
                df.iloc[i, df.columns.get_loc("signal")] = -1
                df.iloc[i, df.columns.get_loc("signal_strength")] = 0.7
        return df


class TrendFollowingStrategy(BaseStrategy):
    """趋势跟踪策略：基于ADX判断趋势强度，配合方向性指标交易"""
    def __init__(self, adx_window: int = 14, adx_threshold: float = 25.0, **kwargs):
        params = {"adx_window": adx_window, "adx_threshold": adx_threshold}
        super().__init__("趋势跟踪", params)
        self.adx_window = adx_window
        self.adx_threshold = adx_threshold

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self._add_signal_columns(df)
        high_diff = df["high"].diff()
        low_diff = -df["low"].diff()
        plus_dm = np.where((high_diff > low_diff) & (high_diff > 0), high_diff, 0)
        minus_dm = np.where((low_diff > high_diff) & (low_diff > 0), low_diff, 0)

        tr = pd.concat([df["high"] - df["low"],
                        (df["high"] - df["close"].shift(1)).abs(),
                        (df["low"] - df["close"].shift(1)).abs()], axis=1).max(axis=1)

        atr = tr.rolling(window=self.adx_window).mean()
        plus_di = 100 * pd.Series(plus_dm).rolling(window=self.adx_window).mean() / atr.replace(0, 1)
        minus_di = 100 * pd.Series(minus_dm).rolling(window=self.adx_window).mean() / atr.replace(0, 1)
        dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 1)
        adx = dx.rolling(window=self.adx_window).mean()

        df["plus_di"] = plus_di
        df["minus_di"] = minus_di
        df["adx"] = adx

        for i in range(self.adx_window * 2, len(df)):
            curr = df.iloc[i]
            prev = df.iloc[i - 1]
            if pd.isna(curr["adx"]):
                continue
            if curr["adx"] > self.adx_threshold:
                if curr["plus_di"] > curr["minus_di"] and prev["plus_di"] <= prev["minus_di"]:
                    df.iloc[i, df.columns.get_loc("signal")] = 1
                    df.iloc[i, df.columns.get_loc("signal_strength")] = min(curr["adx"] / 50, 1.0)
                elif curr["minus_di"] > curr["plus_di"] and prev["minus_di"] <= prev["plus_di"]:
                    df.iloc[i, df.columns.get_loc("signal")] = -1
                    df.iloc[i, df.columns.get_loc("signal_strength")] = min(curr["adx"] / 50, 1.0)
        return df


class GapStrategy(BaseStrategy):
    """缺口回补策略：向上跳空缺口回补买入，向下跳空缺口回补卖出"""
    def __init__(self, gap_pct: float = 0.01, **kwargs):
        params = {"gap_pct": gap_pct}
        super().__init__("缺口回补", params)
        self.gap_pct = gap_pct

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self._add_signal_columns(df)
        df["prev_high"] = df["high"].shift(1)
        df["prev_low"] = df["low"].shift(1)
        df["gap_up"] = (df["low"] - df["prev_high"]) / df["prev_high"].replace(0, 1)
        df["gap_down"] = (df["prev_low"] - df["high"]) / df["prev_low"].replace(0, 1)

        position = 0
        gap_price = 0

        for i in range(1, len(df)):
            curr = df.iloc[i]
            if pd.isna(curr["prev_high"]):
                continue

            if curr["gap_up"] > self.gap_pct and position == 0:
                gap_price = curr["prev_high"]
                position = 1
            elif curr["gap_down"] > self.gap_pct and position == 0:
                gap_price = curr["prev_low"]
                position = -1
            elif position == 1 and curr["close"] <= gap_price:
                df.iloc[i, df.columns.get_loc("signal")] = 1
                df.iloc[i, df.columns.get_loc("signal_strength")] = 0.6
                position = 0
            elif position == -1 and curr["close"] >= gap_price:
                df.iloc[i, df.columns.get_loc("signal")] = -1
                df.iloc[i, df.columns.get_loc("signal_strength")] = 0.6
                position = 0
        return df


class ThreeSoldiersStrategy(BaseStrategy):
    """三白兵三乌鸦策略：连续三根阳线买入，连续三根阴线卖出"""
    def __init__(self, min_body_pct: float = 0.005, **kwargs):
        params = {"min_body_pct": min_body_pct}
        super().__init__("三白兵三乌鸦", params)
        self.min_body_pct = min_body_pct

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self._add_signal_columns(df)
        df["body"] = df["close"] - df["open"]
        df["body_pct"] = df["body"] / df["open"].replace(0, 1)
        df["is_bull"] = (df["body"] > 0) & (df["body_pct"].abs() > self.min_body_pct)
        df["is_bear"] = (df["body"] < 0) & (df["body_pct"].abs() > self.min_body_pct)

        for i in range(3, len(df)):
            if (df.iloc[i]["is_bull"] and df.iloc[i-1]["is_bull"] and df.iloc[i-2]["is_bull"]
                    and df.iloc[i]["close"] > df.iloc[i-1]["close"] > df.iloc[i-2]["close"]):
                df.iloc[i, df.columns.get_loc("signal")] = 1
                df.iloc[i, df.columns.get_loc("signal_strength")] = 0.7
            elif (df.iloc[i]["is_bear"] and df.iloc[i-1]["is_bear"] and df.iloc[i-2]["is_bear"]
                    and df.iloc[i]["close"] < df.iloc[i-1]["close"] < df.iloc[i-2]["close"]):
                df.iloc[i, df.columns.get_loc("signal")] = -1
                df.iloc[i, df.columns.get_loc("signal_strength")] = 0.7
        return df


class SupportResistanceStrategy(BaseStrategy):
    """支撑阻力策略：价格突破阻力位买入，跌破支撑位卖出"""
    def __init__(self, lookback: int = 20, touch_count: int = 2, **kwargs):
        params = {"lookback": lookback, "touch_count": touch_count}
        super().__init__("支撑阻力", params)
        self.lookback = lookback
        self.touch_count = touch_count

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self._add_signal_columns(df)

        for i in range(self.lookback, len(df)):
            window = df.iloc[i - self.lookback:i]
            highs = window["high"].values
            lows = window["low"].values
            curr_close = df.iloc[i]["close"]
            prev_close = df.iloc[i - 1]["close"]

            sorted_highs = np.sort(highs)[::-1]
            resistance = sorted_highs[0]
            touch_h = sum(1 for h in highs if abs(h - resistance) / (resistance + 1e-8) < 0.02)

            sorted_lows = np.sort(lows)
            support = sorted_lows[0]
            touch_l = sum(1 for l in lows if abs(l - support) / (support + 1e-8) < 0.02)

            if touch_h >= self.touch_count and curr_close > resistance and prev_close <= resistance:
                df.iloc[i, df.columns.get_loc("signal")] = 1
                df.iloc[i, df.columns.get_loc("signal_strength")] = 0.7
            elif touch_l >= self.touch_count and curr_close < support and prev_close >= support:
                df.iloc[i, df.columns.get_loc("signal")] = -1
                df.iloc[i, df.columns.get_loc("signal_strength")] = 0.7
        return df


class OBVStrategy(BaseStrategy):
    """OBV能量潮策略：OBV与价格背离时产生买卖信号"""
    def __init__(self, obv_ma_window: int = 20, **kwargs):
        params = {"obv_ma_window": obv_ma_window}
        super().__init__("OBV能量潮", params)
        self.obv_ma_window = obv_ma_window

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self._add_signal_columns(df)
        df["obv"] = (np.sign(df["close"].diff()) * df["volume"]).fillna(0).cumsum()
        df["obv_ma"] = df["obv"].rolling(window=self.obv_ma_window).mean()
        df["price_ma"] = df["close"].rolling(window=self.obv_ma_window).mean()

        for i in range(self.obv_ma_window + 1, len(df)):
            curr = df.iloc[i]
            prev = df.iloc[i - 1]
            if pd.isna(curr["obv_ma"]):
                continue

            price_up = curr["close"] > prev["close"]
            obv_down = curr["obv"] < prev["obv"]
            price_down = curr["close"] < prev["close"]
            obv_up = curr["obv"] > prev["obv"]

            if price_up and obv_down and curr["obv"] < curr["obv_ma"]:
                df.iloc[i, df.columns.get_loc("signal")] = -1
                df.iloc[i, df.columns.get_loc("signal_strength")] = 0.6
            elif price_down and obv_up and curr["obv"] > curr["obv_ma"]:
                df.iloc[i, df.columns.get_loc("signal")] = 1
                df.iloc[i, df.columns.get_loc("signal_strength")] = 0.6
        return df


STRATEGY_REGISTRY = {
    "ma_cross": MACrossStrategy,
    "rsi": RSIStrategy,
    "macd": MACDStrategy,
    "bollinger": BollingerStrategy,
    "momentum": MomentumStrategy,
    "kdj": KDJStrategy,
    "dual_thrust": DualThrustStrategy,
    "turtle": TurtleStrategy,
    "mean_reversion": MeanReversionStrategy,
    "ma_alignment": MAAlignmentStrategy,
    "volume_breakout": VolumeBreakoutStrategy,
    "volatility_breakout": VolatilityBreakoutStrategy,
    "trend_following": TrendFollowingStrategy,
    "gap": GapStrategy,
    "three_soldiers": ThreeSoldiersStrategy,
    "support_resistance": SupportResistanceStrategy,
    "obv": OBVStrategy,
}


def get_strategy(name: str, params: dict = None) -> BaseStrategy:
    cls = STRATEGY_REGISTRY.get(name)
    if cls is None:
        raise ValueError(f"Unknown strategy: {name}. Available: {list(STRATEGY_REGISTRY.keys())}")
    strategy = cls(**(params or {}))
    strategy.key = name
    return strategy


def list_strategies() -> list:
    result = []
    for key, cls in STRATEGY_REGISTRY.items():
        strategy = cls()
        info = strategy.get_info()
        info["key"] = key
        result.append(info)
    return result


class SentimentCycleStrategy(BaseStrategy):
    """情绪周期策略 - 游资核心策略
    根据市场情绪周期进行交易:
    - 情绪冰点(恐惧) → 试探性买入
    - 情绪回暖 → 加仓
    - 情绪高潮 → 减仓
    - 情绪退潮 → 空仓
    """
    
    def __init__(self, 
                 fear_period: int = 20,
                 greed_period: int = 10,
                 fear_threshold: float = 0.3,
                 greed_threshold: float = 0.8,
                 **kwargs):
        params = {
            "fear_period": fear_period,
            "greed_period": greed_period,
            "fear_threshold": fear_threshold,
            "greed_threshold": greed_threshold
        }
        params.update(kwargs)
        super().__init__("情绪周期", params)
        self.fear_period = fear_period
        self.greed_period = greed_period
        self.fear_threshold = fear_threshold
        self.greed_threshold = greed_threshold
    
    def _calculate_sentiment(self, df: pd.DataFrame) -> pd.Series:
        if len(df) < max(self.fear_period, self.greed_period):
            return pd.Series(0.5, index=df.index)
        
        volatility = df["close"].pct_change().rolling(window=self.fear_period).std()
        avg_volatility = volatility.expanding().mean()
        sentiment = 1 - (volatility / avg_volatility.clip(lower=1e-8))
        
        volume_ratio = df["volume"] / df["volume"].rolling(window=self.fear_period).mean()
        sentiment = sentiment * (volume_ratio / (1 + volume_ratio))
        
        price_momentum = df["close"].pct_change(self.greed_period)
        sentiment = sentiment * (1 + price_momentum.clip(-1, 1))
        
        return sentiment.clip(0, 1)
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self._add_signal_columns(df)
        if len(df) < max(self.fear_period, self.greed_period):
            return df
        
        df["sentiment"] = self._calculate_sentiment(df)
        df["sentiment_ma"] = df["sentiment"].rolling(window=5).mean()
        
        position = 0
        for i in range(max(self.fear_period, self.greed_period), len(df)):
            curr_sentiment = df["sentiment"].iloc[i]
            prev_sentiment = df["sentiment"].iloc[i-1]
            
            if position == 0:
                if curr_sentiment < self.fear_threshold and prev_sentiment >= self.fear_threshold:
                    df.iloc[i, df.columns.get_loc("signal")] = 1
                    df.iloc[i, df.columns.get_loc("signal_strength")] = (self.fear_threshold - curr_sentiment) / self.fear_threshold
                    position = 1
            elif position == 1:
                if curr_sentiment > self.greed_threshold and prev_sentiment <= self.greed_threshold:
                    df.iloc[i, df.columns.get_loc("signal")] = -1
                    df.iloc[i, df.columns.get_loc("signal_strength")] = (curr_sentiment - self.greed_threshold) / (1 - self.greed_threshold)
                    position = 0
                elif curr_sentiment > 0.6 and prev_sentiment <= 0.6:
                    df.iloc[i, df.columns.get_loc("signal")] = -1
                    df.iloc[i, df.columns.get_loc("signal_strength")] = 0.5
                    position = 0
        
        return df


class SectorRotationStrategy(BaseStrategy):
    """行业轮动策略 - 机构核心策略
    模拟行业轮动周期:
    低估值 → 高景气 → 政策风口
    例如: 电力→银行→消费→半导体→新能源
    """
    
    def __init__(self,
                 lookback: int = 60,
                 momentum_window: int = 20,
                 value_threshold: float = 0.3,
                 momentum_threshold: float = 0.1,
                 **kwargs):
        params = {
            "lookback": lookback,
            "momentum_window": momentum_window,
            "value_threshold": value_threshold,
            "momentum_threshold": momentum_threshold
        }
        params.update(kwargs)
        super().__init__("行业轮动", params)
        self.lookback = lookback
        self.momentum_window = momentum_window
        self.value_threshold = value_threshold
        self.momentum_threshold = momentum_threshold
    
    def _calculate_value_score(self, df: pd.DataFrame) -> pd.Series:
        pe_ratio = df.get("pe", pd.Series([15] * len(df), index=df.index))
        pb_ratio = df.get("pb", pd.Series([1.5] * len(df), index=df.index))
        
        pe_score = 1 - ((pe_ratio - 10) / 30).clip(0, 1)
        pb_score = 1 - ((pb_ratio - 0.5) / 3).clip(0, 1)
        
        return (pe_score + pb_score) / 2
    
    def _calculate_momentum_score(self, df: pd.DataFrame) -> pd.Series:
        momentum = df["close"].pct_change(self.momentum_window)
        avg_momentum = momentum.expanding().mean()
        momentum_score = ((momentum - avg_momentum) / (avg_momentum.abs() + 1e-8) + 1) / 2
        return momentum_score.clip(0, 1)
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self._add_signal_columns(df)
        if len(df) < self.lookback:
            return df
        
        df["value_score"] = self._calculate_value_score(df)
        df["momentum_score"] = self._calculate_momentum_score(df)
        df["combined_score"] = df["value_score"] * 0.3 + df["momentum_score"] * 0.7
        
        position = 0
        entry_score = 0
        for i in range(self.lookback, len(df)):
            curr_score = df["combined_score"].iloc[i]
            prev_score = df["combined_score"].iloc[i-1]
            
            if position == 0:
                if curr_score > self.value_threshold and curr_score > prev_score:
                    df.iloc[i, df.columns.get_loc("signal")] = 1
                    df.iloc[i, df.columns.get_loc("signal_strength")] = curr_score
                    position = 1
                    entry_score = curr_score
            else:
                if curr_score < entry_score - 0.2 or (curr_score > entry_score + 0.3):
                    df.iloc[i, df.columns.get_loc("signal")] = -1
                    df.iloc[i, df.columns.get_loc("signal_strength")] = abs(curr_score - entry_score)
                    position = 0
        
        return df


class ProsperityInvestmentStrategy(BaseStrategy):
    """景气度投资策略 - 私募核心策略
    投资于高景气度行业:
    - 行业高增长、订单饱满、产品涨价
    - 核心: 景气 + 低估值
    """
    
    def __init__(self,
                 growth_window: int = 30,
                 min_growth_rate: float = 0.15,
                 volume_confirm: bool = True,
                 volume_threshold: float = 1.5,
                 **kwargs):
        params = {
            "growth_window": growth_window,
            "min_growth_rate": min_growth_rate,
            "volume_confirm": volume_confirm,
            "volume_threshold": volume_threshold
        }
        params.update(kwargs)
        super().__init__("景气度投资", params)
        self.growth_window = growth_window
        self.min_growth_rate = min_growth_rate
        self.volume_confirm = volume_confirm
        self.volume_threshold = volume_threshold
    
    def _calculate_growth_score(self, df: pd.DataFrame) -> pd.Series:
        price_growth = df["close"].pct_change(self.growth_window)
        volume_growth = df["volume"].pct_change(self.growth_window)
        
        if self.volume_confirm:
            avg_volume = df["volume"].rolling(window=self.growth_window).mean()
            volume_ratio = df["volume"] / avg_volume
            growth_score = price_growth * 0.7 + (volume_ratio - 1) * 0.3
        else:
            growth_score = price_growth
        
        return growth_score.clip(-1, 1)
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self._add_signal_columns(df)
        if len(df) < self.growth_window * 2:
            return df
        
        df["growth_score"] = self._calculate_growth_score(df)
        df["growth_ma"] = df["growth_score"].rolling(window=5).mean()
        
        position = 0
        for i in range(self.growth_window * 2, len(df)):
            curr_growth = df["growth_score"].iloc[i]
            prev_growth = df["growth_score"].iloc[i-1]
            
            volume_ratio = df["volume"].iloc[i] / df["volume"].iloc[i-20:i].mean() if i >= 20 else 1
            
            if position == 0:
                if curr_growth > self.min_growth_rate and prev_growth <= self.min_growth_rate:
                    if not self.volume_confirm or volume_ratio > self.volume_threshold:
                        df.iloc[i, df.columns.get_loc("signal")] = 1
                        df.iloc[i, df.columns.get_loc("signal_strength")] = min(curr_growth * 2, 1.0)
                        position = 1
            else:
                if curr_growth < -0.05 or (prev_growth > curr_growth and df["growth_ma"].iloc[i] < df["growth_ma"].iloc[i-5]):
                    df.iloc[i, df.columns.get_loc("signal")] = -1
                    df.iloc[i, df.columns.get_loc("signal_strength")] = 0.6
                    position = 0
        
        return df


class BandOperationStrategy(BaseStrategy):
    """波段操作策略 - 私募核心策略
    低吸高抛，不追高:
    - 回调买，突破卖
    - 不长期死拿、不频繁交易
    - 一年操作不超过10次
    """
    
    def __init__(self,
                 band_window: int = 20,
                 buy_band_pct: float = 0.3,
                 sell_band_pct: float = 0.7,
                 min_hold_days: int = 5,
                 max_hold_days: int = 60,
                 **kwargs):
        params = {
            "band_window": band_window,
            "buy_band_pct": buy_band_pct,
            "sell_band_pct": sell_band_pct,
            "min_hold_days": min_hold_days,
            "max_hold_days": max_hold_days
        }
        params.update(kwargs)
        super().__init__("波段操作", params)
        self.band_window = band_window
        self.buy_band_pct = buy_band_pct
        self.sell_band_pct = sell_band_pct
        self.min_hold_days = min_hold_days
        self.max_hold_days = max_hold_days
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self._add_signal_columns(df)
        if len(df) < self.band_window:
            return df
        
        df["band_high"] = df["close"].rolling(window=self.band_window).quantile(self.sell_band_pct)
        df["band_low"] = df["close"].rolling(window=self.band_window).quantile(self.buy_band_pct)
        df["band_mid"] = (df["band_high"] + df["band_low"]) / 2
        
        position = 0
        entry_price = 0
        hold_days = 0
        
        for i in range(self.band_window, len(df)):
            price = df["close"].iloc[i]
            band_high = df["band_high"].iloc[i]
            band_low = df["band_low"].iloc[i]
            
            if position == 0:
                if price <= band_low:
                    df.iloc[i, df.columns.get_loc("signal")] = 1
                    df.iloc[i, df.columns.get_loc("signal_strength")] = (band_low - price) / band_low + 0.5
                    position = 1
                    entry_price = price
                    hold_days = 0
            else:
                hold_days += 1
                if hold_days >= self.min_hold_days:
                    should_sell = False
                    strength = 0.5
                    
                    if price >= band_high:
                        should_sell = True
                        strength = (price - band_high) / band_high + 0.5
                    elif hold_days >= self.max_hold_days:
                        should_sell = True
                        strength = 0.7
                    elif price > entry_price * 1.05 and hold_days >= self.min_hold_days * 2:
                        should_sell = True
                        strength = 0.8
                    
                    if should_sell:
                        df.iloc[i, df.columns.get_loc("signal")] = -1
                        df.iloc[i, df.columns.get_loc("signal_strength")] = min(strength, 1.0)
                        position = 0
        
        return df


class ValueInvestmentStrategy(BaseStrategy):
    """价值投资策略 - 机构核心策略
    长期持有优质股票:
    - 现金流好、ROE高、分红稳定
    - 行业龙头
    - 买了拿几年，不折腾
    """
    
    def __init__(self,
                 rebalance_days: int = 250,
                 min_roe: float = 0.15,
                 max_pe: float = 30,
                 min_dividend: float = 0.02,
                 trend_window: int = 60,
                 **kwargs):
        params = {
            "rebalance_days": rebalance_days,
            "min_roe": min_roe,
            "max_pe": max_pe,
            "min_dividend": min_dividend,
            "trend_window": trend_window
        }
        params.update(kwargs)
        super().__init__("价值投资", params)
        self.rebalance_days = rebalance_days
        self.min_roe = min_roe
        self.max_pe = max_pe
        self.min_dividend = min_dividend
        self.trend_window = trend_window
    
    def _calculate_value_score(self, df: pd.DataFrame) -> pd.Series:
        roe = df.get("roe", pd.Series([0.2] * len(df), index=df.index))
        pe = df.get("pe", pd.Series([20] * len(df), index=df.index))
        dividend = df.get("dividend_yield", pd.Series([0.03] * len(df), index=df.index))
        
        roe_score = (roe / self.min_roe).clip(0, 2)
        pe_score = (self.max_pe / pe.clip(1, None)).clip(0, 2)
        dividend_score = (dividend / self.min_dividend).clip(0, 2)
        
        value_score = (roe_score * 0.4 + pe_score * 0.3 + dividend_score * 0.3) / 2
        return value_score.clip(0, 1)
    
    def _check_trend(self, df: pd.DataFrame, i: int) -> bool:
        if i < self.trend_window:
            return True
        recent = df["close"].iloc[i-self.trend_window:i].values
        return recent[-1] > recent[0] * 0.95
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self._add_signal_columns(df)
        if len(df) < max(self.rebalance_days, self.trend_window):
            return df
        
        df["value_score"] = self._calculate_value_score(df)
        
        position = 0
        last_rebalance = 0
        for i in range(max(self.rebalance_days, self.trend_window), len(df)):
            days_since_rebalance = i - last_rebalance
            value_score = df["value_score"].iloc[i]
            trend_ok = self._check_trend(df, i)
            
            if position == 0:
                if value_score > 0.5 and trend_ok:
                    df.iloc[i, df.columns.get_loc("signal")] = 1
                    df.iloc[i, df.columns.get_loc("signal_strength")] = value_score
                    position = 1
                    last_rebalance = i
            else:
                should_rebalance = False
                if days_since_rebalance >= self.rebalance_days:
                    should_rebalance = True
                elif not trend_ok and value_score < 0.4:
                    should_rebalance = True
                
                if should_rebalance:
                    df.iloc[i, df.columns.get_loc("signal")] = -1
                    df.iloc[i, df.columns.get_loc("signal_strength")] = 0.5
                    position = 0
                    if value_score > 0.5:
                        df.iloc[i, df.columns.get_loc("signal")] = 1
                        df.iloc[i, df.columns.get_loc("signal_strength")] = value_score
                        position = 1
                        last_rebalance = i
        
        return df


class DragonHeadStrategy(BaseStrategy):
    """龙头战法 - 游资核心策略(简化版)
    只做最强龙头:
    - 板块最强股票
    - 涨停突破确认买入
    - 快进快出，不隔夜
    """
    
    def __init__(self,
                 strength_window: int = 20,
                 limit_up_threshold: float = 0.095,
                 breakout_confirm: bool = True,
                 hold_max_days: int = 3,
                 stop_loss_pct: float = 0.03,
                 **kwargs):
        params = {
            "strength_window": strength_window,
            "limit_up_threshold": limit_up_threshold,
            "breakout_confirm": breakout_confirm,
            "hold_max_days": hold_max_days,
            "stop_loss_pct": stop_loss_pct
        }
        params.update(kwargs)
        super().__init__("龙头战法", params)
        self.strength_window = strength_window
        self.limit_up_threshold = limit_up_threshold
        self.breakout_confirm = breakout_confirm
        self.hold_max_days = hold_max_days
        self.stop_loss_pct = stop_loss_pct
    
    def _is_limit_up(self, df: pd.DataFrame, i: int) -> bool:
        if i < 1:
            return False
        prev_close = df["close"].iloc[i-1]
        curr_close = df["close"].iloc[i]
        curr_high = df["high"].iloc[i]
        return (curr_close / prev_close - 1) >= self.limit_up_threshold and curr_high >= curr_close
    
    def _is_breakout(self, df: pd.DataFrame, i: int) -> bool:
        if i < self.strength_window:
            return False
        highs = df["high"].iloc[i-self.strength_window:i].max()
        return df["close"].iloc[i] > highs
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self._add_signal_columns(df)
        if len(df) < self.strength_window:
            return df
        
        df["strength"] = df["close"].pct_change(self.strength_window)
        df["volume_ma"] = df["volume"].rolling(window=10).mean()
        df["volume_ratio"] = df["volume"] / df["volume_ma"]
        
        position = 0
        entry_price = 0
        hold_days = 0
        for i in range(self.strength_window, len(df)):
            is_limit = self._is_limit_up(df, i)
            is_breakout = self._is_breakout(df, i)
            volume_ratio = df["volume_ratio"].iloc[i]
            strength = df["strength"].iloc[i]
            
            if position == 0:
                if is_limit and strength > 0.1 and volume_ratio > 1.5:
                    if not self.breakout_confirm or is_breakout:
                        df.iloc[i, df.columns.get_loc("signal")] = 1
                        df.iloc[i, df.columns.get_loc("signal_strength")] = min(strength * 2 + 0.5, 1.0)
                        position = 1
                        entry_price = df["close"].iloc[i]
                        hold_days = 0
            else:
                hold_days += 1
                current_price = df["close"].iloc[i]
                
                should_sell = False
                strength_sell = 0.5
                
                if current_price < entry_price * (1 - self.stop_loss_pct):
                    should_sell = True
                    strength_sell = 0.9
                elif hold_days >= self.hold_max_days:
                    should_sell = True
                    strength_sell = 0.6
                elif df["close"].iloc[i] < df["close"].iloc[i-1] * 0.97:
                    should_sell = True
                    strength_sell = 0.7
                
                if should_sell:
                    df.iloc[i, df.columns.get_loc("signal")] = -1
                    df.iloc[i, df.columns.get_loc("signal_strength")] = min(strength_sell, 1.0)
                    position = 0
        
        return df


class AllocationManager:
    """资产配置管理器 - 大师兄体系
    顶级操盘手资产配置:
    - 30%-50% 高分红稳健仓
    - 10%-15% 高景气进攻仓
    - 20%-30% 宽基指数仓
    - 10%-20% 现金仓位
    """
    
    def __init__(self,
                 conservative_pct: float = 0.4,
                 aggressive_pct: float = 0.15,
                 index_pct: float = 0.25,
                 cash_pct: float = 0.2,
                 **kwargs):
        self.conservative_pct = conservative_pct
        self.aggressive_pct = aggressive_pct
        self.index_pct = index_pct
        self.cash_pct = cash_pct
        
        self.params = {
            "conservative_pct": conservative_pct,
            "aggressive_pct": aggressive_pct,
            "index_pct": index_pct,
            "cash_pct": cash_pct
        }
    
    def get_allocation(self) -> dict:
        return {
            "conservative": {
                "name": "稳健仓",
                "pct": self.conservative_pct,
                "description": "高分红、稳现金流、弱周期",
                "examples": ["长江电力", "中国神华", "贵州茅台", "中国移动"]
            },
            "aggressive": {
                "name": "进攻仓",
                "pct": self.aggressive_pct,
                "description": "高景气、国产替代、硬科技",
                "examples": ["半导体", "AI", "新能源车", "算力"]
            },
            "index": {
                "name": "指数仓",
                "pct": self.index_pct,
                "description": "沪深300、中证500宽基",
                "examples": ["510300", "510500"]
            },
            "cash": {
                "name": "现金仓",
                "pct": self.cash_pct,
                "description": "预留现金，大跌抄底"
            }
        }
    
    def recommend_rebalance(self, current_allocation: dict) -> dict:
        recommendations = {}
        
        for category, current_pct in current_allocation.items():
            target_pct = getattr(self, f"{category}_pct", 0)
            diff = current_pct - target_pct
            
            if abs(diff) > 0.05:
                if diff > 0:
                    recommendations[category] = {
                        "action": "减仓",
                        "diff": f"-{diff*100:.1f}%",
                        "reason": "超过目标配置"
                    }
                else:
                    recommendations[category] = {
                        "action": "加仓",
                        "diff": f"+{abs(diff)*100:.1f}%",
                        "reason": "低于目标配置"
                    }
        
        return recommendations
    
    def get_risk_control(self) -> dict:
        return {
            "max_single_position": 0.1,
            "max_loss_per_trade": 0.1,
            "stop_loss": 0.1,
            "max_trades_per_year": 10,
            "min_cash_ratio": 0.1,
            "max_leverage": 1.0,
            "warnings": [
                "永远不满仓",
                "单只股票不超过总资金10%",
                "止损必须执行",
                "不追高、不炒题材、不赌消息"
            ]
        }


STRATEGY_REGISTRY.update({
    "sentiment_cycle": SentimentCycleStrategy,
    "sector_rotation": SectorRotationStrategy,
    "prosperity_investment": ProsperityInvestmentStrategy,
    "band_operation": BandOperationStrategy,
    "value_investment": ValueInvestmentStrategy,
    "dragon_head": DragonHeadStrategy,
})


class MACDMultiTimeframeStrategy(BaseStrategy):
    """MACD多时间框架策略
    结合日线和周线MACD信号进行交易
    """
    
    def __init__(self, daily_fast=12, daily_slow=26, daily_signal=9,
                 weekly_fast=8, weekly_slow=17, weekly_signal=9, **kwargs):
        params = {
            'daily_fast': daily_fast, 'daily_slow': daily_slow, 'daily_signal': daily_signal,
            'weekly_fast': weekly_fast, 'weekly_slow': weekly_slow, 'weekly_signal': weekly_signal
        }
        params.update(kwargs)
        super().__init__("MACD多时间框架", params)
        self.daily_fast = daily_fast
        self.daily_slow = daily_slow
        self.daily_signal = daily_signal
        self.weekly_fast = weekly_fast
        self.weekly_slow = weekly_slow
        self.weekly_signal = weekly_signal
    
    def _calculate_macd(self, series, fast, slow, signal):
        ema_fast = series.ewm(span=fast, adjust=False).mean()
        ema_slow = series.ewm(span=slow, adjust=False).mean()
        macd = ema_fast - ema_slow
        macd_signal = macd.ewm(span=signal, adjust=False).mean()
        return macd, macd_signal
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self._add_signal_columns(df)
        if len(df) < max(self.daily_slow, 20):
            return df
        
        df['daily_macd'], df['daily_signal'] = self._calculate_macd(
            df['close'], self.daily_fast, self.daily_slow, self.daily_signal
        )
        
        df['weekly_macd'], df['weekly_signal'] = self._calculate_macd(
            df['close'], self.weekly_fast, self.weekly_slow, self.weekly_signal
        )
        
        df['daily_hist'] = df['daily_macd'] - df['daily_signal']
        df['weekly_hist'] = df['weekly_macd'] - df['weekly_signal']
        
        position = 0
        for i in range(max(self.daily_slow, 20), len(df)):
            daily_hist = df['daily_hist'].iloc[i]
            prev_daily_hist = df['daily_hist'].iloc[i-1]
            weekly_hist = df['weekly_hist'].iloc[i]
            
            if position == 0:
                if prev_daily_hist <= 0 and daily_hist > 0 and weekly_hist > 0:
                    df.iloc[i, df.columns.get_loc("signal")] = 1
                    df.iloc[i, df.columns.get_loc("signal_strength")] = min(abs(daily_hist) * 10, 1.0)
                    position = 1
            else:
                if prev_daily_hist >= 0 and daily_hist < 0:
                    df.iloc[i, df.columns.get_loc("signal")] = -1
                    df.iloc[i, df.columns.get_loc("signal_strength")] = 0.7
                    position = 0
        
        return df


class VolumeWeightedAveragePriceStrategy(BaseStrategy):
    """VWAP成交量加权平均价策略
    价格在VWAP上方做多，下方做空
    """
    
    def __init__(self, window=20, entry_threshold=0.01, exit_threshold=0.005, **kwargs):
        params = {
            'window': window, 'entry_threshold': entry_threshold, 'exit_threshold': exit_threshold
        }
        params.update(kwargs)
        super().__init__("VWAP策略", params)
        self.window = window
        self.entry_threshold = entry_threshold
        self.exit_threshold = exit_threshold
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self._add_signal_columns(df)
        if len(df) < self.window:
            return df
        
        typical_price = (df['high'] + df['low'] + df['close']) / 3
        df['vwap'] = (typical_price * df['volume']).rolling(window=self.window).sum() / \
                     df['volume'].rolling(window=self.window).sum()
        
        position = 0
        for i in range(self.window, len(df)):
            price = df['close'].iloc[i]
            vwap = df['vwap'].iloc[i]
            prev_price = df['close'].iloc[i-1]
            prev_vwap = df['vwap'].iloc[i-1]
            
            pct_diff = (price - vwap) / vwap
            
            if position == 0:
                if prev_price <= prev_vwap and price > vwap:
                    df.iloc[i, df.columns.get_loc("signal")] = 1
                    df.iloc[i, df.columns.get_loc("signal_strength")] = min(abs(pct_diff) * 10, 1.0)
                    position = 1
            else:
                if pct_diff < -self.exit_threshold or (prev_price >= prev_vwap and price < vwap):
                    df.iloc[i, df.columns.get_loc("signal")] = -1
                    df.iloc[i, df.columns.get_loc("signal_strength")] = min(abs(pct_diff) * 10, 1.0)
                    position = 0
        
        return df


class ParabolicSARStrategy(BaseStrategy):
    """抛物线SAR策略
    使用SAR指标判断趋势转折点
    """
    
    def __init__(self, acceleration=0.02, maximum=0.2, **kwargs):
        params = {'acceleration': acceleration, 'maximum': maximum}
        params.update(kwargs)
        super().__init__("SAR抛物线", params)
        self.acceleration = acceleration
        self.maximum = maximum
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self._add_signal_columns(df)
        if len(df) < 2:
            return df
        
        sar = [df['close'].iloc[0]]
        trend = [1]
        ep = [df['high'].iloc[0]]
        af = [self.acceleration]
        
        for i in range(1, len(df)):
            prev_sar = sar[-1]
            prev_trend = trend[-1]
            prev_ep = ep[-1]
            prev_af = af[-1]
            
            new_sar = prev_sar + prev_af * (prev_ep - prev_sar)
            
            if prev_trend == 1:
                if df['low'].iloc[i] < new_sar:
                    new_trend = -1
                    new_sar = ep[-1]
                    new_ep = df['low'].iloc[i]
                    new_af = self.acceleration
                else:
                    new_trend = 1
                    new_ep = max(prev_ep, df['high'].iloc[i])
                    new_af = min(prev_af + self.acceleration, self.maximum) if df['high'].iloc[i] > prev_ep else prev_af
            else:
                if df['high'].iloc[i] > new_sar:
                    new_trend = 1
                    new_sar = ep[-1]
                    new_ep = df['high'].iloc[i]
                    new_af = self.acceleration
                else:
                    new_trend = -1
                    new_ep = min(prev_ep, df['low'].iloc[i])
                    new_af = min(prev_af + self.acceleration, self.maximum) if df['low'].iloc[i] < prev_ep else prev_af
            
            sar.append(new_sar)
            trend.append(new_trend)
            ep.append(new_ep)
            af.append(new_af)
            
            if trend[-1] != trend[-2]:
                df.iloc[i, df.columns.get_loc("signal")] = 1 if trend[-1] == 1 else -1
                df.iloc[i, df.columns.get_loc("signal_strength")] = 0.8
        
        df['sar'] = sar
        return df


class MoneyFlowIndexStrategy(BaseStrategy):
    """资金流量指标策略
    MFI超卖买入，超买卖出
    """
    
    def __init__(self, period=14, oversold=20, overbought=80, **kwargs):
        params = {'period': period, 'oversold': oversold, 'overbought': overbought}
        params.update(kwargs)
        super().__init__("MFI资金流", params)
        self.period = period
        self.oversold = oversold
        self.overbought = overbought
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self._add_signal_columns(df)
        if len(df) < self.period + 1:
            return df
        
        typical_price = (df['high'] + df['low'] + df['close']) / 3
        money_flow = typical_price * df['volume']
        
        positive_flow = [0]
        negative_flow = [0]
        
        for i in range(1, len(typical_price)):
            if typical_price.iloc[i] > typical_price.iloc[i-1]:
                positive_flow.append(money_flow.iloc[i])
                negative_flow.append(0)
            elif typical_price.iloc[i] < typical_price.iloc[i-1]:
                positive_flow.append(0)
                negative_flow.append(money_flow.iloc[i])
            else:
                positive_flow.append(0)
                negative_flow.append(0)
        
        df['positive_flow'] = positive_flow
        df['negative_flow'] = negative_flow
        
        positive_mf = df['positive_flow'].rolling(window=self.period).sum()
        negative_mf = df['negative_flow'].rolling(window=self.period).sum()
        
        mf_ratio = positive_mf / negative_mf.replace(0, np.inf)
        df['mfi'] = 100 - (100 / (1 + mf_ratio))
        
        position = 0
        for i in range(self.period, len(df)):
            mfi = df['mfi'].iloc[i]
            prev_mfi = df['mfi'].iloc[i-1]
            
            if position == 0:
                if prev_mfi <= self.oversold and mfi > self.oversold:
                    df.iloc[i, df.columns.get_loc("signal")] = 1
                    df.iloc[i, df.columns.get_loc("signal_strength")] = (mfi - self.oversold) / 50
                    position = 1
            else:
                if prev_mfi >= self.overbought and mfi < self.overbought:
                    df.iloc[i, df.columns.get_loc("signal")] = -1
                    df.iloc[i, df.columns.get_loc("signal_strength")] = (self.overbought - mfi) / 50
                    position = 0
        
        return df


class SentimentNewsStrategy(BaseStrategy):
    """舆情策略 - 利好买入/利空卖出
    基于新闻情感分析:
    - 舆情连续正面 + 高评分 → 买入
    - 舆情连续负面 + 高评分 → 卖出
    - 结合技术指标确认
    """
    
    def __init__(self,
                 sentiment_window: int = 3,
                 buy_sentiment_score: float = 0.3,
                 sell_sentiment_score: float = -0.3,
                 use_tech_confirm: bool = True,
                 **kwargs):
        params = {
            "sentiment_window": sentiment_window,
            "buy_sentiment_score": buy_sentiment_score,
            "sell_sentiment_score": sell_sentiment_score,
            "use_tech_confirm": use_tech_confirm
        }
        params.update(kwargs)
        super().__init__("舆情策略", params)
        self.sentiment_window = sentiment_window
        self.buy_sentiment_score = buy_sentiment_score
        self.sell_sentiment_score = sell_sentiment_score
        self.use_tech_confirm = use_tech_confirm
    
    def _get_sentiment_data(self, df: pd.DataFrame) -> pd.Series:
        if hasattr(df, 'sentiment_score') and 'sentiment_score' in df.columns:
            return df['sentiment_score']
        
        if not hasattr(self, '_sentiment_data') or self._sentiment_data is None:
            self._sentiment_data = pd.Series([0] * len(df), index=df.index)
        
        return self._sentiment_data
    
    def _check_tech_confirm(self, df: pd.DataFrame, i: int) -> bool:
        if not self.use_tech_confirm:
            return True
        
        if i < 20:
            return False
        
        close = df["close"].iloc[i]
        ma5 = df["close"].iloc[i-5:i].mean()
        ma20 = df["close"].iloc[i-20:i].mean()
        
        return close > ma5 and ma5 > ma20
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self._add_signal_columns(df)
        if len(df) < self.sentiment_window + 10:
            return df
        
        sentiment = self._get_sentiment_data(df)
        sentiment_ma = sentiment.rolling(window=self.sentiment_window).mean()
        
        position = 0
        for i in range(self.sentiment_window + 10, len(df)):
            curr_sent = sentiment_ma.iloc[i]
            prev_sent = sentiment_ma.iloc[i-1]
            
            tech_ok = self._check_tech_confirm(df, i)
            
            if position == 0:
                if curr_sent >= self.buy_sentiment_score and prev_sent < self.buy_sentiment_score:
                    if tech_ok or not self.use_tech_confirm:
                        df.iloc[i, df.columns.get_loc("signal")] = 1
                        df.iloc[i, df.columns.get_loc("signal_strength")] = min(curr_sent + 0.5, 1.0)
                        position = 1
            else:
                if curr_sent <= self.sell_sentiment_score and prev_sent > self.sell_sentiment_score:
                    df.iloc[i, df.columns.get_loc("signal")] = -1
                    df.iloc[i, df.columns.get_loc("signal_strength")] = min(abs(curr_sent) + 0.5, 1.0)
                    position = 0
        
        return df


class SentimentContrarianStrategy(BaseStrategy):
    """舆情反转策略 - 情绪触底反弹
    反向思维:
    - 连续极度负面后转正面 → 逆向买入
    - 连续极度正面后转负面 → 逆向卖出
    - 核心: 别人恐惧我贪婪
    """
    
    def __init__(self,
                 extreme_threshold: float = 0.5,
                 reversal_window: int = 5,
                 **kwargs):
        params = {
            "extreme_threshold": extreme_threshold,
            "reversal_window": reversal_window
        }
        params.update(kwargs)
        super().__init__("舆情反转", params)
        self.extreme_threshold = extreme_threshold
        self.reversal_window = reversal_window
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self._add_signal_columns(df)
        if len(df) < self.reversal_window + 10:
            return df
        
        if hasattr(df, 'sentiment_score') and 'sentiment_score' in df.columns:
            sentiment = df['sentiment_score']
        else:
            sentiment = pd.Series([0] * len(df), index=df.index)
        
        position = 0
        for i in range(self.reversal_window + 10, len(df)):
            window_sent = sentiment.iloc[i - self.reversal_window:i]
            avg_sent = window_sent.mean()
            min_sent = window_sent.min()
            max_sent = window_sent.max()
            curr_sent = sentiment.iloc[i]
            
            if position == 0:
                if avg_sent <= -self.extreme_threshold and min_sent <= -0.6 and curr_sent > -0.2:
                    df.iloc[i, df.columns.get_loc("signal")] = 1
                    df.iloc[i, df.columns.get_loc("signal_strength")] = 0.8
                    position = 1
            else:
                if avg_sent >= self.extreme_threshold and max_sent >= 0.6 and curr_sent < 0.2:
                    df.iloc[i, df.columns.get_loc("signal")] = -1
                    df.iloc[i, df.columns.get_loc("signal_strength")] = 0.8
                    position = 0
        
        return df


STRATEGY_REGISTRY.update({
    "macd_multitimeframe": MACDMultiTimeframeStrategy,
    "vwap": VolumeWeightedAveragePriceStrategy,
    "sar": ParabolicSARStrategy,
    "mfi": MoneyFlowIndexStrategy,
    "sentiment_news": SentimentNewsStrategy,
    "sentiment_contrarian": SentimentContrarianStrategy,
})
