"""
strategies_optimized.py — MakingMoney 策略引擎优化版
====================================================
从 strategies.py (29个策略) 精简合并为 18个核心策略。
消除明显冗余 (MA交叉+MA排列, MACD+多时间框架, RSI+MFI, 布林带+均值回归, 量价突破+波动率突破,
情绪周期+舆情+反转, 行业轮动+景气度, 波段操作+龙头战法等)。

兼容性设计:
- 保留所有原始策略类的 key/name，注册表使用新 key
- strategies_optimized.py 与 strategies.py 可共存，互不影响
- 所有合并策略通过 mode 参数切换原始行为，保持可复现性

合并映射:
  原始策略                              → 优化版
  ──────────────────────────────────────────────────────────────
  ma_cross, ma_alignment, momentum      → ma_cross (mode='cross'|'alignment'|'momentum')
  macd, macd_multitimeframe             → macd (mode='standard'|'multitimeframe')
  rsi, mfi                              → rsi (mode='rsi'|'mfi')
  bollinger, mean_reversion             → bollinger (mode='bollinger'|'zscore')
  volume_breakout, volatility_breakout  → volume_breakout (mode='volume'|'volatility')
  gap, three_soldiers                   → pattern (mode='gap'|'three_soldiers')
  sentiment_cycle, sentiment_news,
    sentiment_contrarian                → sentiment (mode='cycle'|'news'|'contrarian')
  sector_rotation, prosperity_investment → sector_rotation (mode='rotation'|'prosperity')
  band_operation, dragon_head           → band_operation (mode='band'|'dragon_head')
  其余独立策略保持不变:
    trend_following, sar, kdj, dual_thrust, turtle,
    support_resistance, obv, vwap, value_investment

信号强度归一化说明 (signal_strength):
=======================================
所有策略的 signal_strength 统一映射到 [0, 1] 闭区间:
- 0.0 = 无信号 / 极度微弱
- 0.5 = 中等强度
- 1.0 = 最强信号

归一化方法分类:
1. 固定值策略 (MACD金叉死叉、均线排列、SAR、支撑阻力等):
   直接分配固定经验值 (0.5~0.8)，天然在 [0,1] 区间

2. 比例缩放策略 (RSI、KDJ、MACD柱、ADX等):
   用阈值差 / 最大可能范围 计算，如:
   - RSI: (阈值 − 当前值) / 最大偏差, 然后 max(0, min(1, val))
   - KDJ: (阈值 − J值) / 最大偏差
   - ADX: 当前ADX / 50

3. 距离归一化策略 (布林带、双轨突破、海龟等):
   - (价格 − 轨道值) / (标准差或范围), 然后用 min(val, 1.0) 截断

4. 复合评分策略 (行业轮动、价值投资等):
   由多个子评分加权组合，每个子评分已约束在 [0,1]

⚠️ 所有 signal_strength 赋值处必须确保值在 [0, 1] 内。
   推荐统一使用 min(val, 1.0) 或 max(0, min(1, val)) 保护。
"""

import pandas as pd
import numpy as np
from abc import ABC, abstractmethod
from datetime import datetime
from loguru import logger


# ============================================================
# 归一化工具函数
# ============================================================

def _normalize_strength(val: float) -> float:
    """将信号强度映射到 [0, 1] 闭区间。
    
    所有策略的 signal_strength 必须通过此函数或等效逻辑确保区间合规。
    若 val > 1.0 说明归一化公式需调整（应除以更大的分母）。
    
    Args:
        val: 原始信号强度值（可能超出 [0,1] 范围）
    
    Returns:
        [0, 1] 范围内的值
    """
    return max(0.0, min(1.0, float(val)))


# ============================================================
# Base Strategy (unchanged from original)
# ============================================================

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


# ============================================================
# TREND — 趋势跟踪类 (4个)
# ============================================================

class MACrossStrategy(BaseStrategy):
    """均线策略（合并: ma_cross + ma_alignment + momentum）
    mode='cross': 短期均线上穿/下穿长期均线
    mode='alignment': 短中长均线多头/空头排列
    mode='momentum': N日涨幅动量
    """
    def __init__(self, short_window: int = 5, mid_window: int = 20,
                 long_window: int = 60, lookback: int = 20,
                 buy_threshold: float = 0.05, sell_threshold: float = -0.05,
                 mode: str = "cross", **kwargs):
        params = {
            "short_window": short_window, "mid_window": mid_window,
            "long_window": long_window, "lookback": lookback,
            "buy_threshold": buy_threshold, "sell_threshold": sell_threshold,
            "mode": mode,
        }
        params.update(kwargs)
        label_map = {"cross": "均线交叉", "alignment": "均线排列", "momentum": "动量策略"}
        super().__init__(label_map.get(mode, "均线策略"), params)
        self.short_window = short_window
        self.mid_window = mid_window
        self.long_window = long_window
        self.lookback = lookback
        self.buy_threshold = buy_threshold
        self.sell_threshold = sell_threshold
        self.mode = mode

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self._add_signal_columns(df)
        if self.mode == "cross":
            return self._mode_cross(df)
        elif self.mode == "alignment":
            return self._mode_alignment(df)
        elif self.mode == "momentum":
            return self._mode_momentum(df)
        return df

    def _mode_cross(self, df: pd.DataFrame) -> pd.DataFrame:
        if len(df) < self.long_window + 1:
            return df
        df["ma_short"] = df["close"].rolling(window=self.short_window).mean()
        df["ma_long"] = df["close"].rolling(window=self.long_window).mean()
        for i in range(self.long_window, len(df)):
            prev_diff = df["ma_short"].iloc[i-1] - df["ma_long"].iloc[i-1]
            curr_diff = df["ma_short"].iloc[i] - df["ma_long"].iloc[i]
            if prev_diff <= 0 and curr_diff > 0:
                df.iloc[i, df.columns.get_loc("signal")] = 1
                df.iloc[i, df.columns.get_loc("signal_strength")] = min(abs(curr_diff) / df["close"].iloc[i] * 100, 1.0)
            elif prev_diff >= 0 and curr_diff < 0:
                df.iloc[i, df.columns.get_loc("signal")] = -1
                df.iloc[i, df.columns.get_loc("signal_strength")] = min(abs(curr_diff) / df["close"].iloc[i] * 100, 1.0)
        return df

    def _mode_alignment(self, df: pd.DataFrame) -> pd.DataFrame:
        df["ma_short"] = df["close"].rolling(window=self.short_window).mean()
        df["ma_mid"] = df["close"].rolling(window=self.mid_window).mean()
        df["ma_long"] = df["close"].rolling(window=self.long_window).mean()
        for i in range(1, len(df)):
            if pd.isna(df.iloc[i]["ma_long"]):
                continue
            prev = df.iloc[i-1]
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

    def _mode_momentum(self, df: pd.DataFrame) -> pd.DataFrame:
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


