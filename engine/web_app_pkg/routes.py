"""Route handlers for the web app. All routes defined as a Flask Blueprint named 'api'."""

import json
import time
from datetime import datetime

from flask import Blueprint, render_template, jsonify, request, Response
from loguru import logger

from qlib_vnpy_platform.config import load_config, get_config
from qlib_vnpy_platform.core.main_engine import MainEngine
from qlib_vnpy_platform.core.log_manager import get_log_files, read_log, export_logs, get_log_stats
from qlib_vnpy_platform.core.strategies import get_strategy, list_strategies, STRATEGY_REGISTRY
from qlib_vnpy_platform.core.backtest import BacktestEngine
from qlib_vnpy_platform.core.regime_detector import MarketRegimeDetector, StrategySelector
from qlib_vnpy_platform.core.strategy_simulator import StrategySimulator
from qlib_vnpy_platform.core.paper_trading import PaperTradingEngine
# 高级模块
from qlib_vnpy_platform.core.strategy_pool_manager import StrategyPoolManager
from qlib_vnpy_platform.core.portfolio_simulation import PortfolioSimulation
from qlib_vnpy_platform.core.real_time_data import RealTimeDataManager
from qlib_vnpy_platform.core.advanced_risk_manager import AdvancedRiskManager
from qlib_vnpy_platform.core.execution_optimizer import ExecutionOptimizer
# 监控模块
from qlib_vnpy_platform.core.system_monitor import get_system_monitor
from qlib_vnpy_platform.core.data_quality_monitor import get_monitor_instance

from web_app_pkg.helpers import (
    get_engine, safe_jsonify, _sanitize_json,
    _last_analyze_time, ANALYZE_COOLDOWN, VALID_SYMBOL_PATTERN,
)

bp = Blueprint("api", __name__)


@bp.route("/")
def index():
    return render_template("dashboard.html")


@bp.route("/api/health")
def api_health():
    """系统健康检查端点"""
    try:
        eng = get_engine()
        status = eng.get_status()
        health = status.get("health", {})
        return jsonify({
            "status": "ok" if health.get("is_healthy", False) else "degraded",
            "timestamp": datetime.now().isoformat(),
            "uptime": status.get("uptime", "N/A"),
            "watch_list_count": len(status.get("watch_list", [])),
            "error_count": health.get("error_count", 0),
            "last_error": health.get("last_error"),
            "engine_running": status.get("running", False),
            "strategies_loaded": status.get("strategies", {}).get("loaded", 0),
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "error": str(e),
            "timestamp": datetime.now().isoformat(),
        }), 503


@bp.route("/api/status")
def api_status():
    eng = get_engine()
    return jsonify(eng.get_status())


@bp.route("/api/analyze", methods=["POST"])
def api_analyze():
    data = request.json or {}
    symbol = data.get("symbol", "").strip().upper()
    if not symbol:
        return jsonify({"error": "Symbol is required"}), 400

    if not VALID_SYMBOL_PATTERN.match(symbol):
        return jsonify({"error": "Invalid symbol format. Expected: SZ000001, SH600000, etc."}), 400

    now = time.time()
    last_time = _last_analyze_time.get(symbol, 0)
    if now - last_time < ANALYZE_COOLDOWN:
        remaining = int(ANALYZE_COOLDOWN - (now - last_time))
        return jsonify({"error": f"Rate limited. Please wait {remaining}s before analyzing {symbol} again."}), 429

    _last_analyze_time[symbol] = now

    eng = get_engine()
    result = eng.analyze_stock(symbol)
    return safe_jsonify(result)


@bp.route("/api/watch", methods=["POST"])
def api_add_watch():
    data = request.json or {}
    symbol = data.get("symbol", "").strip().upper()
    if not symbol:
        return jsonify({"error": "Symbol is required"}), 400

    if not VALID_SYMBOL_PATTERN.match(symbol):
        return jsonify({"error": "Invalid symbol format"}), 400

    eng = get_engine()
    eng.add_stock(symbol)
    return jsonify({"watch_list": eng._watch_list})


