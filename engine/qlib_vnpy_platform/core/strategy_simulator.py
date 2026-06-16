import pandas as pd
import numpy as np
from datetime import datetime
from loguru import logger
from qlib_vnpy_platform.core.strategies import BaseStrategy, get_strategy, list_strategies, STRATEGY_REGISTRY
from qlib_vnpy_platform.core.data_bridge import DataBridge


class StrategySimulator:
    def __init__(self, initial_capital: float = 100000.0,
                 commission_rate: float = 0.0003,
                 stamp_tax_rate: float = 0.0005,
                 slippage: float = 0.001,
                 min_lot_size: int = 100,
                 position_ratio: float = 1.0):
        self.initial_capital = initial_capital
        self.commission_rate = commission_rate
        self.stamp_tax_rate = stamp_tax_rate
        self.slippage = slippage
        self.min_lot_size = min_lot_size
        self.position_ratio = position_ratio
        self.data_bridge = DataBridge()
        self._simulations = {}

    def simulate_strategy(self, strategy_key: str, symbol: str,
                          days: int = 365) -> dict:
        try:
            strategy = get_strategy(strategy_key)
        except ValueError as e:
            return {"error": str(e)}

        df = self.data_bridge.fetch_stock_daily(symbol, days=days)
        if df is None or df.empty:
            return {"error": f"无法获取 {symbol} 的数据"}

        df = strategy.generate_signals(df)

        capital = self.initial_capital
        position = 0
        avg_cost = 0.0
        trades = []
        equity_curve = []
        daily_returns = []

        for i in range(len(df)):
            row = df.iloc[i]
            price = float(row["close"])
            signal = int(row.get("signal", 0))
            signal_strength = float(row.get("signal_strength", 0))
            date = row.get("date", i)

            if signal == 1 and position == 0:
                invest_amount = capital * self.position_ratio
                actual_price = price * (1 + self.slippage)
                volume = int(invest_amount / (actual_price * self.min_lot_size)) * self.min_lot_size
                if volume > 0:
                    cost = actual_price * volume
                    commission = cost * self.commission_rate
                    total_cost = cost + commission
                    if total_cost <= capital:
                        capital -= total_cost
                        position = volume
                        avg_cost = actual_price
                        trades.append({
                            "date": str(date)[:10],
                            "direction": "BUY",
                            "price": round(actual_price, 2),
                            "volume": volume,
                            "commission": round(commission, 2),
                            "signal_strength": round(signal_strength, 3),
                            "capital_after": round(capital, 2),
                        })

            elif signal == -1 and position > 0:
                actual_price = price * (1 - self.slippage)
                revenue = actual_price * position
                commission = revenue * self.commission_rate
                stamp_tax = revenue * self.stamp_tax_rate
                net_revenue = revenue - commission - stamp_tax
                pnl = (actual_price - avg_cost) * position - commission - stamp_tax
                pnl_pct = (actual_price - avg_cost) / avg_cost * 100 if avg_cost > 0 else 0
                capital += net_revenue
                trades.append({
                    "date": str(date)[:10],
                    "direction": "SELL",
                    "price": round(actual_price, 2),
                    "volume": position,
                    "commission": round(commission, 2),
                    "stamp_tax": round(stamp_tax, 2),
                    "pnl": round(pnl, 2),
                    "pnl_pct": round(pnl_pct, 2),
                    "signal_strength": round(signal_strength, 3),
                    "capital_after": round(capital, 2),
                })
                position = 0
                avg_cost = 0.0

            position_value = position * price
            total_equity = capital + position_value
            equity_curve.append({
                "date": str(date)[:10],
                "equity": round(total_equity, 2),
                "cash": round(capital, 2),
                "position_value": round(position_value, 2),
                "price": round(price, 2),
                "has_position": position > 0,
            })

            if len(equity_curve) >= 2:
                prev_equity = equity_curve[-2]["equity"]
                daily_ret = (total_equity - prev_equity) / prev_equity if prev_equity > 0 else 0
                daily_returns.append(daily_ret)

        current_position = None
        if position > 0:
            last_price = float(df.iloc[-1]["close"])
            unrealized_pnl = (last_price - avg_cost) * position
            unrealized_pnl_pct = (last_price - avg_cost) / avg_cost * 100 if avg_cost > 0 else 0
            current_position = {
                "volume": position,
                "avg_cost": round(avg_cost, 2),
                "current_price": round(last_price, 2),
                "unrealized_pnl": round(unrealized_pnl, 2),
                "unrealized_pnl_pct": round(unrealized_pnl_pct, 2),
                "market_value": round(position * last_price, 2),
            }

        final_equity = capital + (position * float(df.iloc[-1]["close"]) if position > 0 else 0)
        total_return = (final_equity - self.initial_capital) / self.initial_capital * 100

        sell_trades = [t for t in trades if t["direction"] == "SELL"]
        winning = [t for t in sell_trades if t.get("pnl", 0) > 0]
        losing = [t for t in sell_trades if t.get("pnl", 0) < 0]
        win_rate = len(winning) / len(sell_trades) * 100 if sell_trades else 0

        max_drawdown = 0
        peak = equity_curve[0]["equity"] if equity_curve else self.initial_capital
        for eq in equity_curve:
            if eq["equity"] > peak:
                peak = eq["equity"]
            dd = (peak - eq["equity"]) / peak * 100 if peak > 0 else 0
            if dd > max_drawdown:
                max_drawdown = dd

        sharpe = 0
        if len(daily_returns) > 1:
            avg_ret = np.mean(daily_returns)
            std_ret = np.std(daily_returns)
            if std_ret > 0:
                sharpe = avg_ret / std_ret * np.sqrt(252)

        last_row = df.iloc[-1]
        latest_signal = int(last_row.get("signal", 0))
        signal_map = {1: "买入", -1: "卖出", 0: "持有/观望"}

        result = {
            "strategy_key": strategy_key,
            "strategy_name": strategy.name,
            "strategy_params": strategy.params,
            "symbol": symbol,
            "initial_capital": self.initial_capital,
            "final_equity": round(final_equity, 2),
            "total_return_pct": round(total_return, 2),
            "total_pnl": round(final_equity - self.initial_capital, 2),
            "max_drawdown_pct": round(max_drawdown, 2),
            "sharpe_ratio": round(sharpe, 2),
            "win_rate": round(win_rate, 1),
            "total_trades": len(trades),
            "buy_count": len([t for t in trades if t["direction"] == "BUY"]),
            "sell_count": len(sell_trades),
            "winning_trades": len(winning),
            "losing_trades": len(losing),
            "current_position": current_position,
            "latest_signal": signal_map.get(latest_signal, "未知"),
            "latest_signal_value": latest_signal,
            "latest_signal_strength": round(float(last_row.get("signal_strength", 0)), 3),
            "latest_price": round(float(last_row.get("close", 0)), 2),
            "latest_date": str(last_row.get("date", ""))[:10],
            "trades": trades[-20:],
            "equity_curve": equity_curve[-60:],
        }

        self._simulations[f"{strategy_key}_{symbol}"] = result
        return result

    def simulate_all_strategies(self, symbol: str, days: int = 365) -> list:
        results = []
        for strategy_key in STRATEGY_REGISTRY.keys():
            try:
                result = self.simulate_strategy(strategy_key, symbol, days)
                results.append(result)
            except Exception as e:
                logger.error(f"策略 {strategy_key} 模拟失败: {e}")
                results.append({
                    "strategy_key": strategy_key,
                    "strategy_name": strategy_key,
                    "error": str(e),
                })
        results.sort(key=lambda x: x.get("total_return_pct", -999), reverse=True)
        return results

    def get_simulation(self, strategy_key: str, symbol: str) -> dict:
        return self._simulations.get(f"{strategy_key}_{symbol}", {})

    def get_all_simulations(self) -> dict:
        return dict(self._simulations)
