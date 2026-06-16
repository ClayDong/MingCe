import json
import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from loguru import logger
from qlib_vnpy_platform.config import get_config


RISK_MANAGER_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "risk_manager")
os.makedirs(RISK_MANAGER_DIR, exist_ok=True)


class PositionRisk:
    """单持仓风险分析"""
    
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.volume = 0
        self.entry_price = 0.0
        self.current_price = 0.0
        self.entry_date = None
        
        self.unrealized_pnl = 0.0
        self.unrealized_pnl_pct = 0.0
        self.drawdown_pct = 0.0
        self.highest_price_since_entry = 0.0
        self.hold_days = 0
        
        self.stop_loss_price = 0.0
        self.take_profit_price = 0.0
        self.atr_trailing_stop = 0.0
    
    def update(self, current_price: float, atr: float = None):
        """更新风险指标"""
        self.current_price = current_price
        
        self.unrealized_pnl = (current_price - self.entry_price) * self.volume
        if self.entry_price > 0:
            self.unrealized_pnl_pct = (current_price - self.entry_price) / self.entry_price * 100
        
        self.highest_price_since_entry = max(self.highest_price_since_entry, current_price)
        if self.highest_price_since_entry > 0:
            self.drawdown_pct = (current_price - self.highest_price_since_entry) / self.highest_price_since_entry * 100
        
        if atr and atr > 0:
            self.atr_trailing_stop = current_price - 2 * atr
    
    def check_stop_loss(self) -> Tuple[bool, str]:
        """检查止损条件"""
        if self.stop_loss_price > 0 and self.current_price <= self.stop_loss_price:
            return True, "触及固定止损"
        
        if self.atr_trailing_stop > 0 and self.current_price <= self.atr_trailing_stop:
            return True, "触及ATR追踪止损"
        
        if self.hold_days > 0 and self.hold_days > 10 and self.unrealized_pnl_pct < -5:
            return True, "时间止损（持仓过久且亏损）"
        
        return False, ""
    
    def check_take_profit(self) -> Tuple[bool, str]:
        """检查止盈条件"""
        if self.take_profit_price > 0 and self.current_price >= self.take_profit_price:
            return True, "触及固定止盈"
        
        if self.unrealized_pnl_pct > 20 and self.drawdown_pct < -5:
            return True, "获利回撤止盈"
        
        return False, ""
    
    def to_dict(self) -> Dict:
        return {
            "symbol": self.symbol,
            "volume": self.volume,
            "entry_price": self.entry_price,
            "current_price": self.current_price,
            "unrealized_pnl": self.unrealized_pnl,
            "unrealized_pnl_pct": self.unrealized_pnl_pct,
            "drawdown_pct": self.drawdown_pct,
            "hold_days": self.hold_days,
            "stop_loss_price": self.stop_loss_price,
            "take_profit_price": self.take_profit_price,
            "atr_trailing_stop": self.atr_trailing_stop
        }


class PortfolioRisk:
    """组合风险分析"""
    
    def __init__(self):
        self.total_equity = 0.0
        self.initial_capital = 0.0
        self.total_pnl = 0.0
        self.total_pnl_pct = 0.0
        
        self.peak_equity = 0.0
        self.current_drawdown_pct = 0.0
        self.max_drawdown_pct = 0.0
        
        self.daily_pnl = 0.0
        self.daily_pnl_pct = 0.0
        self.weekly_pnl = 0.0
        self.weekly_pnl_pct = 0.0
        
        self.position_count = 0
        self.leverage = 1.0
        self.portfolio_var = 0.0
        
        self.position_concentration: Dict[str, float] = {}  # 单股票仓位
        self.sector_concentration: Dict[str, float] = {}  # 行业仓位
        
        self.winning_positions = 0
        self.losing_positions = 0
        self.win_rate = 0.0