@bp.route("/api/watch", methods=["GET"])
def api_get_watch():
    eng = get_engine()
    return jsonify({"watch_list": eng._watch_list})


@bp.route("/api/watch", methods=["DELETE"])
def api_remove_watch():
    data = request.json or {}
    symbol = data.get("symbol", "").strip().upper()
    if not symbol:
        return jsonify({"error": "Symbol is required"}), 400

    if not VALID_SYMBOL_PATTERN.match(symbol):
        return jsonify({"error": "Invalid symbol format"}), 400

    eng = get_engine()
    eng.remove_stock(symbol)
    return jsonify({"watch_list": eng._watch_list})


@bp.route("/api/trades")
def api_trades():
    eng = get_engine()
    return safe_jsonify({"trades": eng.trading_engine.get_trades(50)})


@bp.route("/api/strategies")
def api_list_strategies():
    strategies = list_strategies()
    return jsonify({"strategies": strategies})


@bp.route("/api/backtest", methods=["POST"])
def api_backtest():
    data = request.json or {}
    symbol = data.get("symbol", "").strip().upper()
    strategy_keys = data.get("strategies", [])
    params = data.get("params", {})
    initial_capital = data.get("initial_capital", 1000000)

    if not symbol:
        return jsonify({"error": "Symbol is required"}), 400
    if not VALID_SYMBOL_PATTERN.match(symbol):
        return jsonify({"error": "Invalid symbol format"}), 400

    eng = get_engine()
    df = eng.data_bridge.fetch_stock_daily(symbol)
    if df.empty:
        return jsonify({"error": f"无法获取 {symbol} 的历史数据"}), 404

    df = eng.data_bridge.calc_technical_indicators(df)

    if not strategy_keys:
        strategy_keys = list(STRATEGY_REGISTRY.keys())

    strategies = []
    for key in strategy_keys:
        if key in STRATEGY_REGISTRY:
            strategy_params = params.get(key, {})
            try:
                s = get_strategy(key, strategy_params)
                strategies.append(s)
            except Exception as e:
                logger.warning(f"Failed to create strategy {key}: {e}")

    if not strategies:
        return jsonify({"error": "No valid strategies"}), 400

    bt = BacktestEngine(initial_capital=initial_capital)
    results = bt.run_multiple(df, strategies, symbol)
    comparison = bt.compare(results)

    regime_detector = MarketRegimeDetector()
    regime = regime_detector.detect(df)

    selector = StrategySelector()
    top_picks = selector.select_best(df, results, top_n=3)

    summary = []
    if not comparison.empty:
        for idx, row in comparison.iterrows():
            summary.append({
                "rank": idx,
                "strategy": row["策略"],
                "params": row["参数"],
                "total_return": row["总收益率%"],
                "max_drawdown": row["最大回撤%"],
                "sharpe": row["夏普比率"],
                "win_rate": row["胜率%"],
                "profit_factor": row.get("盈亏比", 0),
                "trades": int(row["交易次数"]),
            })

    return safe_jsonify({
        "symbol": symbol,
        "regime": regime,
        "results": results,
        "ranking": summary,
        "top_picks": [{
            "strategy": p["strategy"],
            "composite_score": p["composite_score"],
            "regime_match": p["regime_match"],
            "metrics": p["metrics"],
        } for p in top_picks],
    })


