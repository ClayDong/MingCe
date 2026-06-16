import json
import os
import numpy as np
from datetime import datetime, date
from loguru import logger
from qlib_vnpy_platform.core.strategies import get_strategy, STRATEGY_REGISTRY
from qlib_vnpy_platform.core.data_bridge import DataBridge


PAPER_TRADING_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "paper_trading")
os.makedirs(PAPER_TRADING_DIR, exist_ok=True)


class PaperTradingAccount:
    def __init__(self, strategy_key: str, symbol: str, initial_capital: float = 100000.0):
        self.strategy_key = strategy_key
        self.symbol = symbol
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.position = 0
        self.avg_cost = 0.0
        self.trades = []
        self.equity_history = []
        self.created_at = datetime.now().isoformat()
        self.last_run = None
        self.last_signal = "HOLD"
        self.last_signal_value = 0
        self.last_price = 0.0
        self.commission_rate = 0.0003
        self.stamp_tax_rate = 0.0005
        self.slippage = 0.001
        self.min_lot_size = 100

    @property
    def position_value(self) -> float:
        return self.position * self.last_price if self.position > 0 else 0.0

    @property
    def total_equity(self) -> float:
        return self.cash + self.position_value

    @property
    def total_pnl(self) -> float:
        return self.total_equity - self.initial_capital

    @property
    def total_pnl_pct(self) -> float:
        return (self.total_equity - self.initial_capital) / self.initial_capital * 100 if self.initial_capital > 0 else 0

    @property
    def unrealized_pnl(self) -> float:
        if self.position <= 0 or self.avg_cost <= 0:
            return 0.0
        sell_price = self.last_price * (1 - self.slippage)
        revenue = sell_price * self.position
        commission = revenue * self.commission_rate
        stamp_tax = revenue * self.stamp_tax_rate
        return revenue - commission - stamp_tax - self.avg_cost * self.position

    @property
    def unrealized_pnl_pct(self) -> float:
        if self.position <= 0 or self.avg_cost <= 0:
            return 0.0
        sell_price = self.last_price * (1 - self.slippage)
        revenue = sell_price * self.position
        commission = revenue * self.commission_rate
        stamp_tax = revenue * self.stamp_tax_rate
        net_revenue = revenue - commission - stamp_tax
        cost_basis = self.avg_cost * self.position
        return (net_revenue - cost_basis) / cost_basis * 100 if cost_basis > 0 else 0

    def buy(self, price: float, volume: int, signal_strength: float = 0.0) -> dict:
        if self.position > 0:
            return {"status": "SKIPPED", "reason": "已有持仓"}

        actual_price = price * (1 + self.slippage)
        cost = actual_price * volume
        commission = cost * self.commission_rate
        total_cost = cost + commission

        if total_cost > self.cash:
            volume = int(self.cash / (actual_price * self.min_lot_size * (1 + self.commission_rate))) * self.min_lot_size
            if volume <= 0:
                return {"status": "FAILED", "reason": "资金不足"}
            cost = actual_price * volume
            commission = cost * self.commission_rate
            total_cost = cost + commission

        self.cash -= total_cost
        self.position = volume
        self.avg_cost = total_cost / volume

        trade = {
            "date": date.today().isoformat(),
            "time": datetime.now().strftime("%H:%M:%S"),
            "direction": "BUY",
            "price": round(actual_price, 2),
            "raw_price": round(price, 2),
            "volume": volume,
            "commission": round(commission, 2),
            "signal_strength": round(signal_strength, 3),
            "cash_after": round(self.cash, 2),
        }
        self.trades.append(trade)
        self.last_signal = "BUY"
        self.last_signal_value = 1
        logger.info(f"[PaperTrade] {self.strategy_key} BUY {self.symbol}: price={actual_price:.2f}, vol={volume}, cash={self.cash:.2f}")
        return {"status": "FILLED", "trade": trade}

    def sell(self, price: float, volume: int, signal_strength: float = 0.0) -> dict:
        if self.position <= 0:
            return {"status": "SKIPPED", "reason": "无持仓"}

        actual_price = price * (1 - self.slippage)
        revenue = actual_price * volume
        commission = revenue * self.commission_rate
        stamp_tax = revenue * self.stamp_tax_rate
        net_revenue = revenue - commission - stamp_tax
        pnl = (actual_price - self.avg_cost) * volume - commission - stamp_tax
        pnl_pct = (actual_price - self.avg_cost) / self.avg_cost * 100 if self.avg_cost > 0 else 0

        self.cash += net_revenue

        trade = {
            "date": date.today().isoformat(),
            "time": datetime.now().strftime("%H:%M:%S"),
            "direction": "SELL",
            "price": round(actual_price, 2),
            "raw_price": round(price, 2),
            "volume": volume,
            "commission": round(commission, 2),
            "stamp_tax": round(stamp_tax, 2),
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "signal_strength": round(signal_strength, 3),
            "cash_after": round(self.cash, 2),
        }
        self.trades.append(trade)
        self.position = 0
        self.avg_cost = 0.0
        self.last_signal = "SELL"
        self.last_signal_value = -1
        logger.info(f"[PaperTrade] {self.strategy_key} SELL {self.symbol}: price={actual_price:.2f}, vol={volume}, pnl={pnl:.2f}, cash={self.cash:.2f}")
        return {"status": "FILLED", "trade": trade}

    def update_price(self, price: float):
        self.last_price = price

    def record_equity(self):
        self.equity_history.append({
            "date": date.today().isoformat(),
            "equity": round(self.total_equity, 2),
            "cash": round(self.cash, 2),
            "position_value": round(self.position_value, 2),
            "price": round(self.last_price, 2),
            "has_position": self.position > 0,
        })

    def to_dict(self) -> dict:
        return {
            "strategy_key": self.strategy_key,
            "symbol": self.symbol,
            "initial_capital": self.initial_capital,
            "cash": round(self.cash, 2),
            "position": self.position,
            "avg_cost": round(self.avg_cost, 2),
            "last_price": round(self.last_price, 2),
            "position_value": round(self.position_value, 2),
            "total_equity": round(self.total_equity, 2),
            "total_pnl": round(self.total_pnl, 2),
            "total_pnl_pct": round(self.total_pnl_pct, 2),
            "unrealized_pnl": round(self.unrealized_pnl, 2),
            "unrealized_pnl_pct": round(self.unrealized_pnl_pct, 2),
            "trades": self.trades,
            "trade_count": len(self.trades),
            "buy_count": len([t for t in self.trades if t["direction"] == "BUY"]),
            "sell_count": len([t for t in self.trades if t["direction"] == "SELL"]),
            "equity_history": self.equity_history[-60:],
            "created_at": self.created_at,
            "last_run": self.last_run,
            "last_signal": self.last_signal,
            "last_signal_value": self.last_signal_value,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PaperTradingAccount":
        account = cls(
            strategy_key=data["strategy_key"],
            symbol=data["symbol"],
            initial_capital=data.get("initial_capital", 100000),
        )
        account.cash = data.get("cash", account.initial_capital)
        account.position = data.get("position", 0)
        account.avg_cost = data.get("avg_cost", 0.0)
        account.last_price = data.get("last_price", 0.0)
        account.trades = data.get("trades", [])
        account.equity_history = data.get("equity_history", [])
        account.created_at = data.get("created_at", datetime.now().isoformat())
        account.last_run = data.get("last_run", None)
        account.last_signal = data.get("last_signal", "HOLD")
        account.last_signal_value = data.get("last_signal_value", 0)
        return account


class PaperTradingEngine:
    def __init__(self, initial_capital: float = 100000.0):
        self.initial_capital = initial_capital
        self.data_bridge = DataBridge()
        self._accounts = {}
        self._load_all()

    def _account_file(self, strategy_key: str, symbol: str) -> str:
        return os.path.join(PAPER_TRADING_DIR, f"{strategy_key}_{symbol}.json")

    def _load_all(self):
        if not os.path.exists(PAPER_TRADING_DIR):
            return
        for fname in os.listdir(PAPER_TRADING_DIR):
            if fname.endswith(".json"):
                try:
                    with open(os.path.join(PAPER_TRADING_DIR, fname), "r") as f:
                        data = json.load(f)
                    account = PaperTradingAccount.from_dict(data)
                    key = f"{account.strategy_key}_{account.symbol}"
                    self._accounts[key] = account
                except Exception as e:
                    logger.warning(f"Failed to load paper trading account {fname}: {e}")

    def _save_account(self, account: PaperTradingAccount):
        key = f"{account.strategy_key}_{account.symbol}"
        self._accounts[key] = account
        filepath = self._account_file(account.strategy_key, account.symbol)
        try:
            with open(filepath, "w") as f:
                json.dump(account.to_dict(), f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to save paper trading account: {e}")

    def reset_all(self):
        self._accounts = {}
        if os.path.exists(PAPER_TRADING_DIR):
            for fname in os.listdir(PAPER_TRADING_DIR):
                if fname.endswith(".json"):
                    os.remove(os.path.join(PAPER_TRADING_DIR, fname))
        logger.info("All paper trading accounts reset")

    def init_strategy(self, strategy_key: str, symbol: str, force: bool = False) -> PaperTradingAccount:
        key = f"{strategy_key}_{symbol}"
        if key in self._accounts and not force:
            return self._accounts[key]
        account = PaperTradingAccount(strategy_key, symbol, self.initial_capital)
        self._save_account(account)
        logger.info(f"Paper trading account initialized: {strategy_key} / {symbol} / ¥{self.initial_capital}")
        return account

    def init_all_strategies(self, symbol: str, force: bool = True) -> list:
        results = []
        for strategy_key in STRATEGY_REGISTRY.keys():
            try:
                account = self.init_strategy(strategy_key, symbol, force=force)
                results.append(account.to_dict())
            except Exception as e:
                logger.error(f"Failed to init {strategy_key}: {e}")
        return results

    def run_daily(self, strategy_key: str, symbol: str, days: int = 120) -> dict:
        key = f"{strategy_key}_{symbol}"
        account = self._accounts.get(key)
        if account is None:
            account = self.init_strategy(strategy_key, symbol)

        today = date.today().isoformat()
        if account.last_run and account.last_run >= today:
            return {
                "status": "already_run",
                "strategy_key": strategy_key,
                "message": f"今日({today})已运行，无需重复",
                "account": account.to_dict(),
            }

        try:
            strategy = get_strategy(strategy_key)
        except ValueError as e:
            return {"status": "error", "strategy_key": strategy_key, "error": str(e)}

        df = self.data_bridge.fetch_stock_daily(symbol, days=days)
        if df is None or df.empty or len(df) < 30:
            return {"status": "error", "strategy_key": strategy_key, "error": "数据不足"}

        df = strategy.generate_signals(df)

        last_row = df.iloc[-1]
        current_price = float(last_row["close"])
        signal = int(last_row.get("signal", 0))
        signal_strength = float(last_row.get("signal_strength", 0))
        signal_date = str(last_row.get("date", ""))[:10]

        account.update_price(current_price)

        volume = 0
        if signal == 1 and account.position == 0:
            invest = account.cash
            volume = int(invest / (current_price * (1 + account.slippage) * account.min_lot_size * (1 + account.commission_rate))) * account.min_lot_size
            if volume > 0:
                account.buy(current_price, volume, signal_strength)

        elif signal == -1 and account.position > 0:
            account.sell(current_price, account.position, signal_strength)

        if signal == 1 and account.last_signal != "BUY":
            account.last_signal = "买入" if account.position == 0 and volume <= 0 else "BUY"
            account.last_signal_value = 1
        elif signal == -1 and account.last_signal != "SELL":
            account.last_signal = "卖出" if account.position == 0 else "SELL"
            account.last_signal_value = -1
        elif signal == 0:
            account.last_signal = "持有/观望"
            account.last_signal_value = 0
        account.last_run = today
        account.record_equity()
        self._save_account(account)

        sell_trades = [t for t in account.trades if t["direction"] == "SELL"]
        winning = [t for t in sell_trades if t.get("pnl", 0) > 0]
        win_rate = len(winning) / len(sell_trades) * 100 if sell_trades else 0

        max_drawdown = 0
        if account.equity_history:
            peak = account.equity_history[0]["equity"]
            for eq in account.equity_history:
                if eq["equity"] > peak:
                    peak = eq["equity"]
                dd = (peak - eq["equity"]) / peak * 100 if peak > 0 else 0
                if dd > max_drawdown:
                    max_drawdown = dd

        return {
            "status": "ok",
            "strategy_key": strategy_key,
            "strategy_name": strategy.name,
            "symbol": symbol,
            "signal_date": signal_date,
            "signal": account.last_signal,
            "signal_value": signal,
            "signal_strength": round(signal_strength, 3),
            "current_price": round(current_price, 2),
            "account": account.to_dict(),
            "metrics": {
                "win_rate": round(win_rate, 1),
                "max_drawdown_pct": round(max_drawdown, 2),
            },
        }

    def run_daily_all(self, symbol: str, days: int = 120) -> list:
        results = []
        for strategy_key in STRATEGY_REGISTRY.keys():
            try:
                r = self.run_daily(strategy_key, symbol, days)
                results.append(r)
            except Exception as e:
                logger.error(f"Paper trading failed for {strategy_key}: {e}")
                results.append({"status": "error", "strategy_key": strategy_key, "error": str(e)})
        results.sort(key=lambda x: x.get("account", {}).get("total_pnl_pct", -999), reverse=True)
        return results

    def get_account(self, strategy_key: str, symbol: str) -> dict:
        key = f"{strategy_key}_{symbol}"
        account = self._accounts.get(key)
        return account.to_dict() if account else {}

    def get_all_accounts(self, symbol: str = None) -> list:
        results = []
        for key, account in self._accounts.items():
            if symbol and account.symbol != symbol:
                continue
            results.append(account.to_dict())
        results.sort(key=lambda x: x.get("total_pnl_pct", -999), reverse=True)
        return results

    def get_summary(self, symbol: str = None) -> dict:
        accounts = self.get_all_accounts(symbol)
        if not accounts:
            return {"total_strategies": 0, "total_capital": 0}

        total_equity = sum(a["total_equity"] for a in accounts)
        total_initial = sum(a["initial_capital"] for a in accounts)
        profitable = len([a for a in accounts if a["total_pnl"] > 0])
        total_trades = sum(a["trade_count"] for a in accounts)
        with_position = len([a for a in accounts if a["position"] > 0])

        return {
            "total_strategies": len(accounts),
            "total_initial_capital": total_initial,
            "total_current_equity": round(total_equity, 2),
            "total_pnl": round(total_equity - total_initial, 2),
            "total_pnl_pct": round((total_equity - total_initial) / total_initial * 100, 2) if total_initial > 0 else 0,
            "profitable_count": profitable,
            "losing_count": len(accounts) - profitable,
            "total_trades": total_trades,
            "with_position": with_position,
            "symbol": symbol or "ALL",
            "run_date": date.today().isoformat(),
        }