class AdvancedRiskManager:
    """高级风控管理器"""
    
    def __init__(self):
        self.config = get_config()
        self.risk_config = self.config.get("risk", {})
        
        self.initial_capital = 1000000.0
        self.current_capital = 1000000.0
        self.daily_start_capital = 1000000.0
        
        self.position_risks: Dict[str, PositionRisk] = {}
        self.portfolio_risk = PortfolioRisk()
        
        self.risk_limits = {
            "max_single_position_pct": self.risk_config.get("max_single_position", 0.20) * 100,
            "max_sector_position_pct": 40.0,
            "max_position_count": 10,
            "max_daily_loss_pct": self.risk_config.get("daily_loss_circuit_breaker", 0.05) * 100,
            "max_drawdown_pct": 20.0,
            "min_stop_loss_pct": 5.0,
            "max_leverage": 1.0
        }
        
        self.alerts: List[Dict] = []
        self.risk_history: List[Dict] = []
        
        self._circuit_breaker_triggered = False
        
        logger.info("AdvancedRiskManager initialized")
    
    def initialize(self, initial_capital: float):
        """初始化"""
        self.initial_capital = initial_capital
        self.current_capital = initial_capital
        self.daily_start_capital = initial_capital
        self.portfolio_risk.initial_capital = initial_capital
        self.portfolio_risk.peak_equity = initial_capital
    
    def add_position(self, symbol: str, volume: int, entry_price: float, 
                    stop_loss_pct: float = None, take_profit_pct: float = None):
        """添加持仓"""
        position_risk = PositionRisk(symbol)
        position_risk.volume = volume
        position_risk.entry_price = entry_price
        position_risk.current_price = entry_price
        position_risk.highest_price_since_entry = entry_price
        position_risk.entry_date = datetime.now().isoformat()
        position_risk.hold_days = 0
        
        if stop_loss_pct:
            position_risk.stop_loss_price = entry_price * (1 - stop_loss_pct / 100)
        else:
            position_risk.stop_loss_price = entry_price * 0.95  # 默认5%止损
        
        if take_profit_pct:
            position_risk.take_profit_price = entry_price * (1 + take_profit_pct / 100)
        
        self.position_risks[symbol] = position_risk
        logger.info(f"Added position {symbol} for risk tracking")
    
    def remove_position(self, symbol: str):
        """移除持仓"""
        if symbol in self.position_risks:
            del self.position_risks[symbol]
            logger.info(f"Removed position {symbol} from risk tracking")
    
    def calculate_atr(self, prices: pd.Series, period: int = 14) -> float:
        """计算ATR"""
        if len(prices) < period + 1:
            return 0.0
        
        high_low = prices.diff().abs()
        atr = high_low.rolling(window=period).mean().iloc[-1]
        return float(atr)
    
    def update_position(self, symbol: str, current_price: float, 
                       price_history: pd.Series = None):
        """更新单个持仓风险"""
        if symbol not in self.position_risks:
            return
        
        atr = None
        if price_history is not None:
            atr = self.calculate_atr(price_history)
        
        self.position_risks[symbol].update(current_price, atr)
    
    def update_portfolio(self, current_capital: float, 
                        sector_map: Dict[str, str] = None):
        """更新组合风险"""
        self.current_capital = current_capital
        self.portfolio_risk.total_equity = current_capital
        self.portfolio_risk.total_pnl = current_capital - self.initial_capital
        self.portfolio_risk.total_pnl_pct = (current_capital - self.initial_capital) / self.initial_capital * 100
        
        self.portfolio_risk.peak_equity = max(self.portfolio_risk.peak_equity, current_capital)
        self.portfolio_risk.current_drawdown_pct = (current_capital - self.portfolio_risk.peak_equity) / self.portfolio_risk.peak_equity * 100
        self.portfolio_risk.max_drawdown_pct = min(self.portfolio_risk.max_drawdown_pct, 
                                                   self.portfolio_risk.current_drawdown_pct)
        
        self.portfolio_risk.daily_pnl = current_capital - self.daily_start_capital
        if self.daily_start_capital > 0:
            self.portfolio_risk.daily_pnl_pct = self.portfolio_risk.daily_pnl / self.daily_start_capital * 100
        
        self.portfolio_risk.position_count = len(self.position_risks)
        
        total_position_value = 0.0
        self.portfolio_risk.position_concentration = {}
        self.portfolio_risk.sector_concentration = {}
        
        for symbol, pos in self.position_risks.items():
            position_value = pos.volume * pos.current_price
            total_position_value += position_value
            
            if current_capital > 0:
                self.portfolio_risk.position_concentration[symbol] = position_value / current_capital * 100
            
            if sector_map and symbol in sector_map:
                sector = sector_map[symbol]
                if sector not in self.portfolio_risk.sector_concentration:
                    self.portfolio_risk.sector_concentration[sector] = 0.0
                self.portfolio_risk.sector_concentration[sector] += position_value
        
        if current_capital > 0:
            for sector in self.portfolio_risk.sector_concentration:
                self.portfolio_risk.sector_concentration[sector] = \
                    self.portfolio_risk.sector_concentration[sector] / current_capital * 100
        
        winning = 0
        losing = 0
        for pos in self.position_risks.values():
            if pos.unrealized_pnl >= 0:
                winning += 1
            else:
                losing += 1
        
        self.portfolio_risk.winning_positions = winning
        self.portfolio_risk.losing_positions = losing
        total = winning + losing
        self.portfolio_risk.win_rate = winning / total * 100 if total > 0 else 0
        
        self._check_portfolio_limits()
        self._record_risk_snapshot()
    
    def _check_portfolio_limits(self):
        """检查组合风险限制"""
        self.alerts = []
        
        if self.portfolio_risk.daily_pnl_pct <= -self.risk_limits["max_daily_loss_pct"]:
            if not self._circuit_breaker_triggered:
                self._circuit_breaker_triggered = True
                self.alerts.append({
                    "level": "critical",
                    "type": "circuit_breaker",
                    "message": f"日亏损触发熔断: {self.portfolio_risk.daily_pnl_pct:.2f}%",
                    "timestamp": datetime.now().isoformat()
                })
                logger.critical("DAILY LOSS CIRCUIT BREAKER TRIGGERED!")
        
        if self.portfolio_risk.max_drawdown_pct <= -self.risk_limits["max_drawdown_pct"]:
            self.alerts.append({
                "level": "critical",
                "type": "max_drawdown",
                "message": f"最大回撤超限: {self.portfolio_risk.max_drawdown_pct:.2f}%",
                "timestamp": datetime.now().isoformat()
            })
        
        if self.portfolio_risk.position_count > self.risk_limits["max_position_count"]:
            self.alerts.append({
                "level": "warning",
                "type": "position_count",
                "message": f"持仓数量超限: {self.portfolio_risk.position_count}",
                "timestamp": datetime.now().isoformat()
            })
        
        for symbol, pct in self.portfolio_risk.position_concentration.items():
            if pct > self.risk_limits["max_single_position_pct"]:
                self.alerts.append({
                    "level": "warning",
                    "type": "single_position",
                    "message": f"单股票仓位超限: {symbol} {pct:.2f}%",
                    "timestamp": datetime.now().isoformat()
                })
        
        for sector, pct in self.portfolio_risk.sector_concentration.items():
            if pct > self.risk_limits["max_sector_position_pct"]:
                self.alerts.append({
                    "level": "warning",
                    "type": "sector_position",
                    "message": f"行业仓位超限: {sector} {pct:.2f}%",
                    "timestamp": datetime.now().isoformat()
                })
    
    def check_order_risk(self, symbol: str, direction: str, volume: int, 
                        price: float) -> Tuple[bool, str, Dict]:
        """检查订单风险"""
        if self._circuit_breaker_triggered:
            return False, "熔断已触发，禁止开仓", {}
        
        order_value = volume * price
        adjusted_volume = volume
        
        if direction == "BUY":
            if symbol in self.portfolio_risk.position_concentration:
                current_pct = self.portfolio_risk.position_concentration[symbol]
            else:
                current_pct = 0
            
            if self.current_capital > 0:
                new_pct = (current_pct * self.current_capital / 100 + order_value) / self.current_capital * 100
            else:
                new_pct = 0
            
            if new_pct > self.risk_limits["max_single_position_pct"]:
                max_value = self.current_capital * self.risk_limits["max_single_position_pct"] / 100
                current_value = current_pct * self.current_capital / 100
                available_value = max(0, max_value - current_value)
                adjusted_volume = int(available_value / price / 100) * 100 if price > 0 else 0
                
                if adjusted_volume <= 0:
                    return False, "单股票仓位已达上限", {}
                else:
                    return True, f"仓位调整: {volume} -> {adjusted_volume}", {"adjusted_volume": adjusted_volume}
        
        return True, "", {"adjusted_volume": adjusted_volume}
    
    def get_stop_signals(self) -> List[Dict]:
        """获取需要止损/止盈的持仓"""
        signals = []
        
        for symbol, pos in self.position_risks.items():
            sl_triggered, sl_reason = pos.check_stop_loss()
            if sl_triggered:
                signals.append({
                    "symbol": symbol,
                    "action": "SELL",
                    "reason": sl_reason,
                    "type": "stop_loss",
                    "urgency": "high"
                })
                continue
            
            tp_triggered, tp_reason = pos.check_take_profit()
            if tp_triggered:
                signals.append({
                    "symbol": symbol,
                    "action": "SELL",
                    "reason": tp_reason,
                    "type": "take_profit",
                    "urgency": "medium"
                })
        
        return signals
    
    def _record_risk_snapshot(self):
        """记录风险快照"""
        snapshot = {
            "timestamp": datetime.now().isoformat(),
            "total_equity": self.portfolio_risk.total_equity,
            "total_pnl_pct": self.portfolio_risk.total_pnl_pct,
            "daily_pnl_pct": self.portfolio_risk.daily_pnl_pct,
            "drawdown_pct": self.portfolio_risk.current_drawdown_pct,
            "position_count": self.portfolio_risk.position_count,
            "alerts_count": len(self.alerts),
            "circuit_breaker": self._circuit_breaker_triggered
        }
        self.risk_history.append(snapshot)
        
        if len(self.risk_history) > 1000:
            self.risk_history = self.risk_history[-1000:]
    
    def reset_daily(self):
        """重置每日数据"""
        self.daily_start_capital = self.current_capital
        self._circuit_breaker_triggered = False
        logger.info("Daily risk metrics reset")
    
    def get_risk_report(self) -> Dict:
        """获取风险报告"""
        return {
            "portfolio": {
                "total_equity": self.portfolio_risk.total_equity,
                "initial_capital": self.portfolio_risk.initial_capital,
                "total_pnl_pct": self.portfolio_risk.total_pnl_pct,
                "daily_pnl_pct": self.portfolio_risk.daily_pnl_pct,
                "max_drawdown_pct": self.portfolio_risk.max_drawdown_pct,
                "position_count": self.portfolio_risk.position_count,
                "win_rate": self.portfolio_risk.win_rate
            },
            "positions": {k: v.to_dict() for k, v in self.position_risks.items()},
            "concentration": {
                "single_position": self.portfolio_risk.position_concentration,
                "sector": self.portfolio_risk.sector_concentration
            },
            "alerts": self.alerts,
            "limits": self.risk_limits,
            "circuit_breaker": self._circuit_breaker_triggered
        }
    
    def get_stress_test_report(self) -> Dict:
        """获取压力测试报告（简化版）"""
        scenarios = {
            "crash_5pct": -5.0,
            "crash_10pct": -10.0,
            "crash_20pct": -20.0
        }
        
        results = {}
        for name, shock_pct in scenarios.items():
            shock_value = self.portfolio_risk.total_equity * shock_pct / 100
            new_equity = self.portfolio_risk.total_equity + shock_value
            new_drawdown = (new_equity - self.portfolio_risk.peak_equity) / self.portfolio_risk.peak_equity * 100
            
            results[name] = {
                "shock_pct": shock_pct,
                "new_equity": new_equity,
                "new_drawdown_pct": new_drawdown,
                "breaches_circuit_breaker": new_drawdown <= -self.risk_limits["max_drawdown_pct"]
            }
        
        return results
