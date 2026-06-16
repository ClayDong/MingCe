import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta


def _make_test_df(days=200, start_price=10.0, trend=0.001, volatility=0.02):
    dates = [datetime(2024, 1, 1) + timedelta(days=i) for i in range(days)]
    np.random.seed(42)
    returns = np.random.normal(trend, volatility, days)
    close = start_price * np.cumprod(1 + returns)
    high = close * (1 + np.abs(np.random.normal(0, 0.01, days)))
    low = close * (1 - np.abs(np.random.normal(0, 0.01, days)))
    open_ = close * (1 + np.random.normal(0, 0.005, days))
    volume = np.random.randint(100000, 1000000, days)

    return pd.DataFrame({
        "date": dates,
        "open": open_,
        "close": close,
        "high": high,
        "low": low,
        "volume": volume,
    })


class TestStrategies:
    def test_ma_cross_generates_signals(self):
        from qlib_vnpy_platform.core.strategies import MACrossStrategy
        df = _make_test_df(100)
        s = MACrossStrategy(short_window=5, long_window=20)
        result = s.generate_signals(df)
        assert "signal" in result.columns
        assert "signal_strength" in result.columns
        signals = result["signal"].values
        assert set(signals).issubset({-1, 0, 1})

    def test_rsi_strategy(self):
        from qlib_vnpy_platform.core.strategies import RSIStrategy
        df = _make_test_df(100)
        s = RSIStrategy(period=14, oversold=30, overbought=70)
        result = s.generate_signals(df)
        assert "signal" in result.columns
        assert "rsi" in result.columns

    def test_macd_strategy(self):
        from qlib_vnpy_platform.core.strategies import MACDStrategy
        df = _make_test_df(100)
        s = MACDStrategy()
        result = s.generate_signals(df)
        assert "signal" in result.columns
        assert "macd" in result.columns

    def test_bollinger_strategy(self):
        from qlib_vnpy_platform.core.strategies import BollingerStrategy
        df = _make_test_df(100)
        s = BollingerStrategy()
        result = s.generate_signals(df)
        assert "signal" in result.columns
        assert "boll_upper" in result.columns

    def test_momentum_strategy(self):
        from qlib_vnpy_platform.core.strategies import MomentumStrategy
        df = _make_test_df(100)
        s = MomentumStrategy()
        result = s.generate_signals(df)
        assert "signal" in result.columns
        assert "momentum" in result.columns

    def test_kdj_strategy(self):
        from qlib_vnpy_platform.core.strategies import KDJStrategy
        df = _make_test_df(100)
        s = KDJStrategy()
        result = s.generate_signals(df)
        assert "signal" in result.columns
        assert "K" in result.columns

    def test_dual_thrust_strategy(self):
        from qlib_vnpy_platform.core.strategies import DualThrustStrategy
        df = _make_test_df(100)
        s = DualThrustStrategy()
        result = s.generate_signals(df)
        assert "signal" in result.columns

    def test_turtle_strategy(self):
        from qlib_vnpy_platform.core.strategies import TurtleStrategy
        df = _make_test_df(100)
        s = TurtleStrategy()
        result = s.generate_signals(df)
        assert "signal" in result.columns

    def test_mean_reversion_strategy(self):
        from qlib_vnpy_platform.core.strategies import MeanReversionStrategy
        df = _make_test_df(100)
        s = MeanReversionStrategy()
        result = s.generate_signals(df)
        assert "signal" in result.columns
        assert "zscore" in result.columns

    def test_strategy_registry(self):
        from qlib_vnpy_platform.core.strategies import STRATEGY_REGISTRY, get_strategy, list_strategies
        assert len(STRATEGY_REGISTRY) == 29
        s = get_strategy("ma_cross")
        assert s.name == "MA交叉"
        strategies = list_strategies()
        assert len(strategies) == 29
        assert "key" in strategies[0]

    def test_get_strategy_invalid(self):
        from qlib_vnpy_platform.core.strategies import get_strategy
        with pytest.raises(ValueError):
            get_strategy("nonexistent")

    def test_strategy_info(self):
        from qlib_vnpy_platform.core.strategies import MACrossStrategy
        s = MACrossStrategy(short_window=10, long_window=30)
        info = s.get_info()
        assert info["name"] == "MA交叉"
        assert info["params"]["short_window"] == 10
        assert info["params"]["long_window"] == 30

    def test_short_data_returns_no_signals(self):
        from qlib_vnpy_platform.core.strategies import MACrossStrategy
        df = _make_test_df(10)
        s = MACrossStrategy(short_window=5, long_window=20)
        result = s.generate_signals(df)
        assert result["signal"].sum() == 0