class MACDStrategy(BaseStrategy):
    """MACD策略（合并: macd + macd_multitimeframe）
    mode='standard': 标准MACD金叉死叉
    mode='multitimeframe': 日线+周线双重确认
    """
    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9,
                 weekly_fast: int = 8, weekly_slow: int = 17, weekly_signal: int = 9,
                 mode: str = "standard", **kwargs):
        params = {
            "fast": fast, "slow": slow, "signal": signal,
            "weekly_fast": weekly_fast, "weekly_slow": weekly_slow,
            "weekly_signal": weekly_signal, "mode": mode,
        }
        params.update(kwargs)
        label_map = {"standard": "MACD金叉死叉", "multitimeframe": "MACD多时间框架"}
        super().__init__(label_map.get(mode, "MACD"), params)
        self.fast = fast
        self.slow = slow
        self.signal_period = signal
        self.weekly_fast = weekly_fast
        self.weekly_slow = weekly_slow
        self.weekly_signal = weekly_signal
        self.mode = mode

    def _calc_macd(self, series, fast, slow, signal):
        ema_fast = series.ewm(span=fast, adjust=False).mean()
        ema_slow = series.ewm(span=slow, adjust=False).mean()
        macd = ema_fast - ema_slow
        macd_signal = macd.ewm(span=signal, adjust=False).mean()
        return macd, macd_signal, macd - macd_signal

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self._add_signal_columns(df)
        if self.mode == "standard":
            return self._mode_standard(df)
        elif self.mode == "multitimeframe":
            return self._mode_multitimeframe(df)
        return df

    def _mode_standard(self, df: pd.DataFrame) -> pd.DataFrame:
        if len(df) < self.slow + self.signal_period:
            return df
        _, _, hist = self._calc_macd(df["close"], self.fast, self.slow, self.signal_period)
        df["macd_hist"] = hist
        for i in range(self.slow, len(df)):
            prev_hist = df["macd_hist"].iloc[i-1]
            curr_hist = df["macd_hist"].iloc[i]
            if prev_hist <= 0 and curr_hist > 0:
                df.iloc[i, df.columns.get_loc("signal")] = 1
                df.iloc[i, df.columns.get_loc("signal_strength")] = min(abs(curr_hist) / df["close"].iloc[i] * 10, 1.0)
            elif prev_hist >= 0 and curr_hist < 0:
                df.iloc[i, df.columns.get_loc("signal")] = -1
                df.iloc[i, df.columns.get_loc("signal_strength")] = min(abs(curr_hist) / df["close"].iloc[i] * 10, 1.0)
        return df

    def _mode_multitimeframe(self, df: pd.DataFrame) -> pd.DataFrame:
        min_len = max(self.slow, 20)
        if len(df) < min_len:
            return df
        _, _, daily_hist = self._calc_macd(df["close"], self.fast, self.slow, self.signal_period)
        _, _, weekly_hist = self._calc_macd(df["close"], self.weekly_fast, self.weekly_slow, self.weekly_signal)
        df["daily_hist"] = daily_hist
        df["weekly_hist"] = weekly_hist
        position = 0
        for i in range(min_len, len(df)):
            dh = df["daily_hist"].iloc[i]
            pdh = df["daily_hist"].iloc[i-1]
            wh = df["weekly_hist"].iloc[i]
            if position == 0:
                if pdh <= 0 and dh > 0 and wh > 0:
                    df.iloc[i, df.columns.get_loc("signal")] = 1
                    df.iloc[i, df.columns.get_loc("signal_strength")] = min(abs(dh) * 10, 1.0)
                    position = 1
            else:
                if pdh >= 0 and dh < 0:
                    df.iloc[i, df.columns.get_loc("signal")] = -1
                    df.iloc[i, df.columns.get_loc("signal_strength")] = 0.7
                    position = 0
        return df


class TrendFollowingStrategy(BaseStrategy):
    """趋势跟踪策略：基于ADX判断趋势强度，配合+DI/-DI方向性指标交易"""
    def __init__(self, adx_window: int = 14, adx_threshold: float = 25.0, **kwargs):
        params = {"adx_window": adx_window, "adx_threshold": adx_threshold}
        params.update(kwargs)
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
            prev = df.iloc[i-1]
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


class ParabolicSARStrategy(BaseStrategy):
    """抛物线SAR策略：使用SAR指标判断趋势转折点"""
    def __init__(self, acceleration=0.02, maximum=0.2, **kwargs):
        params = {"acceleration": acceleration, "maximum": maximum}
        params.update(kwargs)
        super().__init__("SAR抛物线", params)
        self.acceleration = acceleration
        self.maximum = maximum

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self._add_signal_columns(df)
        if len(df) < 2:
            return df
        sar = [df["close"].iloc[0]]
        trend = [1]
        ep = [df["high"].iloc[0]]
        af = [self.acceleration]
        for i in range(1, len(df)):
            prev_sar = sar[-1]; prev_trend = trend[-1]; prev_ep = ep[-1]; prev_af = af[-1]
            new_sar = prev_sar + prev_af * (prev_ep - prev_sar)
            if prev_trend == 1:
                if df["low"].iloc[i] < new_sar:
                    new_trend = -1; new_sar = ep[-1]
                    new_ep = df["low"].iloc[i]; new_af = self.acceleration
                else:
                    new_trend = 1
                    new_ep = max(prev_ep, df["high"].iloc[i])
                    new_af = min(prev_af + self.acceleration, self.maximum) if df["high"].iloc[i] > prev_ep else prev_af
            else:
                if df["high"].iloc[i] > new_sar:
                    new_trend = 1; new_sar = ep[-1]
                    new_ep = df["high"].iloc[i]; new_af = self.acceleration
                else:
                    new_trend = -1
                    new_ep = min(prev_ep, df["low"].iloc[i])
                    new_af = min(prev_af + self.acceleration, self.maximum) if df["low"].iloc[i] < prev_ep else prev_af
            sar.append(new_sar); trend.append(new_trend); ep.append(new_ep); af.append(new_af)
            if trend[-1] != trend[-2]:
                df.iloc[i, df.columns.get_loc("signal")] = 1 if trend[-1] == 1 else -1
                df.iloc[i, df.columns.get_loc("signal_strength")] = 0.8
        df["sar"] = sar
        return df


# ============================================================
# OSCILLATOR — 震荡指标类 (3个)
# ============================================================

class KDJStrategy(BaseStrategy):
    """KDJ策略：K线上穿D线且J<20买入，K线下穿D线且J>80卖出"""
    def __init__(self, n: int = 9, m1: int = 3, m2: int = 3, **kwargs):
        params = {"n": n, "m1": m1, "m2": m2}
        params.update(kwargs)
        super().__init__("KDJ金叉死叉", params)
        self.n = n; self.m1 = m1; self.m2 = m2

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self._add_signal_columns(df)
        if len(df) < self.n:
            return df
        low_min = df["low"].rolling(window=self.n).min()
        high_max = df["high"].rolling(window=self.n).max()
        rsv = (df["close"] - low_min) / (high_max - low_min).replace(0, np.inf) * 100
        df["K"] = rsv.ewm(alpha=1/self.m1, min_periods=self.m1, adjust=False).mean()
        df["D"] = df["K"].ewm(alpha=1/self.m2, min_periods=self.m2, adjust=False).mean()
        df["J"] = 3 * df["K"] - 2 * df["D"]
        for i in range(self.n, len(df)):
            prev_k = df["K"].iloc[i-1]; curr_k = df["K"].iloc[i]
            prev_d = df["D"].iloc[i-1]; curr_d = df["D"].iloc[i]
            j_val = df["J"].iloc[i]
            if prev_k <= prev_d and curr_k > curr_d and j_val < 20:
                df.iloc[i, df.columns.get_loc("signal")] = 1
                df.iloc[i, df.columns.get_loc("signal_strength")] = min((20 - j_val) / 20, 1.0)
            elif prev_k >= prev_d and curr_k < curr_d and j_val > 80:
                df.iloc[i, df.columns.get_loc("signal")] = -1
                df.iloc[i, df.columns.get_loc("signal_strength")] = min((j_val - 80) / 20, 1.0)
        return df


