import json
import time
import threading
from datetime import datetime, timedelta
from pathlib import Path
from loguru import logger
from qlib_vnpy_platform.config import PROJECT_ROOT, DATA_DIR
from qlib_vnpy_platform.core.strategies import get_strategy, STRATEGY_REGISTRY
from qlib_vnpy_platform.core.backtest import BacktestEngine
from qlib_vnpy_platform.core.regime_detector import MarketRegimeDetector, StrategySelector


class StrategyMonitor:
    def __init__(self, data_bridge):
        self.data_bridge = data_bridge
        self._monitoring = False
        self._thread = None
        self._watch_symbols = []
        self._scan_interval = 300
        self._signal_alerts = []
        self._daily_reports = []
        self._last_report_date = None
        self._report_time = (15, 10)
        self._latest_scan_results = {}
        self._reports_dir = DATA_DIR / "strategy_reports"
        self._reports_dir.mkdir(parents=True, exist_ok=True)

    def configure(self, symbols: list = None, scan_interval: int = 300,
                  report_time: tuple = (15, 10)):
        if symbols:
            self._watch_symbols = symbols
        self._scan_interval = max(60, scan_interval)
        self._report_time = report_time

    def start(self):
        if self._monitoring:
            return
        self._monitoring = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info(f"StrategyMonitor started: watching {self._watch_symbols}")

    def stop(self):
        self._monitoring = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("StrategyMonitor stopped")

    @property
    def is_running(self):
        return self._monitoring

    @property
    def status(self):
        return {
            "running": self._monitoring,
            "watch_symbols": self._watch_symbols,
            "scan_interval": self._scan_interval,
            "signal_alerts_count": len(self._signal_alerts),
            "latest_scan_time": self._latest_scan_results.get("_scan_time"),
            "daily_reports_count": len(self._daily_reports),
        }

    def get_latest_signals(self, symbol: str = None) -> dict:
        if symbol:
            return self._latest_scan_results.get(symbol, {})
        return {k: v for k, v in self._latest_scan_results.items() if k != "_scan_time"}

    def get_signal_alerts(self, limit: int = 50) -> list:
        return self._signal_alerts[-limit:]

    def get_daily_reports(self, limit: int = 10) -> list:
        return self._daily_reports[-limit:]

    def scan_once(self, symbol: str) -> dict:
        return self._scan_symbol(symbol)

    def scan_all(self) -> dict:
        results = {}
        for symbol in self._watch_symbols:
            try:
                results[symbol] = self._scan_symbol(symbol)
            except Exception as e:
                logger.error(f"StrategyMonitor scan error for {symbol}: {e}")
                results[symbol] = {"error": str(e)}
        results["_scan_time"] = datetime.now().isoformat()
        self._latest_scan_results = results
        return results

    def generate_daily_report(self) -> dict:
        report = self._build_daily_report()
        self._daily_reports.append(report)
        self._save_report(report)
        return report

    def _scan_symbol(self, symbol: str) -> dict:
        df = self.data_bridge.fetch_stock_daily(symbol)
        if df.empty:
            return {"error": f"无法获取 {symbol} 数据"}

        df = self.data_bridge.calc_technical_indicators(df)

        detector = MarketRegimeDetector()
        regime = detector.detect(df)

        all_strategies = [get_strategy(key) for key in STRATEGY_REGISTRY.keys()]
        engine = BacktestEngine()
        results = engine.run_multiple(df, all_strategies, symbol)

        selector = StrategySelector()
        top_picks = selector.select_best(df, results, top_n=3)

        current_signals = []
        for r in results:
            if "error" in r:
                continue
            ls = r.get("latest_signals", {})
            if ls and ls.get("signal", 0) != 0:
                alert = {
                    "strategy": r["strategy"]["name"],
                    "strategy_key": r["strategy"].get("key", ""),
                    "signal": ls.get("signal", 0),
                    "action": ls.get("action", ""),
                    "next_action": ls.get("next_action", ""),
                    "price": ls.get("close", 0),
                    "date": ls.get("date", ""),
                    "signal_strength": ls.get("signal_strength", 0),
                    "indicators": ls.get("indicators", {}),
                }
                current_signals.append(alert)

                if ls.get("signal") in (1, -1):
                    self._signal_alerts.append({
                        "timestamp": datetime.now().isoformat(),
                        "symbol": symbol,
                        **alert,
                    })
                    if len(self._signal_alerts) > 500:
                        self._signal_alerts = self._signal_alerts[-500:]

        latest_price = float(df.iloc[-1]["close"]) if not df.empty else 0
        latest_date = str(df.iloc[-1].get("date", "")) if not df.empty else ""

        return {
            "symbol": symbol,
            "price": latest_price,
            "date": latest_date,
            "regime": regime,
            "top_picks": [{
                "strategy": p["strategy"],
                "composite_score": p["composite_score"],
                "regime_match": p["regime_match"],
                "metrics": p["metrics"],
            } for p in top_picks],
            "current_signals": current_signals,
            "strategy_results": [{
                "strategy": r["strategy"],
                "metrics": r.get("metrics", {}),
                "latest_signals": r.get("latest_signals", {}),
                "trade_pairs": r.get("trade_pairs", [])[-5:],
                "open_position": r.get("open_position"),
            } for r in results if "error" not in r],
        }

    def _build_daily_report(self) -> dict:
        now = datetime.now()
        report = {
            "date": now.strftime("%Y-%m-%d"),
            "generated_at": now.isoformat(),
            "symbols": {},
        }

        for symbol in self._watch_symbols:
            try:
                scan = self._scan_symbol(symbol)
                report["symbols"][symbol] = {
                    "price": scan.get("price", 0),
                    "regime": scan.get("regime", {}),
                    "top_picks": scan.get("top_picks", []),
                    "current_signals": scan.get("current_signals", []),
                    "strategy_summary": [],
                }

                for sr in scan.get("strategy_results", []):
                    m = sr.get("metrics", {})
                    ls = sr.get("latest_signals", {})
                    report["symbols"][symbol]["strategy_summary"].append({
                        "strategy": sr["strategy"]["name"],
                        "total_return": m.get("total_return", 0),
                        "sharpe_ratio": m.get("sharpe_ratio", 0),
                        "max_drawdown": m.get("max_drawdown", 0),
                        "win_rate": m.get("win_rate", 0),
                        "total_trades": m.get("total_trades", 0),
                        "avg_hold_days": m.get("avg_hold_days", 0),
                        "latest_action": ls.get("next_action", ""),
                        "open_position": sr.get("open_position"),
                    })
            except Exception as e:
                logger.error(f"Daily report error for {symbol}: {e}")
                report["symbols"][symbol] = {"error": str(e)}

        return report

    def _save_report(self, report: dict):
        date_str = report["date"]
        filepath = self._reports_dir / f"report_{date_str}.json"
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        logger.info(f"Daily report saved to {filepath}")

    def _run_loop(self):
        last_scan_time = None
        while self._monitoring:
            try:
                now = datetime.now()

                if last_scan_time:
                    elapsed = (now - last_scan_time).total_seconds()
                    if elapsed < self._scan_interval:
                        time.sleep(min(10, self._scan_interval - elapsed))
                        continue

                last_scan_time = now
                self.scan_all()

                rh, rm = self._report_time
                current_minutes = now.hour * 60 + now.minute
                target_minutes = rh * 60 + rm
                if abs(current_minutes - target_minutes) < 3:
                    today_str = now.strftime("%Y-%m-%d")
                    if self._last_report_date != today_str:
                        self._last_report_date = today_str
                        self.generate_daily_report()

            except Exception as e:
                logger.error(f"StrategyMonitor loop error: {e}")

            time.sleep(10)
