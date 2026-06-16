import json
import time
import pandas as pd
import numpy as np
from datetime import datetime
from pathlib import Path
from loguru import logger
from qlib_vnpy_platform.config import get_config, PROJECT_ROOT, LOGS_DIR
from qlib_vnpy_platform.core.data_bridge import DataBridge
from qlib_vnpy_platform.core.news_fetcher import NewsFetcher
from qlib_vnpy_platform.core.llm_analyzer import LLManalyzer
from qlib_vnpy_platform.core.signal_router import SignalRouter
from qlib_vnpy_platform.core.risk_manager import RiskManager
from qlib_vnpy_platform.core.log_manager import setup_logging


class TradingEngine:
    def __init__(self, load_persistence: bool = True):
        self.config = get_config()["trading"]
        self.commission_rate = self.config.get("commission_rate", 0.0003)
        self.slippage = self.config.get("slippage", 0.001)
        self.min_lot_size = self.config.get("min_lot_size", 100)
        self.mode = self.config.get("mode", "paper")
        
        if self.mode == "live":
            logger.warning("=" * 60)
            logger.warning("⚠️  ⚠️  ⚠️  实盘交易模式已开启！")
            logger.warning("⚠️  请确认您已充分了解风险，此模式将进行真实交易！")
            logger.warning("=" * 60)
        else:
            logger.info("📊 模拟交易模式已开启 - 安全无风险")

        from qlib_vnpy_platform.core.persistence import PersistenceManager
        self.persistence = PersistenceManager()
        
        self._positions = {}
        self._orders = []
        self._trades = []
        self._cash = 1000000.0  # 可用现金
        self._initial_capital = 1000000.0  # 初始资金
        self._daily_pnl = 0.0
        self._total_pnl = 0.0
        self._sector_map = self.load_sector_map()
        
        if load_persistence:
            self._load_state()
        
        logger.info(f"TradingEngine initialized: mode={self.mode}, cash={self._cash}")

    def _get_state(self) -> dict:
        return {
            "positions": self._positions,
            "orders": self._orders,
            "trades": self._trades,
            "cash": self._cash,
            "initial_capital": self._initial_capital,
            "total_pnl": self._total_pnl,
            "saved_at": datetime.now().isoformat()
        }
    
    def _save_state(self):
        try:
            state = self._get_state()
            self.persistence.save_trading_state(state)
            logger.debug("Trading state saved")
        except Exception as e:
            logger.error(f"Failed to save trading state: {e}")
    
    def _load_state(self):
        try:
            state = self.persistence.load_trading_state()
            if state:
                self._positions = state.get("positions", {})
                self._orders = state.get("orders", [])
                self._trades = state.get("trades", [])
                self._cash = state.get("cash", 1000000.0)
                self._initial_capital = state.get("initial_capital", 1000000.0)
                self._total_pnl = state.get("total_pnl", 0.0)
                logger.info(f"Trading state loaded: {len(self._positions)} positions, {len(self._trades)} trades")
        except Exception as e:
            logger.error(f"Failed to load trading state: {e}")

    def load_sector_map(self) -> dict:
        """加载行业映射表，优先从配置读取，否则使用空映射。"""
        try:
            full_config = get_config()
            sector_config = full_config.get("sector_map", {})
            if sector_config:
                logger.info(f"Loaded sector_map from config with {len(sector_config)} entries")
                return sector_config
        except Exception as e:
            logger.warning(f"Failed to load sector_map from config: {e}")
        logger.info("Using empty sector_map (configure in settings.yaml to add mappings)")
        return {}

    def get_stock_sector(self, symbol: str) -> str:
        return self._sector_map.get(symbol, "其他")

    @property
    def account(self) -> dict:
        position_value = sum(
            p.get("volume", 0) * p.get("current_price", 0)
            for p in self._positions.values()
        )
        total_capital = self._cash + position_value
        return {
            "total_capital": total_capital,
            "cash": self._cash,
            "position_value": position_value,
            "initial_capital": self._initial_capital,
            "daily_pnl": self._daily_pnl,
            "total_pnl": total_capital - self._initial_capital,
            "total_pnl_pct": (total_capital - self._initial_capital) / self._initial_capital,
        }

    @property
    def portfolio(self) -> dict:
        return {"positions": self._positions}

    def execute_order(self, order: dict) -> dict:
        symbol = order.get("symbol", "")
        direction = order.get("direction", "HOLD")
        volume = order.get("adjusted_volume", order.get("volume", 0))
        price = order.get("price", 0)

        if direction == "HOLD" or volume <= 0:
            return {"status": "SKIPPED", "reason": "无需交易"}

        if price <= 0:
            price = self._get_current_price(symbol)
            if price <= 0:
                return {"status": "FAILED", "reason": "无法获取价格"}

        actual_price = price * (1 + self.slippage) if direction == "BUY" else price * (1 - self.slippage)
        commission = actual_price * volume * self.commission_rate

        trade = {
            "symbol": symbol,
            "direction": direction,
            "volume": volume,
            "price": actual_price,
            "commission": commission,
            "timestamp": datetime.now().isoformat(),
            "mode": self.mode,
        }

        pnl = 0
        if direction == "BUY":
            cost = actual_price * volume + commission
            if cost > self._cash:
                affordable_volume = int(self._cash / (actual_price * (1 + self.commission_rate)) / self.min_lot_size) * self.min_lot_size
                if affordable_volume <= 0:
                    return {"status": "FAILED", "reason": "资金不足"}
                volume = affordable_volume
                commission = actual_price * volume * self.commission_rate
                cost = actual_price * volume + commission
                trade["volume"] = volume
                trade["commission"] = commission

            self._cash -= cost

            if symbol in self._positions:
                pos = self._positions[symbol]
                total_volume = pos["volume"] + volume
                avg_cost = (pos["avg_cost"] * pos["volume"] + actual_price * volume) / total_volume
                pos["volume"] = total_volume
                pos["avg_cost"] = avg_cost
                pos["current_price"] = actual_price
                pos["market_value"] = total_volume * actual_price
            else:
                self._positions[symbol] = {
                    "volume": volume,
                    "avg_cost": actual_price,
                    "current_price": actual_price,
                    "market_value": volume * actual_price,
                    "buy_date": datetime.now().strftime("%Y-%m-%d"),
                    "sector": self.get_stock_sector(symbol),
                }

        elif direction == "SELL":
            if symbol not in self._positions:
                return {"status": "FAILED", "reason": "无持仓"}

            pos = self._positions[symbol]
            if volume > pos["volume"]:
                volume = pos["volume"]
                trade["volume"] = volume

            stamp_tax = actual_price * volume * 0.0005
            revenue = actual_price * volume - commission - stamp_tax
            self._cash += revenue

            pnl = (actual_price - pos["avg_cost"]) * volume - commission - stamp_tax
            self._daily_pnl += pnl
            self._total_pnl += pnl

            pos["volume"] -= volume
            pos["current_price"] = price
            pos["market_value"] = pos["volume"] * price

            if pos["volume"] <= 0:
                del self._positions[symbol]

        trade["pnl"] = pnl if direction == "SELL" else 0
        self._trades.append(trade)

        order_record = {
            **order,
            "status": "FILLED",
            "filled_price": actual_price,
            "filled_volume": volume,
            "commission": commission,
            "timestamp": datetime.now().isoformat(),
        }
        self._orders.append(order_record)
        
        self._save_state()
        self.persistence.append_trade(trade)

        logger.info(f"Trade executed: {direction} {symbol} {volume}@{actual_price:.2f}, "
                    f"commission={commission:.2f}")
        return {"status": "FILLED", "trade": trade}

    def update_position_prices(self, price_data: dict):
        updated = False
        for symbol, pos in self._positions.items():
            if symbol in price_data:
                current_price = price_data[symbol].get("price", pos.get("current_price", 0))
                pos["current_price"] = current_price
                pos["market_value"] = pos["volume"] * current_price
                updated = True
        if updated:
            self._save_state()

    def get_positions(self) -> dict:
        return dict(self._positions)

    def get_trades(self, limit: int = 50) -> list:
        return self._trades[-limit:]

    def get_orders(self, limit: int = 50) -> list:
        return self._orders[-limit:]

    def _get_current_price(self, symbol: str) -> float:
        if symbol in self._positions:
            return self._positions[symbol].get("current_price", 0)
        return 0

    def reset_daily(self):
        self._daily_pnl = 0.0
        logger.info("TradingEngine daily reset")