class RSIStrategy(BaseStrategy):
    """RSI/MFI振荡器策略（合并: rsi + mfi）
    mode='rsi': RSI超买超卖
    mode='mfi': 资金流量指标超买超卖
    """
    def __init__(self, period: int = 14, oversold: float = 30, overbought: float = 70,
                 mode: str = "rsi", **kwargs):
        params = {"period": period, "oversold": oversold, "overbought": overbought, "mode": mode}
        params.update(kwargs)
        label_map = {"rsi": "RSI超买超卖", "mfi": "MFI资金流"}
        super().__init__(label_map.get(mode, "RSI"), params)
        self.period = period
        self.oversold = oversold
        self.overbought = overbought
        self.mode = mode

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self._add_signal_columns(df)
        if self.mode == "mfi":
            return self._mode_mfi(df)
        return self._mode_rsi(df)

    def _mode_rsi(self, df: pd.DataFrame) -> pd.DataFrame:
        if len(df) < self.period + 1:
            return df
        delta = df["close"].diff()
        gain = delta.where(delta > 0, 0)
        loss = (-delta).where(delta < 0, 0)
        avg_gain = gain.ewm(alpha=1/self.period, min_periods=self.period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1/self.period, min_periods=self.period, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, np.inf)
        df["rsi"] = 100 - (100 / (1 + rs))
        for i in range(self.period, len(df)):
            rsi_val = df["rsi"].iloc[i]; prev_rsi = df["rsi"].iloc[i-1]
            if prev_rsi <= self.oversold and rsi_val > self.oversold:
                df.iloc[i, df.columns.get_loc("signal")] = 1
                df.iloc[i, df.columns.get_loc("signal_strength")] = (self.oversold + (50 - self.oversold)/2 - rsi_val) / 50
            elif prev_rsi >= self.overbought and rsi_val < self.overbought:
                df.iloc[i, df.columns.get_loc("signal")] = -1
                df.iloc[i, df.columns.get_loc("signal_strength")] = (rsi_val - (50 + (self.overbought - 50)/2)) / 50
            df.iloc[i, df.columns.get_loc("signal_strength")] = max(0, min(1, abs(df.iloc[i, df.columns.get_loc("signal_strength")])))
        return df

    def _mode_mfi(self, df: pd.DataFrame) -> pd.DataFrame:
        if len(df) < self.period + 1:
            return df
        typical_price = (df["high"] + df["low"] + df["close"]) / 3
        money_flow = typical_price * df["volume"]
        pos_f = [0]; neg_f = [0]
        for i in range(1, len(typical_price)):
            if typical_price.iloc[i] > typical_price.iloc[i-1]:
                pos_f.append(money_flow.iloc[i]); neg_f.append(0)
            elif typical_price.iloc[i] < typical_price.iloc[i-1]:
                pos_f.append(0); neg_f.append(money_flow.iloc[i])
            else:
                pos_f.append(0); neg_f.append(0)
        df["positive_flow"] = pos_f; df["negative_flow"] = neg_f
        pos_mf = df["positive_flow"].rolling(window=self.period).sum()
        neg_mf = df["negative_flow"].rolling(window=self.period).sum()
        mf_ratio = pos_mf / neg_mf.replace(0, np.inf)
        df["mfi"] = 100 - (100 / (1 + mf_ratio))
        position = 0
        for i in range(self.period, len(df)):
            mfi = df["mfi"].iloc[i]; prev_mfi = df["mfi"].iloc[i-1]
            if position == 0:
                if prev_mfi <= self.oversold and mfi > self.oversold:
                    df.iloc[i, df.columns.get_loc("signal")] = 1
                    df.iloc[i, df.columns.get_loc("signal_strength")] = min((mfi - self.oversold) / 50, 1.0)  # 归一化至 [0,1]
                    position = 1
            else:
                if prev_mfi >= self.overbought and mfi < self.overbought:
                    df.iloc[i, df.columns.get_loc("signal")] = -1
                    df.iloc[i, df.columns.get_loc("signal_strength")] = (self.overbought - mfi) / 50
                    position = 0
        return df


class BollingerStrategy(BaseStrategy):
    """布林带/均值回归策略（合并: bollinger + mean_reversion）
    mode='bollinger': 价格触及上下轨交易
    mode='zscore': Z-score均值回归
    """
    def __init__(self, window: int = 20, num_std: float = 2.0,
                 entry_std: float = 2.0, exit_std: float = 0.5,
                 mode: str = "bollinger", **kwargs):
        params = {
            "window": window, "num_std": num_std,
            "entry_std": entry_std, "exit_std": exit_std, "mode": mode,
        }
        params.update(kwargs)
        label_map = {"bollinger": "布林带突破", "zscore": "均值回归"}
        super().__init__(label_map.get(mode, "布林带"), params)
        self.window = window; self.num_std = num_std
        self.entry_std = entry_std; self.exit_std = exit_std
        self.mode = mode

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self._add_signal_columns(df)
        if self.mode == "zscore":
            return self._mode_zscore(df)
        return self._mode_bollinger(df)

    def _mode_bollinger(self, df: pd.DataFrame) -> pd.DataFrame:
        if len(df) < self.window:
            return df
        df["boll_mid"] = df["close"].rolling(window=self.window).mean()
        boll_std = df["close"].rolling(window=self.window).std()
        df["boll_upper"] = df["boll_mid"] + self.num_std * boll_std
        df["boll_lower"] = df["boll_mid"] - self.num_std * boll_std
        for i in range(self.window, len(df)):
            price = df["close"].iloc[i]; prev_price = df["close"].iloc[i-1]
            lower = df["boll_lower"].iloc[i]; upper = df["boll_upper"].iloc[i]
            if prev_price <= lower and price > lower:
                df.iloc[i, df.columns.get_loc("signal")] = 1
                df.iloc[i, df.columns.get_loc("signal_strength")] = min((price - lower) / (boll_std.iloc[i] + 1e-8) * 0.5 + 0.5, 1.0)
            elif prev_price >= upper and price < upper:
                df.iloc[i, df.columns.get_loc("signal")] = -1
                df.iloc[i, df.columns.get_loc("signal_strength")] = min((upper - price) / (boll_std.iloc[i] + 1e-8) * 0.5 + 0.5, 1.0)
        return df

    def _mode_zscore(self, df: pd.DataFrame) -> pd.DataFrame:
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
                df.iloc[i, df.columns.get_loc("signal_strength")] = 0.3; position = 0
            elif position == -1 and zscore < self.exit_std:
                df.iloc[i, df.columns.get_loc("signal")] = 1
                df.iloc[i, df.columns.get_loc("signal_strength")] = 0.3; position = 0
        return df


# ============================================================
# BREAKOUT — 突破类 (4个)
# ============================================================