@bp.route("/api/backtest/quick", methods=["POST"])
def api_backtest_quick():
    data = request.json or {}
    symbol = data.get("symbol", "").strip().upper()

    if not symbol:
        return jsonify({"error": "Symbol is required"}), 400
    if not VALID_SYMBOL_PATTERN.match(symbol):
        return jsonify({"error": "Invalid symbol format"}), 400

    eng = get_engine()
    df = eng.data_bridge.fetch_stock_daily(symbol)
    if df.empty:
        return jsonify({"error": f"无法获取 {symbol} 的历史数据"}), 404

    df = eng.data_bridge.calc_technical_indicators(df)

    bt = BacktestEngine()
    all_strategies = [get_strategy(key) for key in STRATEGY_REGISTRY.keys()]
    results = bt.run_multiple(df, all_strategies, symbol)
    comparison = bt.compare(results)

    regime_detector = MarketRegimeDetector()
    regime = regime_detector.detect(df)

    selector = StrategySelector()
    top_picks = selector.select_best(df, results, top_n=3)

    summary = []
    for _, row in comparison.iterrows():
        summary.append({
            "rank": int(row.name) if hasattr(row, "name") else 0,
            "strategy": row["策略"],
            "params": row["参数"],
            "total_return": row["总收益率%"],
            "max_drawdown": row["最大回撤%"],
            "sharpe": row["夏普比率"],
            "win_rate": row["胜率%"],
            "profit_factor": row.get("盈亏比", 0),
            "trades": int(row["交易次数"]),
        })

    return safe_jsonify({
        "symbol": symbol,
        "regime": regime,
        "results": results,
        "ranking": summary,
        "top_picks": [{
            "strategy": p["strategy"],
            "composite_score": p["composite_score"],
            "regime_match": p["regime_match"],
            "metrics": p["metrics"],
        } for p in top_picks],
    })


@bp.route("/api/positions")
def api_positions():
    eng = get_engine()
    return safe_jsonify({"positions": eng.trading_engine.get_positions()})


@bp.route("/api/strategy/monitor/toggle", methods=["POST"])
def api_strategy_monitor_toggle():
    eng = get_engine()
    data = request.json or {}
    action = data.get("action", "toggle")
    if action == "start" or (action == "toggle" and not eng.strategy_monitor.is_running):
        eng.strategy_monitor.configure(symbols=list(eng._watch_list))
        eng.strategy_monitor.start()
        return jsonify({"status": "started", "monitoring": True})
    else:
        eng.strategy_monitor.stop()
        return jsonify({"status": "stopped", "monitoring": False})


@bp.route("/api/strategy/monitor/status")
def api_strategy_monitor_status():
    eng = get_engine()
    return safe_jsonify(eng.strategy_monitor.status)


@bp.route("/api/strategy/monitor/scan", methods=["POST"])
def api_strategy_monitor_scan():
    eng = get_engine()
    data = request.json or {}
    symbol = data.get("symbol", "").strip().upper()
    if symbol:
        if not VALID_SYMBOL_PATTERN.match(symbol):
            return jsonify({"error": "Invalid symbol format"}), 400
        result = eng.strategy_monitor.scan_once(symbol)
        return safe_jsonify(result)
    results = eng.strategy_monitor.scan_all()
    return safe_jsonify(results)


@bp.route("/api/strategy/monitor/signals")
def api_strategy_monitor_signals():
    eng = get_engine()
    symbol = request.args.get("symbol", "").strip().upper()
    limit = int(request.args.get("limit", 50))
    signals = eng.strategy_monitor.get_signal_alerts(limit)
    if symbol:
        signals = [s for s in signals if s.get("symbol") == symbol]
    return safe_jsonify({"alerts": signals, "total": len(signals)})


@bp.route("/api/strategy/monitor/report")
def api_strategy_monitor_report():
    eng = get_engine()
    action = request.args.get("action", "latest")
    if action == "generate":
        report = eng.strategy_monitor.generate_daily_report()
        return safe_jsonify(report)
    reports = eng.strategy_monitor.get_daily_reports(5)
    if reports:
        return safe_jsonify(reports[-1])
    return jsonify({"message": "暂无报告，请先生成"})


@bp.route("/api/strategy/monitor/latest")
def api_strategy_monitor_latest():
    eng = get_engine()
    symbol = request.args.get("symbol", "").strip().upper()
    
    # 如果没有结果，先执行一次扫描
    result = eng.strategy_monitor.get_latest_signals(symbol)
    if not result or result.get("error") or len(result.get("current_signals", [])) == 0:
        try:
            result = eng.strategy_monitor.scan_once(symbol)
        except Exception as e:
            logger.error(f"Failed to scan symbol: {e}")
    
    # 同时支持两种格式返回
    response = result.copy() if result else {}
    # 添加signals字段作为current_signals的别名
    if "current_signals" in response:
        response["signals"] = response["current_signals"]
    
    return safe_jsonify(response)


