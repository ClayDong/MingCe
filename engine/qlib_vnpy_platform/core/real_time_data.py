import json
import os
import time
import threading
from datetime import datetime
from typing import Dict, List, Optional, Any, Callable
from loguru import logger
from qlib_vnpy_platform.core.data_bridge import DataBridge
from qlib_vnpy_platform.config import get_config


REAL_TIME_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "real_time")
os.makedirs(REAL_TIME_DATA_DIR, exist_ok=True)


class MarketDataPoint:
    """单个股票的市场数据点"""
    
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.timestamp = None
        self.open = 0.0
        self.high = 0.0
        self.low = 0.0
        self.close = 0.0
        self.volume = 0
        self.amount = 0.0
        self.bid_price = 0.0
        self.bid_volume = 0
        self.ask_price = 0.0
        self.ask_volume = 0
        self.high_limit = 0.0
        self.low_limit = 0.0
        self.pre_close = 0.0
        self.change = 0.0
        self.change_pct = 0.0
        self.is_trading = False
        self.is_limit_up = False
        self.is_limit_down = False
    
    def update_from_dict(self, data: Dict):
        """从字典更新数据"""
        self.timestamp = data.get("timestamp", datetime.now().isoformat())
        self.open = float(data.get("open", 0))
        self.high = float(data.get("high", 0))
        self.low = float(data.get("low", 0))
        self.close = float(data.get("close", 0))
        self.volume = int(data.get("volume", 0))
        self.amount = float(data.get("amount", 0))
        self.bid_price = float(data.get("bid_price", 0))
        self.bid_volume = int(data.get("bid_volume", 0))
        self.ask_price = float(data.get("ask_price", 0))
        self.ask_volume = int(data.get("ask_volume", 0))
        self.high_limit = float(data.get("high_limit", 0))
        self.low_limit = float(data.get("low_limit", 0))
        self.pre_close = float(data.get("pre_close", 0))
        
        if self.pre_close > 0:
            self.change = self.close - self.pre_close
            self.change_pct = self.change / self.pre_close * 100
        
        if self.high_limit > 0 and abs(self.close - self.high_limit) < 0.01:
            self.is_limit_up = True
        else:
            self.is_limit_up = False
            
        if self.low_limit > 0 and abs(self.close - self.low_limit) < 0.01:
            self.is_limit_down = True
        else:
            self.is_limit_down = False
    
    def to_dict(self) -> Dict:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "amount": self.amount,
            "bid_price": self.bid_price,
            "bid_volume": self.bid_volume,
            "ask_price": self.ask_price,
            "ask_volume": self.ask_volume,
            "high_limit": self.high_limit,
            "low_limit": self.low_limit,
            "pre_close": self.pre_close,
            "change": self.change,
            "change_pct": self.change_pct,
            "is_trading": self.is_trading,
            "is_limit_up": self.is_limit_up,
            "is_limit_down": self.is_limit_down
        }


