import pandas as pd
import numpy as np
from datetime import datetime
from loguru import logger
from qlib_vnpy_platform.core.strategies import BaseStrategy, get_strategy, list_strategies


class BacktestEngine:
    def __init__(self, initial_capital: float = 1000000.0,
                 commission_rate: float = 0.0003,
                 slippage: float = 0.001,
                 min_lot_size: int = 100,
                 position_ratio: float = 0.3,
                 stamp_tax_rate: float = 0.0005):
        self.initial_capital = initial_capital
        self.commission_rate = commission_rate
        self.slippage = slippage
        self.min_lot_size = min_lot_size
        self.position_ratio = position_ratio
        self.stamp_tax_rate = stamp_tax_rate

    def run(self, df: pd.DataFrame, strategy: BaseStrategy,
            symbol: str = "UNKNOWN") -> dict:
        if df.empty or len(df) < 30:
            return {"error": "数据不足，至少需要30条记录"}

        df = strategy.generate_signals(df)

        capital = self.initial_capital
        position = 0
        avg_cost = 0.0
        trades = []
        trade_pairs = []
        equity_curve = []
        daily_returns = []
        current_buy = None

        for i in range(len(df)):
            row = df.iloc[i]
            price = float(row["close"])
            high = float(row.get("high", price))
            low = float(row.get("low", price))
            signal = int(row.get("signal", 0))
            signal_strength = float(row.get("signal_strength", 0))
            date = row.get("date", i)

            if signal == 1 and position == 0:
                invest_amount = capital * self.position_ratio
                actual_price = price * (1 + self.slippage)
                volume = int(invest_amount / (actual_price * self.min_lot_size)) * self.min_lot_size
                if volume > 0:
                    cost = actual_price * volume
                    commission = cost * self.commission_rate
                    total_cost = cost + commission
                    if total_cost <= capital:
                        capital -= total_cost
                        position = volume
                        avg_cost = actual_price
                        trade_record = {
                            "date": str(date),
                            "direction": "BUY",
                            "price": round(actual_price, 2),
                            "raw_price": round(price, 2),
                            "volume": volume,
                            "commission": round(commission, 2),
                            "reason": strategy.name,
                            "signal_strength": round(signal_strength, 3),
                        }
                        trades.append(trade_record)
                        current_buy = {
                            "entry_date": str(date),
                            "entry_price": round(actual_price, 2),
                            "entry_raw_price": round(price, 2),
                            "volume": volume,
                            "commission": round(commission, 2),
                            "signal_strength": round(signal_strength, 3),
                        }

            elif signal == -1 and position > 0:
                actual_price = price * (1 - self.slippage)
                revenue = actual_price * position
                commission = revenue * self.commission_rate
                stamp_tax = revenue * self.stamp_tax_rate
                net_revenue = revenue - commission - stamp_tax
                pnl = (actual_price - avg_cost) * position - commission - stamp_tax
                pnl_pct = (actual_price - avg_cost) / avg_cost * 100 if avg_cost > 0 else 0
                capital += net_revenue

                trade_record = {
                    "date": str(date),
                    "direction": "SELL",
                    "price": round(actual_price, 2),
                    "raw_price": round(price, 2),
                    "volume": position,
                    "commission": round(commission, 2),
                    "stamp_tax": round(stamp_tax, 2),
                    "pnl": round(pnl, 2),
                    "pnl_pct": round(pnl_pct, 2),
                    "reason": strategy.name,
                    "signal_strength": round(signal_strength, 3),
                }
                trades.append(trade_record)

                if current_buy:
                    hold_days = self._calc_hold_days(current_buy["entry_date"], str(date))
                    pair = {
                        "entry_date": current_buy["entry_date"],
                        "entry_price": current_buy["entry_price"],
                        "entry_raw_price": current_buy["entry_raw_price"],
                        "exit_date": str(date),
                        "exit_price": round(actual_price, 2),
                        "exit_raw_price": round(price, 2),
                        "volume": current_buy["volume"],
                        "hold_days": hold_days,
                        "pnl": round(pnl, 2),
                        "pnl_pct": round(pnl_pct, 2),
                        "entry_commission": current_buy["commission"],
                        "exit_commission": round(commission, 2),
                        "exit_stamp_tax": round(stamp_tax, 2),
                        "total_cost": round(current_buy["commission"] + commission + stamp_tax, 2),
                        "entry_signal_strength": current_buy["signal_strength"],
                        "exit_signal_strength": round(signal_strength, 3),
                        "result": "盈利" if pnl > 0 else ("亏损" if pnl < 0 else "持平"),
                    }
                    trade_pairs.append(pair)
                    current_buy = None

                position = 0
                avg_cost = 0.0

            position_value = position * price
            total_equity = capital + position_value
            equity_curve.append({
                "date": str(date),
                "equity": round(total_equity, 2),
                "cash": round(capital, 2),
                "position_value": round(position_value, 2),
                "price": round(price, 2),
                "has_position": position > 0,
            })

            if len(equity_curve) >= 2:
                prev_equity = equity_curve[-2]["equity"]
                daily_ret = (total_equity - prev_equity) / prev_equity if prev_equity > 0 else 0
                daily_returns.append(daily_ret)

        open_position = None
        if position > 0 and current_buy:
            last_price = df.iloc[-1]["close"]
            actual_price = last_price * (1 - self.slippage)
            revenue = actual_price * position
            commission = revenue * self.commission_rate
            stamp_tax = revenue * self.stamp_tax_rate
            pnl = (actual_price - avg_cost) * position - commission - stamp_tax
            pnl_pct = (actual_price - avg_cost) / avg_cost * 100 if avg_cost > 0 else 0
            open_position = {
                "entry_date": current_buy["entry_date"],
                "entry_price": current_buy["entry_price"],
                "current_price": round(float(last_price), 2),
                "volume": current_buy["volume"],
                "unrealized_pnl": round(pnl, 2),
                "unrealized_pnl_pct": round(pnl_pct, 2),
                "hold_days": self._calc_hold_days(current_buy["entry_date"], str(df.iloc[-1].get("date", ""))),
            }
            final_equity = capital + position * float(last_price)
        else:
            final_equity = capital
        metrics = self._calc_metrics(equity_curve, daily_returns, trades, trade_pairs)

        latest_signals = self._extract_latest_signals(df, strategy)

        return {
            "symbol": symbol,
            "strategy": strategy.get_info(),
            "metrics": metrics,
            "trades": trades,
            "trade_pairs": trade_pairs,
            "open_position": open_position,
            "latest_signals": latest_signals,
            "equity_curve": equity_curve,
            "total_trades": len(trades),
        }

    def _calc_hold_days(self, entry_date_str: str, exit_date_str: str) -> int:
        try:
            entry = pd.Timestamp(entry_date_str)
            exit_ = pd.Timestamp(exit_date_str)
            return max(1, (exit_ - entry).days)
        except Exception:
            return 0

    def _extract_latest_signals(self, df: pd.DataFrame, strategy: BaseStrategy) -> dict:
        if df.empty:
            return {}

        last_row = df.iloc[-1]
        second_last = df.iloc[-2] if len(df) >= 2 else last_row

        current_signal = int(last_row.get("signal", 0))
        prev_signal = int(second_last.get("signal", 0))

        signal_desc = {1: "买入", -1: "卖出", 0: "持有/观望"}
        current_action = signal_desc.get(current_signal, "未知")

        next_action = "观望"
        if current_signal == 1:
            next_action = "建议买入"
        elif current_signal == -1:
            next_action = "建议卖出"
        elif prev_signal == 1 and current_signal == 0:
            next_action = "已买入，持有等待卖出信号"
        elif prev_signal == -1 and current_signal == 0:
            next_action = "已卖出，等待买入信号"

        latest = {
            "date": str(last_row.get("date", "")),
            "close": round(float(last_row.get("close", 0)), 2),
            "signal": current_signal,
            "signal_strength": round(float(last_row.get("signal_strength", 0)), 3),
            "action": current_action,
            "next_action": next_action,
        }

        strategy_columns = {
            "MACrossStrategy": ["ma_short", "ma_long"],
            "RSIStrategy": ["rsi"],
            "MACDStrategy": ["macd", "macd_signal", "macd_hist"],
            "BollingerStrategy": ["boll_mid", "boll_upper", "boll_lower"],
            "MomentumStrategy": ["momentum"],
            "KDJStrategy": ["K", "D", "J"],
            "DualThrustStrategy": ["upper_bound", "lower_bound"],
            "TurtleStrategy": ["entry_high", "exit_low", "atr"],
            "MeanReversionStrategy": ["zscore", "mean"],
            "MAAlignmentStrategy": ["ma_short", "ma_mid", "ma_long"],
            "VolumeBreakoutStrategy": ["vol_ratio", "highest", "lowest"],
            "VolatilityBreakoutStrategy": ["bb_upper", "bb_lower", "bb_width"],
            "TrendFollowingStrategy": ["plus_di", "minus_di", "adx"],
            "GapStrategy": ["gap_up", "gap_down"],
            "ThreeSoldiersStrategy": ["body_pct"],
            "SupportResistanceStrategy": [],
            "OBVStrategy": ["obv", "obv_ma"],
            "SentimentCycleStrategy": ["sentiment", "sentiment_ma"],
            "SectorRotationStrategy": ["value_score", "momentum_score", "combined_score"],
            "ProsperityInvestmentStrategy": ["growth_score", "growth_ma"],
            "BandOperationStrategy": ["band_high", "band_low", "band_mid"],
            "ValueInvestmentStrategy": ["value_score"],
            "DragonHeadStrategy": ["strength", "volume_ratio"],
            "MACDMultiTimeframeStrategy": ["macd_daily", "macd_signal_daily", "macd_weekly", "macd_signal_weekly"],
            "VolumeWeightedAveragePriceStrategy": ["vwap", "vwap_deviation"],
            "ParabolicSARStrategy": ["sar", "sar_trend"],
            "MoneyFlowIndexStrategy": ["mfi"],
            "SentimentNewsStrategy": ["sentiment_score", "news_count"],
            "SentimentContrarianStrategy": ["fear_index", "greed_index"],
        }

        cols = strategy_columns.get(type(strategy).__name__, [])
        indicators = {}
        for col in cols:
            if col in last_row.index:
                val = last_row[col]
                if pd.notna(val) and np.isfinite(val):
                    indicators[col] = round(float(val), 4)
        latest["indicators"] = indicators

        return latest

    def _calc_metrics(self, equity_curve: list, daily_returns: list,
                      trades: list, trade_pairs: list) -> dict:
        if not equity_curve:
            return {}

        final_equity = equity_curve[-1]["equity"]
        total_return = (final_equity - self.initial_capital) / self.initial_capital

        buy_trades = [t for t in trades if t["direction"] == "BUY"]
        sell_trades = [t for t in trades if t["direction"] == "SELL"]

        winning_trades = [t for t in sell_trades if t.get("pnl", 0) > 0]
        losing_trades = [t for t in sell_trades if t.get("pnl", 0) < 0]

        win_rate = len(winning_trades) / len(sell_trades) if sell_trades else 0

        total_profit = sum(t["pnl"] for t in winning_trades) if winning_trades else 0
        total_loss = abs(sum(t["pnl"] for t in losing_trades)) if losing_trades else 0
        profit_factor = total_profit / total_loss if total_loss > 0 else 999.99 if total_profit > 0 else 0

        avg_profit = total_profit / len(winning_trades) if winning_trades else 0
        avg_loss = total_loss / len(losing_trades) if losing_trades else 0

        max_drawdown = 0
        peak = equity_curve[0]["equity"]
        peak_idx = 0

        for i, eq in enumerate(equity_curve):
            if eq["equity"] > peak:
                peak = eq["equity"]
                peak_idx = i
            dd = (peak - eq["equity"]) / peak if peak > 0 else 0
            if dd > max_drawdown:
                max_drawdown = dd

        sharpe_ratio = 0
        if daily_returns and len(daily_returns) > 1:
            avg_ret = np.mean(daily_returns)
            std_ret = np.std(daily_returns)
            if std_ret > 0:
                sharpe_ratio = avg_ret / std_ret * np.sqrt(252)

        calmar_ratio = total_return / max_drawdown if max_drawdown > 0 else 999.99 if total_return > 0 else 0

        avg_hold_days = 0
        if trade_pairs:
            avg_hold_days = round(np.mean([p["hold_days"] for p in trade_pairs]), 1)

        max_single_profit = max((p["pnl"] for p in trade_pairs), default=0)
        max_single_loss = min((p["pnl"] for p in trade_pairs), default=0)

        return {
            "total_return": round(total_return * 100, 2),
            "annual_return": round(total_return * 252 / max(len(equity_curve), 1) * 100, 2),
            "max_drawdown": round(max_drawdown * 100, 2),
            "sharpe_ratio": round(sharpe_ratio, 2),
            "calmar_ratio": round(calmar_ratio, 2),
            "win_rate": round(win_rate * 100, 1),
            "profit_factor": round(profit_factor, 2),
            "total_trades": len(trades),
            "buy_count": len(buy_trades),
            "sell_count": len(sell_trades),
            "winning_trades": len(winning_trades),
            "losing_trades": len(losing_trades),
            "avg_profit": round(avg_profit, 2),
            "avg_loss": round(avg_loss, 2),
            "avg_hold_days": avg_hold_days,
            "max_single_profit": round(max_single_profit, 2),
            "max_single_loss": round(max_single_loss, 2),
            "final_equity": round(final_equity, 2),
            "total_pnl": round(final_equity - self.initial_capital, 2),
        }

    def run_multiple(self, df: pd.DataFrame, strategies: list,
                     symbol: str = "UNKNOWN") -> list:
        results = []
        for strategy in strategies:
            try:
                result = self.run(df, strategy, symbol)
                results.append(result)
            except Exception as e:
                logger.error(f"Backtest failed for {strategy.name}: {e}")
                results.append({
                    "symbol": symbol,
                    "strategy": strategy.get_info(),
                    "error": str(e),
                })
        return results

    def compare(self, results: list) -> pd.DataFrame:
        rows = []
        for r in results:
            if "error" in r:
                continue
            m = r.get("metrics", {})
            rows.append({
                "策略": r["strategy"]["name"],
                "参数": str(r["strategy"]["params"]),
                "总收益率%": m.get("total_return", 0),
                "年化收益%": m.get("annual_return", 0),
                "最大回撤%": m.get("max_drawdown", 0),
                "夏普比率": m.get("sharpe_ratio", 0),
                "卡尔玛比率": m.get("calmar_ratio", 0),
                "胜率%": m.get("win_rate", 0),
                "盈亏比": m.get("profit_factor", 0),
                "交易次数": m.get("total_trades", 0),
                "最终资金": m.get("final_equity", 0),
            })

        df = pd.DataFrame(rows)
        if not df.empty:
            df = df.sort_values("夏普比率", ascending=False).reset_index(drop=True)
            df.index += 1
            df.index.name = "排名"
        return df

    def run_out_of_sample(self, df: pd.DataFrame, strategy: BaseStrategy,
                          symbol: str = "UNKNOWN",
                          train_ratio: float = 0.7) -> dict:
        if df.empty or len(df) < 60:
            return {"error": "数据不足，至少需要60条记录"}

        split_idx = int(len(df) * train_ratio)
        train_df = df.iloc[:split_idx].copy()
        test_df = df.iloc[split_idx:].copy()

        train_result = self.run(train_df, strategy, symbol)
        test_result = self.run(test_df, strategy, symbol)

        train_metrics = train_result.get("metrics", {})
        test_metrics = test_result.get("metrics", {})

        train_return = train_metrics.get("total_return", 0)
        test_return = test_metrics.get("total_return", 0)
        return_decay = 0
        if abs(train_return) > 0.01:
            return_decay = (train_return - test_return) / abs(train_return) * 100

        overfitting_risk = "低"
        if return_decay > 50:
            overfitting_risk = "高"
        elif return_decay > 30:
            overfitting_risk = "中高"
        elif return_decay > 15:
            overfitting_risk = "中"

        return {
            "symbol": symbol,
            "strategy": strategy.get_info(),
            "train_ratio": train_ratio,
            "train_period": {
                "start": str(train_df.iloc[0].get("date", ""))[:10],
                "end": str(train_df.iloc[-1].get("date", ""))[:10],
                "rows": len(train_df),
            },
            "test_period": {
                "start": str(test_df.iloc[0].get("date", ""))[:10],
                "end": str(test_df.iloc[-1].get("date", ""))[:10],
                "rows": len(test_df),
            },
            "train_metrics": train_metrics,
            "test_metrics": test_metrics,
            "return_decay_pct": round(return_decay, 2),
            "overfitting_risk": overfitting_risk,
            "recommendation": "策略在样本外表现稳定，可考虑实盘" if overfitting_risk == "低" else
                              "策略存在一定过拟合风险，建议谨慎" if overfitting_risk in ["中", "中高"] else
                              "策略过拟合风险高，不建议实盘",
        }

    def run_sensitivity(self, df: pd.DataFrame, strategy: BaseStrategy,
                        symbol: str = "UNKNOWN",
                        param_name: str = None,
                        variations: list = None) -> dict:
        if param_name is None or variations is None:
            variations = [-0.2, -0.1, 0, 0.1, 0.2]

        base_params = strategy.params.copy()
        if param_name not in base_params:
            return {"error": f"参数 {param_name} 不存在于策略中，可用参数: {list(base_params.keys())}"}

        base_value = base_params[param_name]
        if not isinstance(base_value, (int, float)):
            return {"error": f"参数 {param_name} 不是数值类型，无法进行敏感性分析"}

        results = []
        for var in variations:
            new_value = base_value * (1 + var)
            if isinstance(base_value, int):
                new_value = int(round(new_value))
                if new_value <= 0:
                    continue

            try:
                new_params = base_params.copy()
                new_params[param_name] = new_value
                from qlib_vnpy_platform.core.strategies import get_strategy as create_strategy
                new_strategy = create_strategy(strategy.key, new_params)
                bt_result = self.run(df, new_strategy, symbol)
                metrics = bt_result.get("metrics", {})
                results.append({
                    "variation_pct": round(var * 100, 1),
                    "param_value": new_value,
                    "total_return": metrics.get("total_return", 0),
                    "max_drawdown": metrics.get("max_drawdown", 0),
                    "sharpe_ratio": metrics.get("sharpe_ratio", 0),
                    "win_rate": metrics.get("win_rate", 0),
                    "total_trades": metrics.get("total_trades", 0),
                })
            except Exception as e:
                logger.warning(f"Sensitivity test failed for {param_name}={new_value}: {e}")

        if len(results) < 2:
            return {"error": "敏感性分析结果不足"}

        returns = [r["total_return"] for r in results]
        return_range = max(returns) - min(returns)
        base_return = next((r["total_return"] for r in results if r["variation_pct"] == 0), returns[len(results)//2])
        sensitivity = return_range / abs(base_return) * 100 if abs(base_return) > 0.01 else 0

        stability = "稳定"
        if sensitivity > 50:
            stability = "极不稳定"
        elif sensitivity > 30:
            stability = "不稳定"
        elif sensitivity > 15:
            stability = "一般"

        return {
            "symbol": symbol,
            "strategy_key": strategy.key,
            "param_name": param_name,
            "base_value": base_value,
            "sensitivity_pct": round(sensitivity, 2),
            "stability": stability,
            "results": results,
            "recommendation": "参数稳定，策略可靠" if stability == "稳定" else
                              "参数敏感度一般，需注意" if stability == "一般" else
                              "参数过于敏感，策略不可靠",
        }

    def full_validation(self, df: pd.DataFrame, strategy: BaseStrategy,
                        symbol: str = "UNKNOWN") -> dict:
        full_result = self.run(df, strategy, symbol)
        oos_result = self.run_out_of_sample(df, strategy, symbol)

        param_name = None
        base_params = strategy.params
        for k, v in base_params.items():
            if isinstance(v, (int, float)) and v > 0:
                param_name = k
                break

        sens_result = {}
        if param_name:
            sens_result = self.run_sensitivity(df, strategy, symbol, param_name)

        full_metrics = full_result.get("metrics", {})
        oos_metrics = oos_result.get("test_metrics", {})

        score = 0
        if full_metrics.get("sharpe_ratio", 0) > 0.5:
            score += 20
        if full_metrics.get("sharpe_ratio", 0) > 1.0:
            score += 10
        if full_metrics.get("max_drawdown", 0) < 20:
            score += 15
        if full_metrics.get("max_drawdown", 0) < 10:
            score += 10
        if full_metrics.get("win_rate", 0) > 45:
            score += 15
        if full_metrics.get("win_rate", 0) > 55:
            score += 10
        if oos_result.get("overfitting_risk") == "低":
            score += 15
        elif oos_result.get("overfitting_risk") == "中":
            score += 5
        if sens_result.get("stability") == "稳定":
            score += 15
        elif sens_result.get("stability") == "一般":
            score += 5

        grade = "D"
        if score >= 80:
            grade = "A"
        elif score >= 65:
            grade = "B"
        elif score >= 50:
            grade = "C"

        return {
            "symbol": symbol,
            "strategy": strategy.get_info(),
            "strategy_key": strategy.key,
            "full_backtest": full_metrics,
            "out_of_sample": oos_result,
            "sensitivity": sens_result if param_name else {"info": "无数值参数，跳过敏感性分析"},
            "validation_score": score,
            "validation_grade": grade,
            "recommendation": {
                "A": "策略验证通过，建议进入Paper Trading阶段",
                "B": "策略基本可靠，可小资金Paper Trading验证",
                "C": "策略存在风险，需优化后再验证",
                "D": "策略不可靠，不建议使用",
            }.get(grade, "策略不可靠"),
        }
