"""
数据质量保障模块
提供数据验证、异常检测、完整性检查等功能
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from loguru import logger


class DataQualityChecker:
    """数据质量检查器"""
    
    def __init__(self):
        self.quality_rules = {
            "missing_rate_threshold": 0.001,  # 缺失率阈值 0.1%
            "price_change_threshold": 0.20,     # 价格变化阈值 20%
            "volume_change_threshold": 10.0,   # 成交量变化阈值 10倍
            "outlier_std_threshold": 5.0,      # 异常值标准差倍数
            "duplicate_check": True,           # 重复检查
            "consistency_check": True,         # 一致性检查
        }
        self.quality_history = []
    
    def check_completeness(self, df: pd.DataFrame, required_columns: List[str]) -> Dict[str, Any]:
        """检查数据完整性"""
        result = {
            "passed": True,
            "missing_columns": [],
            "missing_rate": {},
            "total_rows": len(df),
            "issues": []
        }
        
        # 检查必需列
        for col in required_columns:
            if col not in df.columns:
                result["missing_columns"].append(col)
                result["issues"].append(f"Missing required column: {col}")
                result["passed"] = False
        
        # 检查缺失率
        for col in df.columns:
            missing_rate = df[col].isnull().sum() / len(df)
            result["missing_rate"][col] = missing_rate
            
            if missing_rate > self.quality_rules["missing_rate_threshold"]:
                result["issues"].append(
                    f"Column '{col}' missing rate {missing_rate:.2%} exceeds threshold "
                    f"{self.quality_rules['missing_rate_threshold']:.2%}"
                )
                result["passed"] = False
        
        return result
    
    def check_accuracy(self, df: pd.DataFrame, price_cols: List[str] = None) -> Dict[str, Any]:
        """检查数据准确性"""
        result = {
            "passed": True,
            "issues": [],
            "invalid_values": {},
            "negative_prices": [],
            "zero_prices": []
        }
        
        if price_cols is None:
            price_cols = ["close", "open", "high", "low"]
        
        for col in price_cols:
            if col not in df.columns:
                continue
            
            # 检查负数价格
            neg_mask = df[col] < 0
            if neg_mask.any():
                result["negative_prices"].append({
                    "column": col,
                    "count": neg_mask.sum(),
                    "indices": df[neg_mask].index.tolist()[:10]
                })
                result["issues"].append(f"Found {neg_mask.sum()} negative prices in {col}")
                result["passed"] = False
            
            # 检查零价格
            zero_mask = df[col] == 0
            if zero_mask.any():
                result["zero_prices"].append({
                    "column": col,
                    "count": zero_mask.sum(),
                    "indices": df[zero_mask].index.tolist()[:10]
                })
                result["issues"].append(f"Found {zero_mask.sum()} zero prices in {col}")
            
            # 检查极端值
            mean_val = df[col].mean()
            std_val = df[col].std()
            threshold = self.quality_rules["outlier_std_threshold"] * std_val
            
            outliers = df[(df[col] - mean_val).abs() > threshold]
            if len(outliers) > 0:
                result["invalid_values"][col] = {
                    "count": len(outliers),
                    "mean": mean_val,
                    "std": std_val,
                    "threshold": threshold,
                    "sample_indices": outliers.index.tolist()[:5]
                }
                result["issues"].append(
                    f"Found {len(outliers)} outliers in {col} "
                    f"(mean={mean_val:.2f}, std={std_val:.2f})"
                )
        
        return result
    
    def check_consistency(self, df: pd.DataFrame) -> Dict[str, Any]:
        """检查数据一致性"""
        result = {
            "passed": True,
            "issues": [],
            "high_low_inverted": [],
            "price_range_anomalies": []
        }
        
        # 检查最高价 >= 最低价
        if "high" in df.columns and "low" in df.columns:
            inverted = df[df["high"] < df["low"]]
            if len(inverted) > 0:
                result["high_low_inverted"].extend(inverted.index.tolist()[:10])
                result["issues"].append(f"Found {len(inverted)} records where high < low")
                result["passed"] = False
        
        # 检查开盘价和收盘价是否在最高价和最低价范围内
        if all(col in df.columns for col in ["open", "close", "high", "low"]):
            out_of_range = df[
                (df["open"] > df["high"]) | (df["open"] < df["low"]) |
                (df["close"] > df["high"]) | (df["close"] < df["low"])
            ]
            if len(out_of_range) > 0:
                result["price_range_anomalies"].extend(out_of_range.index.tolist()[:10])
                result["issues"].append(f"Found {len(out_of_range)} records with price outside high-low range")
                result["passed"] = False
        
        return result
    
    def check_timeliness(self, df: pd.DataFrame, 
                        max_gap_days: int = 5,
                        expected_business_days: int = 252) -> Dict[str, Any]:
        """检查数据时效性"""
        result = {
            "passed": True,
            "issues": [],
            "date_gaps": [],
            "stale_data_days": 0
        }
        
        if "date" not in df.columns:
            result["issues"].append("No date column found for timeliness check")
            return result
        
        df = df.sort_values("date")
        
        # 检查日期连续性
        df["date"] = pd.to_datetime(df["date"])
        date_diff = df["date"].diff().dt.days
        
        # 找出超过最大间隔的日期
        gap_mask = date_diff > max_gap_days
        if gap_mask.any():
            gap_indices = df[gap_mask].index.tolist()
            for i, idx in enumerate(gap_indices):
                if i < len(gap_indices) - 1:
                    gap_days = date_diff.loc[idx]
                    result["date_gaps"].append({
                        "after_date": str(df.loc[idx, "date"].date()),
                        "gap_days": int(gap_days)
                    })
            result["issues"].append(f"Found {len(gap_indices)} date gaps > {max_gap_days} days")
            result["passed"] = False
        
        # 检查数据是否过期
        latest_date = df["date"].max()
        stale_days = (datetime.now() - latest_date).days
        result["stale_data_days"] = stale_days
        
        if stale_days > max_gap_days:
            result["issues"].append(f"Data is {stale_days} days stale (max {max_gap_days})")
            result["passed"] = False
        
        return result
    
    def check_duplicates(self, df: pd.DataFrame, key_columns: List[str]) -> Dict[str, Any]:
        """检查重复数据"""
        result = {
            "passed": True,
            "duplicate_count": 0,
            "duplicate_indices": [],
            "issues": []
        }
        
        duplicates = df[df.duplicated(subset=key_columns, keep=False)]
        result["duplicate_count"] = len(duplicates)
        
        if len(duplicates) > 0:
            result["duplicate_indices"] = duplicates.index.tolist()[:20]
            result["issues"].append(f"Found {len(duplicates)} duplicate records based on {key_columns}")
            result["passed"] = False
        
        return result
    
    def check_volatility_anomaly(self, df: pd.DataFrame, 
                                 price_col: str = "close",
                                 volatility_threshold: float = 0.5) -> Dict[str, Any]:
        """检查波动率异常"""
        result = {
            "passed": True,
            "anomalous_dates": [],
            "issues": []
        }
        
        if price_col not in df.columns:
            return result
        
        # 计算日收益率
        returns = df[price_col].pct_change()
        
        # 计算滚动波动率
        rolling_std = returns.rolling(window=20).std()
        
        # 检查异常高的波动率
        mean_volatility = rolling_std.mean()
        anomalous = rolling_std > mean_volatility * (1 + volatility_threshold)
        
        if anomalous.any():
            anomalous_dates = df[anomalous]["date"].tolist() if "date" in df.columns else anomalous.index.tolist()
            result["anomalous_dates"] = anomalous_dates[:10]
            result["issues"].append(
                f"Found {anomalous.sum()} days with volatility > {volatility_threshold*100}% above mean"
            )
            result["passed"] = False
        
        return result
    
    def run_full_check(self, df: pd.DataFrame, 
                      symbol: str,
                      required_columns: List[str] = None) -> Dict[str, Any]:
        """运行完整的数据质量检查"""
        if required_columns is None:
            required_columns = ["date", "open", "high", "low", "close", "volume"]
        
        result = {
            "symbol": symbol,
            "timestamp": datetime.now().isoformat(),
            "total_rows": len(df),
            "checks": {},
            "overall_passed": True,
            "quality_score": 100.0,
            "issues_summary": []
        }
        
        # 执行各项检查
        checks = [
            ("completeness", self.check_completeness(df, required_columns)),
            ("accuracy", self.check_accuracy(df)),
            ("consistency", self.check_consistency(df)),
            ("timeliness", self.check_timeliness(df)),
            ("duplicates", self.check_duplicates(df, ["date"])),
            ("volatility", self.check_volatility_anomaly(df))
        ]
        
        for check_name, check_result in checks:
            result["checks"][check_name] = check_result
            if not check_result["passed"]:
                result["overall_passed"] = False
                result["issues_summary"].extend(check_result["issues"])
                result["quality_score"] -= 15.0  # 每项检查失败扣15分
        
        result["quality_score"] = max(0.0, result["quality_score"])
        
        # 记录历史
        self.quality_history.append({
            "symbol": symbol,
            "timestamp": result["timestamp"],
            "quality_score": result["quality_score"],
            "passed": result["overall_passed"]
        })
        
        return result


class DataValidator:
    """数据验证器 - 用于实时数据验证"""
    
    @staticmethod
    def validate_price(price: float) -> Tuple[bool, Optional[str]]:
        """验证价格是否合理"""
        if price is None or pd.isna(price):
            return False, "Price is None or NaN"
        if price <= 0:
            return False, f"Price must be positive, got {price}"
        if price > 100000:  # A股单股最高价格通常不超过10万
            return False, f"Price {price} exceeds maximum reasonable value"
        return True, None
    
    @staticmethod
    def validate_volume(volume: int) -> Tuple[bool, Optional[str]]:
        """验证成交量是否合理"""
        if volume is None or pd.isna(volume):
            return False, "Volume is None or NaN"
        if volume < 0:
            return False, "Volume cannot be negative"
        if volume > 1000000000:  # 单日成交量通常不超过10亿股
            return False, f"Volume {volume} is unusually large"
        return True, None
    
    @staticmethod
    def validate_orderbook(orderbook: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """验证订单簿数据"""
        errors = []
        
        required_fields = ["symbol", "bids", "asks"]
        for field in required_fields:
            if field not in orderbook:
                errors.append(f"Missing required field: {field}")
        
        if errors:
            return False, errors
        
        # 验证买卖盘价格
        bids = orderbook.get("bids", [])
        asks = orderbook.get("asks", [])
        
        if bids and asks:
            if bids[0]["price"] > asks[0]["price"]:
                errors.append(f"Best bid ({bids[0]['price']}) > best ask ({asks[0]['price']})")
        
        return len(errors) == 0, errors


class DataImputer:
    """数据填补器 - 处理缺失数据"""
    
    @staticmethod
    def forward_fill(df: pd.DataFrame, columns: List[str]) -> pd.DataFrame:
        """前向填充"""
        df_copy = df.copy()
        for col in columns:
            if col in df_copy.columns:
                df_copy[col] = df_copy[col].fillna(method="ffill")
        return df_copy
    
    @staticmethod
    def backward_fill(df: pd.DataFrame, columns: List[str]) -> pd.DataFrame:
        """后向填充"""
        df_copy = df.copy()
        for col in columns:
            if col in df_copy.columns:
                df_copy[col] = df_copy[col].fillna(method="bfill")
        return df_copy
    
    @staticmethod
    def interpolate(df: pd.DataFrame, columns: List[str], method: str = "linear") -> pd.DataFrame:
        """插值填充"""
        df_copy = df.copy()
        for col in columns:
            if col in df_copy.columns:
                df_copy[col] = df_copy[col].interpolate(method=method)
        return df_copy
    
    @staticmethod
    def fill_with_ma(df: pd.DataFrame, columns: List[str], window: int = 5) -> pd.DataFrame:
        """使用移动平均填充"""
        df_copy = df.copy()
        for col in columns:
            if col in df_copy.columns:
                ma = df_copy[col].rolling(window=window, min_periods=1).mean()
                df_copy[col] = df_copy[col].fillna(ma)
        return df_copy
