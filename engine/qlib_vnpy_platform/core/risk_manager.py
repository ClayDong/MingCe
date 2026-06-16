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

        # ATR 动态止损配置
        self.atr_stop_multiplier = self.config.get("atr_stop_multiplier", 2.0)
        self.atr_period = self.config.get("atr_period", 14)
        self.max_atr_stop_pct = self.config.get("max_atr_stop_pct", 0.08)  # 单股最大止损 8%
        self.min_atr_stop_pct = self.config.get("min_atr_stop_pct", 0.02)  # 单股最小止损 2%

        self._circuit_breaker_active = False
        self._daily_pnl = 0.0
        self._daily_start_capital = 0.0
        self._warnings = []
        self._last_reset_date = None
        self._sector_map = {}
        # 持仓的 ATR 缓存：{symbol: {"atr": float, "updated_at": datetime, "stop_loss": float}}
        self._atr_cache = {}
        logger.info("RiskManager initialized (with ATR dynamic stop-loss)")

    def set_sector_map(self, sector_map: dict):
        self._sector_map = sector_map

    def get_stock_sector(self, symbol: str) -> str:
        return self._sector_map.get(symbol, "其他")

    def update_atr(self, symbol: str, df) -> float:
        """更新某只股票的 ATR 值，并计算动态止损价。

        Args:
            symbol: 股票代码
            df: 包含 high/low/close 列的 DataFrame

        Returns:
            ATR 值（价格单位）
        """
        try:
            import pandas as pd
            import numpy as np

            if df is None or len(df) < self.atr_period + 1:
                logger.debug(f"ATR 计算数据不足: {symbol}")
                return 0.0

            df = df.copy()
            high = df["high"]
            low = df["low"]
            close = df["close"]

            tr1 = high - low
            tr2 = (high - close.shift(1)).abs()
            tr3 = (low - close.shift(1)).abs()
            tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

            # Wilder's ATR
            atr = tr.ewm(alpha=1/self.atr_period, adjust=False).mean().iloc[-1]

            if pd.isna(atr) or atr <= 0:
                return 0.0

            current_price = float(close.iloc[-1])
            atr_pct = atr / current_price if current_price > 0 else 0

            # 限制止损幅度在 [min, max] 之间
            stop_pct = min(max(atr_pct * self.atr_stop_multiplier, self.min_atr_stop_pct),
                          self.max_atr_stop_pct)
            stop_loss_price = current_price * (1 - stop_pct)

            self._atr_cache[symbol] = {
                "atr": float(atr),
                "atr_pct": float(atr_pct),
                "stop_loss": float(stop_loss_price),
                "stop_pct": float(stop_pct),
                "current_price": current_price,
                "updated_at": datetime.now(),
            }

            logger.debug(
                f"ATR 更新 {symbol}: ATR={atr:.2f} ({atr_pct*100:.2f}%), "
                f"止损={stop_loss_price:.2f} (-{stop_pct*100:.2f}%)"
            )
            return float(atr)

        except Exception as e:
            logger.warning(f"ATR 计算失败 {symbol}: {e}")
            return 0.0

    def get_dynamic_stop_loss(self, symbol: str, current_price: float = None) -> float:
        """获取动态止损价（基于 ATR）。

        Args:
            symbol: 股票代码
            current_price: 当前价（可选，用于校准）

        Returns:
            止损价，0 表示无 ATR 数据
        """
        cache = self._atr_cache.get(symbol)
        if not cache:
            return 0.0

        stop_loss = cache["stop_loss"]

        # 如果传入了当前价，且价格已上涨，则上移止损（trailing stop）
        if current_price and current_price > cache["current_price"]:
            stop_pct = cache["stop_pct"]
            new_stop = current_price * (1 - stop_pct)
            if new_stop > stop_loss:
                stop_loss = new_stop
                cache["stop_loss"] = new_stop
                cache["current_price"] = current_price
                logger.debug(f"Trailing stop 上移 {symbol}: {stop_loss:.2f}")

        return stop_loss

    def check_stop_loss(self, symbol: str, current_price: float, position: dict) -> dict:
        """检查是否触发止损（ATR 动态止损）。

        Args:
            symbol: 股票代码
            current_price: 当前价
            position: 持仓信息

        Returns:
            {"triggered": bool, "reason": str, "stop_loss": float}
        """
        result = {"triggered": False, "reason": "", "stop_loss": 0.0}

        stop_loss = self.get_dynamic_stop_loss(symbol, current_price)
        if stop_loss <= 0:
            # 无 ATR 数据，使用固定止损
            cost = position.get("cost_price", 0)
            if cost > 0:
                stop_loss = cost * (1 - self.max_single_loss)
                result["stop_loss"] = stop_loss
                if current_price <= stop_loss:
                    result["triggered"] = True
                    result["reason"] = f"固定止损触发: {current_price:.2f} ≤ {stop_loss:.2f}"
            return result

        result["stop_loss"] = stop_loss
        if current_price <= stop_loss:
            result["triggered"] = True
            result["reason"] = f"ATR 动态止损触发: {current_price:.2f} ≤ {stop_loss:.2f}"

        return result

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

            # 行业集中度实时计算（含本次下单）
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

            # 买入时记录 ATR 止损信息到订单
            atr_cache = self._atr_cache.get(symbol)
            if atr_cache:
                result["atr_stop_loss"] = atr_cache["stop_loss"]
                result["atr_stop_pct"] = atr_cache["stop_pct"]
                # 如果订单没有止损价，使用 ATR 止损
                if not order.get("stop_loss"):
                    result["suggested_stop_loss"] = atr_cache["stop_loss"]

        # 卖出时检查 ATR 止损是否应主动触发
        elif direction == "SELL":
            position = portfolio.get("positions", {}).get(symbol, {})
            if position and price > 0:
                stop_check = self.check_stop_loss(symbol, price, position)
                if stop_check["triggered"] and not order.get("reason", "").startswith("ATR"):
                    result["warnings"].append(
                        f"⚠️ {stop_check['reason']}（建议确认卖出）"
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

    # T+0 品种前缀列表（可转债、ETF、科创板做市标的等）
    T0_PREFIXES = ("11", "12", "13", "51", "52", "56", "58", "159", "510", "511", "512", "513", "518")

    @staticmethod
    def _is_t0_symbol(symbol: str) -> bool:
        """判断是否 T+0 交易品种。

        可转债 (11xxxx)、ETF (51xxxx/159xxx)、科创板做市标的等。
        """
        # 去掉前缀后的纯数字部分
        code = symbol
        for prefix in ("SH", "SZ", "BJ", "HK", "US_"):
            if symbol.startswith(prefix):
                code = symbol[len(prefix):]
                break
        return any(code.startswith(p) for p in RiskManager.T0_PREFIXES)

    def check_sell_restriction(self, symbol: str, direction: str,
                               portfolio: dict) -> dict:
        """检查卖出限制。

        普通 A 股 T+1 限制，T+0 品种（可转债/ETF）不受限。
        """
        result = {"approved": True, "reason": ""}

        if direction != "SELL":
            return result

        position = portfolio.get("positions", {}).get(symbol, {})
        if not position:
            result["approved"] = False
            result["reason"] = f"无持仓: {symbol}"
            return result

        # T+0 品种豁免
        if self._is_t0_symbol(symbol):
            logger.debug(f"T+0 symbol {symbol}: sell restriction skipped")
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
                result["reason"] = "T+1限制: 当日买入不可卖出（普通A股）"
                logger.info(f"T+1 restriction for {symbol}")

        # 科创板 (688xxx) 特殊规则提示
        if symbol.startswith("SH688"):
            logger.debug(f"科创板股票 {symbol}：上市前5日无涨跌幅限制，此后±20%")

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

        # ATR 止损状态
        atr_status = {}
        for sym, cache in self._atr_cache.items():
            if sym in positions:
                pos = positions[sym]
                current_price = pos.get("market_value", 0) / pos.get("volume", 1) if pos.get("volume", 0) > 0 else 0
                stop_check = self.check_stop_loss(sym, current_price, pos) if current_price > 0 else {}
                atr_status[sym] = {
                    "atr": round(cache["atr"], 2),
                    "atr_pct": round(cache["atr_pct"] * 100, 2),
                    "stop_loss": round(cache["stop_loss"], 2),
                    "stop_pct": round(cache["stop_pct"] * 100, 2),
                    "stop_triggered": stop_check.get("triggered", False),
                }

        return {
            "circuit_breaker_active": self._circuit_breaker_active,
            "daily_pnl": self._daily_pnl,
            "daily_pnl_pct": daily_pnl_pct,
            "daily_loss_warning": self.daily_loss_warning,
            "daily_loss_circuit_breaker": self.daily_loss_circuit_breaker,
            "warnings": self._warnings[-10:],
            "risk_level": self._assess_risk_level(daily_pnl_pct),
            "sector_concentration": sector_pct,
            "atr_stops": atr_status,
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
