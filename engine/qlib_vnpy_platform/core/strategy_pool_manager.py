import json
import os
from datetime import datetime
from typing import Dict, List, Optional, Any
from loguru import logger
from pathlib import Path
from qlib_vnpy_platform.core.strategies import BaseStrategy, get_strategy, list_strategies, STRATEGY_REGISTRY
from qlib_vnpy_platform.core.backtest import BacktestEngine
from qlib_vnpy_platform.config import get_config


STRATEGY_POOL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "strategy_pool")
os.makedirs(STRATEGY_POOL_DIR, exist_ok=True)


class StrategyPoolManager:
    """策略池管理器：管理策略池、策略分组、参数优化结果"""
    
    def __init__(self):
        self.config = get_config()
        self.strategies: Dict[str, Dict] = {}  # {strategy_key: {meta_data}}
        self.groups: Dict[str, List[str]] = {
            "all": [],
            "technical": [],
            "trend": [],
            "mean_reversion": [],
            "professional": []
        }
        self.optimization_results: Dict[str, Dict] = {}
        self.backtest_results: Dict[str, Dict] = {}
        
        self._load_from_disk()
        logger.info("StrategyPoolManager initialized")
    
    def _get_pool_file_path(self) -> str:
        return os.path.join(STRATEGY_POOL_DIR, "strategy_pool.json")
    
    def _get_optimization_file_path(self) -> str:
        return os.path.join(STRATEGY_POOL_DIR, "optimization_results.json")
    
    def _get_backtest_file_path(self) -> str:
        return os.path.join(STRATEGY_POOL_DIR, "backtest_results.json")
    
    def _save_to_disk(self):
        """保存到磁盘"""
        pool_data = {
            "strategies": self.strategies,
            "groups": self.groups,
            "last_updated": datetime.now().isoformat()
        }
        with open(self._get_pool_file_path(), "w", encoding="utf-8") as f:
            json.dump(pool_data, f, ensure_ascii=False, indent=2)
        
        if self.optimization_results:
            with open(self._get_optimization_file_path(), "w", encoding="utf-8") as f:
                json.dump(self.optimization_results, f, ensure_ascii=False, indent=2)
        
        if self.backtest_results:
            with open(self._get_backtest_file_path(), "w", encoding="utf-8") as f:
                json.dump(self.backtest_results, f, ensure_ascii=False, indent=2)
    
    def _load_from_disk(self):
        """从磁盘加载"""
        # 初始化基础策略库
        self._initialize_base_pool()
        
        # 加载已有数据
        if os.path.exists(self._get_pool_file_path()):
            try:
                with open(self._get_pool_file_path(), "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.strategies = data.get("strategies", {})
                    self.groups = data.get("groups", self.groups)
            except Exception as e:
                logger.warning(f"Failed to load strategy pool: {e}")
        
        if os.path.exists(self._get_optimization_file_path()):
            try:
                with open(self._get_optimization_file_path(), "r", encoding="utf-8") as f:
                    self.optimization_results = json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load optimization results: {e}")
        
        if os.path.exists(self._get_backtest_file_path()):
            try:
                with open(self._get_backtest_file_path(), "r", encoding="utf-8") as f:
                    self.backtest_results = json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load backtest results: {e}")
    
    def _initialize_base_pool(self):
        """初始化基础策略库"""
        strategy_list = list_strategies()
        
        for strategy_info in strategy_list:
            strategy_key = strategy_info.get("key")
            if not strategy_key:
                continue
                
            if strategy_key not in self.strategies:
                try:
                    strategy = get_strategy(strategy_key)
                    self.strategies[strategy_key] = {
                        "key": strategy_key,
                        "name": strategy.name if hasattr(strategy, "name") else strategy_info.get("name", strategy_key),
                        "description": strategy.__doc__ or strategy_info.get("description", ""),
                        "category": self._auto_categorize(strategy_key),
                        "enabled": True,
                        "priority": 50,
                        "created_at": datetime.now().isoformat(),
                        "last_used": None,
                        "params": strategy.params if hasattr(strategy, "params") else strategy_info.get("params", {}),
                        "performance": {
                            "total_trades": 0,
                            "win_rate": 0.0,
                            "profit_factor": 0.0,
                            "sharpe_ratio": 0.0,
                            "max_drawdown": 0.0,
                            "annual_return": 0.0
                        }
                    }
                    self.groups["all"].append(strategy_key)
                    
                    # 自动分组
                    cat = self.strategies[strategy_key]["category"]
                    if cat in self.groups:
                        if strategy_key not in self.groups[cat]:
                            self.groups[cat].append(strategy_key)
                
                except Exception as e:
                    logger.warning(f"Failed to initialize strategy {strategy_key}: {e}")
        
        self._save_to_disk()
    
    def _auto_categorize(self, strategy_key: str) -> str:
        """自动分类策略"""
        key = strategy_key.lower()
        
        professional_keywords = ["sentiment", "sector", "prosperity", "band", "value", "dragon", "head"]
        trend_keywords = ["momentum", "turtle", "trend", "breakout", "channel"]
        mean_reversion_keywords = ["bollinger", "rsi", "mean", "reversion", "oscillator"]
        
        for kw in professional_keywords:
            if kw in key:
                return "professional"
        
        for kw in trend_keywords:
            if kw in key:
                return "trend"
        
        for kw in mean_reversion_keywords:
            if kw in key:
                return "mean_reversion"
        
        return "technical"
    
    def get_strategy_info(self, strategy_key: str) -> Optional[Dict]:
        """获取策略信息"""
        return self.strategies.get(strategy_key)
    
    def get_all_strategies(self) -> List[Dict]:
        """获取所有策略信息"""
        return list(self.strategies.values())
    
    def get_strategies_by_group(self, group_name: str) -> List[Dict]:
        """根据分组获取策略"""
        if group_name not in self.groups:
            return []
        
        return [self.strategies[key] for key in self.groups[group_name] if key in self.strategies]
    
    def update_strategy_priority(self, strategy_key: str, priority: int):
        """更新策略优先级"""
        if strategy_key in self.strategies:
            self.strategies[strategy_key]["priority"] = priority
            self._save_to_disk()
            logger.info(f"Updated {strategy_key} priority to {priority}")
    
    def toggle_strategy_enabled(self, strategy_key: str, enabled: Optional[bool] = None):
        """启用/禁用策略"""
        if strategy_key in self.strategies:
            if enabled is None:
                enabled = not self.strategies[strategy_key]["enabled"]
            self.strategies[strategy_key]["enabled"] = enabled
            self._save_to_disk()
            logger.info(f"Strategy {strategy_key} {'enabled' if enabled else 'disabled'}")
    
    def create_custom_group(self, group_name: str, strategy_keys: List[str]):
        """创建自定义策略分组"""
        self.groups[group_name] = [k for k in strategy_keys if k in self.strategies]
        self._save_to_disk()
        logger.info(f"Created group {group_name} with {len(self.groups[group_name])} strategies")
    
    def add_strategy_to_group(self, strategy_key: str, group_name: str):
        """添加策略到分组"""
        if strategy_key in self.strategies and group_name in self.groups:
            if strategy_key not in self.groups[group_name]:
                self.groups[group_name].append(strategy_key)
                self._save_to_disk()
    
    def remove_strategy_from_group(self, strategy_key: str, group_name: str):
        """从分组移除策略"""
        if group_name in self.groups and strategy_key in self.groups[group_name]:
            self.groups[group_name].remove(strategy_key)
            self._save_to_disk()
    
    def save_backtest_result(self, strategy_key: str, symbol: str, result: Dict):
        """保存回测结果"""
        key = f"{strategy_key}_{symbol}"
        self.backtest_results[key] = {
            "strategy_key": strategy_key,
            "symbol": symbol,
            "result": result,
            "backtested_at": datetime.now().isoformat()
        }
        
        if strategy_key in self.strategies:
            perf = self.strategies[strategy_key].get("performance", {})
            if "sharpe_ratio" in result:
                perf["sharpe_ratio"] = result.get("sharpe_ratio", 0)
            if "max_drawdown" in result:
                perf["max_drawdown"] = result.get("max_drawdown", 0)
            if "annual_return" in result:
                perf["annual_return"] = result.get("annual_return", 0)
            self.strategies[strategy_key]["performance"] = perf
        
        self._save_to_disk()
    
    def get_backtest_result(self, strategy_key: str, symbol: str) -> Optional[Dict]:
        """获取回测结果"""
        key = f"{strategy_key}_{symbol}"
        return self.backtest_results.get(key)
    
    def save_optimization_result(self, strategy_key: str, symbol: str, 
                                 optimized_params: Dict, performance: Dict):
        """保存参数优化结果"""
        key = f"{strategy_key}_{symbol}"
        self.optimization_results[key] = {
            "strategy_key": strategy_key,
            "symbol": symbol,
            "optimized_params": optimized_params,
            "performance": performance,
            "optimized_at": datetime.now().isoformat()
        }
        self._save_to_disk()
    
    def get_optimization_result(self, strategy_key: str, symbol: str) -> Optional[Dict]:
        """获取参数优化结果"""
        key = f"{strategy_key}_{symbol}"
        return self.optimization_results.get(key)
    
    def get_best_strategies(self, group_name: str = "all", 
                           metric: str = "sharpe_ratio", 
                           top_n: int = 5) -> List[Dict]:
        """获取最优策略"""
        strategies = self.get_strategies_by_group(group_name)
        enabled_strategies = [s for s in strategies if s.get("enabled", True)]
        
        def get_metric(s):
            perf = s.get("performance", {})
            return perf.get(metric, -999)
        
        sorted_strategies = sorted(
            enabled_strategies,
            key=get_metric,
            reverse=True
        )
        
        return sorted_strategies[:top_n]
    
    def get_status(self) -> Dict:
        """获取策略池状态"""
        return {
            "total_strategies": len(self.strategies),
            "enabled_strategies": len([s for s in self.strategies.values() if s.get("enabled", True)]),
            "groups": {k: len(v) for k, v in self.groups.items()},
            "backtest_results_count": len(self.backtest_results),
            "optimization_results_count": len(self.optimization_results),
            "last_updated": datetime.now().isoformat()
        }
