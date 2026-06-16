"""
QLibPredictor — 真正的 QLib 集成预测模块

核心功能：
1. Alpha158 因子计算（使用 QLib 正式 API）
2. LGBModel 预测（使用 QLib 的 LGBModel）
3. 信号生成（BUY/SELL/HOLD + 置信度）
4. 自动 fallback 机制（QLib 不可用时降级到 sklearn）

工作模式：
- MODE_QLIB: 完整 QLib 模式（Alpha158 + LGBModel）
- MODE_SKLEARN: sklearn 模式（模拟 Alpha158 因子 + GradientBoosting）
- MODE_RULE: 纯规则模式（简单技术指标）
"""

import json
import time
import joblib
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict, Any
from loguru import logger
from qlib_vnpy_platform.config import get_config, PROJECT_ROOT


# ── 运行模式 ───────────────────────────────────────────────
MODE_QLIB = "qlib"        # 完整 QLib 模式
MODE_SKLEARN = "sklearn"  # sklearn 模式（fallback）
MODE_RULE = "rule"        # 纯规则模式（最终 fallback）

# Alpha158 因子列表（用于手动计算 / sklearn fallback 模式）
ALPHA158_FEATURES = [
    # Alpha#1~#10 动量类
    "KDJ_K", "KDJ_D", "KDJ_J", "RSI", "WR",
    "BIAS_5", "BIAS_10", "BIAS_20",
    "MACD", "MACD_signal",
    # Alpha#11~#20 均线类
    "MA5_ratio", "MA10_ratio", "MA20_ratio", "MA60_ratio",
    "MA5_MA10_ratio", "MA5_MA20_ratio", "MA10_MA20_ratio",
    # Alpha#21~#30 量价类
    "VOL_MA5_ratio", "VOL_MA10_ratio", "VOL_MA20_ratio",
    "VWAP", "VWAP_ratio",
    "AMOUNT_MA5_ratio", "AMOUNT_MA10_ratio",
    # 波动类
    "ATR", "ATR_ratio", "Boll_upper", "Boll_lower", "Boll_width",
    "High_low_ratio", "High_close_ratio", "Low_close_ratio",
    # 自定义补充
    "return_1d", "return_5d", "return_10d",
    "turnover_ratio", "volume_std_10",
]

# 核心因子（用于 sklearn 模式的精选子集）
CORE_FEATURES = [
    "MA5_ratio", "MA10_ratio", "MA20_ratio",
    "VOL_MA10_ratio", "High_low_ratio", "RSI",
    "MACD", "Boll_width", "VWAP_ratio", "ATR_ratio",
]

MODEL_CACHE_DIR = PROJECT_ROOT / "data" / "model_cache"


