import json
import os
import time
import random
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
from loguru import logger
from qlib_vnpy_platform.config import get_config


EXECUTION_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "execution")
os.makedirs(EXECUTION_DIR, exist_ok=True)


class Order:
    """订单对象"""
    
    def __init__(self, symbol: str, direction: str, volume: int, 
                 order_type: str = "market", price: float = 0.0):
        self.order_id = f"ORD_{int(time.time() * 1000)}_{random.randint(1000, 9999)}"
        self.symbol = symbol
        self.direction = direction  # BUY/SELL
        self.volume = volume
        self.filled_volume = 0
        self.remaining_volume = volume
        self.order_type = order_type  # market/limit
        self.price = price
        self.status = "pending"  # pending/partially_filled/filled/cancelled/rejected
        self.create_time = datetime.now().isoformat()
        self.update_time = None
        self.avg_fill_price = 0.0
        self.total_cost = 0.0
        self.strategy = ""
        self.reason = ""
        self.execution_plan: List[Dict] = []
    
    def to_dict(self) -> Dict:
        return {
            "order_id": self.order_id,
            "symbol": self.symbol,
            "direction": self.direction,
            "volume": self.volume,
            "filled_volume": self.filled_volume,
            "remaining_volume": self.remaining_volume,
            "order_type": self.order_type,
            "price": self.price,
            "status": self.status,
            "create_time": self.create_time,
            "update_time": self.update_time,
            "avg_fill_price": self.avg_fill_price,
            "total_cost": self.total_cost,
            "strategy": self.strategy,
            "reason": self.reason
        }


class ExecutionSlice:
    """订单切片"""
    
    def __init__(self, volume: int, delay_seconds: int = 0, 
                 price_strategy: str = "follow"):
        self.volume = volume
        self.delay_seconds = delay_seconds
        self.price_strategy = price_strategy  # follow/aggressive/passive
        self.executed = False
        self.execution_time = None
        self.execution_price = 0.0