class TestBacktestEngine:
    def test_basic_backtest(self):
        from qlib_vnpy_platform.core.backtest import BacktestEngine
        from qlib_vnpy_platform.core.strategies import MACrossStrategy
        df = _make_test_df(200)
        engine = BacktestEngine(initial_capital=1000000)
        result = engine.run(df, MACrossStrategy(), "TEST")
        assert "metrics" in result
        assert "trades" in result
        assert "equity_curve" in result
        assert result["symbol"] == "TEST"

    def test_metrics_completeness(self):
        from qlib_vnpy_platform.core.backtest import BacktestEngine
        from qlib_vnpy_platform.core.strategies import MACrossStrategy
        df = _make_test_df(200)
        engine = BacktestEngine()
        result = engine.run(df, MACrossStrategy(), "TEST")
        m = result["metrics"]
        expected_keys = [
            "total_return", "annual_return", "max_drawdown", "sharpe_ratio",
            "calmar_ratio", "win_rate", "profit_factor", "total_trades",
            "buy_count", "sell_count", "winning_trades", "losing_trades",
            "avg_profit", "avg_loss", "final_equity", "total_pnl",
        ]
        for key in expected_keys:
            assert key in m, f"Missing metric: {key}"

    def test_equity_curve_length(self):
        from qlib_vnpy_platform.core.backtest import BacktestEngine
        from qlib_vnpy_platform.core.strategies import MACrossStrategy
        df = _make_test_df(200)
        engine = BacktestEngine()
        result = engine.run(df, MACrossStrategy(), "TEST")
        assert len(result["equity_curve"]) == 200

    def test_insufficient_data(self):
        from qlib_vnpy_platform.core.backtest import BacktestEngine
        from qlib_vnpy_platform.core.strategies import MACrossStrategy
        df = _make_test_df(5)
        engine = BacktestEngine()
        result = engine.run(df, MACrossStrategy(), "TEST")
        assert "error" in result

    def test_run_multiple(self):
        from qlib_vnpy_platform.core.backtest import BacktestEngine
        from qlib_vnpy_platform.core.strategies import MACrossStrategy, RSIStrategy, MACDStrategy
        df = _make_test_df(200)
        engine = BacktestEngine()
        strategies = [MACrossStrategy(), RSIStrategy(), MACDStrategy()]
        results = engine.run_multiple(df, strategies, "TEST")
        assert len(results) == 3

    def test_compare(self):
        from qlib_vnpy_platform.core.backtest import BacktestEngine
        from qlib_vnpy_platform.core.strategies import MACrossStrategy, RSIStrategy
        df = _make_test_df(200)
        engine = BacktestEngine()
        results = engine.run_multiple(df, [MACrossStrategy(), RSIStrategy()], "TEST")
        comparison = engine.compare(results)
        assert not comparison.empty
        assert "策略" in comparison.columns
        assert "夏普比率" in comparison.columns

    def test_commission_and_slippage(self):
        from qlib_vnpy_platform.core.backtest import BacktestEngine
        from qlib_vnpy_platform.core.strategies import MACrossStrategy
        df = _make_test_df(200)
        engine = BacktestEngine(commission_rate=0.001, slippage=0.002)
        result = engine.run(df, MACrossStrategy(), "TEST")
        assert "metrics" in result
        for trade in result["trades"]:
            if "commission" in trade:
                assert trade["commission"] > 0

    def test_position_closes_at_end(self):
        from qlib_vnpy_platform.core.backtest import BacktestEngine
        from qlib_vnpy_platform.core.strategies import MACrossStrategy
        df = _make_test_df(200)
        engine = BacktestEngine()
        result = engine.run(df, MACrossStrategy(), "TEST")
        final_equity = result["metrics"]["final_equity"]
        assert final_equity > 0