@bp.route("/api/strategy/llm_advice", methods=["POST"])
def api_strategy_llm_advice():
    data = request.json or {}
    symbol = data.get("symbol", "").strip().upper()
    if not symbol:
        return jsonify({"error": "Symbol is required"}), 400
    if not VALID_SYMBOL_PATTERN.match(symbol):
        return jsonify({"error": "Invalid symbol format"}), 400

    eng = get_engine()
    df = eng.data_bridge.fetch_stock_daily(symbol)
    if df.empty:
        return jsonify({"error": f"无法获取 {symbol} 的数据"}), 404
    df = eng.data_bridge.calc_technical_indicators(df)

    all_strategies = [get_strategy(key) for key in STRATEGY_REGISTRY.keys()]
    bt = BacktestEngine()
    results = bt.run_multiple(df, all_strategies, symbol)

    detector = MarketRegimeDetector()
    regime = detector.detect(df)

    advice = eng.llm_analyzer.generate_strategy_advice(symbol, results, regime)
    return safe_jsonify(advice)


@bp.route("/api/scheduler/toggle", methods=["POST"])
def api_scheduler_toggle():
    eng = get_engine()
    data = request.json or {}
    auto_trade = data.get("auto_trade", False)

    if eng.scheduler.is_running:
        eng.scheduler.stop()
    else:
        eng.scheduler.configure(
            watch_list=eng._watch_list,
            scan_interval=300,
            auto_trade=auto_trade,
        )
        eng.scheduler.start()

    return safe_jsonify(eng.scheduler.status)


@bp.route("/api/scheduler/status")
def api_scheduler_status():
    eng = get_engine()
    return safe_jsonify(eng.scheduler.status)


@bp.route("/api/logs")
def api_logs():
    filename = request.args.get("file", "")
    lines = min(int(request.args.get("lines", 100)), 1000)
    level = request.args.get("level", None)
    entries = read_log(filename, lines=lines, level_filter=level)
    return jsonify({"entries": entries, "count": len(entries)})


@bp.route("/api/logs/files")
def api_log_files():
    stats = get_log_stats()
    return jsonify(stats)


@bp.route("/api/logs/export")
def api_logs_export():
    filename = request.args.get("file", None)
    date_from = request.args.get("from", None)
    date_to = request.args.get("to", None)
    level = request.args.get("level", None)
    fmt = request.args.get("format", "json")

    content = export_logs(filename=filename, date_from=date_from, date_to=date_to,
                          level=level, format=fmt)

    if fmt == "json":
        return Response(content, mimetype="application/json",
                        headers={"Content-Disposition": "attachment; filename=logs_export.json"})
    else:
        return Response(content, mimetype="text/plain",
                        headers={"Content-Disposition": "attachment; filename=logs_export.txt"})


_strategy_simulator = None


def get_strategy_simulator():
    global _strategy_simulator
    if _strategy_simulator is None:
        _strategy_simulator = StrategySimulator(initial_capital=100000)
    return _strategy_simulator


@bp.route("/api/simulation/run", methods=["POST"])
def api_simulation_run():
    data = request.json or {}
    symbol = data.get("symbol", "SZ002594").strip().upper()
    if not VALID_SYMBOL_PATTERN.match(symbol):
        return jsonify({"error": "Invalid symbol format"}), 400

    days = data.get("days", 365)
    strategy_keys = data.get("strategies", None)

    sim = get_strategy_simulator()

    if strategy_keys:
        results = []
        for key in strategy_keys:
            if key in STRATEGY_REGISTRY:
                try:
                    r = sim.simulate_strategy(key, symbol, days)
                    results.append(r)
                except Exception as e:
                    results.append({"strategy_key": key, "error": str(e)})
    else:
        results = sim.simulate_all_strategies(symbol, days)

    return safe_jsonify({"symbol": symbol, "initial_capital": 100000, "results": results})


@bp.route("/api/simulation/status")
def api_simulation_status():
    sim = get_strategy_simulator()
    return safe_jsonify(sim.get_all_simulations())


_paper_trading_engine = None