class DualThrustStrategy(BaseStrategy):
    """双轨突破策略：基于N日高低价范围突破"""
    def __init__(self, lookback: int = 4, k1: float = 0.5, k2: float = 0.5, **kwargs):
        params = {"lookback": lookback, "k1": k1, "k2": k2}
        params.update(kwargs)
        super().__init__("双轨突破(Dual Thrust)", params)
        self.lookback = lookback; self.k1 = k1; self.k2 = k2

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
            price = df["close"].iloc[i]; upper = df["upper_bound"].iloc[i]; lower = df["lower_bound"].iloc[i]
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
        self.entry_window = entry_window; self.exit_window = exit_window
        self.atr_period = atr_period; self.risk_pct = risk_pct

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self._add_signal_columns(df)
        min_len = max(self.entry_window, self.exit_window, self.atr_period) + 1
        if len(df) < min_len:
            return df
        df["entry_high"] = df["high"].rolling(window=self.entry_window).max().shift(1)
        df["exit_low"] = df["low"].rolling(window=self.exit_window).min().shift(1)
        tr = pd.concat([df["high"] - df["low"],
                        (df["high"] - df["close"].shift(1)).abs(),
                        (df["low"] - df["close"].shift(1)).abs()], axis=1).max(axis=1)
        df["atr"] = tr.rolling(window=self.atr_period).mean()
        position = 0
        for i in range(min_len, len(df)):
            price = df["close"].iloc[i]
            entry_high = df["entry_high"].iloc[i]; exit_low = df["exit_low"].iloc[i]
            if position <= 0 and pd.notna(entry_high) and price > entry_high:
                df.iloc[i, df.columns.get_loc("signal")] = 1
                df.iloc[i, df.columns.get_loc("signal_strength")] = min((price - entry_high) / (df["atr"].iloc[i] + 1e-8), 1.0)
                position = 1
            elif position >= 0 and pd.notna(exit_low) and price < exit_low:
                df.iloc[i, df.columns.get_loc("signal")] = -1
                df.iloc[i, df.columns.get_loc("signal_strength")] = min((exit_low - price) / (df["atr"].iloc[i] + 1e-8), 1.0)
                position = -1
        return df


class VolumeBreakoutStrategy(BaseStrategy):
    """量价/波动率突破策略（合并: volume_breakout + volatility_breakout）
    mode='volume': 放量突破近N日高点/低点
    mode='volatility': 价格突破布林带宽度一定比例
    """
    def __init__(self, lookback: int = 20, volume_ratio: float = 1.5,
                 bb_window: int = 20, bb_std: float = 2.0, breakout_pct: float = 0.5,
                 mode: str = "volume", **kwargs):
        params = {
            "lookback": lookback, "volume_ratio": volume_ratio,
            "bb_window": bb_window, "bb_std": bb_std, "breakout_pct": breakout_pct,
            "mode": mode,
        }
        params.update(kwargs)
        label_map = {"volume": "量价突破", "volatility": "波动率突破"}
        super().__init__(label_map.get(mode, "量价突破"), params)
        self.lookback = lookback; self.volume_ratio = volume_ratio
        self.bb_window = bb_window; self.bb_std = bb_std; self.breakout_pct = breakout_pct
        self.mode = mode

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self._add_signal_columns(df)
        if self.mode == "volatility":
            return self._mode_volatility(df)
        return self._mode_volume(df)

    def _mode_volume(self, df: pd.DataFrame) -> pd.DataFrame:
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

    def _mode_volatility(self, df: pd.DataFrame) -> pd.DataFrame:
        df["bb_mid"] = df["close"].rolling(window=self.bb_window).mean()
        df["bb_std_val"] = df["close"].rolling(window=self.bb_window).std()
        df["bb_upper"] = df["bb_mid"] + self.bb_std * df["bb_std_val"]
        df["bb_lower"] = df["bb_mid"] - self.bb_std * df["bb_std_val"]
        for i in range(self.bb_window, len(df)):
            curr = df.iloc[i]; prev = df.iloc[i-1]
            if pd.isna(curr["bb_upper"]):
                continue
            band_width = curr["bb_upper"] - curr["bb_lower"]
            upper_target = curr["bb_upper"] + band_width * self.breakout_pct
            lower_target = curr["bb_lower"] - band_width * self.breakout_pct
            if curr["close"] > upper_target and prev["close"] <= upper_target:
                df.iloc[i, df.columns.get_loc("signal")] = 1
                df.iloc[i, df.columns.get_loc("signal_strength")] = 0.7
            elif curr["close"] < lower_target and prev["close"] >= lower_target:
                df.iloc[i, df.columns.get_loc("signal")] = -1
                df.iloc[i, df.columns.get_loc("signal_strength")] = 0.7
        return df


# ============================================================
# SUPPORT / RESISTANCE — 支撑阻力类 (1个)
# ============================================================

class SupportResistanceStrategy(BaseStrategy):
    """支撑阻力策略：价格突破阻力位买入，跌破支撑位卖出"""
    def __init__(self, lookback: int = 20, touch_count: int = 2, **kwargs):
        params = {"lookback": lookback, "touch_count": touch_count}
        params.update(kwargs)
        super().__init__("支撑阻力", params)
        self.lookback = lookback; self.touch_count = touch_count

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self._add_signal_columns(df)
        for i in range(self.lookback, len(df)):
            window = df.iloc[i - self.lookback:i]
            highs = window["high"].values; lows = window["low"].values
            curr_close = df.iloc[i]["close"]; prev_close = df.iloc[i-1]["close"]
            sorted_highs = np.sort(highs)[::-1]; resistance = sorted_highs[0]
            touch_h = sum(1 for h in highs if abs(h - resistance) / (resistance + 1e-8) < 0.02)
            sorted_lows = np.sort(lows); support = sorted_lows[0]
            touch_l = sum(1 for l in lows if abs(l - support) / (support + 1e-8) < 0.02)
            if touch_h >= self.touch_count and curr_close > resistance and prev_close <= resistance:
                df.iloc[i, df.columns.get_loc("signal")] = 1
                df.iloc[i, df.columns.get_loc("signal_strength")] = 0.7
            elif touch_l >= self.touch_count and curr_close < support and prev_close >= support:
                df.iloc[i, df.columns.get_loc("signal")] = -1
                df.iloc[i, df.columns.get_loc("signal_strength")] = 0.7
        return df


# ============================================================
# PATTERN — K线形态类 (合并: gap + three_soldiers)
# ============================================================

class PatternStrategy(BaseStrategy):
    """K线形态策略（合并: gap + three_soldiers）
    mode='gap': 缺口回补
    mode='three_soldiers': 三白兵三乌鸦
    """
    def __init__(self, gap_pct: float = 0.01, min_body_pct: float = 0.005,
                 mode: str = "gap", **kwargs):
        params = {"gap_pct": gap_pct, "min_body_pct": min_body_pct, "mode": mode}
        params.update(kwargs)
        label_map = {"gap": "缺口回补", "three_soldiers": "三白兵三乌鸦"}
        super().__init__(label_map.get(mode, "K线形态"), params)
        self.gap_pct = gap_pct; self.min_body_pct = min_body_pct; self.mode = mode

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self._add_signal_columns(df)
        if self.mode == "three_soldiers":
            return self._mode_three_soldiers(df)
        return self._mode_gap(df)

    def _mode_gap(self, df: pd.DataFrame) -> pd.DataFrame:
        df["prev_high"] = df["high"].shift(1)
        df["prev_low"] = df["low"].shift(1)
        df["gap_up"] = (df["low"] - df["prev_high"]) / df["prev_high"].replace(0, 1)
        df["gap_down"] = (df["prev_low"] - df["high"]) / df["prev_low"].replace(0, 1)
        position = 0; gap_price = 0
        for i in range(1, len(df)):
            curr = df.iloc[i]
            if pd.isna(curr["prev_high"]): continue
            if curr["gap_up"] > self.gap_pct and position == 0:
                gap_price = curr["prev_high"]; position = 1
            elif curr["gap_down"] > self.gap_pct and position == 0:
                gap_price = curr["prev_low"]; position = -1
            elif position == 1 and curr["close"] <= gap_price:
                df.iloc[i, df.columns.get_loc("signal")] = 1
                df.iloc[i, df.columns.get_loc("signal_strength")] = 0.6; position = 0
            elif position == -1 and curr["close"] >= gap_price:
                df.iloc[i, df.columns.get_loc("signal")] = -1
                df.iloc[i, df.columns.get_loc("signal_strength")] = 0.6; position = 0
        return df

    def _mode_three_soldiers(self, df: pd.DataFrame) -> pd.DataFrame:
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


