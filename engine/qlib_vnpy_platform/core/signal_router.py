from loguru import logger
from qlib_vnpy_platform.config import get_config


class SignalRouter:
    def __init__(self):
        self.config = get_config()["signal"]
        self.weight_qlib = self.config.get("weight_qlib", 0.6)
        self.weight_llm = self.config.get("weight_llm", 0.4)
        self.buy_threshold = self.config.get("buy_threshold", 0.2)
        self.sell_threshold = self.config.get("sell_threshold", -0.2)
        self.base_risk_ratio = self.config.get("base_risk_ratio", 0.02)
        self._signal_history = []
        logger.info(f"SignalRouter initialized: w_qlib={self.weight_qlib}, "
                    f"w_llm={self.weight_llm}")

    def fuse_signals(self, symbol: str, qlib_pred: float = None,
                     llm_result: dict = None, current_price: float = None) -> dict:
        qlib_score = self._qlib_to_signal(qlib_pred) if qlib_pred is not None else 0.0
        llm_score = self._llm_to_signal(llm_result) if llm_result else 0.0

        has_qlib = qlib_pred is not None
        has_llm = llm_result is not None and not llm_result.get("error")

        if has_qlib and has_llm:
            final_score = self.weight_qlib * qlib_score + self.weight_llm * llm_score
            confidence = abs(final_score)
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

        signal = {
            "symbol": symbol,
            "direction": direction,
            "score": final_score,
            "confidence": confidence,
            "current_price": current_price,
            "qlib_score": qlib_score,
            "llm_score": llm_score,
            "qlib_pred": qlib_pred,
            "llm_signal": llm_result.get("signal") if llm_result else None,
            "llm_confidence": llm_result.get("confidence") if llm_result else None,
            "target_price": llm_result.get("target_price") if llm_result else None,
            "stop_loss": llm_result.get("stop_loss") if llm_result else None,
            "risk_level": llm_result.get("risk_level", "MEDIUM") if llm_result else "MEDIUM",
            "reason": llm_result.get("reason", "") if llm_result else "",
            "key_factors": llm_result.get("key_factors", []) if llm_result else [],
        }

        self._signal_history.append(signal)
        if len(self._signal_history) > 1000:
            self._signal_history = self._signal_history[-500:]

        logger.info(f"Signal for {symbol}: direction={direction}, score={final_score:.4f}, "
                    f"confidence={confidence:.4f}")
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

        current_price = signal.get("current_price") or 0
        if current_price <= 0:
            current_price = signal.get("target_price") or 0

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

        logger.info(f"Order for {signal['symbol']}: direction={order['direction']}, "
                    f"volume={volume}, confidence={signal['confidence']:.2f}")
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
        current_price = signal.get("current_price") or signal.get("target_price", 0)
        stop_loss = signal.get("stop_loss")

        if current_price <= 0:
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