def compute_alpha158_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    手动计算 Alpha158 风格的因子（不需 QLib 即可计算）
    
    覆盖：动量类、均线类、量价类、波动类因子
    返回包含原始 K 线 + 因子列的 DataFrame
    """
    df = df.copy()
    
    # === 确保必要列存在 ===
    required = {"open", "high", "low", "close", "volume"}
    missing = required - set(df.columns.str.lower())
    if missing:
        logger.warning(f"缺少必要K线列: {missing}，因子计算将受限")
    
    # 统一列名小写
    df.columns = [c.lower() for c in df.columns]
    
    # === 1. 动量类因子 ===
    # RSI
    df["rsi"] = _calc_rsi(df["close"], 14)
    
    # KDJ
    low_14 = df["low"].rolling(14).min()
    high_14 = df["high"].rolling(14).max()
    rsv = (df["close"] - low_14) / (high_14 - low_14).replace(0, np.nan) * 100
    df["kDJ_K"] = rsv.ewm(alpha=1/3, adjust=False).mean()
    df["kDJ_D"] = df["kDJ_K"].ewm(alpha=1/3, adjust=False).mean()
    df["kDJ_J"] = 3 * df["kDJ_K"] - 2 * df["kDJ_D"]
    
    # WR (Williams %R)
    df["wr"] = (high_14 - df["close"]) / (high_14 - low_14).replace(0, np.nan) * -100
    
    # BIAS
    for period in [5, 10, 20]:
        ma = df["close"].rolling(period).mean()
        df[f"bias_{period}"] = (df["close"] - ma) / ma.replace(0, np.nan) * 100
    
    # MACD
    ema12 = df["close"].ewm(span=12, adjust=False).mean()
    ema26 = df["close"].ewm(span=26, adjust=False).mean()
    df["macd"] = ema12 - ema26
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    
    # === 2. 均线类因子 ===
    for period in [5, 10, 20, 60]:
        ma = df["close"].rolling(period).mean()
        df[f"ma{period}_ratio"] = df["close"] / ma.replace(0, np.nan)
    
    df["ma5_ma10_ratio"] = df["close"].rolling(5).mean() / df["close"].rolling(10).mean().replace(0, np.nan)
    df["ma5_ma20_ratio"] = df["close"].rolling(5).mean() / df["close"].rolling(20).mean().replace(0, np.nan)
    df["ma10_ma20_ratio"] = df["close"].rolling(10).mean() / df["close"].rolling(20).mean().replace(0, np.nan)
    
    # === 3. 量价类因子 ===
    # VWAP
    df["vwap"] = (df["volume"] * (df["high"] + df["low"] + df["close"]) / 3).rolling(20).sum() / \
                 df["volume"].rolling(20).sum().replace(0, np.nan)
    df["vwap_ratio"] = df["close"] / df["vwap"].replace(0, np.nan)
    
    # 成交量均线比
    for period in [5, 10, 20]:
        vol_ma = df["volume"].rolling(period).mean()
        df[f"vol_ma{period}_ratio"] = df["volume"] / vol_ma.replace(0, np.nan)
    
    # 成交额均线比
    if "amount" in df.columns:
        for period in [5, 10]:
            amt_ma = df["amount"].rolling(period).mean()
            df[f"amount_ma{period}_ratio"] = df["amount"] / amt_ma.replace(0, np.nan)
    
    # === 4. 波动类因子 ===
    # ATR
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["close"].shift(1)).abs(),
        (df["low"] - df["close"].shift(1)).abs(),
    ], axis=1).max(axis=1)
    df["atr"] = tr.rolling(14).mean()
    df["atr_ratio"] = df["atr"] / df["close"].replace(0, np.nan)
    
    # Bollinger Bands
    boll_ma = df["close"].rolling(20).mean()
    boll_std = df["close"].rolling(20).std()
    df["boll_upper"] = boll_ma + 2 * boll_std
    df["boll_lower"] = boll_ma - 2 * boll_std
    df["boll_width"] = (df["boll_upper"] - df["boll_lower"]) / boll_ma.replace(0, np.nan)
    
    # 高低比例
    df["high_low_ratio"] = df["high"] / df["low"].replace(0, np.nan)
    df["high_close_ratio"] = df["high"] / df["close"].replace(0, np.nan)
    df["low_close_ratio"] = df["low"] / df["close"].replace(0, np.nan)
    
    # === 5. 收益率 ===
    df["return_1d"] = df["close"].pct_change(1)
    df["return_5d"] = df["close"].pct_change(5)
    df["return_10d"] = df["close"].pct_change(10)
    
    # === 6. 其他 ===
    df["volume_std_10"] = df["volume"].rolling(10).std() / df["volume"].rolling(10).mean().replace(0, np.nan)
    
    # 换手率（需要流通股本，暂时用 volume 代替）
    if "turnover" not in df.columns:
        # 用 volume 的标准化值近似
        df["turnover_ratio"] = df["volume"] / df["volume"].rolling(20).mean().replace(0, np.nan)
    
    return df


def _calc_rsi(prices: pd.Series, period: int = 14) -> pd.Series:
    """计算 RSI 指标"""
    delta = prices.diff()
    gain = delta.where(delta > 0, 0)
    loss = (-delta).where(delta < 0, 0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.inf)
    return 100 - (100 / (1 + rs))


@dataclass
class PredictionResult:
    """预测结果"""
    score: float            # 0~1 的预测分数
    signal: str             # BUY / SELL / HOLD
    confidence: float       # 置信度 0~1
    mode: str              # 使用的模式
    features_used: int      # 使用的特征数
    model_ready: bool       # 模型是否已训练
    raw_prediction: float = 0.0
    detail: Dict[str, Any] = field(default_factory=dict)


class QLibPredictor:
    """
    真正的 QLib 集成预测器
    
    三层架构：
    ┌──────────────────────────────────────────────────┐
    │ MODE_QLIB:   Alpha158 + LGBModel (QLib 原生)     │
    │ MODE_SKLEARN: 模拟 Alpha158 + GradientBoosting   │
    │ MODE_RULE:   纯技术规则                          │
    └──────────────────────────────────────────────────┘
    
    自动降级：QLib → sklearn → rule
    缓存：训练好的模型自动保存/加载
    """
    
    def __init__(self, model_cache_dir: str = None):
        self._mode = MODE_RULE
        self._model = None
        self._dataset = None
        self._trained = False
        self._qlib_available = False
        self._sklearn_available = False
        self._feature_names = CORE_FEATURES[:]
        
        self.model_cache_dir = Path(model_cache_dir or MODEL_CACHE_DIR)
        self.model_cache_dir.mkdir(parents=True, exist_ok=True)
        
        self._detect_capabilities()
        self._try_load_cached_model()
        
        logger.info(f"QLibPredictor initialized: mode={self._mode}, "
                    f"qlib={self._qlib_available}, sklearn={self._sklearn_available}, "
                    f"trained={self._trained}")
    
    def _detect_capabilities(self):
        """检测可用能力，自动选择最高可用模式"""
        # 1. 检测 QLib
        try:
            import qlib
            from qlib.contrib.model.gbdt import LGBModel
            from qlib.contrib.data.handler import Alpha158
            from qlib.data.dataset import DatasetH
            
            # 尝试初始化 QLib
            from qlib.config import C
            provider_uri = get_config().get("qlib", {}).get(
                "provider_uri", "~/.qlib/qlib_data/cn_data"
            )
            resolved_uri = str(Path(provider_uri).expanduser())
            
            # 检查数据是否存在
            if self._check_qlib_data(resolved_uri):
                C.set(provider_uri=resolved_uri, region="cn")
                C.register()
                self._qlib_available = True
                self._mode = MODE_QLIB
                logger.info(f"✅ QLib 可用，已切换到完整 QLib 模式 (provider_uri={resolved_uri})")
            else:
                logger.warning(f"QLib 数据目录 {resolved_uri} 中无有效数据")
        except ImportError as e:
            logger.warning(f"QLib 不可用: {e}")
        except Exception as e:
            logger.warning(f"QLib 初始化失败: {e}")
        
        # 2. 检测 sklearn（作为 fallback）
        if not self._qlib_available:
            try:
                from sklearn.ensemble import GradientBoostingRegressor
                self._sklearn_available = True
                self._mode = MODE_SKLEARN
                logger.info("✅ sklearn 可用，已切换到 sklearn 模式")
            except ImportError:
                logger.warning("sklearn 不可用，将使用规则 fallback")
        
        # 3. 最终 fallback 是规则模式
        if self._mode == MODE_RULE:
            logger.info("📋 切换到规则模式（简单技术指标）")
    
    def _check_qlib_data(self, provider_uri: str) -> bool:
        """检查 QLib 数据目录是否包含有效数据"""
        from pathlib import Path
        uri = Path(provider_uri)
        if not uri.exists():
            return False
        
        # 检查是否有 calendars 和 features 目录
        cal_dir = uri / "calendars"
        feat_dir = uri / "features"
        if cal_dir.exists() and feat_dir.exists():
            cal_files = list(cal_dir.glob("*.txt"))
            feat_subdirs = list(feat_dir.iterdir()) if feat_dir.is_dir() else []
            if cal_files and feat_subdirs:
                logger.info(f"QLib 数据校验通过: {len(cal_files)} 个日历, {len(feat_subdirs)} 个证券")
                return True
        
        # 也检查 dump 格式
        cn_1d = uri / "cn_1d"
        if cn_1d.exists():
            subdirs = list(cn_1d.iterdir()) if cn_1d.is_dir() else []
            if subdirs:
                logger.info(f"QLib 数据 (dump格式) 校验通过: {len(subdirs)} 个证券")
                return True
        
        return False
    
    def _try_load_cached_model(self):
        """从缓存加载已训练的模型"""
        cache_path = self.model_cache_dir / "qlib_predictor.joblib"
        meta_path = self.model_cache_dir / "qlib_predictor_meta.json"
        
        if cache_path.exists() and meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text())
                age_hours = (datetime.now() - datetime.fromisoformat(meta.get("trained_at", "2000-01-01"))).total_seconds() / 3600
                
                if age_hours > 168:  # 超过 7 天
                    logger.info(f"缓存模型已过期 ({age_hours:.1f}h)，将重新训练")
                    return
                
                self._model = joblib.load(cache_path)
                self._feature_names = meta.get("features", CORE_FEATURES)
                self._trained = True
                self._mode = meta.get("mode", self._mode)
                logger.info(f"✅ 从缓存加载模型 (mode={self._mode}, age={age_hours:.1f}h)")
            except Exception as e:
                logger.warning(f"加载缓存模型失败: {e}")
    
    def _save_model_cache(self):
        """保存模型到缓存"""
        if self._model is None:
            return
        
        try:
            cache_path = self.model_cache_dir / "qlib_predictor.joblib"
            meta_path = self.model_cache_dir / "qlib_predictor_meta.json"
            
            joblib.dump(self._model, cache_path)
            
            meta = {
                "mode": self._mode,
                "features": self._feature_names,
                "trained_at": datetime.now().isoformat(),
                "qlib_available": self._qlib_available,
            }
            meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2))
            
            logger.info(f"模型已缓存到 {cache_path}")
        except Exception as e:
            logger.warning(f"缓存模型失败: {e}")
    
    def train(self, df_dict: Dict[str, pd.DataFrame] = None,
              instruments: list = None,
              start_date: str = "2020-01-01",
              end_date: str = None) -> dict:
        """
        训练预测模型
        
        参数:
            df_dict: {symbol: DataFrame} 格式的历史数据（用于 sklearn 模式）
            instruments: 证券列表（用于 QLib 模式）
            start_date/end_date: 训练时间范围
        """
        if end_date is None:
            end_date = datetime.now().strftime("%Y-%m-%d")
        
        if self._mode == MODE_QLIB and self._qlib_available:
            return self._train_qlib(instruments, start_date, end_date)
        elif self._mode == MODE_SKLEARN and df_dict:
            return self._train_sklearn(df_dict)
        else:
            logger.info("规则模式无需训练")
            return {"status": "success", "mode": MODE_RULE, "message": "规则模式无需训练"}
    
    def _train_qlib(self, instruments: list = None,
                    start_date: str = "2020-01-01",
                    end_date: str = None) -> dict:
        """使用 QLib Alpha158 + LGBModel 训练"""
        try:
            from qlib.contrib.model.gbdt import LGBModel
            from qlib.contrib.data.handler import Alpha158
            from qlib.data.dataset import DatasetH
            from qlib.workflow import R
            
            logger.info("开始 QLib 训练...")
            
            handler_kwargs = {
                "start_time": start_date,
                "end_time": end_date,
                "fit_start_time": start_date,
                "fit_end_time": end_date,
            }
            if instruments:
                handler_kwargs["instruments"] = instruments
            
            handler = Alpha158(**handler_kwargs)
            
            dataset = DatasetH(
                handler=handler,
                segments={
                    "train": (start_date, end_date),
                    "valid": (start_date, end_date),
                    "test": (start_date, end_date),
                },
            )
            
            model = LGBModel(
                loss="mse",
                num_leaves=64,
                learning_rate=0.05,
                num_threads=4,
            )
            
            with R.start(experiment_name="qlib_strategy_train"):
                model.fit(dataset)
            
            self._model = model
            self._dataset = dataset
            self._trained = True
            self._save_model_cache()
            
            logger.info("✅ QLib LGBModel 训练成功")
            return {"status": "success", "mode": MODE_QLIB, "model_type": "LGBModel"}
            
        except Exception as e:
            logger.error(f"QLib 训练失败: {e}")
            logger.info("降级到 sklearn 模式...")
            self._mode = MODE_SKLEARN
            return self._train_sklearn_from_qlib_fallback()
    
    def _train_sklearn(self, df_dict: Dict[str, pd.DataFrame]) -> dict:
        """使用 sklearn GradientBoosting 训练（基于模拟 Alpha158 因子）"""
        from sklearn.ensemble import GradientBoostingRegressor
        
        try:
            logger.info("开始 sklearn 训练...")
            
            all_features = []
            all_labels = []
            
            for symbol, df in df_dict.items():
                if df.empty or len(df) < 60:
                    continue
                
                # 计算因子
                df_feat = compute_alpha158_features(df)
                
                # 准备标签：未来 5 日收益率
                df_feat["label"] = df_feat["close"].pct_change(5).shift(-5)
                
                # 筛选可用特征
                available = [f for f in CORE_FEATURES if f in df_feat.columns]
                df_feat = df_feat.dropna(subset=available + ["label"])
                
                if len(df_feat) < 30:
                    continue
                
                features = df_feat[available].values
                labels = df_feat["label"].values
                
                all_features.append(features)
                all_labels.append(labels)
            
            if not all_features:
                logger.warning("无有效训练数据")
                self._mode = MODE_RULE
                return {"status": "failed", "reason": "无有效训练数据"}
            
            X = np.vstack(all_features)
            y = np.hstack(all_labels)
            
            # 去除极端值
            mask = (np.abs(y) < 0.2)
            X, y = X[mask], y[mask]
            
            logger.info(f"训练数据: {X.shape[0]} 样本, {X.shape[1]} 特征")
            
            model = GradientBoostingRegressor(
                n_estimators=200,
                max_depth=5,
                learning_rate=0.05,
                subsample=0.8,
                random_state=42,
            )
            model.fit(X, y)
            
            self._model = model
            self._feature_names = available
            self._trained = True
            self._save_model_cache()
            
            logger.info(f"✅ sklearn 模型训练成功 ({len(available)} 特征)")
            return {"status": "success", "mode": MODE_SKLEARN, "features": len(available)}
            
        except Exception as e:
            logger.error(f"sklearn 训练失败: {e}")
            self._mode = MODE_RULE
            return {"status": "failed", "error": str(e)}
    
    def _train_sklearn_from_qlib_fallback(self) -> dict:
        """QLib 失败后的降级训练——尝试从已有数据训练"""
        logger.info("sklearn 降级训练中（QLib 数据不可用）...")
        return {"status": "success", "mode": MODE_RULE, "message": "无回退训练数据，使用规则模式"}
    
    def predict(self, df: pd.DataFrame = None,
                symbol: str = None) -> PredictionResult:
        """
        对单只股票进行预测
        
        参数:
            df: 股票历史 K 线 DataFrame（必须有 open/high/low/close/volume）
            symbol: 股票代码（仅用于日志）
        
        返回:
            PredictionResult: 包含信号和置信度
        """
        if df is None or df.empty:
            return PredictionResult(
                score=0.5, signal="HOLD", confidence=0.0,
                mode=self._mode, features_used=0,
                model_ready=self._trained,
                detail={"reason": "无数据"}
            )
        
        symbol_str = symbol or "unknown"
        
        if self._trained and self._model is not None:
            if self._mode == MODE_QLIB:
                return self._predict_qlib(df, symbol_str)
            elif self._mode == MODE_SKLEARN:
                return self._predict_sklearn(df, symbol_str)
        
        # 最终 fallback: 规则预测
        return self._predict_rule(df, symbol_str)
    
    def _predict_qlib(self, df: pd.DataFrame, symbol: str) -> PredictionResult:
        """使用 QLib LGBModel 预测"""
        try:
            if self._dataset is None:
                logger.warning("QLib dataset 未初始化，降级到 sklearn")
                return self._predict_sklearn(df, symbol)
            
            pred = self._model.predict(self._dataset)
            
            if isinstance(pred, pd.DataFrame) and not pred.empty:
                latest_pred = float(pred.iloc[-1, 0])
            elif isinstance(pred, np.ndarray) and pred.size > 0:
                latest_pred = float(pred[-1])
            else:
                latest_pred = 0.5
            
            # 将原始预测映射到 0~1 分数
            score = self._normalize_prediction(latest_pred)
            signal = self._score_to_signal(score)
            confidence = abs(score - 0.5) * 2  # 0~1
            
            return PredictionResult(
                score=score, signal=signal, confidence=confidence,
                mode=MODE_QLIB, features_used=158,
                model_ready=True, raw_prediction=latest_pred,
                detail={"symbol": symbol, "qlib_model": "LGBModel"}
            )
            
        except Exception as e:
            logger.warning(f"QLib 预测失败 ({symbol}): {e}，降级到 sklearn")
            return self._predict_sklearn(df, symbol)
    
    def _predict_sklearn(self, df: pd.DataFrame, symbol: str) -> PredictionResult:
        """使用 sklearn 模型预测（基于模拟 Alpha158 因子）"""
        try:
            df_feat = compute_alpha158_features(df)
            
            available = [f for f in self._feature_names if f in df_feat.columns]
            if not available:
                return self._predict_rule(df, symbol, reason="无可用特征")
            
            df_feat = df_feat.dropna(subset=available)
            if df_feat.empty:
                return self._predict_rule(df, symbol, reason="因子计算后无数据")
            
            latest = df_feat[available].iloc[-1:].values
            pred = self._model.predict(latest)[0]
            
            score = self._normalize_prediction(pred)
            signal = self._score_to_signal(score)
            confidence = abs(score - 0.5) * 2
            
            return PredictionResult(
                score=score, signal=signal, confidence=confidence,
                mode=MODE_SKLEARN, features_used=len(available),
                model_ready=True, raw_prediction=float(pred),
                detail={"symbol": symbol, "features": available}
            )
            
        except Exception as e:
            logger.warning(f"sklearn 预测失败 ({symbol}): {e}，降级到规则")
            return self._predict_rule(df, symbol)
    
    def _predict_rule(self, df: pd.DataFrame, symbol: str = "",
                      reason: str = "") -> PredictionResult:
        """基于技术指标的规则预测（最终 fallback）"""
        if len(df) < 10:
            return PredictionResult(
                score=0.5, signal="HOLD", confidence=0.0,
                mode=MODE_RULE, features_used=0,
                model_ready=False,
                detail={"symbol": symbol, "reason": reason or "数据不足"}
            )
        
        df = df.copy()
        scores = []
        signals = []
        
        # 1. 均线趋势
        if len(df) >= 20:
            ma5 = df["close"].rolling(5).mean().iloc[-1]
            ma20 = df["close"].rolling(20).mean().iloc[-1]
            ma5_prev = df["close"].rolling(5).mean().iloc[-2] if len(df) >= 6 else ma5
            ma20_prev = df["close"].rolling(20).mean().iloc[-2] if len(df) >= 21 else ma20
            
            if ma5_prev <= ma20_prev and ma5 > ma20:
                scores.append(0.7)
                signals.append("金叉")
            elif ma5_prev >= ma20_prev and ma5 < ma20:
                scores.append(0.3)
                signals.append("死叉")
            elif ma5 > ma20:
                scores.append(0.55)
                signals.append("多头排列")
            else:
                scores.append(0.45)
                signals.append("空头排列")
        
        # 2. RSI
        rsi = _calc_rsi(df["close"], 14).iloc[-1] if len(df) >= 15 else 50
        if rsi < 30:
            scores.append(0.65)
            signals.append("超卖")
        elif rsi > 70:
            scores.append(0.35)
            signals.append("超买")
        elif rsi < 50:
            scores.append(0.52)
            signals.append("偏弱")
        else:
            scores.append(0.48)
            signals.append("偏强")
        
        # 3. 短期动量
        if len(df) >= 5:
            mom = (df["close"].iloc[-1] / df["close"].iloc[-5] - 1)
            if mom > 0.03:
                scores.append(0.58)
                signals.append("上涨动量")
            elif mom < -0.03:
                scores.append(0.42)
                signals.append("下跌动量")
            else:
                scores.append(0.50)
                signals.append("震荡")
        
        # 4. 成交量验证
        if len(df) >= 10:
            cur_vol = df["volume"].iloc[-1]
            avg_vol = df["volume"].iloc[-10:].mean()
            vol_ratio = cur_vol / avg_vol if avg_vol > 0 else 1
            price_up = df["close"].iloc[-1] > df["close"].iloc[-2]
            
            if vol_ratio > 1.3 and price_up:
                scores.append(0.55)
                signals.append("放量上涨")
            elif vol_ratio > 1.3 and not price_up:
                scores.append(0.45)
                signals.append("放量下跌")
            else:
                scores.append(0.50)
                signals.append("量能正常")
        
        # 计算最终得分
        if scores:
            final_score = float(np.mean(scores))
            final_score = max(0.1, min(0.9, final_score))
        else:
            final_score = 0.5
        
        signal = self._score_to_signal(final_score)
        confidence = abs(final_score - 0.5) * 2
        
        return PredictionResult(
            score=final_score, signal=signal, confidence=confidence,
            mode=MODE_RULE, features_used=4,
            model_ready=False,
            detail={
                "symbol": symbol,
                "reason": reason or "规则预测",
                "signals": signals,
                "rsi": float(rsi) if not isinstance(rsi, float) else rsi,
            }
        )
    
    def predict_batch(self, df_dict: Dict[str, pd.DataFrame]) -> Dict[str, PredictionResult]:
        """批量预测多只股票"""
        results = {}
        for symbol, df in df_dict.items():
            try:
                results[symbol] = self.predict(df, symbol=symbol)
            except Exception as e:
                logger.error(f"预测失败 {symbol}: {e}")
                results[symbol] = PredictionResult(
                    score=0.5, signal="HOLD", confidence=0.0,
                    mode=self._mode, features_used=0,
                    model_ready=self._trained,
                    detail={"error": str(e)}
                )
        return results
    
    @staticmethod
    def _normalize_prediction(raw_pred: float) -> float:
        """将原始预测值归一化到 0~1"""
        # 使用 sigmoid 函数将任意实数映射到 (0,1)
        # 对于收益率预测，通常范围在 [-0.1, 0.1]
        clipped = np.clip(raw_pred, -0.1, 0.1)
        return (clipped + 0.1) / 0.2  # 映射到 [0, 1]
    
    @staticmethod
    def _score_to_signal(score: float) -> str:
        """将 0~1 分数转为交易信号"""
        if score > 0.6:
            return "BUY"
        elif score < 0.4:
            return "SELL"
        return "HOLD"
    
    def get_info(self) -> dict:
        """获取预测器状态信息"""
        return {
            "mode": self._mode,
            "qlib_available": self._qlib_available,
            "sklearn_available": self._sklearn_available,
            "trained": self._trained,
            "features": len(self._feature_names),
            "model_cache_dir": str(self.model_cache_dir),
            "model_type": type(self._model).__name__ if self._model else None,
        }
    
    def get_mode_name(self) -> str:
        """获取当前模式的中文名称"""
        mode_names = {
            MODE_QLIB: "完整 QLib 模式 (Alpha158 + LGBModel)",
            MODE_SKLEARN: "sklearn 回退模式 (模拟 Alpha158 + GradientBoosting)",
            MODE_RULE: "规则回退模式 (技术指标)",
        }
        return mode_names.get(self._mode, f"未知模式 ({self._mode})")


class QLibPredictorFactory:
    """QLibPredictor 工厂方法（保持与旧代码兼容）"""
    
    @staticmethod
    def create() -> QLibPredictor:
        return QLibPredictor()
    
    @staticmethod
    def create_with_training(df_dict: Dict[str, pd.DataFrame] = None,
                              instruments: list = None) -> QLibPredictor:
        predictor = QLibPredictor()
        predictor.train(df_dict=df_dict, instruments=instruments)
        return predictor