def get_paper_trading():
    global _paper_trading_engine
    if _paper_trading_engine is None:
        _paper_trading_engine = PaperTradingEngine(initial_capital=100000)
    return _paper_trading_engine


@bp.route("/mobile")
def mobile_dashboard():
    return render_template("h5_dashboard.html")


@bp.route("/api/paper/init", methods=["POST"])
def api_paper_init():
    data = request.json or {}
    symbol = data.get("symbol", "SZ002594").strip().upper()
    if not VALID_SYMBOL_PATTERN.match(symbol):
        return jsonify({"error": "Invalid symbol format"}), 400

    reset = data.get("reset", False)
    pt = get_paper_trading()
    if reset:
        pt.reset_all()

    results = pt.init_all_strategies(symbol, force=True)
    return safe_jsonify({"symbol": symbol, "initial_capital": 100000, "accounts": results, "reset": reset})


@bp.route("/api/paper/run", methods=["POST"])
def api_paper_run():
    data = request.json or {}
    symbol = data.get("symbol", "SZ002594").strip().upper()
    if not VALID_SYMBOL_PATTERN.match(symbol):
        return jsonify({"error": "Invalid symbol format"}), 400

    pt = get_paper_trading()
    results = pt.run_daily_all(symbol)
    summary = pt.get_summary(symbol)
    return safe_jsonify({"symbol": symbol, "summary": summary, "results": results})


@bp.route("/api/paper/status")
def api_paper_status():
    symbol = request.args.get("symbol", None)
    pt = get_paper_trading()
    accounts = pt.get_all_accounts(symbol)
    summary = pt.get_summary(symbol)
    return safe_jsonify({"summary": summary, "accounts": accounts})


@bp.route("/api/paper/reset", methods=["POST"])
def api_paper_reset():
    pt = get_paper_trading()
    pt.reset_all()
    return safe_jsonify({"status": "ok", "message": "所有模拟盘账户已清零"})


@bp.route("/api/validation/run", methods=["POST"])
def api_validation_run():
    data = request.json or {}
    symbol = data.get("symbol", "SZ002594").strip().upper()
    if not VALID_SYMBOL_PATTERN.match(symbol):
        return jsonify({"error": "Invalid symbol format"}), 400

    strategy_keys = data.get("strategies", None)
    days = data.get("days", 365)

    from qlib_vnpy_platform.core.backtest import BacktestEngine
    from qlib_vnpy_platform.core.data_bridge import DataBridge

    db = DataBridge()
    df = db.fetch_stock_daily(symbol, days=days)
    if df is None or df.empty:
        return safe_jsonify({"error": f"无法获取 {symbol} 的数据"})

    engine = BacktestEngine(
        initial_capital=100000,
        commission_rate=0.0003,
        stamp_tax_rate=0.0005,
        slippage=0.001,
        position_ratio=1.0,
    )

    keys = strategy_keys if strategy_keys else list(STRATEGY_REGISTRY.keys())
    results = []
    for key in keys:
        try:
            strategy = get_strategy(key)
            validation = engine.full_validation(df, strategy, symbol)
            results.append(validation)
        except Exception as e:
            logger.error(f"Validation failed for {key}: {e}")
            results.append({"strategy_key": key, "error": str(e)})

    results.sort(key=lambda x: x.get("validation_score", 0), reverse=True)
    return safe_jsonify({"symbol": symbol, "results": results})


# === 高级模块 API ===

_strategy_pool_manager = None


def get_strategy_pool():
    global _strategy_pool_manager
    if _strategy_pool_manager is None:
        _strategy_pool_manager = StrategyPoolManager()
    return _strategy_pool_manager


@bp.route("/api/strategy_pool/status")
def api_strategy_pool_status():
    pm = get_strategy_pool()
    return safe_jsonify(pm.get_status())


@bp.route("/api/strategy_pool/all")
def api_strategy_pool_all():
    pm = get_strategy_pool()
    return safe_jsonify({"strategies": pm.get_all_strategies()})