# ============================================================
# VOLUME — 量价类 (2个)
# ============================================================

class OBVStrategy(BaseStrategy):
    """OBV能量潮策略：OBV与价格背离时产生买卖信号"""
    def __init__(self, obv_ma_window: int = 20, **kwargs):
        params = {"obv_ma_window": obv_ma_window}
        params.update(kwargs)
        super().__init__("OBV能量潮", params)
        self.obv_ma_window = obv_ma_window

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self._add_signal_columns(df)
        df["obv"] = (np.sign(df["close"].diff()) * df["volume"]).fillna(0).cumsum()
        df["obv_ma"] = df["obv"].rolling(window=self.obv_ma_window).mean()
        df["price_ma"] = df["close"].rolling(window=self.obv_ma_window).mean()
        for i in range(self.obv_ma_window + 1, len(df)):
            curr = df.iloc[i]; prev = df.iloc[i-1]
            if pd.isna(curr["obv_ma"]): continue
            if curr["close"] > prev["close"] and curr["obv"] < prev["obv"] and curr["obv"] < curr["obv_ma"]:
                df.iloc[i, df.columns.get_loc("signal")] = -1
                df.iloc[i, df.columns.get_loc("signal_strength")] = 0.6
            elif curr["close"] < prev["close"] and curr["obv"] > prev["obv"] and curr["obv"] > curr["obv_ma"]:
                df.iloc[i, df.columns.get_loc("signal")] = 1
                df.iloc[i, df.columns.get_loc("signal_strength")] = 0.6
        return df


class VWAPStrategy(BaseStrategy):
    """VWAP成交量加权平均价策略：价格在VWAP上方做多，下方做空"""
    def __init__(self, window=20, entry_threshold=0.01, exit_threshold=0.005, **kwargs):
        params = {"window": window, "entry_threshold": entry_threshold, "exit_threshold": exit_threshold}
        params.update(kwargs)
        super().__init__("VWAP策略", params)
        self.window = window; self.entry_threshold = entry_threshold; self.exit_threshold = exit_threshold

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self._add_signal_columns(df)
        if len(df) < self.window:
            return df
        typical_price = (df["high"] + df["low"] + df["close"]) / 3
        df["vwap"] = (typical_price * df["volume"]).rolling(window=self.window).sum() / \
                     df["volume"].rolling(window=self.window).sum()
        position = 0
        for i in range(self.window, len(df)):
            price = df["close"].iloc[i]; vwap = df["vwap"].iloc[i]
            prev_price = df["close"].iloc[i-1]; prev_vwap = df["vwap"].iloc[i-1]
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


# ============================================================
# SENTIMENT — 情绪策略 (合并: sentiment_cycle + sentiment_news + sentiment_contrarian)
# ============================================================

class SentimentStrategy(BaseStrategy):
    """情绪策略（合并: sentiment_cycle + sentiment_news + sentiment_contrarian）
    mode='cycle': 情绪冰点→回暖→高潮→退潮
    mode='news': 舆情利好/利空驱动
    mode='contrarian': 舆情反向思维（别人恐惧我贪婪）
    """
    def __init__(self,
                 fear_period: int = 20, greed_period: int = 10,
                 fear_threshold: float = 0.3, greed_threshold: float = 0.8,
                 sentiment_window: int = 3,
                 buy_sentiment_score: float = 0.3, sell_sentiment_score: float = -0.3,
                 use_tech_confirm: bool = True,
                 extreme_threshold: float = 0.5, reversal_window: int = 5,
                 mode: str = "cycle", **kwargs):
        params = {
            "fear_period": fear_period, "greed_period": greed_period,
            "fear_threshold": fear_threshold, "greed_threshold": greed_threshold,
            "sentiment_window": sentiment_window,
            "buy_sentiment_score": buy_sentiment_score,
            "sell_sentiment_score": sell_sentiment_score,
            "use_tech_confirm": use_tech_confirm,
            "extreme_threshold": extreme_threshold,
            "reversal_window": reversal_window,
            "mode": mode,
        }
        params.update(kwargs)
        label_map = {"cycle": "情绪周期", "news": "舆情策略", "contrarian": "舆情反转"}
        super().__init__(label_map.get(mode, "情绪策略"), params)
        self.fear_period = fear_period; self.greed_period = greed_period
        self.fear_threshold = fear_threshold; self.greed_threshold = greed_threshold
        self.sentiment_window = sentiment_window
        self.buy_sentiment_score = buy_sentiment_score
        self.sell_sentiment_score = sell_sentiment_score
        self.use_tech_confirm = use_tech_confirm
        self.extreme_threshold = extreme_threshold
        self.reversal_window = reversal_window
        self.mode = mode
        self._sentiment_data = None

    def _get_sentiment_data(self, df: pd.DataFrame) -> pd.Series:
        if "sentiment_score" in df.columns:
            return df["sentiment_score"]
        if self._sentiment_data is None:
            self._sentiment_data = pd.Series([0] * len(df), index=df.index)
        return self._sentiment_data

    def _calc_sentiment(self, df: pd.DataFrame) -> pd.Series:
        if len(df) < max(self.fear_period, self.greed_period):
            return pd.Series(0.5, index=df.index)
        volatility = df["close"].pct_change().rolling(window=self.fear_period).std()
        avg_vol = volatility.expanding().mean()
        sentiment = 1 - (volatility / avg_vol.clip(lower=1e-8))
        vol_ratio = df["volume"] / df["volume"].rolling(window=self.fear_period).mean()
        sentiment = sentiment * (vol_ratio / (1 + vol_ratio))
        mom = df["close"].pct_change(self.greed_period)
        sentiment = sentiment * (1 + mom.clip(-1, 1))
        return sentiment.clip(0, 1)

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self._add_signal_columns(df)
        if self.mode == "news":
            return self._mode_news(df)
        elif self.mode == "contrarian":
            return self._mode_contrarian(df)
        return self._mode_cycle(df)

    def _mode_cycle(self, df: pd.DataFrame) -> pd.DataFrame:
        min_len = max(self.fear_period, self.greed_period)
        if len(df) < min_len:
            return df
        df["sentiment"] = self._calc_sentiment(df)
        position = 0
        for i in range(min_len, len(df)):
            curr_s = df["sentiment"].iloc[i]
            prev_s = df["sentiment"].iloc[i-1]
            if position == 0:
                if curr_s < self.fear_threshold and prev_s >= self.fear_threshold:
                    df.iloc[i, df.columns.get_loc("signal")] = 1
                    df.iloc[i, df.columns.get_loc("signal_strength")] = (self.fear_threshold - curr_s) / self.fear_threshold
                    position = 1
            elif position == 1:
                if curr_s > self.greed_threshold and prev_s <= self.greed_threshold:
                    df.iloc[i, df.columns.get_loc("signal")] = -1
                    df.iloc[i, df.columns.get_loc("signal_strength")] = (curr_s - self.greed_threshold) / (1 - self.greed_threshold)
                    position = 0
                elif curr_s > 0.6 and prev_s <= 0.6:
                    df.iloc[i, df.columns.get_loc("signal")] = -1
                    df.iloc[i, df.columns.get_loc("signal_strength")] = 0.5
                    position = 0
        return df

    def _check_tech_confirm(self, df, i):
        if not self.use_tech_confirm:
            return True
        if i < 20:
            return False
        close = df["close"].iloc[i]
        ma5 = df["close"].iloc[i-5:i].mean()
        ma20 = df["close"].iloc[i-20:i].mean()
        return close > ma5 and ma5 > ma20

    def _mode_news(self, df: pd.DataFrame) -> pd.DataFrame:
        if len(df) < self.sentiment_window + 10:
            return df
        sentiment = self._get_sentiment_data(df)
        sma = sentiment.rolling(window=self.sentiment_window).mean()
        position = 0
        for i in range(self.sentiment_window + 10, len(df)):
            curr_s = sma.iloc[i]; prev_s = sma.iloc[i-1]
            tech_ok = self._check_tech_confirm(df, i)
            if position == 0:
                if curr_s >= self.buy_sentiment_score and prev_s < self.buy_sentiment_score:
                    if tech_ok or not self.use_tech_confirm:
                        df.iloc[i, df.columns.get_loc("signal")] = 1
                        df.iloc[i, df.columns.get_loc("signal_strength")] = min(curr_s + 0.5, 1.0)
                        position = 1
            else:
                if curr_s <= self.sell_sentiment_score and prev_s > self.sell_sentiment_score:
                    df.iloc[i, df.columns.get_loc("signal")] = -1
                    df.iloc[i, df.columns.get_loc("signal_strength")] = min(abs(curr_s) + 0.5, 1.0)
                    position = 0
        return df

    def _mode_contrarian(self, df: pd.DataFrame) -> pd.DataFrame:
        if len(df) < self.reversal_window + 10:
            return df
        sentiment = self._get_sentiment_data(df)
        position = 0
        for i in range(self.reversal_window + 10, len(df)):
            window_s = sentiment.iloc[i - self.reversal_window:i]
            avg_s = window_s.mean(); min_s = window_s.min(); max_s = window_s.max()
            curr_s = sentiment.iloc[i]
            if position == 0:
                if avg_s <= -self.extreme_threshold and min_s <= -0.6 and curr_s > -0.2:
                    df.iloc[i, df.columns.get_loc("signal")] = 1
                    df.iloc[i, df.columns.get_loc("signal_strength")] = 0.8
                    position = 1
            else:
                if avg_s >= self.extreme_threshold and max_s >= 0.6 and curr_s < 0.2:
                    df.iloc[i, df.columns.get_loc("signal")] = -1
                    df.iloc[i, df.columns.get_loc("signal_strength")] = 0.8
                    position = 0
        return df