class QLibModel:
    """
    QLibModel — 改造后采用真正的 QLibPredictor 作为后端
    
    保持与 SignalRouter 的兼容性（simple_predict 返回 float 0~1），
    内部使用 QLibPredictor 的三层架构：QLib → sklearn → rule
    
    兼容旧接口：
      - simple_predict(df) -> float  （0~1 评分，保持原样）
      - predict(instruments) -> pd.DataFrame  （QLib 原生预测，可能返回空）
      - train(...) -> dict
      - get_info() -> dict  （新增）
    """

    def __init__(self):
        from qlib_vnpy_platform.core.qlib_predictor import QLibPredictor
        self._predictor = QLibPredictor()
        self._trained = False
        logger.info(f"QLibModel initialized with {self._predictor.get_mode_name()}")

    def init_qlib(self):
        """保持兼容——实际初始化已在 QLibPredictor 构造函数中完成"""
        if self._predictor._qlib_available:
            logger.info("QLib already initialized via QLibPredictor")
        else:
            logger.warning("QLib not available, using fallback mode")

    def train(self, df_dict: dict = None, instruments: list = None,
              start_date: str = "2020-01-01", end_date: str = None,
              model_type: str = "lgb") -> dict:
        """
        训练模型
        
        参数:
            df_dict: {symbol: DataFrame} — sklearn 模式需要
            instruments: list[str] — QLib 模式需要
            start_date/end_date: 训练时间范围
            model_type: 保留参数（QLib模式下固定用 LGBModel）
        """
        result = self._predictor.train(
            df_dict=df_dict,
            instruments=instruments,
            start_date=start_date,
            end_date=end_date,
        )
        if result.get("status") == "success":
            self._trained = True
        return result

    def predict(self, instruments: list = None) -> pd.DataFrame:
        """QLib 原生预测接口（保留兼容，可能返回空）"""
        if not self._trained:
            logger.warning("Model not trained, returning empty predictions")
            return pd.DataFrame()

        try:
            if self._predictor._dataset is not None:
                pred = self._predictor._model.predict(self._predictor._dataset)
                return pred
        except Exception as e:
            logger.error(f"QLib prediction failed: {e}")

        return pd.DataFrame()

    def simple_predict(self, df: pd.DataFrame) -> float:
        """
        核心预测接口 — 返回 0~1 的评分
        
        内部委托给 QLibPredictor.predict()，支持三层 fallback。
        """
        if df is None or df.empty:
            return 0.5

        try:
            result = self._predictor.predict(df)
            logger.info(f"simple_predict: score={result.score:.4f}, "
                        f"signal={result.signal}, confidence={result.confidence:.2f}, "
                        f"mode={result.mode}")
            return result.score
        except Exception as e:
            logger.warning(f"QLibPredictor prediction failed, using built-in rule fallback: {e}")
            return self._builtin_rule_fallback(df)

    def predict_with_detail(self, df: pd.DataFrame) -> dict:
        """
        详细预测接口 — 返回完整预测信息（供高级使用）
        
        返回:
            {
                "score": float,       # 0~1
                "signal": str,        # BUY/SELL/HOLD
                "confidence": float,  # 0~1
                "mode": str,          # qlib/sklearn/rule
                "features_used": int,
                "model_ready": bool,
                "detail": dict,
            }
        """
        if df is None or df.empty:
            return {"score": 0.5, "signal": "HOLD", "confidence": 0.0,
                    "mode": "rule", "features_used": 0, "model_ready": False,
                    "detail": {"reason": "无数据"}}

        try:
            result = self._predictor.predict(df)
            return {
                "score": result.score,
                "signal": result.signal,
                "confidence": result.confidence,
                "mode": result.mode,
                "features_used": result.features_used,
                "model_ready": result.model_ready,
                "detail": result.detail,
            }
        except Exception as e:
            return {"score": 0.5, "signal": "HOLD", "confidence": 0.0,
                    "mode": "rule", "features_used": 0, "model_ready": False,
                    "detail": {"error": str(e)}}

    def get_info(self) -> dict:
        """获取 QLibModel 状态信息"""
        info = self._predictor.get_info()
        info["trained"] = self._trained
        return info

    def get_mode_name(self) -> str:
        """获取当前运行模式的中文描述"""
        return self._predictor.get_mode_name()

    def _builtin_rule_fallback(self, df: pd.DataFrame) -> float:
        """内置规则 fallback（当 QLibPredictor.predict 异常时的最后保障）"""
        if len(df) < 10:
            return 0.5

        df = df.copy()
        scores = []

        # 1. MA5/MA20 交叉
        if len(df) >= 20:
            ma5 = df["close"].rolling(5).mean().iloc[-1]
            ma20 = df["close"].rolling(20).mean().iloc[-1]
            ma5_prev = df["close"].rolling(5).mean().iloc[-2] if len(df) >= 6 else ma5
            ma20_prev = df["close"].rolling(20).mean().iloc[-2] if len(df) >= 21 else ma20
            if ma5_prev <= ma20_prev and ma5 > ma20:
                scores.append(0.7)
            elif ma5_prev >= ma20_prev and ma5 < ma20:
                scores.append(0.3)
            elif ma5 > ma20:
                scores.append(0.55)
            else:
                scores.append(0.45)

        # 2. RSI
        rsi = self._calc_rsi(df["close"], 14).iloc[-1] if len(df) >= 15 else 50
        if rsi < 30:
            scores.append(0.65)
        elif rsi > 70:
            scores.append(0.35)
        elif rsi < 50:
            scores.append(0.52)
        else:
            scores.append(0.48)

        # 3. 短期动量
        if len(df) >= 5:
            mom = (df["close"].iloc[-1] / df["close"].iloc[-5] - 1)
            if mom > 0.03:
                scores.append(0.58)
            elif mom < -0.03:
                scores.append(0.42)
            else:
                scores.append(0.50)

        # 4. 成交量
        if len(df) >= 10:
            cur_vol = df["volume"].iloc[-1]
            avg_vol = df["volume"].iloc[-10:].mean()
            if cur_vol > avg_vol * 1.3 and df["close"].iloc[-1] > df["close"].iloc[-2]:
                scores.append(0.55)
            elif cur_vol > avg_vol * 1.3 and df["close"].iloc[-1] < df["close"].iloc[-2]:
                scores.append(0.45)
            else:
                scores.append(0.50)

        final_score = float(np.mean(scores)) if scores else 0.5
        final_score = max(0.1, min(0.9, final_score))
        logger.info(f"Built-in rule fallback: {final_score:.4f}")
        return final_score

    @staticmethod
    def _calc_rsi(prices: pd.Series, period: int = 14) -> pd.Series:
        delta = prices.diff()
        gain = delta.where(delta > 0, 0)
        loss = (-delta).where(delta < 0, 0)
        avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, np.inf)
        return 100 - (100 / (1 + rs))