class TestRegimeDetector:
    def test_trending_market(self):
        from qlib_vnpy_platform.core.regime_detector import MarketRegimeDetector
        df = _make_test_df(200, trend=0.005, volatility=0.01)
        detector = MarketRegimeDetector()
        regime = detector.detect(df)
        assert "regime" in regime
        assert "recommended_strategies" in regime
        assert "reason" in regime

    def test_volatile_market(self):
        from qlib_vnpy_platform.core.regime_detector import MarketRegimeDetector
        df = _make_test_df(200, trend=0.0, volatility=0.05)
        detector = MarketRegimeDetector()
        regime = detector.detect(df)
        assert regime["regime"] in ["trending", "mean_reverting", "volatile", "neutral", "unknown"]

    def test_short_data(self):
        from qlib_vnpy_platform.core.regime_detector import MarketRegimeDetector
        df = _make_test_df(10)
        detector = MarketRegimeDetector()
        regime = detector.detect(df)
        assert regime["regime"] == "unknown"

    def test_strategy_selector(self):
        from qlib_vnpy_platform.core.regime_detector import StrategySelector
        from qlib_vnpy_platform.core.backtest import BacktestEngine
        from qlib_vnpy_platform.core.strategies import MACrossStrategy, RSIStrategy
        df = _make_test_df(200)
        engine = BacktestEngine()
        results = engine.run_multiple(df, [MACrossStrategy(), RSIStrategy()], "TEST")
        selector = StrategySelector()
        top = selector.select_best(df, results, top_n=2)
        assert len(top) <= 2
        assert "composite_score" in top[0]

    def test_hurst_calculation(self):
        from qlib_vnpy_platform.core.regime_detector import MarketRegimeDetector
        detector = MarketRegimeDetector()
        series = pd.Series(np.cumsum(np.random.randn(200)))
        h = detector._calc_hurst(series)
        assert 0 <= h <= 1


class TestIntegration:
    def test_full_pipeline(self):
        from qlib_vnpy_platform.core.strategies import get_strategy, STRATEGY_REGISTRY
        from qlib_vnpy_platform.core.backtest import BacktestEngine
        from qlib_vnpy_platform.core.regime_detector import MarketRegimeDetector, StrategySelector

        df = _make_test_df(200)
        all_strategies = [get_strategy(key) for key in STRATEGY_REGISTRY.keys()]
        engine = BacktestEngine(initial_capital=1000000)
        results = engine.run_multiple(df, all_strategies, "TEST001")
        assert len(results) == 29

        comparison = engine.compare(results)
        assert not comparison.empty

        detector = MarketRegimeDetector()
        regime = detector.detect(df)
        assert regime["regime"] in ["trending", "mean_reverting", "volatile", "neutral", "unknown"]

        selector = StrategySelector()
        top = selector.select_best(df, results, top_n=3)
        assert len(top) <= 3
        assert top[0]["composite_score"] >= top[-1]["composite_score"]

    def test_strategy_with_params(self):
        from qlib_vnpy_platform.core.strategies import get_strategy
        from qlib_vnpy_platform.core.backtest import BacktestEngine

        df = _make_test_df(200)
        s = get_strategy("ma_cross", {"short_window": 10, "long_window": 30})
        engine = BacktestEngine()
        result = engine.run(df, s, "TEST")
        assert "metrics" in result