# ============================================================
# SECTOR / ROTATION — 行业/轮动类 (合并: sector_rotation + prosperity_investment)
# ============================================================

class SectorRotationStrategy(BaseStrategy):
    """行业轮动/景气度策略（合并: sector_rotation + prosperity_investment）
    mode='rotation': 行业轮动（估值+动量综合评分）
    mode='prosperity': 景气度投资（行业高增长+量价配合）
    """
    def __init__(self,
                 lookback: int = 60, momentum_window: int = 20,
                 value_threshold: float = 0.3, momentum_threshold: float = 0.1,
                 growth_window: int = 30, min_growth_rate: float = 0.15,
                 volume_confirm: bool = True, volume_threshold: float = 1.5,
                 mode: str = "rotation", **kwargs):
        params = {
            "lookback": lookback, "momentum_window": momentum_window,
            "value_threshold": value_threshold, "momentum_threshold": momentum_threshold,
            "growth_window": growth_window, "min_growth_rate": min_growth_rate,
            "volume_confirm": volume_confirm, "volume_threshold": volume_threshold,
            "mode": mode,
        }
        params.update(kwargs)
        label_map = {"rotation": "行业轮动", "prosperity": "景气度投资"}
        super().__init__(label_map.get(mode, "行业轮动"), params)
        self.lookback = lookback; self.momentum_window = momentum_window
        self.value_threshold = value_threshold; self.momentum_threshold = momentum_threshold
        self.growth_window = growth_window; self.min_growth_rate = min_growth_rate
        self.volume_confirm = volume_confirm; self.volume_threshold = volume_threshold
        self.mode = mode

    def _calc_value_score(self, df):
        pe = df.get("pe", pd.Series([15]*len(df), index=df.index))
        pb = df.get("pb", pd.Series([1.5]*len(df), index=df.index))
        pe_score = 1 - ((pe - 10) / 30).clip(0, 1)
        pb_score = 1 - ((pb - 0.5) / 3).clip(0, 1)
        return (pe_score + pb_score) / 2

    def _calc_momentum_score(self, df):
        mom = df["close"].pct_change(self.momentum_window)
        avg_mom = mom.expanding().mean()
        return ((mom - avg_mom) / (avg_mom.abs() + 1e-8) + 1).clip(0, 1) / 2

    def _calc_growth_score(self, df):
        price_growth = df["close"].pct_change(self.growth_window)
        if self.volume_confirm:
            avg_vol = df["volume"].rolling(window=self.growth_window).mean()
            vol_ratio = df["volume"] / avg_vol
            score = price_growth * 0.7 + (vol_ratio - 1) * 0.3
        else:
            score = price_growth
        return score.clip(-1, 1)

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self._add_signal_columns(df)
        if self.mode == "prosperity":
            return self._mode_prosperity(df)
        return self._mode_rotation(df)

    def _mode_rotation(self, df):
        if len(df) < self.lookback:
            return df
        df["value_score"] = self._calc_value_score(df)
        df["momentum_score"] = self._calc_momentum_score(df)
        df["combined_score"] = df["value_score"] * 0.3 + df["momentum_score"] * 0.7
        position = 0; entry_score = 0
        for i in range(self.lookback, len(df)):
            curr = df["combined_score"].iloc[i]
            prev = df["combined_score"].iloc[i-1]
            if position == 0:
                if curr > self.value_threshold and curr > prev:
                    df.iloc[i, df.columns.get_loc("signal")] = 1
                    df.iloc[i, df.columns.get_loc("signal_strength")] = curr
                    position = 1; entry_score = curr
            else:
                if curr < entry_score - 0.2 or curr > entry_score + 0.3:
                    df.iloc[i, df.columns.get_loc("signal")] = -1
                    df.iloc[i, df.columns.get_loc("signal_strength")] = abs(curr - entry_score)
                    position = 0
        return df

    def _mode_prosperity(self, df):
        if len(df) < self.growth_window * 2:
            return df
        df["growth_score"] = self._calc_growth_score(df)
        position = 0
        for i in range(self.growth_window * 2, len(df)):
            curr_g = df["growth_score"].iloc[i]
            prev_g = df["growth_score"].iloc[i-1]
            vol_ratio = df["volume"].iloc[i] / df["volume"].iloc[i-20:i].mean() if i >= 20 else 1
            if position == 0:
                if curr_g > self.min_growth_rate and prev_g <= self.min_growth_rate:
                    if not self.volume_confirm or vol_ratio > self.volume_threshold:
                        df.iloc[i, df.columns.get_loc("signal")] = 1
                        df.iloc[i, df.columns.get_loc("signal_strength")] = min(curr_g * 2, 1.0)
                        position = 1
            else:
                if curr_g < -0.05 or (prev_g > curr_g and i >= 5 and
                    df["growth_score"].iloc[i] < df["growth_score"].iloc[i-5]):
                    df.iloc[i, df.columns.get_loc("signal")] = -1
                    df.iloc[i, df.columns.get_loc("signal_strength")] = 0.6
                    position = 0
        return df


