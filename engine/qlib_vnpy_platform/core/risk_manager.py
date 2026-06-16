from datetime import datetime
from loguru import logger
from qlib_vnpy_platform.config import get_config


class RiskManager:
    def __init__(self):
        self.config = get_config()["risk"]
        self.max_single_position = self.config.get("max_single_position", 0.30)
        self.daily_loss_warning = self.config.get("daily_loss_warning", 0.03)
        self.daily_loss_circuit_breaker = self.config.get("daily_loss_circuit_breaker", 0.05)
        self.max_single_loss = self.config.get("max_single_loss", 0.02)
        self.min_confidence = self.config.get("min_confidence", 0.4)
        self.max_sector_concentration = self.config.get("max_sector_concentration", 0.40)
        self.max_holdings = self.config.get("max_holdings", 20)

        self._circuit_breaker_active = False
        self._daily_pnl = 0.0
        self._daily_start_capital = 0.0
        self._warnings = []
        self._last_reset_date = None
        self._sector_map = {}
        logger.info("RiskManager initialized")

    def set_sector_map(self, sector_map: dict):
        self._sector_map = sector_map

    def get_stock_sector(self, symbol: str) -> str:
        return self._sector_map.get(symbol, "其他")

    def check_order(self, order: dict, account: dict, portfolio: dict) -> dict:
        self._check_daily_reset(account)

        result = {
            "approved": True,
            "reason": "",
            "adjusted_volume": order.get("volume", 0),
            "warnings": [],
        }

        if self._circuit_breaker_active:
            result["approved"] = False
            result["reason"] = f"日亏损熔断已触发（日亏损>{self.daily_loss_circuit_breaker*100}%）"
            logger.warning(f"Order rejected: circuit breaker active")
            return result

        if order.get("direction") == "HOLD" or order.get("volume", 0) <= 0:
            return result

        confidence = order.get("confidence", 0)
        if confidence < self.min_confidence:
            result["approved"] = False
            result["reason"] = f"信号置信度({confidence:.2f})低于阈值({self.min_confidence})"
            logger.warning(f"Order rejected: low confidence {confidence:.2f}")
            return result

        symbol = order.get("symbol", "")
        direction = order.get("direction", "")
        volume = order.get("volume", 0)
        price = order.get("price", 0)

        if direction == "BUY":
            current_position_value = portfolio.get("positions", {}).get(symbol, {}).get("market_value", 0)
            order_value = volume * price if price > 0 else 0
            total_capital = account.get("total_capital", 100000)

            if total_capital > 0:
                position_ratio = (current_position_value + order_value) / total_capital
                if position_ratio > self.max_single_position:
                    max_volume = int(
                        (total_capital * self.max_single_position - current_position_value)
                        / price / 100
                    ) * 100 if price > 0 else 0
                    if max_volume <= 0:
                        result["approved"] = False
                        result["reason"] = f"单股持仓超过上限({self.max_single_position*100}%)"
                    else:
                        result["adjusted_volume"] = max_volume
                        result["warnings"].append(
                            f"仓位调整: {volume}→{max_volume}（单股持仓上限）"
                        )
                    logger.warning(f"Position limit: {symbol}, ratio={position_ratio:.2%}")

            num_holdings = len([p for p in portfolio.get("positions", {}).values()
                              if p.get("volume", 0) > 0])
            if symbol not in portfolio.get("positions", {}) and num_holdings >= self.max_holdings:
                result["approved"] = False
                result["reason"] = f"持仓数量已达上限({self.max_holdings})"
                logger.warning(f"Max holdings reached: {num_holdings}")

            sector = self.get_stock_sector(symbol)
            sector_value = order_value
            positions = portfolio.get("positions", {})

            for sym, pos in positions.items():
                if sym != symbol and self.get_stock_sector(sym) == sector:
                    sector_value += pos.get("market_value", 0)

            if total_capital > 0:
                sector_ratio = sector_value / total_capital
                if sector_ratio > self.max_sector_concentration:
                    result["approved"] = False
                    result["reason"] = f"行业集中度超限: {sector}({sector_ratio:.1%})>{self.max_sector_concentration:.0%}"
                    logger.warning(f"Sector concentration limit: {sector}={sector_ratio:.2%}")
                elif sector_ratio > self.max_sector_concentration * 0.8:
                    result["warnings"].append(
                        f"行业集中度预警: {sector}({sector_ratio:.1%}), 阈值{self.max_sector_concentration:.0%}"
                    )

        daily_pnl_pct = self._get_daily_pnl_pct(account)
        if daily_pnl_pct < -self.daily_loss_warning:
            warning = f"日亏损预警: {daily_pnl_pct:.2%}（阈值: -{self.daily_loss_warning:.0%}）"
            result["warnings"].append(warning)
            self._add_warning("DAILY_LOSS_WARNING", warning)
            logger.warning(warning)

        if daily_pnl_pct < -self.daily_loss_circuit_breaker:
            self._circuit_breaker_active = True
            result["approved"] = False
            result["reason"] = f"日亏损熔断: {daily_pnl_pct:.2%}"
            logger.error(f"Circuit breaker triggered: {daily_pnl_pct:.2%}")

        trading_mode = get_config()["trading"].get("mode", "paper")
        if trading_mode == "live":
            now = datetime.now()
            current_minutes = now.hour * 60 + now.minute
            morning_open = 9 * 60 + 30
            morning_close = 11 * 60 + 30
            afternoon_open = 13 * 60
            afternoon_close = 15 * 60

            if current_minutes < morning_open:
                result["approved"] = False
                result["reason"] = "非交易时段（开盘前9:30）"
            elif morning_close <= current_minutes < afternoon_open:
                result["approved"] = False
                result["reason"] = "非交易时段（午间休市11:30-13:00）"
            elif current_minutes >= afternoon_close:
                result["approved"] = False
                result["reason"] = "非交易时段（收盘后15:00）"

        return result

    def check_sell_restriction(self, symbol: str, direction: str,
                               portfolio: dict) -> dict:
        result = {"approved": True, "reason": ""}

        if direction != "SELL":
            return result

        position = portfolio.get("positions", {}).get(symbol, {})
        if not position:
            result["approved"] = False
            result["reason"] = f"无持仓: {symbol}"
            return result

        buy_date = position.get("buy_date")
        if buy_date:
            if isinstance(buy_date, str):
                buy_date = datetime.strptime(buy_date, "%Y-%m-%d").date()
            if isinstance(buy_date, datetime):
                buy_date = buy_date.date()
            today = datetime.now().date()
            if (today - buy_date).days < 1:
                result["approved"] = False
                result["reason"] = "T+1限制: 当日买入不可卖出"
                logger.info(f"T+1 restriction for {symbol}")

        return result

    def update_daily_pnl(self, pnl: float):
        self._daily_pnl += pnl

    def reset_circuit_breaker(self):
        self._circuit_breaker_active = False
        self._daily_pnl = 0.0
        logger.info("Circuit breaker reset")

    def get_risk_status(self, account: dict, portfolio: dict = None) -> dict:
        self._check_daily_reset(account)
        daily_pnl_pct = self._get_daily_pnl_pct(account)

        sector_concentration = {}
        positions = {}
        if portfolio:
            positions = portfolio.get("positions", {})
        elif "positions" in account:
            positions = account.get("positions", {})
        total_capital = account.get("total_capital", 1)

        for sym, pos in positions.items():
            sector = self.get_stock_sector(sym)
            sector_concentration[sector] = sector_concentration.get(sector, 0) + pos.get("market_value", 0)

        sector_pct = {s: round(v / total_capital, 4) for s, v in sector_concentration.items() if v > 0}

        return {
            "circuit_breaker_active": self._circuit_breaker_active,
            "daily_pnl": self._daily_pnl,
            "daily_pnl_pct": daily_pnl_pct,
            "daily_loss_warning": self.daily_loss_warning,
            "daily_loss_circuit_breaker": self.daily_loss_circuit_breaker,
            "warnings": self._warnings[-10:],
            "risk_level": self._assess_risk_level(daily_pnl_pct),
            "sector_concentration": sector_pct,
        }

    def _check_daily_reset(self, account: dict):
        today = datetime.now().date()
        if self._last_reset_date != today:
            self._daily_pnl = 0.0
            self._circuit_breaker_active = False
            self._last_reset_date = today
            self._daily_start_capital = account.get("total_capital", 100000)
            logger.info(f"Risk daily reset for {today}")

    def _get_daily_pnl_pct(self, account: dict) -> float:
        total_capital = account.get("total_capital", 100000)
        if total_capital <= 0:
            return 0.0
        return self._daily_pnl / total_capital

    def _assess_risk_level(self, daily_pnl_pct: float) -> str:
        if self._circuit_breaker_active:
            return "CRITICAL"
        if daily_pnl_pct < -self.daily_loss_warning:
            return "HIGH"
        if daily_pnl_pct < -self.daily_loss_warning / 2:
            return "MEDIUM"
        return "LOW"

    def _add_warning(self, warning_type: str, message: str):
        self._warnings.append({
            "type": warning_type,
            "message": message,
            "timestamp": datetime.now().isoformat(),
        })
        if len(self._warnings) > 100:
            self._warnings = self._warnings[-50:]
