import json
import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from loguru import logger
from qlib_vnpy_platform.core.strategies import BaseStrategy, get_strategy
from qlib_vnpy_platform.core.data_bridge import DataBridge
from qlib_vnpy_platform.core.backtest import BacktestEngine
from qlib_vnpy_platform.config import get_config


PORTFOLIO_SIM_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "portfolio_sim")
os.makedirs(PORTFOLIO_SIM_DIR, exist_ok=True)


class PortfolioPosition:
    """单支持仓"""
    
    def __init__(self, symbol: str, volume: int, entry_price: float, entry_date: str):
        self.symbol = symbol
        self.volume = volume
        self.entry_price = entry_price
        self.entry_date = entry_date
        self.current_price = entry_price
        self.highest_price = entry_price
        self.unrealized_pnl = 0.0
        self.unrealized_pnl_pct = 0.0
        self.hold_days = 0
    
    def update(self, current_price: float, current_date: str):
        """更新持仓信息"""
        self.current_price = current_price
        self.highest_price = max(self.highest_price, current_price)
        
        # 计算浮盈
        self.unrealized_pnl = (current_price - self.entry_price) * self.volume
        self.unrealized_pnl_pct = (current_price - self.entry_price) / self.entry_price * 100
        
        # 计算持仓天数
        try:
            entry_dt = datetime.fromisoformat(self.entry_date.replace("Z", "+00:00"))
            current_dt = datetime.fromisoformat(current_date.replace("Z", "+00:00"))
            self.hold_days = (current_dt - entry_dt).days
        except Exception:
            pass
    
    def to_dict(self) -> Dict:
        return {
            "symbol": self.symbol,
            "volume": self.volume,
            "entry_price": self.entry_price,
            "entry_date": self.entry_date,
            "current_price": self.current_price,
            "highest_price": self.highest_price,
            "unrealized_pnl": self.unrealized_pnl,
            "unrealized_pnl_pct": self.unrealized_pnl_pct,
            "hold_days": self.hold_days,
            "market_value": self.volume * self.current_price
        }