# ============================================================
# ACTIVE TRADING — 主动/波段交易类 (合并: band_operation + dragon_head)
# ============================================================

class ActiveTradingStrategy(BaseStrategy):
    """主动交易策略（合并: band_operation + dragon_head）
    mode='swing': 波段操作 — 低吸高抛，不追高
    mode='dragon_head': 龙头战法 — 只做最强龙头，快进快出
    """
    def __init__(self,
                 band_window: int = 20, buy_band_pct: float = 0.3,
                 sell_band_pct: float = 0.7, min_hold_days: int = 5,
                 max_hold_days: int = 60,
                 strength_window: int = 20, limit_up_threshold: float = 0.095,
                 breakout_confirm: bool = True, stop_loss_pct: float = 0.03,
                 mode: str = "swing", **kwargs):
        params = {
            "band_window": band_window, "buy_band_pct": buy_band_pct,
            "sell_band_pct": sell_band_pct, "min_hold_days": min_hold_days,
            "max_hold_days": max_hold_days,
            "strength_window": strength_window,
            "limit_up_threshold": limit_up_threshold,
            "breakout_confirm": breakout_confirm,
            "stop_loss_pct": stop_loss_pct,
            "mode": mode,
        }
        params.update(kwargs)
        label_map = {"swing": "波段操作", "dragon_head": "龙头战法"}
        super().__init__(label_map.get(mode, "主动交易"), params)
        self.band_window = band_window; self.buy_band_pct = buy_band_pct
        self.sell_band_pct = sell_band_pct; self.min_hold_days = min_hold_days
        self.max_hold_days = max_hold_days
        self.strength_window = strength_window
        self.limit_up_threshold = limit_up_threshold
        self.breakout_confirm = breakout_confirm
        self.stop_loss_pct = stop_loss_pct
        self.mode = mode

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self._add_signal_columns(df)
        if self.mode == "dragon_head":
            return self._mode_dragon_head(df)
        return self._mode_swing(df)

    def _mode_swing(self, df):
        if len(df) < self.band_window:
            return df
        df["band_high"] = df["close"].rolling(window=self.band_window).quantile(self.sell_band_pct)
        df["band_low"] = df["close"].rolling(window=self.band_window).quantile(self.buy_band_pct)
        position = 0; entry_price = 0; hold_days = 0
        for i in range(self.band_window, len(df)):
            price = df["close"].iloc[i]
            band_high = df["band_high"].iloc[i]; band_low = df["band_low"].iloc[i]
            if position == 0:
                if price <= band_low:
                    df.iloc[i, df.columns.get_loc("signal")] = 1
                    df.iloc[i, df.columns.get_loc("signal_strength")] = min((band_low - price) / band_low + 0.5, 1.0)  # 归一化至 [0,1]
                    position = 1; entry_price = price; hold_days = 0
            else:
                hold_days += 1
                if hold_days >= self.min_hold_days:
                    should_sell = False; strength = 0.5
                    if price >= band_high:
                        should_sell = True; strength = (price - band_high) / band_high + 0.5
                    elif hold_days >= self.max_hold_days:
                        should_sell = True; strength = 0.7
                    elif price > entry_price * 1.05 and hold_days >= self.min_hold_days * 2:
                        should_sell = True; strength = 0.8
                    if should_sell:
                        df.iloc[i, df.columns.get_loc("signal")] = -1
                        df.iloc[i, df.columns.get_loc("signal_strength")] = min(strength, 1.0)
                        position = 0
        return df

    def _is_limit_up(self, df, i):
        if i < 1: return False
        prev_close = df["close"].iloc[i-1]
        curr_close = df["close"].iloc[i]
        curr_high = df["high"].iloc[i]
        return (curr_close / prev_close - 1) >= self.limit_up_threshold and curr_high >= curr_close

    def _is_breakout(self, df, i):
        if i < self.strength_window: return False
        highs = df["high"].iloc[i-self.strength_window:i].max()
        return df["close"].iloc[i] > highs

    def _mode_dragon_head(self, df):
        if len(df) < self.strength_window:
            return df
        df["strength"] = df["close"].pct_change(self.strength_window)
        df["volume_ma"] = df["volume"].rolling(window=10).mean()
        df["volume_ratio"] = df["volume"] / df["volume_ma"]
        position = 0; entry_price = 0; hold_days = 0
        for i in range(self.strength_window, len(df)):
            is_limit = self._is_limit_up(df, i)
            is_breakout = self._is_breakout(df, i)
            vol_ratio = df["volume_ratio"].iloc[i]
            strength = df["strength"].iloc[i]
            if position == 0:
                if is_limit and strength > 0.1 and vol_ratio > 1.5:
                    if not self.breakout_confirm or is_breakout:
                        df.iloc[i, df.columns.get_loc("signal")] = 1
                        df.iloc[i, df.columns.get_loc("signal_strength")] = min(strength * 2 + 0.5, 1.0)
                        position = 1; entry_price = df["close"].iloc[i]; hold_days = 0
            else:
                hold_days += 1
                curr_price = df["close"].iloc[i]
                should_sell = False; sell_strength = 0.5
                if curr_price < entry_price * (1 - self.stop_loss_pct):
                    should_sell = True; sell_strength = 0.9
                elif hold_days >= self.max_hold_days:
                    should_sell = True; sell_strength = 0.6
                elif i > 0 and df["close"].iloc[i] < df["close"].iloc[i-1] * 0.97:
                    should_sell = True; sell_strength = 0.7
                if should_sell:
                    df.iloc[i, df.columns.get_loc("signal")] = -1
                    df.iloc[i, df.columns.get_loc("signal_strength")] = min(sell_strength, 1.0)
                    position = 0
        return df


# ============================================================
# VALUE — 价值投资 (独立)
# ============================================================