class MainEngine:
    def __init__(self):
        setup_logging()

        self.data_bridge = DataBridge()
        self.news_fetcher = NewsFetcher()
        self.llm_analyzer = LLManalyzer()
        self.signal_router = SignalRouter()
        self.risk_manager = RiskManager()
        
        # 从配置加载行业映射
        try:
            config = get_config()
            sector_map = config.get("sector_map", {})
            self.risk_manager.set_sector_map(sector_map)
            logger.info(f"Set risk_manager sector_map with {len(sector_map)} entries")
        except Exception as e:
            logger.warning(f"Failed to load sector_map for risk_manager: {e}")
        
        self.trading_engine = TradingEngine()
        self.qlib_model = QLibModel()

        self._watch_list = []
        self._running = False
        self._start_time = datetime.now()
        self._analysis_results = {}

        from qlib_vnpy_platform.core.scheduler import Scheduler
        self.scheduler = Scheduler(self)

        from qlib_vnpy_platform.core.strategy_monitor import StrategyMonitor
        self.strategy_monitor = StrategyMonitor(self.data_bridge)

        self._load_default_watchlist()

        logger.info("MainEngine initialized - all modules ready")
    
    def _load_default_watchlist(self):
        config = get_config()
        watchlist_config = config.get("watchlist", {})
        default_stocks = watchlist_config.get("default_stocks", [])
        
        if default_stocks:
            logger.info(f"Loading default watchlist: {default_stocks}")
            for symbol in default_stocks:
                self.add_stock(symbol)
            logger.info(f"Loaded {len(self._watch_list)} default stocks")

    def add_stock(self, symbol: str):
        if symbol not in self._watch_list:
            self._watch_list.append(symbol)
            logger.info(f"Added {symbol} to watch list")
            if self.scheduler._watch_list != self._watch_list:
                self.scheduler._watch_list = list(self._watch_list)
            self.strategy_monitor.configure(symbols=list(self._watch_list))

    def remove_stock(self, symbol: str):
        if symbol in self._watch_list:
            self._watch_list.remove(symbol)
            logger.info(f"Removed {symbol} from watch list")
            if self.scheduler._watch_list != self._watch_list:
                self.scheduler._watch_list = list(self._watch_list)
            self.strategy_monitor.configure(symbols=list(self._watch_list))

    def analyze_stock(self, symbol: str, use_llm: bool = True,
                      use_qlib: bool = True, auto_trade: bool = False) -> dict:
        logger.info(f"Starting analysis for {symbol}")
        result = {
            "symbol": symbol,
            "timestamp": datetime.now().isoformat(),
            "market_data": {},
            "news": [],
            "qlib_pred": None,
            "llm_result": None,
            "signal": None,
            "order": None,
            "risk_check": None,
        }

        realtime_data = self.data_bridge.fetch_stock_realtime(symbol)
        result["market_data"] = realtime_data

        daily_df = self.data_bridge.fetch_stock_daily(symbol)
        if not daily_df.empty:
            daily_df = self.data_bridge.calc_technical_indicators(daily_df)
            latest_row = daily_df.iloc[-1]

            if not realtime_data:
                realtime_data = {
                    "price": float(latest_row.get("close", 0)),
                    "change_pct": float(latest_row.get("change_pct", 0)),
                    "volume": float(latest_row.get("volume", 0)),
                    "high": float(latest_row.get("high", 0)),
                    "low": float(latest_row.get("low", 0)),
                    "open": float(latest_row.get("open", 0)),
                }

            for indicator in ["ma5", "ma10", "ma20", "rsi", "macd", "macd_signal",
                             "boll_upper", "boll_lower"]:
                if indicator in latest_row and not pd.isna(latest_row[indicator]):
                    realtime_data[indicator] = float(latest_row[indicator])

            result["market_data"] = realtime_data

        if use_qlib and not daily_df.empty:
            qlib_pred = self.qlib_model.simple_predict(daily_df)
            result["qlib_pred"] = qlib_pred

        if use_llm:
            news_list = self.news_fetcher.fetch_stock_news(symbol)
            result["news"] = news_list
            news_text = self.news_fetcher.format_news_for_llm(news_list)

            llm_result = self.llm_analyzer.analyze(
                stock_code=symbol,
                market_data=realtime_data,
                news_text=news_text,
                qlib_pred=result.get("qlib_pred"),
            )
            result["llm_result"] = llm_result

        current_price = realtime_data.get("price", 0) if realtime_data else 0

        signal = self.signal_router.fuse_signals(
            symbol=symbol,
            qlib_pred=result.get("qlib_pred"),
            llm_result=result.get("llm_result"),
            current_price=current_price,
        )
        result["signal"] = signal

        if signal["direction"] != "HOLD":
            order = self.signal_router.signal_to_order(
                signal, self.trading_engine.account
            )
            result["order"] = order

            risk_check = self.risk_manager.check_order(
                order, self.trading_engine.account, self.trading_engine.portfolio
            )

            if order["direction"] == "SELL" and risk_check["approved"]:
                sell_check = self.risk_manager.check_sell_restriction(
                    symbol, "SELL", self.trading_engine.portfolio
                )
                if not sell_check["approved"]:
                    risk_check["approved"] = False
                    risk_check["reason"] = sell_check["reason"]

            result["risk_check"] = risk_check

            if risk_check["approved"]:
                if auto_trade:
                    if risk_check.get("adjusted_volume"):
                        order["adjusted_volume"] = risk_check["adjusted_volume"]
                    trade_result = self.trading_engine.execute_order(order)
                    result["trade_result"] = trade_result
                else:
                    logger.info(f"Auto-trade disabled, order not executed for {symbol}")
                    result["trade_result"] = {"status": "PENDING", "reason": "auto_trade disabled"}
            else:
                logger.info(f"Order rejected by risk manager: {risk_check['reason']}")

        self._analysis_results[symbol] = result
        return result

    def analyze_all(self) -> list:
        results = []
        for symbol in self._watch_list:
            try:
                result = self.analyze_stock(symbol)
                results.append(result)
            except Exception as e:
                logger.error(f"Analysis failed for {symbol}: {e}")
                results.append({
                    "symbol": symbol,
                    "error": str(e),
                    "timestamp": datetime.now().isoformat(),
                })
        return results

    def get_status(self) -> dict:
        from qlib_vnpy_platform.core.strategies import STRATEGY_REGISTRY
        return {
            "status": "running" if self._running else "stopped",
            "start_time": self._start_time.isoformat() if self._start_time else None,
            "uptime": str(datetime.now() - self._start_time) if self._start_time else "N/A",
            "strategies": {
                "loaded": len(STRATEGY_REGISTRY),
                "running": 0,
                "backtesting": 0,
            },
            "data_sources": {
                "qlib_available": self.data_bridge.is_qlib_available(),
                "akshare_available": self.data_bridge.is_akshare_available(),
                "tushare_available": self.data_bridge.is_tushare_available(),
            },
            "llm": {
                "available": self.llm_analyzer.is_available(),
                "model": self.llm_analyzer.get_model_name(),
            },
            "running": self._running,
            "watch_list": self._watch_list,
            "account": self.trading_engine.account,
            "positions": self.trading_engine.get_positions(),
            "risk_status": self.risk_manager.get_risk_status(self.trading_engine.account, self.trading_engine.portfolio),
            "llm_stats": self.llm_analyzer.get_stats(),
            "recent_trades": self.trading_engine.get_trades(10),
        }

    def get_analysis_result(self, symbol: str) -> dict:
        return self._analysis_results.get(symbol, {})
    
    def switch_trading_mode(self, new_mode: str) -> dict:
        valid_modes = ["paper", "live"]
        if new_mode not in valid_modes:
            return {"status": "FAILED", "reason": f"无效的交易模式，必须是: {valid_modes}"}

        if new_mode == self.trading_engine.mode:
            return {"status": "SKIPPED", "reason": "当前已经是该模式"}

        old_mode = self.trading_engine.mode
        self.trading_engine.mode = new_mode

        if new_mode == "live":
            logger.warning("=" * 60)
            logger.warning("⚠️  ⚠️  ⚠️  已切换到实盘交易模式！")
            logger.warning("⚠️  请谨慎操作！")
            logger.warning("=" * 60)
        else:
            logger.info("已切换到模拟交易模式")

        return {"status": "SUCCESS", "old_mode": old_mode, "new_mode": new_mode}