@bp.route("/api/strategy_pool/group/<group_name>")
def api_strategy_pool_group(group_name):
    pm = get_strategy_pool()
    return safe_jsonify({"group": group_name, "strategies": pm.get_strategies_by_group(group_name)})


@bp.route("/api/strategy_pool/toggle", methods=["POST"])
def api_strategy_pool_toggle():
    data = request.json or {}
    strategy_key = data.get("strategy_key", None)
    if not strategy_key:
        return jsonify({"error": "strategy_key required"}), 400
    
    pm = get_strategy_pool()
    pm.toggle_strategy_enabled(strategy_key, data.get("enabled"))
    return safe_jsonify({"status": "ok"})


_portfolio_sim = None


def get_portfolio_sim():
    global _portfolio_sim
    if _portfolio_sim is None:
        _portfolio_sim = PortfolioSimulation(initial_capital=1000000)
    return _portfolio_sim


@bp.route("/api/portfolio/status")
def api_portfolio_status():
    ps = get_portfolio_sim()
    return safe_jsonify(ps.get_summary())


_advanced_risk_manager = None


def get_advanced_risk_manager():
    global _advanced_risk_manager
    if _advanced_risk_manager is None:
        _advanced_risk_manager = AdvancedRiskManager()
        _advanced_risk_manager.initialize(1000000)
    return _advanced_risk_manager


@bp.route("/api/risk/report")
def api_risk_report():
    arm = get_advanced_risk_manager()
    return safe_jsonify(arm.get_risk_report())


@bp.route("/api/risk/stress_test")
def api_risk_stress_test():
    arm = get_advanced_risk_manager()
    return safe_jsonify(arm.get_stress_test_report())


_execution_optimizer = None


def get_execution_optimizer():
    global _execution_optimizer
    if _execution_optimizer is None:
        _execution_optimizer = ExecutionOptimizer()
    return _execution_optimizer


@bp.route("/api/execution/optimize", methods=["POST"])
def api_execution_optimize():
    data = request.json or {}
    symbol = data.get("symbol", "SZ002594").upper()
    direction = data.get("direction", "BUY")
    volume = data.get("volume", 1000)
    urgency = data.get("urgency", "normal")
    current_price = data.get("price", 100.0)
    
    eo = get_execution_optimizer()
    result = eo.optimize_execution(symbol, direction, volume, current_price, urgency=urgency)
    return safe_jsonify(result)


@bp.route("/api/execution/report")
def api_execution_report():
    eo = get_execution_optimizer()
    return safe_jsonify(eo.get_execution_report())


# === 监控模块 API ===

@bp.route("/api/monitor/system")
def api_monitor_system():
    """系统健康监控端点"""
    try:
        monitor = get_system_monitor()
        health = monitor.check_system_health()
        return jsonify({
            "status": "ok",
            "timestamp": datetime.now().isoformat(),
            "data": health
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }), 500


@bp.route("/api/monitor/system/summary")
def api_monitor_system_summary():
    """系统健康监控摘要（格式化文本）"""
    try:
        monitor = get_system_monitor()
        summary = monitor.get_status_summary()
        return jsonify({
            "status": "ok",
            "timestamp": datetime.now().isoformat(),
            "summary": summary
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }), 500


@bp.route("/api/monitor/data_quality/check", methods=["POST"])
def api_data_quality_check():
    """数据质量检查端点"""
    try:
        data = request.json or {}
        symbol = data.get("symbol", "SZ002594").strip().upper()
        
        monitor = get_monitor_instance()
        record = monitor.check_symbol_quality(symbol)
        
        return jsonify({
            "status": "ok",
            "timestamp": datetime.now().isoformat(),
            "symbol": symbol,
            "quality_score": record.quality_score,
            "passed": record.passed,
            "issues": record.issues_summary,
            "record": record.__dict__
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }), 500


@bp.route("/api/monitor/data_quality/summary")
def api_data_quality_summary():
    """数据质量监控摘要"""
    try:
        monitor = get_monitor_instance()
        summary = monitor.get_quality_summary()
        
        return jsonify({
            "status": "ok",
            "timestamp": datetime.now().isoformat(),
            "summary": summary
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }), 500
