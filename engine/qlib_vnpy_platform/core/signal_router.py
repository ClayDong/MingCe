"""信号融合路由 — 动态权重融合 + 信号独立性评估。

改进点：
1. 动态权重：根据市场波动率自适应调整 QLib/LLM 权重
2. 信号独立性：多策略相关时降低置信度
3. Bayesian 融合替代简单线性加权
"""

import math
from loguru import logger
from qlib_vnpy_platform.config import get_config


class SignalRouter:
    """信号融合路由，支持动态权重调节和信号独立性评估。"""

    # 策略类别分组（同组策略高度相关，信号应折价）
    # 涵盖 strategies.py 和 strategies_optimized.py 中的所有策略名称
    CORRELATED_GROUPS = {
        "trend": ["MA交叉", "MACD金叉死叉", "MACD多时间框架", "均线多头排列", "SAR抛物线", "ma_cross", "macd"],
        "momentum": ["动量策略", "VWAP策略", "OBV能量潮", "量价突破", "momentum", "vwap"],
        "mean_reversion": ["RSI超买超卖", "KDJ金叉死叉", "均值回归", "MFI资金流", "rsi", "kdj", "mean_reversion", "mfi"],
        "breakout": ["双轨突破(Dual Thrust)", "海龟交易", "布林带突破", "波动率突破", "支撑阻力", "bollinger", "dual_thrust", "turtle"],
        "sentiment": ["情绪周期", "舆情策略", "舆情反转", "龙头战法", "sentiment_cycle", "sector_rotation", "dragon_head"],
    }

    def __init__(self):
        self.config = get_config()["signal"]
        self.weight_qlib_base = self.config.get("weight_qlib", 0.6)
        self.weight_llm_base = self.config.get("weight_llm", 0.4)
        self.buy_threshold = self.config.get("buy_threshold", 0.2)
        self.sell_threshold = self.config.get("sell_threshold", -0.2)
        self.base_risk_ratio = self.config.get("base_risk_ratio", 0.02)
        self.volatility_regime = "normal"  # normal / high / low
        self.market_regime = "neutral"  # trending / mean_reverting / volatile / neutral
        self._signal_history = []
        logger.info(
            f"SignalRouter initialized: w_qlib={self.weight_qlib_base}, "
            f"w_llm={self.weight_llm_base}"
        )

    # 市场状态对应的策略组权重（趋势市加重趋势策略，震荡市加重均值回归策略）
    REGIME_STRATEGY_WEIGHTS = {
        "trending": {
            "trend": 1.3, "momentum": 1.2, "breakout": 1.1,
            "mean_reversion": 0.6, "sentiment": 0.9,
        },
        "mean_reverting": {
            "trend": 0.6, "momentum": 0.7, "breakout": 0.7,
            "mean_reversion": 1.4, "sentiment": 1.0,
        },
        "volatile": {
            "trend": 0.8, "momentum": 0.7, "breakout": 1.3,
            "mean_reversion": 0.8, "sentiment": 0.9,
        },
        "neutral": {
            "trend": 1.0, "momentum": 1.0, "breakout": 1.0,
            "mean_reversion": 1.0, "sentiment": 1.0,
        },
    }

    def set_market_regime(self, regime: str):
        """设置市场状态（来自 regime_detector）。

        Args:
            regime: trending / mean_reverting / volatile / neutral
        """
        if regime in self.REGIME_STRATEGY_WEIGHTS:
            self.market_regime = regime
            logger.info(f"SignalRouter market regime set to: {regime}")
        else:
            logger.warning(f"Invalid market regime: {regime}, keeping {self.market_regime}")

    def _get_strategy_group_weight(self, strategy_name: str) -> float:
        """根据当前市场状态，获取某策略的权重系数。

        趋势市：趋势/动量策略权重 ×1.3，均值回归策略 ×0.6
        震荡市：均值回归策略 ×1.4，趋势策略 ×0.6
        """
        weights = self.REGIME_STRATEGY_WEIGHTS.get(self.market_regime, self.REGIME_STRATEGY_WEIGHTS["neutral"])

        for group, members in self.CORRELATED_GROUPS.items():
            if strategy_name in members:
                return weights.get(group, 1.0)

        return 1.0  # 未知分组默认权重 1.0

    def arbitrate_conflicting_signals(self, strategies: list[dict]) -> dict:
        """仲裁冲突信号 — 按市场状态加权投票。

        当多个策略给出矛盾信号（如 MA 金叉买入 vs RSI 超买卖出）时，
        根据当前市场状态对策略组加权，输出最终方向。

        Args:
            strategies: 策略信号列表，每个 dict 包含 strategy/signal 字段

        Returns:
            {
                "direction": "BUY"/"SELL"/"HOLD",
                "confidence": float,
                "vote_summary": {"buy_weight": ..., "sell_weight": ..., "hold_weight": ...},
                "dominant_group": str,
                "conflict_detected": bool,
            }
        """
        if not strategies:
            return {
                "direction": "HOLD", "confidence": 0.0,
                "vote_summary": {"buy_weight": 0, "sell_weight": 0, "hold_weight": 0},
                "dominant_group": "", "conflict_detected": False,
            }

        buy_weight = 0.0
        sell_weight = 0.0
        hold_weight = 0.0
        group_votes = {}

        for s in strategies:
            name = s.get("strategy", s.get("strategy_name", ""))
            signal = s.get("signal", s.get("direction", "HOLD")).upper()
            strength = abs(float(s.get("signal_strength", s.get("confidence", 0.5)) or 0.5))

            group_weight = self._get_strategy_group_weight(name)
            vote_weight = group_weight * (0.5 + strength * 0.5)  # 信号强度也影响权重

            # 识别策略所属组
            strategy_group = "independent"
            for group, members in self.CORRELATED_GROUPS.items():
                if name in members:
                    strategy_group = group
                    break

            if signal == "BUY":
                buy_weight += vote_weight
                group_votes.setdefault(strategy_group, {"buy": 0, "sell": 0, "hold": 0})["buy"] += 1
            elif signal == "SELL":
                sell_weight += vote_weight
                group_votes.setdefault(strategy_group, {"buy": 0, "sell": 0, "hold": 0})["sell"] += 1
            else:
                hold_weight += vote_weight
                group_votes.setdefault(strategy_group, {"buy": 0, "sell": 0, "hold": 0})["hold"] += 1

        total_weight = buy_weight + sell_weight + hold_weight
        if total_weight <= 0:
            return {
                "direction": "HOLD", "confidence": 0.0,
                "vote_summary": {"buy_weight": 0, "sell_weight": 0, "hold_weight": 0},
                "dominant_group": "", "conflict_detected": False,
            }

        # 判断方向
        if buy_weight > sell_weight and buy_weight > hold_weight:
            direction = "BUY"
            confidence = buy_weight / total_weight
            dominant_group = max(group_votes.items(), key=lambda x: x[1]["buy"])[0] if group_votes else ""
        elif sell_weight > buy_weight and sell_weight > hold_weight:
            direction = "SELL"
            confidence = sell_weight / total_weight
            dominant_group = max(group_votes.items(), key=lambda x: x[1]["sell"])[0] if group_votes else ""
        else:
            direction = "HOLD"
            confidence = hold_weight / total_weight
            dominant_group = ""

        # 冲突检测：买卖权重都较高
        conflict_detected = (
            min(buy_weight, sell_weight) > total_weight * 0.25
            and abs(buy_weight - sell_weight) < total_weight * 0.2
        )

        return {
            "direction": direction,
            "confidence": round(confidence, 4),
            "vote_summary": {
                "buy_weight": round(buy_weight, 2),
                "sell_weight": round(sell_weight, 2),
                "hold_weight": round(hold_weight, 2),
            },
            "dominant_group": dominant_group,
            "conflict_detected": conflict_detected,
            "market_regime": self.market_regime,
        }

    def _get_dynamic_weights(self) -> tuple[float, float]:
        """根据市场波动率状态动态调整 QLib/LLM 权重。

        - 高波动（趋势市）: 加重 QLib（量化模型擅长趋势）
        - 低波动（震荡市）: 加重 LLM（宏观判断更有效）
        - 正常: 使用基础权重
        """
        w_qlib = self.weight_qlib_base
        w_llm = self.weight_llm_base

        if self.volatility_regime == "high":
            # 高波动趋势市 → QLib 占 70%
            w_qlib = min(w_qlib * 1.2, 0.8)
            w_llm = 1.0 - w_qlib
        elif self.volatility_regime == "low":
            # 低波动震荡市 → LLM 占 50%
            w_llm = min(w_llm * 1.3, 0.6)
            w_qlib = 1.0 - w_llm

        return w_qlib, w_llm

    def set_volatility_regime(self, regime: str):
        """设置当前市场波动状态。"""
        if regime in ("high", "normal", "low"):
            self.volatility_regime = regime
            logger.info(f"SignalRouter volatility regime set to: {regime}")
        else:
            logger.warning(f"Invalid volatility regime: {regime}, keeping {self.volatility_regime}")

    @staticmethod
    def _estimate_signal_independence(strategies: list[dict]) -> float:
        """评估多个策略信号的独立性程度。

        相同类别组的策略越多 → 独立性越低 → 置信度折扣越大。
        返回 0~1 的折扣因子：
        - 1.0 = 完全独立
        - 0.5 = 一半信号相关
        - 0.0 = 全部相关
        """
        if not strategies:
            return 1.0

        group_counts = {}
        for s in strategies:
            name = s.get("strategy", s.get("strategy_name", ""))
            for group, members in SignalRouter.CORRELATED_GROUPS.items():
                if name in members:
                    group_counts[group] = group_counts.get(group, 0) + 1
                    break
            else:
                # 不在任何已知分组，视为独立
                group_counts["independent"] = group_counts.get("independent", 0) + 1

        if not group_counts:
            return 1.0

        # 同组策略占比越高，独立性越低
        total = len(strategies)
        max_group_ratio = max(group_counts.values()) / total if total > 0 else 0

        # 折扣因子：最大同组占比超过 40% 时开始打折
        penalty = max(0.0, (max_group_ratio - 0.4) / 0.6)
        independence = 1.0 - penalty * 0.5  # 最多打 5 折

        return max(0.5, min(1.0, independence))

    def fuse_signals(
        self,
        symbol: str,
        qlib_pred: float = None,
        llm_result: dict = None,
        current_price: float = None,
        strategies: list[dict] = None,
    ) -> dict:
        """融合 QLib 和 LLM 信号，输出综合判断。

        使用 Bayesian 启发式融合 + 信号独立性折扣。

        Args:
            symbol: 股票代码
            qlib_pred: QLib 预测值 (0~1)
            llm_result: LLM 分析结果
            current_price: 当前价格
            strategies: 用于评估独立性的策略信号列表

        Returns:
            融合后的信号字典
        """
        qlib_score = self._qlib_to_signal(qlib_pred) if qlib_pred is not None else 0.0
        llm_score = self._llm_to_signal(llm_result) if llm_result else 0.0

        has_qlib = qlib_pred is not None
        has_llm = llm_result is not None and not llm_result.get("error")

        # 动态权重
        w_qlib, w_llm = self._get_dynamic_weights()

        if has_qlib and has_llm:
            # Bayesian 启发式融合：当两者方向一致时增强置信度
            if qlib_score * llm_score > 0:
                # 方向一致：增大权重，增强信号
                alignment_bonus = abs(qlib_score * llm_score) * 0.3
                final_score = w_qlib * qlib_score + w_llm * llm_score
                final_score += alignment_bonus * (1 if final_score > 0 else -1)
            else:
                # 方向相反：使用加权平均，降低置信度
                final_score = w_qlib * qlib_score + w_llm * llm_score

            confidence = abs(final_score)

            # 信号独立性折扣
            if strategies:
                independence = self._estimate_signal_independence(strategies)
                confidence *= independence
        elif has_qlib:
            final_score = qlib_score
            confidence = abs(qlib_score) * 0.8
        elif has_llm:
            final_score = llm_score
            confidence = abs(llm_score) * 0.8
        else:
            final_score = 0.0
            confidence = 0.0

        direction = self._score_to_direction(final_score)

        # 信号冲突仲裁：如果策略列表存在且方向冲突，使用市场状态加权投票
        arbitration = None
        if strategies and len(strategies) >= 2:
            arbitration = self.arbitrate_conflicting_signals(strategies)
            # 如果仲裁检测到冲突，且仲裁方向与分数方向不一致，以仲裁为准
            if arbitration["conflict_detected"]:
                logger.info(
                    f"信号冲突检测: score方向={direction}, 仲裁方向={arbitration['direction']} "
                    f"(市场状态={self.market_regime}, 主导组={arbitration['dominant_group']})"
                )
                # 冲突时降低置信度
                confidence *= 0.7
                # 如果仲裁方向与分数方向相反，采用仲裁方向
                if arbitration["direction"] != "HOLD" and arbitration["direction"] != direction:
                    direction = arbitration["direction"]
                    logger.info(f"采用仲裁方向: {direction} (覆盖原 {final_score:.4f})")

        signal = {
            "symbol": symbol,
            "direction": direction,
            "score": round(final_score, 4),
            "confidence": round(confidence, 4),
            "current_price": current_price,
            "qlib_score": round(qlib_score, 4),
            "llm_score": round(llm_score, 4),
            "qlib_pred": qlib_pred,
            "llm_signal": llm_result.get("signal") if llm_result else None,
            "llm_confidence": llm_result.get("confidence") if llm_result else None,
            "target_price": llm_result.get("target_price") if llm_result else None,
            "stop_loss": llm_result.get("stop_loss") if llm_result else None,
            "risk_level": llm_result.get("risk_level", "MEDIUM") if llm_result else "MEDIUM",
            "reason": llm_result.get("reason", "") if llm_result else "",
            "key_factors": llm_result.get("key_factors", []) if llm_result else [],
            "fusion_info": {
                "w_qlib": round(w_qlib, 2),
                "w_llm": round(w_llm, 2),
                "volatility_regime": self.volatility_regime,
                "market_regime": self.market_regime,
                "signal_independence": round(
                    self._estimate_signal_independence(strategies), 2
                )
                if strategies
                else 1.0,
                "aligned": qlib_score * llm_score > 0 if (has_qlib and has_llm) else None,
                "arbitration": arbitration,
            },
        }

        self._signal_history.append(signal)
        if len(self._signal_history) > 1000:
            self._signal_history = self._signal_history[-500:]

        logger.info(
            f"Signal for {symbol}: direction={direction}, score={final_score:.4f}, "
            f"confidence={confidence:.4f} (w_qlib={w_qlib:.2f}, w_llm={w_llm:.2f})"
        )
        return signal

    def signal_to_order(self, signal: dict, account: dict) -> dict:
        if signal["direction"] == "HOLD":
            return {
                "symbol": signal["symbol"],
                "direction": "HOLD",
                "volume": 0,
                "price": signal.get("target_price", 0),
                "reason": "信号为HOLD，不执行交易",
            }

        base_volume = self._calc_position_size(signal, account)
        risk_coeff = self._calc_risk_coefficient(signal, account)

        volume = int(base_volume * signal["confidence"] * risk_coeff / 100) * 100
        volume = max(0, volume)

        current_price = signal.get("current_price") or signal.get("target_price") or 0
        if current_price <= 0:
            current_price = 0

        order = {
            "symbol": signal["symbol"],
            "direction": signal["direction"],
            "volume": volume,
            "price": current_price,
            "target_price": signal.get("target_price"),
            "stop_loss": signal.get("stop_loss"),
            "confidence": signal["confidence"],
            "risk_coeff": risk_coeff,
            "reason": signal.get("reason", ""),
        }

        logger.info(
            f"Order for {signal['symbol']}: direction={order['direction']}, "
            f"volume={volume}, confidence={signal['confidence']:.2f}"
        )
        return order

    def _qlib_to_signal(self, pred_score: float) -> float:
        return (pred_score - 0.5) * 2

    def _llm_to_signal(self, llm_result: dict) -> float:
        signal_map = {"BUY": 1.0, "SELL": -1.0, "HOLD": 0.0}
        direction = llm_result.get("signal", "HOLD")
        confidence = llm_result.get("confidence", 0.5)
        try:
            confidence = float(confidence)
        except (ValueError, TypeError):
            confidence = 0.5
        return signal_map.get(direction, 0.0) * confidence

    def _score_to_direction(self, score: float) -> str:
        if score > self.buy_threshold:
            return "BUY"
        elif score < self.sell_threshold:
            return "SELL"
        return "HOLD"

    def _calc_position_size(self, signal: dict, account: dict) -> float:
        total_capital = account.get("total_capital", 100000)
        current_price = signal.get("current_price") or signal.get("target_price", 0) or 0
        stop_loss = signal.get("stop_loss")

        if current_price is None or current_price <= 0:
            return 0

        if stop_loss and stop_loss > 0 and signal["direction"] == "BUY":
            risk_per_share = current_price - stop_loss
            if risk_per_share > 0:
                position_value = total_capital * self.base_risk_ratio
                shares = position_value / risk_per_share
                return shares

        max_position_value = total_capital * 0.3
        return max_position_value / current_price

    def _calc_risk_coefficient(self, signal: dict, account: dict) -> float:
        coeff = 1.0

        total_capital = account.get("total_capital", 100000)
        daily_pnl = account.get("daily_pnl", 0)
        daily_pnl_pct = daily_pnl / total_capital if total_capital > 0 else 0

        risk_config = get_config()["risk"]
        if daily_pnl_pct < -risk_config.get("daily_loss_warning", 0.03):
            coeff *= 0.5

        if daily_pnl_pct < -risk_config.get("daily_loss_circuit_breaker", 0.05):
            coeff = 0.0

        risk_level = signal.get("risk_level", "MEDIUM")
        risk_level_map = {"LOW": 1.0, "MEDIUM": 0.7, "HIGH": 0.3}
        coeff *= risk_level_map.get(risk_level, 0.7)

        return min(1.0, max(0.0, coeff))

    def get_signal_history(self, symbol: str = None, limit: int = 50) -> list:
        if symbol:
            filtered = [s for s in self._signal_history if s["symbol"] == symbol]
        else:
            filtered = self._signal_history
        return filtered[-limit:]