class ExecutionOptimizer:
    """执行优化器：负责智能拆单和订单执行"""
    
    def __init__(self):
        self.config = get_config()
        
        self.orders: Dict[str, Order] = {}
        self.active_orders: List[str] = []
        self.execution_history: List[Dict] = []
        
        self.min_slice_size = 100  # 最小切片手数
        self.max_slice_size = 10000  # 最大切片手数
        self.default_slices = 5  # 默认切片数
        self.slice_delay_range = (3, 15)  # 切片延迟范围（秒）
        
        self.price_offset_buy = 0.001  # 买入价格偏移
        self.price_offset_sell = 0.001  # 卖出价格偏移
        
        self._running = False
        self._pending_slices: List[Tuple[Order, ExecutionSlice]] = []
        
        logger.info("ExecutionOptimizer initialized")
    
    def create_order(self, symbol: str, direction: str, volume: int,
                    order_type: str = "market", price: float = 0.0,
                    strategy: str = "", reason: str = "") -> Order:
        """创建订单"""
        order = Order(symbol, direction, volume, order_type, price)
        order.strategy = strategy
        order.reason = reason
        
        self.orders[order.order_id] = order
        logger.info(f"Created order {order.order_id}: {direction} {symbol} {volume}")
        
        return order
    
    def create_execution_plan(self, order: Order, 
                            current_price: float,
                            avg_volume_1min: float = None,
                            avg_volume_5min: float = None) -> List[ExecutionSlice]:
        """创建执行计划（智能拆单）"""
        slices = []
        
        if order.volume <= self.min_slice_size * 2:
            slice = ExecutionSlice(order.volume, 0, "aggressive")
            slices.append(slice)
        else:
            volume_remaining = order.volume
            num_slices = min(self.default_slices, int(volume_remaining / self.min_slice_size))
            num_slices = max(2, num_slices)
            
            base_slice_size = int(volume_remaining / num_slices / 100) * 100
            
            for i in range(num_slices):
                if i == num_slices - 1:
                    slice_volume = volume_remaining
                else:
                    slice_volume = base_slice_size
                
                delay = random.randint(self.slice_delay_range[0], self.slice_delay_range[1])
                
                if i == 0:
                    price_strategy = "aggressive"
                elif i == num_slices - 1:
                    price_strategy = "passive"
                else:
                    price_strategy = "follow"
                
                slice = ExecutionSlice(slice_volume, delay if i > 0 else 0, price_strategy)
                slices.append(slice)
                volume_remaining -= slice_volume
        
        order.execution_plan = [
            {"volume": s.volume, "delay": s.delay_seconds, "strategy": s.price_strategy}
            for s in slices
        ]
        
        return slices
    
    def calculate_execution_price(self, direction: str, current_price: float,
                                 bid_price: float = None, ask_price: float = None,
                                 price_strategy: str = "follow") -> float:
        """计算执行价格"""
        if direction == "BUY":
            if ask_price and ask_price > 0:
                base_price = ask_price
            else:
                base_price = current_price * (1 + self.price_offset_buy)
            
            if price_strategy == "aggressive":
                return base_price * 1.001
            elif price_strategy == "passive":
                return base_price * 0.999
            else:
                return base_price
        else:
            if bid_price and bid_price > 0:
                base_price = bid_price
            else:
                base_price = current_price * (1 - self.price_offset_sell)
            
            if price_strategy == "aggressive":
                return base_price * 0.999
            elif price_strategy == "passive":
                return base_price * 1.001
            else:
                return base_price
    
    def simulate_execution(self, order: Order, current_price: float,
                          bid_price: float = None, ask_price: float = None) -> Dict:
        """模拟订单执行"""
        slices = self.create_execution_plan(order, current_price)
        
        total_filled = 0
        total_cost = 0
        execution_steps = []
        
        for i, slice in enumerate(slices):
            exec_price = self.calculate_execution_price(
                order.direction, current_price, 
                bid_price, ask_price,
                slice.price_strategy
            )
            
            total_filled += slice.volume
            total_cost += exec_price * slice.volume
            
            execution_steps.append({
                "slice_index": i,
                "volume": slice.volume,
                "execution_price": exec_price,
                "delay": slice.delay_seconds,
                "strategy": slice.price_strategy
            })
            
            # 模拟价格变动
            price_change = random.uniform(-0.002, 0.002)
            current_price *= (1 + price_change)
        
        avg_fill_price = total_cost / total_filled if total_filled > 0 else 0
        
        result = {
            "order_id": order.order_id,
            "symbol": order.symbol,
            "direction": order.direction,
            "total_volume": order.volume,
            "avg_fill_price": avg_fill_price,
            "total_cost": total_cost,
            "slippage_est": (avg_fill_price - current_price) / current_price * 100 if order.direction == "BUY" 
                          else (current_price - avg_fill_price) / current_price * 100,
            "execution_steps": execution_steps,
            "estimated_time_seconds": sum(s.delay_seconds for s in slices)
        }
        
        return result
    
    def optimize_execution(self, symbol: str, direction: str, volume: int,
                          current_price: float, bid_price: float = None,
                          ask_price: float = None, urgency: str = "normal",
                          strategy: str = "", reason: str = "") -> Dict:
        """优化执行并返回最佳方案"""
        order = self.create_order(symbol, direction, volume, "market", 0, strategy, reason)
        
        if urgency == "high":
            execution_strategy = {
                "slices": 1,
                "price_strategy": "aggressive",
                "expected_slippage": 0.2
            }
        elif urgency == "low":
            execution_strategy = {
                "slices": 10,
                "price_strategy": "passive",
                "expected_slippage": 0.05
            }
        else:
            execution_strategy = {
                "slices": 5,
                "price_strategy": "follow",
                "expected_slippage": 0.1
            }
        
        simulation = self.simulate_execution(order, current_price, bid_price, ask_price)
        
        return {
            "order": order.to_dict(),
            "strategy": execution_strategy,
            "simulation": simulation
        }
    
    def check_limits_for_execution(self, symbol: str, direction: str, volume: int,
                                  current_price: float, is_limit_up: bool = False,
                                  is_limit_down: bool = False) -> Tuple[bool, str]:
        """检查执行限制"""
        if direction == "BUY" and is_limit_up:
            return False, "涨停无法买入"
        
        if direction == "SELL" and is_limit_down:
            return False, "跌停无法卖出"
        
        if volume < 100:
            return False, "最小单位100股"
        
        return True, ""
    
    def execute_vwap(self, symbol: str, direction: str, volume: int,
                    duration_minutes: int = 30, num_slices: int = 10) -> Dict:
        """VWAP执行策略"""
        interval_seconds = duration_minutes * 60 / num_slices
        slice_volume = int(volume / num_slices / 100) * 100
        
        slices = []
        for i in range(num_slices):
            if i == num_slices - 1:
                remaining = volume - slice_volume * i
                if remaining > 0:
                    slices.append(ExecutionSlice(remaining, int(i * interval_seconds), "follow"))
            else:
                slices.append(ExecutionSlice(slice_volume, int(i * interval_seconds), "follow"))
        
        return {
            "strategy": "vwap",
            "duration_minutes": duration_minutes,
            "slices": len(slices),
            "plan": slices
        }
    
    def execute_twap(self, symbol: str, direction: str, volume: int,
                    duration_minutes: int = 30, num_slices: int = 10) -> Dict:
        """TWAP执行策略"""
        return self.execute_vwap(symbol, direction, volume, duration_minutes, num_slices)
    
    def get_execution_report(self, order_id: str = None) -> Dict:
        """获取执行报告"""
        if order_id:
            order = self.orders.get(order_id)
            if order:
                return {"order": order.to_dict()}
            return {"error": "Order not found"}
        
        return {
            "total_orders": len(self.orders),
            "active_orders": len(self.active_orders),
            "recent_executions": self.execution_history[-20:],
            "statistics": self._calculate_execution_statistics()
        }
    
    def _calculate_execution_statistics(self) -> Dict:
        """计算执行统计"""
        if not self.execution_history:
            return {}
        
        total_orders = len(self.execution_history)
        filled_orders = [h for h in self.execution_history if h.get("status") == "filled"]
        
        if filled_orders:
            slippages = [h.get("slippage_pct", 0) for h in filled_orders]
            avg_slippage = sum(slippages) / len(slippages)
        else:
            avg_slippage = 0
        
        return {
            "total_orders": total_orders,
            "filled_orders": len(filled_orders),
            "avg_slippage_pct": avg_slippage
        }
    
    def record_execution(self, order: Order, fill_price: float, fill_volume: int):
        """记录执行结果"""
        order.filled_volume += fill_volume
        order.remaining_volume -= fill_volume
        
        if order.filled_volume == order.volume:
            order.status = "filled"
        elif order.filled_volume > 0:
            order.status = "partially_filled"
        
        order.avg_fill_price = ((order.avg_fill_price * (order.filled_volume - fill_volume)) + 
                                (fill_price * fill_volume)) / order.filled_volume if order.filled_volume > 0 else 0
        order.total_cost = order.avg_fill_price * order.filled_volume
        order.update_time = datetime.now().isoformat()
        
        record = {
            "order_id": order.order_id,
            "symbol": order.symbol,
            "direction": order.direction,
            "fill_price": fill_price,
            "fill_volume": fill_volume,
            "status": order.status,
            "timestamp": datetime.now().isoformat()
        }
        self.execution_history.append(record)
        
        if len(self.execution_history) > 1000:
            self.execution_history = self.execution_history[-1000:]
        
        logger.info(f"Executed {order.order_id}: {fill_volume} at {fill_price}")