class PortfolioSimulation:
    """组合模拟回测引擎：支持多策略、多股票组合回测"""
    
    def __init__(self, initial_capital: float = 1000000.0, 
                 commission_rate: float = 0.0003,
                 slippage: float = 0.001,
                 min_lot_size: int = 100,
                 max_single_position: float = 0.20,
                 max_holdings: int = 10):
        
        self.initial_capital = initial_capital
        self.capital = initial_capital
        self.commission_rate = commission_rate
        self.slippage = slippage
        self.min_lot_size = min_lot_size
        self.max_single_position = max_single_position
        self.max_holdings = max_holdings
        
        self.positions: Dict[str, PortfolioPosition] = {}
        self.trades: List[Dict] = []
        self.equity_curve: List[Dict] = []
        self.daily_returns: List[Dict] = []
        self.holdings_history: List[Dict] = []
        
        self.strategy_allocations: Dict[str, float] = {}  # 策略权重分配
        self.strategy_positions: Dict[str, List[str]] = {}  # 策略对应持仓
        
        self.start_date: Optional[str] = None
        self.end_date: Optional[str] = None
        
        self.data_bridge = DataBridge()
        self.backtest_engine = BacktestEngine(
            initial_capital=initial_capital,
            commission_rate=commission_rate,
            slippage=slippage,
            min_lot_size=min_lot_size
        )
        
        logger.info(f"PortfolioSimulation initialized with {initial_capital:,.0f} capital")
    
    def set_strategy_allocations(self, allocations: Dict[str, float]):
        """设置策略权重分配"""
        total_weight = sum(allocations.values())
        if total_weight > 0:
            self.strategy_allocations = {k: v / total_weight for k, v in allocations.items()}
        else:
            self.strategy_allocations = allocations
        logger.info(f"Strategy allocations set: {self.strategy_allocations}")
    
    @property
    def total_equity(self) -> float:
        """总权益"""
        position_value = sum(p.volume * p.current_price for p in self.positions.values())
        return self.capital + position_value
    
    @property
    def total_pnl(self) -> float:
        """总盈亏"""
        return self.total_equity - self.initial_capital
    
    @property
    def total_pnl_pct(self) -> float:
        """总盈亏百分比"""
        return (self.total_equity - self.initial_capital) / self.initial_capital * 100
    
    def _calculate_position_size(self, target_pct: float, current_price: float) -> int:
        """计算下单手数"""
        target_value = self.total_equity * target_pct
        volume = int(target_value / (current_price * self.min_lot_size)) * self.min_lot_size
        return max(0, volume)
    
    def _buy(self, symbol: str, volume: int, price: float, 
            date: str, strategy_key: str = "", reason: str = "") -> bool:
        """执行买入"""
        actual_price = price * (1 + self.slippage)
        cost = actual_price * volume
        commission = cost * self.commission_rate
        total_cost = cost + commission
        
        if total_cost > self.capital:
            logger.warning(f"Insufficient capital to buy {symbol}")
            return False
        
        self.capital -= total_cost
        
        if symbol in self.positions:
            # 加仓：计算平均成本
            existing = self.positions[symbol]
            total_volume = existing.volume + volume
            avg_price = (existing.entry_price * existing.volume + actual_price * volume) / total_volume
            existing.volume = total_volume
            existing.entry_price = avg_price
        else:
            # 新建持仓
            self.positions[symbol] = PortfolioPosition(symbol, volume, actual_price, date)
        
        if strategy_key:
            if strategy_key not in self.strategy_positions:
                self.strategy_positions[strategy_key] = []
            if symbol not in self.strategy_positions[strategy_key]:
                self.strategy_positions[strategy_key].append(symbol)
        
        trade = {
            "date": date,
            "symbol": symbol,
            "direction": "BUY",
            "volume": volume,
            "price": actual_price,
            "commission": commission,
            "strategy": strategy_key,
            "reason": reason
        }
        self.trades.append(trade)
        logger.info(f"BUY {symbol} {volume} @ {actual_price:.2f} (Strategy: {strategy_key})")
        return True
    
    def _sell(self, symbol: str, volume: int, price: float, 
             date: str, strategy_key: str = "", reason: str = "") -> bool:
        """执行卖出"""
        if symbol not in self.positions:
            return False
        
        position = self.positions[symbol]
        sell_volume = min(volume, position.volume)
        actual_price = price * (1 - self.slippage)
        
        revenue = actual_price * sell_volume
        commission = revenue * self.commission_rate
        stamp_tax = revenue * 0.0005  # 印花税
        net_revenue = revenue - commission - stamp_tax
        
        self.capital += net_revenue
        
        pnl = (actual_price - position.entry_price) * sell_volume
        
        if sell_volume == position.volume:
            del self.positions[symbol]
            # 从策略持仓中移除
            for s_key, symbols in self.strategy_positions.items():
                if symbol in symbols:
                    symbols.remove(symbol)
        else:
            position.volume -= sell_volume
        
        trade = {
            "date": date,
            "symbol": symbol,
            "direction": "SELL",
            "volume": sell_volume,
            "price": actual_price,
            "commission": commission,
            "stamp_tax": stamp_tax,
            "pnl": pnl,
            "strategy": strategy_key,
            "reason": reason
        }
        self.trades.append(trade)
        logger.info(f"SELL {symbol} {sell_volume} @ {actual_price:.2f}, PNL: {pnl:.2f} (Strategy: {strategy_key})")
        return True
    
    def _update_all_positions(self, prices: Dict[str, float], date: str):
        """更新所有持仓"""
        for symbol, price in prices.items():
            if symbol in self.positions:
                self.positions[symbol].update(price, date)
    
    def _record_equity(self, date: str):
        """记录权益曲线"""
        self.equity_curve.append({
            "date": date,
            "equity": self.total_equity,
            "capital": self.capital,
            "position_value": self.total_equity - self.capital
        })
    
    def run_multi_symbol_backtest(self, symbols: List[str], 
                                 strategy_allocations: Dict[str, float],
                                 start_date: str, end_date: str) -> Dict:
        """运行多股票多策略组合回测"""
        self.set_strategy_allocations(strategy_allocations)
        self.start_date = start_date
        self.end_date = end_date
        
        logger.info(f"Starting multi-symbol backtest: {len(symbols)} symbols, {len(strategy_allocations)} strategies")
        
        # 获取所有数据
        symbol_data: Dict[str, pd.DataFrame] = {}
        date_index = None
        
        for symbol in symbols:
            try:
                df = self.data_bridge.get_historical_data(symbol, start_date, end_date)
                if not df.empty:
                    symbol_data[symbol] = df
                    if date_index is None:
                        date_index = df["date"].values
            except Exception as e:
                logger.warning(f"Failed to get data for {symbol}: {e}")
        
        if not symbol_data:
            return {"error": "No valid data available"}
        
        # 按日期回测
        for date_idx, current_date in enumerate(date_index):
            current_date_str = str(current_date)
            
            # 获取当日价格
            current_prices = {}
            for symbol, df in symbol_data.items():
                if date_idx < len(df):
                    row = df.iloc[date_idx]
                    current_prices[symbol] = float(row["close"])
            
            self._update_all_positions(current_prices, current_date_str)
            
            # 处理每个策略的信号
            for strategy_key, weight in self.strategy_allocations.items():
                if weight <= 0:
                    continue
                
                try:
                    strategy = get_strategy(strategy_key)
                    
                    for symbol, df in symbol_data.items():
                        if date_idx < 30:
                            continue
                        
                        # 获取历史数据到当前日期
                        history_df = df.iloc[:date_idx+1].copy()
                        
                        # 生成信号
                        signals_df = strategy.generate_signals(history_df)
                        if len(signals_df) < 2:
                            continue
                        
                        last_signal = signals_df.iloc[-1]["signal"]
                        prev_signal = signals_df.iloc[-2]["signal"]
                        
                        current_price = current_prices.get(symbol, 0)
                        if current_price <= 0:
                            continue
                        
                        # 买入信号
                        if last_signal == 1 and prev_signal != 1:
                            if symbol not in self.positions:
                                current_holdings = len(self.positions)
                                if current_holdings < self.max_holdings:
                                    position_size = self._calculate_position_size(
                                        self.max_single_position * weight, 
                                        current_price
                                    )
                                    if position_size > 0:
                                        self._buy(
                                            symbol, position_size, current_price, 
                                            current_date_str, strategy_key, 
                                            f"{strategy.name} signal"
                                        )
                        
                        # 卖出信号
                        elif last_signal == -1 and prev_signal != -1:
                            if symbol in self.positions:
                                self._sell(
                                    symbol, self.positions[symbol].volume, 
                                    current_price, current_date_str, 
                                    strategy_key, f"{strategy.name} signal"
                                )
                
                except Exception as e:
                    logger.warning(f"Strategy {strategy_key} error: {e}")
            
            self._record_equity(current_date_str)
        
        # 计算最终表现
        result = self._calculate_performance_metrics()
        logger.info(f"Backtest completed: {result['total_return_pct']:.2f}% return")
        
        return result
    
    def _calculate_performance_metrics(self) -> Dict:
        """计算完整的业绩指标"""
        if len(self.equity_curve) < 2:
            return {}
        
        equity_series = pd.Series([e["equity"] for e in self.equity_curve])
        dates = pd.Series([e["date"] for e in self.equity_curve])
        
        returns = equity_series.pct_change().dropna()
        
        # 基础指标
        total_return = (equity_series.iloc[-1] - self.initial_capital) / self.initial_capital
        
        # 最大回撤
        cummax = equity_series.cummax()
        drawdown = (equity_series - cummax) / cummax
        max_drawdown = drawdown.min()
        
        # 年化收益（假设252交易日）
        trading_days = len(equity_series)
        if trading_days > 0:
            annual_return = (1 + total_return) ** (252 / trading_days) - 1
        else:
            annual_return = 0
        
        # 夏普比率（假设无风险利率3%）
        risk_free_rate = 0.03
        excess_returns = returns - risk_free_rate / 252
        if len(excess_returns) > 0 and excess_returns.std() > 0:
            sharpe_ratio = np.sqrt(252) * excess_returns.mean() / excess_returns.std()
        else:
            sharpe_ratio = 0
        
        # 索提诺比率
        downside_returns = returns[returns < 0]
        if len(downside_returns) > 0 and downside_returns.std() > 0:
            sortino_ratio = np.sqrt(252) * returns.mean() / downside_returns.std()
        else:
            sortino_ratio = sharpe_ratio
        
        # 卡玛比率
        if max_drawdown < 0:
            calmar_ratio = annual_return / abs(max_drawdown)
        else:
            calmar_ratio = 0
        
        # 胜率 - 只算有盈亏记录的卖出交易
        closed_trades_with_pnl = [t for t in self.trades if t["direction"] == "SELL" and "pnl" in t]
        winning_trades = [t for t in closed_trades_with_pnl if t.get("pnl", 0) > 0]
        total_closed_trades = len(closed_trades_with_pnl)
        win_rate = len(winning_trades) / total_closed_trades if total_closed_trades > 0 else 0
        
        # 盈亏比
        gross_profit = sum(t["pnl"] for t in closed_trades_with_pnl if t.get("pnl", 0) > 0)
        gross_loss = abs(sum(t["pnl"] for t in closed_trades_with_pnl if t.get("pnl", 0) < 0))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")
        
        return {
            "initial_capital": self.initial_capital,
            "final_equity": self.total_equity,
            "total_pnl": self.total_pnl,
            "total_return_pct": total_return * 100,
            "annual_return_pct": annual_return * 100,
            "max_drawdown_pct": max_drawdown * 100,
            "sharpe_ratio": sharpe_ratio,
            "sortino_ratio": sortino_ratio,
            "calmar_ratio": calmar_ratio,
            "win_rate": win_rate * 100,
            "profit_factor": profit_factor,
            "total_trades": len(self.trades),
            "closed_trades": total_closed_trades,
            "equity_curve": self.equity_curve,
            "trades": self.trades[-100:],  # 只返回最近100笔
            "positions": [p.to_dict() for p in self.positions.values()]
        }
    
    def save_result(self, name: str):
        """保存回测结果"""
        result = {
            "name": name,
            "initial_capital": self.initial_capital,
            "strategy_allocations": self.strategy_allocations,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "performance": self._calculate_performance_metrics(),
            "saved_at": datetime.now().isoformat()
        }
        
        file_path = os.path.join(PORTFOLIO_SIM_DIR, f"portfolio_{name}.json")
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Portfolio result saved to {file_path}")
    
    def get_summary(self) -> Dict:
        """获取组合摘要"""
        perf = self._calculate_performance_metrics()
        return {
            "initial_capital": self.initial_capital,
            "current_equity": self.total_equity,
            "total_pnl": self.total_pnl,
            "total_pnl_pct": self.total_pnl_pct,
            "positions_count": len(self.positions),
            "trades_count": len(self.trades),
            "performance": perf
        }