class RealTimeDataManager:
    """实时数据管理器：负责获取和缓存实时市场数据"""
    
    def __init__(self, update_interval: int = 3):
        self.config = get_config()
        self.update_interval = update_interval
        self.data_bridge = DataBridge()
        
        self.market_data: Dict[str, MarketDataPoint] = {}
        self.watchlist: List[str] = []
        self.subscribers: List[Callable] = []
        
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_update_time = None
        
        logger.info("RealTimeDataManager initialized")
    
    def set_watchlist(self, symbols: List[str]):
        """设置关注列表"""
        self.watchlist = symbols
        for symbol in symbols:
            if symbol not in self.market_data:
                self.market_data[symbol] = MarketDataPoint(symbol)
        logger.info(f"Watchlist set: {symbols}")
    
    def add_symbol(self, symbol: str):
        """添加单个股票到关注列表"""
        if symbol not in self.watchlist:
            self.watchlist.append(symbol)
        if symbol not in self.market_data:
            self.market_data[symbol] = MarketDataPoint(symbol)
    
    def remove_symbol(self, symbol: str):
        """从关注列表移除股票"""
        if symbol in self.watchlist:
            self.watchlist.remove(symbol)
        if symbol in self.market_data:
            del self.market_data[symbol]
    
    def subscribe(self, callback: Callable):
        """订阅数据更新"""
        if callback not in self.subscribers:
            self.subscribers.append(callback)
    
    def unsubscribe(self, callback: Callable):
        """取消订阅"""
        if callback in self.subscribers:
            self.subscribers.remove(callback)
    
    def _notify_subscribers(self):
        """通知订阅者"""
        data = self.get_all_market_data()
        for callback in self.subscribers:
            try:
                callback(data)
            except Exception as e:
                logger.warning(f"Subscriber callback error: {e}")
    
    def _fetch_real_time_data(self) -> Dict[str, MarketDataPoint]:
        """获取实时数据"""
        result = {}
        
        for symbol in self.watchlist:
            try:
                data_point = MarketDataPoint(symbol)
                
                # 尝试从数据源获取实时数据
                try:
                    df = self.data_bridge.get_realtime_quote(symbol)
                    if not df.empty:
                        latest = df.iloc[-1]
                        data_point.update_from_dict({
                            "timestamp": datetime.now().isoformat(),
                            "open": latest.get("open", 0),
                            "high": latest.get("high", 0),
                            "low": latest.get("low", 0),
                            "close": latest.get("close", 0),
                            "volume": latest.get("volume", 0),
                            "amount": latest.get("amount", 0)
                        })
                        data_point.is_trading = True
                except Exception as e:
                    # 如果没有实时数据，使用历史数据最后一条模拟
                    try:
                        df = self.data_bridge.get_historical_data(symbol, period="1d")
                        if not df.empty:
                            latest = df.iloc[-1]
                            data_point.update_from_dict({
                                "timestamp": datetime.now().isoformat(),
                                "open": latest.get("open", 0),
                                "high": latest.get("high", 0),
                                "low": latest.get("low", 0),
                                "close": latest.get("close", 0),
                                "volume": latest.get("volume", 0),
                                "amount": latest.get("amount", 0)
                            })
                    except Exception:
                        pass
                
                result[symbol] = data_point
                self.market_data[symbol] = data_point
                
            except Exception as e:
                logger.warning(f"Failed to fetch data for {symbol}: {e}")
        
        return result
    
    def _run_loop(self):
        """主循环"""
        while self._running:
            try:
                self._fetch_real_time_data()
                self._last_update_time = datetime.now()
                self._notify_subscribers()
            except Exception as e:
                logger.error(f"Real-time data update error: {e}")
            
            time.sleep(self.update_interval)
    
    def start(self):
        """启动实时数据获取"""
        if self._running:
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("RealTimeDataManager started")
    
    def stop(self):
        """停止实时数据获取"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("RealTimeDataManager stopped")
    
    def get_market_data(self, symbol: str) -> Optional[MarketDataPoint]:
        """获取单个股票数据"""
        return self.market_data.get(symbol)
    
    def get_all_market_data(self) -> Dict[str, Dict]:
        """获取所有股票数据"""
        return {k: v.to_dict() for k, v in self.market_data.items()}
    
    def get_price(self, symbol: str) -> float:
        """获取最新价格"""
        data = self.market_data.get(symbol)
        if data:
            return data.close
        return 0.0
    
    def is_limit_up(self, symbol: str) -> bool:
        """检查是否涨停"""
        data = self.market_data.get(symbol)
        if data:
            return data.is_limit_up
        return False
    
    def is_limit_down(self, symbol: str) -> bool:
        """检查是否跌停"""
        data = self.market_data.get(symbol)
        if data:
            return data.is_limit_down
        return False
    
    def get_status(self) -> Dict:
        """获取状态"""
        return {
            "running": self._running,
            "watchlist": self.watchlist,
            "last_update": self._last_update_time.isoformat() if self._last_update_time else None,
            "subscribers_count": len(self.subscribers),
            "market_data_count": len(self.market_data)
        }
    
    def save_snapshot(self):
        """保存当前数据快照"""
        snapshot = {
            "timestamp": datetime.now().isoformat(),
            "market_data": self.get_all_market_data()
        }
        file_path = os.path.join(REAL_TIME_DATA_DIR, f"snapshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False, indent=2)
        logger.info(f"Snapshot saved to {file_path}")


class OrderBook:
    """订单簿（买卖盘）"""
    
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.bids: List[Dict] = []  # 买盘: [{"price": 10.0, "volume": 1000}, ...]
        self.asks: List[Dict] = []  # 卖盘
        self.timestamp = None
    
    def update(self, bids: List[Dict], asks: List[Dict]):
        """更新订单簿"""
        self.bids = sorted(bids, key=lambda x: x["price"], reverse=True)
        self.asks = sorted(asks, key=lambda x: x["price"])
        self.timestamp = datetime.now().isoformat()
    
    def get_best_bid(self) -> Optional[Dict]:
        """获取最佳买价"""
        return self.bids[0] if self.bids else None
    
    def get_best_ask(self) -> Optional[Dict]:
        """获取最佳卖价"""
        return self.asks[0] if self.asks else None
    
    def get_spread(self) -> float:
        """获取买卖价差"""
        best_bid = self.get_best_bid()
        best_ask = self.get_best_ask()
        if best_bid and best_ask:
            return best_ask["price"] - best_bid["price"]
        return 0.0
    
    def get_depth(self, levels: int = 5) -> Dict:
        """获取指定深度的订单簿"""
        return {
            "bids": self.bids[:levels],
            "asks": self.asks[:levels],
            "timestamp": self.timestamp
        }