class ValueInvestmentStrategy(BaseStrategy):
    """价值投资策略：长期持有优质股票（ROE高、PE低、分红稳定）"""
    def __init__(self, rebalance_days: int = 250, min_roe: float = 0.15,
                 max_pe: float = 30, min_dividend: float = 0.02,
                 trend_window: int = 60, **kwargs):
        params = {
            "rebalance_days": rebalance_days, "min_roe": min_roe,
            "max_pe": max_pe, "min_dividend": min_dividend,
            "trend_window": trend_window,
        }
        params.update(kwargs)
        super().__init__("价值投资", params)
        self.rebalance_days = rebalance_days; self.min_roe = min_roe
        self.max_pe = max_pe; self.min_dividend = min_dividend
        self.trend_window = trend_window

    def _calc_value_score(self, df):
        roe = df.get("roe", pd.Series([0.2]*len(df), index=df.index))
        pe = df.get("pe", pd.Series([20]*len(df), index=df.index))
        div = df.get("dividend_yield", pd.Series([0.03]*len(df), index=df.index))
        roe_score = (roe / self.min_roe).clip(0, 2)
        pe_score = (self.max_pe / pe.clip(1, None)).clip(0, 2)
        div_score = (div / self.min_dividend).clip(0, 2)
        return ((roe_score * 0.4 + pe_score * 0.3 + div_score * 0.3) / 2).clip(0, 1)

    def _check_trend(self, df, i):
        if i < self.trend_window: return True
        recent = df["close"].iloc[i-self.trend_window:i].values
        return recent[-1] > recent[0] * 0.95

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self._add_signal_columns(df)
        min_len = max(self.rebalance_days, self.trend_window)
        if len(df) < min_len:
            return df
        df["value_score"] = self._calc_value_score(df)
        position = 0; last_rebalance = 0
        for i in range(min_len, len(df)):
            days_since = i - last_rebalance
            vs = df["value_score"].iloc[i]
            trend_ok = self._check_trend(df, i)
            if position == 0:
                if vs > 0.5 and trend_ok:
                    df.iloc[i, df.columns.get_loc("signal")] = 1
                    df.iloc[i, df.columns.get_loc("signal_strength")] = vs
                    position = 1; last_rebalance = i
            else:
                should_rebalance = days_since >= self.rebalance_days or (not trend_ok and vs < 0.4)
                if should_rebalance:
                    df.iloc[i, df.columns.get_loc("signal")] = -1
                    df.iloc[i, df.columns.get_loc("signal_strength")] = 0.5
                    position = 0
                    if vs > 0.5:
                        df.iloc[i, df.columns.get_loc("signal")] = 1
                        df.iloc[i, df.columns.get_loc("signal_strength")] = vs
                        position = 1; last_rebalance = i
        return df


# ============================================================
# 策略注册表（18个核心策略）
# ============================================================

STRATEGY_REGISTRY = {
    # ---- 趋势跟踪 (4) ----
    "ma_cross":      MACrossStrategy,          # 均线交叉/排列/动量 (合并原ma_cross, ma_alignment, momentum)
    "macd":          MACDStrategy,             # MACD金叉死叉/多时间框架 (合并原macd, macd_multitimeframe)
    "trend_following": TrendFollowingStrategy,  # ADX趋势跟踪 (不变)
    "sar":           ParabolicSARStrategy,      # SAR抛物线 (不变)

    # ---- 震荡指标 (3) ----
    "kdj":           KDJStrategy,              # KDJ (不变)
    "rsi":           RSIStrategy,              # RSI超买超卖/MFI资金流 (合并原rsi, mfi)
    "bollinger":     BollingerStrategy,        # 布林带/均值回归 (合并原bollinger, mean_reversion)

    # ---- 突破 (3) ----
    "dual_thrust":   DualThrustStrategy,       # 双轨突破 (不变)
    "turtle":        TurtleStrategy,           # 海龟交易 (不变)
    "volume_breakout": VolumeBreakoutStrategy, # 量价/波动率突破 (合并原volume_breakout, volatility_breakout)

    # ---- 支撑阻力 (1) ----
    "support_resistance": SupportResistanceStrategy,  # 支撑阻力 (不变)

    # ---- K线形态 (1) ----
    "pattern":       PatternStrategy,          # 缺口回补/三白兵三乌鸦 (合并原gap, three_soldiers)

    # ---- 量价 (2) ----
    "obv":           OBVStrategy,              # OBV能量潮 (不变)
    "vwap":          VWAPStrategy,             # VWAP (不变)

    # ---- 情绪 (1) ----
    "sentiment":     SentimentStrategy,        # 情绪周期/舆情/反转 (合并原sentiment_cycle, sentiment_news, sentiment_contrarian)

    # ---- 行业/轮动 (1) ----
    "sector_rotation": SectorRotationStrategy, # 行业轮动/景气度 (合并原sector_rotation, prosperity_investment)

    # ---- 主动交易 (1) ----
    "active_trading": ActiveTradingStrategy,   # 波段操作/龙头战法 (合并原band_operation, dragon_head)

    # ---- 价值投资 (1) ----
    "value_investment": ValueInvestmentStrategy,  # 价值投资 (不变)
}


# ============================================================
# 兼容性映射：旧key → 新策略 + 推荐mode
# ============================================================

# 被合并的旧策略映射（用于兼容查询或迁移）
MERGE_MAP = {
    # 旧key → (新key, 新mode)
    "ma_alignment":         ("ma_cross", "alignment"),
    "momentum":             ("ma_cross", "momentum"),
    "macd_multitimeframe":  ("macd", "multitimeframe"),
    "mfi":                  ("rsi", "mfi"),
    "mean_reversion":       ("bollinger", "zscore"),
    "volatility_breakout":  ("volume_breakout", "volatility"),
    "gap":                  ("pattern", "gap"),
    "three_soldiers":       ("pattern", "three_soldiers"),
    "sentiment_cycle":      ("sentiment", "cycle"),
    "sentiment_news":       ("sentiment", "news"),
    "sentiment_contrarian": ("sentiment", "contrarian"),
    "prosperity_investment":("sector_rotation", "prosperity"),
    "band_operation":       ("active_trading", "swing"),
    "dragon_head":          ("active_trading", "dragon_head"),
}

# 独立保留（key不变）的策略
INDEPENDENT_KEYS = {
    "ma_cross", "macd", "trend_following", "sar",
    "kdj", "rsi", "bollinger",
    "dual_thrust", "turtle", "volume_breakout",
    "support_resistance", "pattern", "obv", "vwap",
    "sentiment", "sector_rotation", "active_trading",
    "value_investment",
}


# ============================================================
# 工厂函数 (与 original strategies.py 兼容)
# ============================================================

def get_strategy(name: str, params: dict = None) -> BaseStrategy:
    """获取策略实例（支持新旧key自动兼容）"""
    params = params or {}
    cls = STRATEGY_REGISTRY.get(name)

    # 检查是否旧 key（被合并的）
    if cls is None and name in MERGE_MAP:
        new_key, mode = MERGE_MAP[name]
        cls = STRATEGY_REGISTRY[new_key]
        # 自动注入 mode 参数（不覆盖用户显式指定）
        if "mode" not in params:
            params["mode"] = mode

    if cls is None:
        raise ValueError(
            f"Unknown strategy: '{name}'. "
            f"Available: {list(STRATEGY_REGISTRY.keys())}. "
            f"Merged old keys (use with mode param): {list(MERGE_MAP.keys())}"
        )

    strategy = cls(**params)
    strategy.key = name
    return strategy


def list_strategies() -> list:
    """列出所有已注册的策略"""
    result = []
    for key, cls in STRATEGY_REGISTRY.items():
        strategy = cls()
        info = strategy.get_info()
        info["key"] = key
        result.append(info)
    return result


def get_merge_info() -> dict:
    """获取合并信息：哪些旧策略被合并到了哪里"""
    return {
        "total_original": 29,
        "total_optimized": len(STRATEGY_REGISTRY),
        "reduced_by": 29 - len(STRATEGY_REGISTRY),
        "merged": {
            old: {"into": new, "mode": mode}
            for old, (new, mode) in sorted(MERGE_MAP.items())
        },
        "independent": sorted(INDEPENDENT_KEYS),
    }
