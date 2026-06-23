"""FastAPI 应用入口 — 定时任务 + HTTP API。

每天 08:00(early) / 09:10(morning) / 11:35(noon) / 15:10(close)
自动生成并推送市场日报。15:35 基金监控。
提供手动触发、健康检查、缓存管理等管理接口。
"""

import json
import zlib
import base64
import uuid
import time
from pathlib import Path
from contextlib import asynccontextmanager
from datetime import datetime, date

from fastapi import FastAPI, BackgroundTasks, Query, HTTPException, Request
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger

from core.database import get_db
from services.report_generator import generate_daily_report, push_daily_report
from services.feishu_service import close_client, build_strategy_signals_card
from services.fund_monitor import FundMonitor, FundMonitorConfig, build_fund_monitor_card
from services.strategy_adapter import get_adapter
from services.alert_service import send_alert
from config.settings import get_settings

settings = get_settings()
scheduler = AsyncIOScheduler(timezone=settings.TZ)

# 基金监控配置
_fund_monitor_config = FundMonitorConfig()
_fund_monitor_cache_path = Path(__file__).parent.parent / "fund_monitor_config.json"
if _fund_monitor_cache_path.exists():
    try:
        with open(_fund_monitor_cache_path, "r") as f:
            config_data = json.load(f)
            _fund_monitor_config = FundMonitorConfig(**config_data)
    except Exception:
        pass

import asyncio
_task_store: dict[str, dict] = {}
_task_lock = asyncio.Lock()
_MAX_TASKS = 100


def _set_task(task_id: str, value: dict):
    _task_store[task_id] = value

def _get_task(task_id: str) -> dict | None:
    return _task_store.get(task_id)


def _prune_task_store():
    """清理超出限制的旧任务记录。"""
    while len(_task_store) > _MAX_TASKS:
        _task_store.pop(next(iter(_task_store)))


async def _persist_task(task_id: str, status: str, task_type: str = "",
                         result: str = "", error: str = ""):
    """持久化任务状态到 SQLite（异步，失败不阻塞主流程）。

    内存中的 _task_store 仍然保留，作为快速查询缓存；
    SQLite 作为持久化备份，重启后可恢复。
    """
    try:
        from core.database import get_db
        db = await get_db()
        await db.execute(
            """INSERT INTO task_store (task_id, task_type, status, result, error, updated_at)
               VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(task_id) DO UPDATE SET
                   status = excluded.status,
                   result = excluded.result,
                   error = excluded.error,
                   updated_at = CURRENT_TIMESTAMP""",
            (task_id, task_type, status, result, error),
        )
    except Exception as e:
        logger.debug(f"任务状态持久化失败（不影响主流程）: {e}")


async def _load_tasks_from_db():
    """启动时从 SQLite 恢复最近的任务状态。"""
    try:
        from core.database import get_db
        db = await get_db()
        rows = await db.fetchall(
            """SELECT task_id, task_type, status, result, error, updated_at
               FROM task_store
               WHERE updated_at >= datetime('now', '-1 day')
               ORDER BY updated_at DESC
               LIMIT 50""",
        )
        for row in rows:
            r = dict(row)
            # 将 running 状态标记为 interrupted（重启后无法继续）
            status = r["status"]
            if status == "running":
                status = "interrupted"
            _task_store[r["task_id"]] = {
                "status": status,
                "type": r["task_type"],
                "result": r["result"],
                "error": r["error"],
                "restored": True,
            }
        if rows:
            logger.info(f"✓ 从 SQLite 恢复 {len(rows)} 个任务状态")
    except Exception as e:
        logger.debug(f"从 SQLite 恢复任务状态失败: {e}")


# ── 调度任务 ──────────────────────────────────────────────

async def scheduled_report(version: str):
    """定时任务：生成并推送日报。"""
    logger.info(f"Scheduled report triggered: {version}")
    task_id = f"sched_{version}_{date.today().isoformat()}"
    _task_store[task_id] = {"status": "running", "version": version}
    _prune_task_store()
    await _persist_task(task_id, "running", "scheduled_report")
    try:
        data = await generate_daily_report(version)
        await push_daily_report(data)

        # 持仓卖出告警：收盘版额外检查持仓股的卖出信号
        if version == "close":
            await _check_holdings_sell_signals()

        _task_store[task_id] = {"status": "completed", "version": version}
        await _persist_task(task_id, "completed", "scheduled_report")
        logger.info(f"Scheduled report {version} completed")
    except Exception as e:
        _task_store[task_id] = {"status": "failed", "version": version, "error": str(e)}
        await _persist_task(task_id, "failed", "scheduled_report", error=str(e))
        logger.error(f"Scheduled report {version} failed: {e}", exc_info=True)
        await send_alert(
            f"📰 日报 [{version}] 生成失败\n```\n{str(e)[:300]}\n```",
            level="error",
        )


async def _check_holdings_sell_signals():
    """检查持仓股的卖出信号，有卖出信号时主动推送告警。

    决策闭环关键：用户加了持仓后，系统主动监控卖出时机。
    """
    try:
        from services.portfolio_manager import get_holdings
        from services.strategy_adapter import get_adapter
        from services.feishu_service import send_card_message, get_tenant_token

        holdings = await get_holdings()
        if not holdings:
            return

        symbols = [h["symbol"] for h in holdings]
        logger.info(f"持仓卖出信号检查: {len(symbols)} 只持仓股")

        adapter = get_adapter()
        signals = await adapter.get_signals_async(symbols)
        if not signals:
            return

        # 筛选卖出信号明确的股票（sell_count - buy_count > 2）
        sell_alerts = []
        for sym, sig in signals.items():
            if "error" in sig:
                continue
            buy_n = sig.get("buy_count", 0)
            sell_n = sig.get("sell_count", 0)
            net = buy_n - sell_n
            if net < -2:  # 偏空
                holding = next((h for h in holdings if h["symbol"] == sym), {})
                cost = holding.get("cost_price", 0)
                current = sig.get("price", 0)
                profit_pct = ((current - cost) / cost * 100) if cost and current else 0
                sell_alerts.append({
                    "name": sig.get("stock_name", sym),
                    "symbol": sym,
                    "price": current,
                    "profit_pct": profit_pct,
                    "sell_count": sell_n,
                    "buy_count": buy_n,
                    "sell_signals": sig.get("sell_signals", [])[:3],
                })

        if not sell_alerts:
            logger.info("持仓卖出信号检查完成: 无卖出信号")
            return

        # 推送卖出告警卡片
        if settings.FEISHU_CHAT_ID:
            await get_tenant_token()
            lines = ["## ⚠️ 持仓卖出信号告警", ""]
            for a in sell_alerts:
                profit_icon = "🟢" if a["profit_pct"] >= 0 else "🔴"
                lines.append(
                    f"**{a['name']}** ({a['symbol']})\n"
                    f"{profit_icon} 现价 {a['price']:.2f} | 盈亏 {a['profit_pct']:+.1f}%\n"
                    f"🔴 卖出信号 {a['sell_count']} 个 vs 🟢 买入 {a['buy_count']} 个\n"
                )
                for s in a["sell_signals"]:
                    lines.append(f"  - {s.get('strategy_name', '')} 强度 {s.get('signal_strength', 0):.0%}")
                lines.append("")

            lines.append("---\n⚠️ 以上为策略信号提示，不构成投资建议。请结合基本面和仓位管理决策。")

            card = {
                "header": {
                    "title": {"tag": "plain_text", "content": "⚠️ 持仓卖出信号告警"},
                    "template": "red",
                },
                "elements": [{"tag": "markdown", "content": "\n".join(lines)}],
            }
            await send_card_message(settings.FEISHU_CHAT_ID, card)
            logger.info(f"持仓卖出告警已推送: {len(sell_alerts)} 只股票")
    except Exception as e:
        logger.error(f"持仓卖出信号检查失败（不影响日报）: {e}")


async def scheduled_fund_monitor():
    """定时任务：基金监控。"""
    logger.info("Scheduled fund monitor triggered")
    task_id = f"fund_monitor_{date.today().isoformat()}"
    _task_store[task_id] = {"status": "running", "type": "fund_monitor"}
    _prune_task_store()
    try:
        monitor = FundMonitor(_fund_monitor_config)
        result = await monitor.run_monitor()
        
        if result.get("status") == "success":
            # 保存本地报告
            output_dir = Path("./data/fund_monitor")
            output_dir.mkdir(parents=True, exist_ok=True)
            output_file = output_dir / f"monitor_{result.get('date', date.today().isoformat())}.json"
            with open(output_file, "w") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            
            # 发送飞书通知
            if settings.FEISHU_CHAT_ID:
                from services.feishu_service import send_card_message, get_tenant_token
                await get_tenant_token()
                card = build_fund_monitor_card(result)
                await send_card_message(settings.FEISHU_CHAT_ID, card)
            
            _task_store[task_id] = {"status": "completed", "type": "fund_monitor"}
            logger.info("Scheduled fund monitor completed")
        else:
            _task_store[task_id] = {"status": "failed", "type": "fund_monitor", "error": result.get("message")}
    except Exception as e:
        _task_store[task_id] = {"status": "failed", "type": "fund_monitor", "error": str(e)}
        logger.error(f"Scheduled fund monitor failed: {e}", exc_info=True)
        await send_alert(
            f"📊 基金监控失败\n```\n{str(e)[:300]}\n```",
            level="warning",
        )



# ── 应用生命周期 ──────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动/关闭生命周期管理。"""
    db = await get_db()
    logger.info("Database initialized successfully")

    # 从 SQLite 恢复最近的任务状态
    await _load_tasks_from_db()

    # 清理过期缓存
    from core.cache import FileCache
    cache = FileCache()
    cleaned = cache.clean_expired(max_age_hours=48)
    logger.info(f"Cleaned {cleaned} expired cache files on startup")

    # 注册定时任务
    for version, hour, minute in [("early", 8, 0), ("morning", 9, 10), ("noon", 11, 35), ("close", 15, 10)]:
        scheduler.add_job(
            scheduled_report, "cron", hour=hour, minute=minute,
            args=[version], id=f"{version}_report", misfire_grace_time=600,
            replace_existing=True,
        )
    # 策略信号已注入到 close 报告（15:10）中，不再单独推送
    # 基金监控：每个交易日收盘后15:35执行
    scheduler.add_job(
        scheduled_fund_monitor, "cron", hour=15, minute=35,
        id="fund_monitor", misfire_grace_time=600,
        replace_existing=True,
    )

    # 信号生命周期评估：每日 16:00 执行
    async def scheduled_signal_evaluation():
        """定时任务：评估活跃信号的生命周期。"""
        from services.signal_tracker import get_signal_tracker
        tracker = get_signal_tracker()
        stats = await tracker.evaluate_active_signals()
        logger.info(f"信号生命周期评估完成: {stats}")

    scheduler.add_job(
        scheduled_signal_evaluation, "cron", hour=16, minute=0,
        id="signal_evaluation", misfire_grace_time=600,
        replace_existing=True,
    )

    # 每日凌晨3点清理过期缓存
    async def scheduled_cache_cleanup():
        from core.cache import FileCache
        cache = FileCache()
        cleaned = cache.clean_expired(max_age_hours=48)
        logger.info(f"定时缓存清理: 清理了 {cleaned} 个过期文件")

    scheduler.add_job(
        scheduled_cache_cleanup, "cron", hour=3, minute=0,
        id="cache_cleanup", misfire_grace_time=300,
        replace_existing=True,
    )

    scheduler.start()
    logger.info("Scheduler started: 08:00(early) / 09:10(morning) / 11:35(noon) / 15:10(close) / 15:35(fund_monitor) / 16:00(signal_eval) / 五维框架 v2.0")

    yield

    scheduler.shutdown(wait=True)
    await db.close()
    await close_client()
    logger.info("Shutdown complete")


# ── FastAPI 应用 ──────────────────────────────────────────

app = FastAPI(title="明策 (MingCe) — 全景投资决策系统", version=settings.VERSION, lifespan=lifespan)

# 注册 API v1 路由（不删除旧路由，保持向后兼容）
from app.routers import v1_router
app.include_router(v1_router)

@app.middleware("http")
async def log_requests(request: Request, call_next):
    """请求日志中间件。"""
    start = time.time()
    response = await call_next(request)
    duration = time.time() - start
    logger.info(f"{request.method} {request.url.path} {response.status_code} {duration:.3f}s")
    return response


# 需要认证的写操作端点列表
_WRITE_ENDPOINTS = {
    "/api/report/generate", "/api/cache/clear", "/api/cache/clean",
    "/api/send_message", "/api/fund-monitor/run", "/api/fund-monitor/config",
    "/api/data-quality/reset-monitor", "/api/wisdom/analyze",
    "/api/strategy-signals/push",
}

@app.middleware("http")
async def api_auth_middleware(request: Request, call_next):
    """API Key 认证中间件 — 仅保护写操作端点。"""
    if settings.API_KEY and request.url.path in _WRITE_ENDPOINTS:
        auth = request.headers.get("Authorization", "")
        api_key = request.query_params.get("api_key", "")
        token = auth.replace("Bearer ", "") if auth.startswith("Bearer ") else api_key
        if token != settings.API_KEY:
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=401, content={"detail": "无效的 API Key"})
    return await call_next(request)


@app.get("/")
async def root():
    """根路径欢迎页，返回服务基本信息与可用端点。"""
    return {
        "service": "明策 (MingCe) — 全景投资决策系统",
        "version": settings.VERSION,
        "status": "running",
        "docs": "/docs",
        "redoc": "/redoc",
        "openapi": "/openapi.json",
        "endpoints": {
            "health": "/health",
            "metrics": "/metrics",
            "strategy_signals": "/api/strategy-signals",
            "report_generate": "/api/report/generate",
            "report_latest": "/api/report/latest",
            "task_status": "/api/task/{task_id}",
            "data_quality": "/api/data-quality/status",
            "fund_monitor_run": "/api/fund-monitor/run",
            "fund_monitor_config": "/api/fund-monitor/config",
        },
    }


@app.get("/health")
async def health():
    """健康检查接口（带详细组件状态）。"""
    db_ok = False
    db_error = None
    try:
        db = await get_db()
        row = await db.fetchone("SELECT 1")
        db_ok = row is not None
    except Exception as e:
        db_error = str(e)

    # 检查 LLM 服务
    llm_ok = bool(settings.LLM_API_KEY and settings.LLM_BASE_URL and settings.LLM_MODEL)

    # 检查飞书服务
    feishu_ok = bool(settings.FEISHU_APP_ID and settings.FEISHU_APP_SECRET and settings.FEISHU_CHAT_ID)
    
    # 外部依赖探测（轻量级）
    llm_reachable = None
    try:
        if llm_ok:
            import httpx
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(f"{settings.LLM_BASE_URL.rstrip('/')}/models", headers={"Authorization": f"Bearer {settings.LLM_API_KEY}"})
                llm_reachable = r.status_code == 200
    except Exception:
        llm_reachable = False

    # 检查缓存
    from core.cache import FileCache
    cache = FileCache()
    cache_ok = cache is not None and hasattr(cache, 'cache_dir')

    # 检查数据源（快速检查）
    from core.data_quality import get_monitor
    monitor = get_monitor()
    degraded_sources = [
        name for name, stats in monitor.source_stats.items()
        if stats.get("consecutive_failures", 0) >= 2
    ]

    all_ok = db_ok and llm_ok and cache_ok and feishu_ok
    status = "ok" if all_ok else "degraded"
    if not db_ok:
        status = "critical"

    return {
        "status": status,
        "timestamp": datetime.now().isoformat(),
        "components": {
            "database": {
                "status": "connected" if db_ok else "disconnected",
                "error": db_error,
            },
            "llm": {
                "status": "configured" if llm_ok else "unconfigured",
                "model": settings.LLM_MODEL or "N/A",
                "reachable": llm_reachable,
            },
            "feishu": {
                "status": "configured" if feishu_ok else "unconfigured",
            },
            "cache": {
                "status": "ok" if cache_ok else "error",
            },
            "scheduler": {
                "status": "running" if scheduler.running else "stopped",
                "jobs": [j.id for j in scheduler.get_jobs()],
            },
            "data_sources": {
                "total": len(monitor.source_stats),
                "degraded": degraded_sources,
            },
        },
        "version": settings.VERSION,
    }


@app.get("/metrics")
async def prometheus_metrics():
    """Prometheus 指标端点（Prometheus 文本格式）。"""
    from core.cache import FileCache
    from core.data_quality import get_monitor as _get_monitor
    from services.data_fetcher import get_latest_quality_report
    from pathlib import Path
    import time as _time

    lines = []
    lines.append('# HELP mingce_info 明策系统元信息')
    lines.append('# TYPE mingce_info gauge')
    lines.append(f'mingce_info{{version="{settings.VERSION}",debug="{str(settings.DEBUG).lower()}"}} 1')

    lines.append('')
    lines.append('# HELP mingce_scheduler_running 调度器运行状态')
    lines.append('# TYPE mingce_scheduler_running gauge')
    lines.append(f'mingce_scheduler_running {1 if scheduler.running else 0}')

    lines.append('')
    lines.append('# HELP mingce_database_up 数据库连接状态')
    lines.append('# TYPE mingce_database_up gauge')
    try:
        _db = await get_db()
        await _db.fetchone("SELECT 1")
        lines.append('mingce_database_up 1')
    except Exception:
        lines.append('mingce_database_up 0')

    lines.append('')
    lines.append('# HELP mingce_llm_configured LLM 配置状态')
    lines.append('# TYPE mingce_llm_configured gauge')
    llm_ok = 1 if (settings.LLM_API_KEY and settings.LLM_BASE_URL and settings.LLM_MODEL) else 0
    lines.append(f'mingce_llm_configured {llm_ok}')

    _cache = FileCache()
    lines.append('')
    lines.append('# HELP mingce_cache_files 缓存文件数')
    lines.append('# TYPE mingce_cache_files gauge')
    try:
        cache_files = len(list(Path(settings.CACHE_DIR).glob("*.json"))) if Path(settings.CACHE_DIR).exists() else 0
    except Exception:
        cache_files = 0
    lines.append(f'mingce_cache_files {cache_files}')

    _mon = _get_monitor()
    lines.append('')
    lines.append('# HELP mingce_data_source_health 数据源健康状态')
    lines.append('# TYPE mingce_data_source_health gauge')
    for src_name, stats in _mon.source_stats.items():
        health = _mon.get_health(src_name)
        val = 1 if health.value == "healthy" else 0
        failures = stats.get("consecutive_failures", 0)
        lines.append(f'mingce_data_source_health{{source="{src_name}",failures="{failures}"}} {val}')

    lines.append('')
    lines.append('# HELP mingce_data_quality_score 各模块数据质量评分')
    lines.append('# TYPE mingce_data_quality_score gauge')
    for mod in ["market", "macro", "north_flow", "global_macro", "crypto", "futures"]:
        report = get_latest_quality_report(mod)
        if report:
            score = report.metrics.overall_score
            level = report.metrics.level.value
            lines.append(f'mingce_data_quality_score{{module="{mod}",level="{level}"}} {score:.2f}')

    lines.append('')
    lines.append('# HELP mingce_reports_today 今日已生成报告数')
    lines.append('# TYPE mingce_reports_today gauge')
    try:
        _db2 = await get_db()
        today = date.today().isoformat()
        rows = await _db2.fetchall("SELECT COUNT(*) as cnt FROM daily_reports WHERE report_date = ?", (today,))
        report_count = rows[0]["cnt"] if rows else 0
    except Exception:
        report_count = 0
    lines.append(f'mingce_reports_today {report_count}')

    return "\n".join(lines) + "\n"


@app.get("/api/metrics")
async def metrics():
    """运行状态指标。"""
    db = await get_db()
    today = date.today().isoformat()
    report_status = {}
    for v in ["early", "morning", "noon", "close"]:
        row = await db.fetchone(
            "SELECT status, created_at FROM daily_reports WHERE report_date = ? AND version = ?",
            (today, v),
        )
        report_status[v] = {
            "status": row["status"] if row else "not_generated",
            "created_at": row["created_at"] if row else None,
        }
    return {
        "date": today,
        "reports": report_status,
        "scheduler_running": scheduler.running,
        "scheduled_jobs": [j.id for j in scheduler.get_jobs()],
        "active_tasks": len(_task_store),
        "recent_tasks": list(_task_store.values())[-10:],
    }


# ── 策略信号 API ──────────────────────────────────────


@app.get("/api/strategy-signals")
async def get_strategy_signals(
    symbol: str = Query(None, description="股票代码，如 SZ002594。不传则返回所有自选股"),
    background_tasks: BackgroundTasks = None,
):
    """获取 MakingMoney 策略信号。

    通过 subprocess 调用 MakingMoney 的策略引擎，分析指定股票或全部自选股。

    Args:
        symbol: 可选，指定股票代码。不传则返回所有自选股信号。

    Returns:
        dict: 策略信号数据
    """
    adapter = get_adapter()
    if symbol:
        result = await adapter.get_signals_async([symbol])
        if result:
            # 返回单只股票数据
            data = result.get(symbol, result)
            return {"success": True, "data": data, "symbol": symbol}
        return {"success": False, "error": f"无法获取 {symbol} 的策略信号"}
    else:
        result = await adapter.get_all_signals_async()
        if result and result.get("symbols"):
            return {"success": True, "symbols": result["symbols"],
                    "total": result.get("total_symbols", 0),
                    "date": result.get("date", "")}
        return {"success": False, "error": "无法获取策略信号"}


@app.post("/api/strategy-signals/batch")
async def batch_strategy_signals(request: Request):
    """批量获取多个股票的策略信号。

    请求格式:
    ```json
    {
        "symbols": ["SZ002594", "SH600519", "SZ300750"]
    }
    ```
    """
    try:
        body = await request.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"无效的 JSON: {e}")

    symbols = body.get("symbols", [])
    if not symbols or not isinstance(symbols, list):
        raise HTTPException(status_code=400, detail="symbols 必须是包含股票代码的非空列表")

    if len(symbols) > 50:
        raise HTTPException(status_code=400, detail="单次请求最多 50 只股票")

    adapter = get_adapter()
    result = await adapter.get_signals_async(symbols)
    return {"success": True, "symbols": result, "requested": len(symbols), "returned": len(result)}


@app.post("/api/strategy-signals/push")
async def push_strategy_signals(
    background_tasks: BackgroundTasks,
    version: str = Query("opening", description="opening / early / morning / noon / close"),
):
    """手动触发策略信号推送。"""
    task_id = str(uuid.uuid4())[:8]
    _task_store[task_id] = {"status": "pending", "type": "strategy_signals_push", "version": version}
    _prune_task_store()
    background_tasks.add_task(_run_push_strategy_signals, task_id, version)
    return {"status": "accepted", "task_id": task_id, "version": version, "message": "策略信号推送任务已提交"}


async def _run_push_strategy_signals(task_id: str, version: str = "opening"):
    """执行策略信号推送。"""
    try:
        _task_store[task_id]["status"] = "running"
        await _persist_task(task_id, "running", "strategy_signals_push")
        adapter = get_adapter()
        signals_data = await adapter.get_all_signals_async()
        if signals_data and signals_data.get("symbols"):
            from services.feishu_service import send_card_message, get_tenant_token
            await get_tenant_token()
            card = build_strategy_signals_card(signals_data, version=version)
            ok = await send_card_message(settings.FEISHU_CHAT_ID, card)
            if ok:
                _task_store[task_id] = {"status": "completed", "type": "strategy_signals_push",
                                        "stocks": len(signals_data.get("symbols", {}))}
                await _persist_task(task_id, "completed", "strategy_signals_push",
                                    result=f"stocks={len(signals_data.get('symbols', {}))}")
            else:
                _task_store[task_id] = {"status": "failed", "type": "strategy_signals_push", "error": "send failed"}
                await _persist_task(task_id, "failed", "strategy_signals_push", error="send failed")
        else:
            _task_store[task_id] = {"status": "failed", "type": "strategy_signals_push", "error": "no signal data"}
            await _persist_task(task_id, "failed", "strategy_signals_push", error="no signal data")
    except Exception as e:
        _task_store[task_id] = {"status": "failed", "type": "strategy_signals_push", "error": str(e)}
        await _persist_task(task_id, "failed", "strategy_signals_push", error=str(e))
        logger.error(f"Strategy signals push failed: {e}", exc_info=True)


# ── 旧版日报 API ──────────────────────────────────────


@app.post("/api/report/generate")
async def manual_generate(
    background_tasks: BackgroundTasks,
    version: str = Query("close", description="报告版本: morning/noon/close"),
):
    """手动触发日报生成并推送。"""
    task_id = str(uuid.uuid4())[:8]
    _task_store[task_id] = {"status": "pending", "version": version}
    _prune_task_store()
    background_tasks.add_task(_run_generate_and_push, task_id, version)
    return {"status": "accepted", "task_id": task_id, "version": version, "message": "日报生成任务已提交"}


async def _run_generate_and_push(task_id: str, version: str):
    try:
        _task_store[task_id]["status"] = "running"
        await _persist_task(task_id, "running", "manual_report")
        data = await generate_daily_report(version)
        await push_daily_report(data)
        _task_store[task_id]["status"] = "completed"
        await _persist_task(task_id, "completed", "manual_report")
    except Exception as e:
        _task_store[task_id]["status"] = "failed"
        _task_store[task_id]["error"] = str(e)
        await _persist_task(task_id, "failed", "manual_report", error=str(e))
        logger.error(f"Manual report generation failed: {e}", exc_info=True)


@app.get("/api/task/{task_id}")
async def get_task_status(task_id: str):
    """查询异步任务状态。"""
    task = _task_store.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@app.post("/api/report/test")
async def test_push():
    """发送测试消息到飞书。"""
    from services.feishu_service import send_card_message
    card = {
        "header": {
            "template": "green",
            "title": {"tag": "plain_text", "content": "✅ 测试消息"},
        },
        "elements": [{"tag": "markdown", "content": "宏观市场日报机器人已成功连接！\n每日 09:10/11:35/15:10 自动推送日报。"}],
    }
    ok = await send_card_message(settings.FEISHU_CHAT_ID, card)
    return {"sent": ok}


@app.post("/api/send_message")
async def api_send_message(request: Request):
    """通用消息转发端点 — 供 MakingMoney 等外部服务复用飞书通知能力。

    请求格式:
    ```json
    {
        "msg_type": "text",        # 消息类型: "text" 或 "markdown"
        "content": "消息内容"       # 消息正文
    }
    ```
    """
    from services.feishu_service import send_card_message, send_text_message

    try:
        body = await request.json()
    except Exception as e:
        logger.error(f"Invalid JSON body: {e}")
        raise HTTPException(status_code=400, detail=f"无效的 JSON 请求体: {e}")

    msg_type = body.get("msg_type", "text")
    content = body.get("content", "")

    if not content or not content.strip():
        raise HTTPException(status_code=400, detail="content 不能为空")

    chat_id = settings.FEISHU_CHAT_ID
    if not chat_id:
        logger.error("FEISHU_CHAT_ID is not configured")
        return {"sent": False, "error": "飞书 Chat ID 未配置"}

    try:
        if msg_type == "text":
            ok = await send_text_message(chat_id, content)
        elif msg_type == "markdown":
            # 将 markdown 内容包装为飞书卡片发送
            card = {
                "header": {
                    "template": "blue",
                    "title": {"tag": "plain_text", "content": "📨 消息通知"},
                },
                "elements": [
                    {"tag": "markdown", "content": content},
                ],
            }
            ok = await send_card_message(chat_id, card)
        else:
            raise HTTPException(status_code=400, detail=f"不支持的 msg_type: {msg_type}，仅支持 text/markdown")

        if ok:
            logger.info(f"Message forwarded successfully: type={msg_type}, len={len(content)}")
            return {"sent": True, "msg_type": msg_type}
        else:
            logger.error(f"Failed to send message: type={msg_type}")
            return {"sent": False, "error": "飞书消息发送失败"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error forwarding message: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"消息发送异常: {e}")


@app.post("/api/cache/clear")
async def api_clear_cache(key: str = Query(None, description="清除指定缓存键，不传则清空所有")):
    """清除数据缓存。"""
    from core.cache import FileCache
    FileCache().clear(key=key)
    return {"cleared": True, "key": key or "all", "message": f"缓存{' ' + key if key else '全部'}已清除"}


@app.post("/api/cache/clean")
async def api_clean_cache(max_age_hours: int = Query(48, description="清理超过指定小时的缓存文件")):
    """清理过期缓存文件。"""
    from core.cache import FileCache
    cleaned = FileCache().clean_expired(max_age_hours=max_age_hours)
    return {"cleaned": cleaned, "message": f"已清理 {cleaned} 个过期缓存文件"}


@app.get("/api/report/latest")
async def get_latest_report(version: str = Query(None, description="morning/noon/close")):
    """获取最新生成的日报数据。"""
    db = await get_db()
    today = date.today().isoformat()

    if version:
        row = await db.fetchone(
            "SELECT * FROM daily_reports WHERE report_date = ? AND version = ? ORDER BY id DESC LIMIT 1",
            (today, version),
        )
    else:
        row = await db.fetchone(
            "SELECT * FROM daily_reports WHERE report_date = ? ORDER BY id DESC LIMIT 1",
            (today,),
        )

    if row:
        return {
            "found": True, "report_date": row["report_date"],
            "version": row["version"], "status": row["status"],
            "created_at": row["created_at"],
            "content": json.loads(zlib.decompress(base64.b64decode(row["content"][5:])).decode("utf-8") if isinstance(row["content"], str) and row["content"].startswith("ZLIB:") else row["content"]),
        }
    return {"found": False, "message": "今日尚无已生成的日报"}


@app.get("/api/data-quality/status")
async def get_data_quality_status():
    """获取数据质量总体状态。"""
    from services.data_fetcher import get_latest_quality_report
    from core.data_quality import get_monitor, DataQualityLevel
    
    monitor = get_monitor()
    modules = ["market", "north_flow", "macro", "etf", "leading", "global_macro", "bse",
               "us_market", "crypto", "futures", "monetary", "comparison"]
    
    reports = {}
    overall_score = 0.0
    count = 0
    
    for module in modules:
        report = get_latest_quality_report(module)
        if report:
            reports[module] = report.to_dict()
            overall_score += report.metrics.overall_score
            count += 1
    
    # 获取数据源健康状态
    source_health = {}
    for source_name, stats in monitor.source_stats.items():
        source_health[source_name] = {
            "health": monitor.get_health(source_name).value,
            "success_count": stats["success_count"],
            "failure_count": stats["failure_count"],
            "consecutive_failures": stats["consecutive_failures"],
            "last_error": stats["last_error"],
        }
    
    overall_level = DataQualityLevel.UNKNOWN.value
    if count > 0:
        avg_score = overall_score / count
        if avg_score >= 0.95:
            overall_level = DataQualityLevel.EXCELLENT.value
        elif avg_score >= 0.85:
            overall_level = DataQualityLevel.GOOD.value
        elif avg_score >= 0.7:
            overall_level = DataQualityLevel.ACCEPTABLE.value
        elif avg_score >= 0.5:
            overall_level = DataQualityLevel.WARNING.value
        else:
            overall_level = DataQualityLevel.CRITICAL.value
    
    return {
        "overall": {
            "score": overall_score / count if count > 0 else 0,
            "level": overall_level,
            "modules_with_reports": count,
        },
        "modules": reports,
        "sources": source_health,
    }


@app.get("/api/data-quality/report/{module_name}")
async def get_module_quality_report(module_name: str):
    """获取指定模块的数据质量报告。"""
    from services.data_fetcher import get_latest_quality_report
    
    report = get_latest_quality_report(module_name)
    if report:
        return {"found": True, "report": report.to_dict()}
    return {"found": False, "message": f"模块 {module_name} 暂无数据质量报告"}


@app.post("/api/data-quality/reset-monitor")
async def reset_data_source_monitor(source_name: str = Query(None, description="指定数据源名称，不传则重置全部")):
    """重置数据源监控统计。"""
    from core.data_quality import get_monitor
    
    monitor = get_monitor()
    monitor.reset(source_name)
    
    if source_name:
        return {"reset": True, "source": source_name, "message": f"已重置数据源 {source_name} 的统计"}
    return {"reset": True, "message": "已重置所有数据源的监控统计"}


# ── 基金监控 API ──────────────────────────────────────────

@app.post("/api/fund-monitor/run")
async def run_fund_monitor(background_tasks: BackgroundTasks):
    """手动触发基金监控。"""
    task_id = str(uuid.uuid4())[:8]
    _task_store[task_id] = {"status": "pending", "type": "fund_monitor"}
    _prune_task_store()
    background_tasks.add_task(_run_fund_monitor_task, task_id)
    return {"status": "accepted", "task_id": task_id, "message": "基金监控任务已提交"}


async def _run_fund_monitor_task(task_id: str):
    """执行基金监控任务。"""
    try:
        _task_store[task_id]["status"] = "running"
        await _persist_task(task_id, "running", "fund_monitor")
        monitor = FundMonitor(_fund_monitor_config)
        result = await monitor.run_monitor()

        if result.get("status") == "success":
            # 保存本地报告
            output_dir = Path("./data/fund_monitor")
            output_dir.mkdir(parents=True, exist_ok=True)
            output_file = output_dir / f"monitor_{result.get('date', date.today().isoformat())}.json"
            with open(output_file, "w") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)

            # 发送飞书通知
            if settings.FEISHU_CHAT_ID:
                from services.feishu_service import send_card_message, get_tenant_token
                await get_tenant_token()
                card = build_fund_monitor_card(result)
                await send_card_message(settings.FEISHU_CHAT_ID, card)

            _task_store[task_id] = {"status": "completed", "type": "fund_monitor", "result": result}
            await _persist_task(task_id, "completed", "fund_monitor", result="success")
        else:
            _task_store[task_id] = {"status": "failed", "type": "fund_monitor", "error": result.get("message")}
            await _persist_task(task_id, "failed", "fund_monitor", error=result.get("message", ""))
    except Exception as e:
        _task_store[task_id] = {"status": "failed", "type": "fund_monitor", "error": str(e)}
        await _persist_task(task_id, "failed", "fund_monitor", error=str(e))
        logger.error(f"Fund monitor task failed: {e}", exc_info=True)


@app.get("/api/fund-monitor/config")
async def get_fund_monitor_config():
    """获取基金监控配置（敏感信息除外）。"""
    return {
        "fund_code": _fund_monitor_config.fund_code,
        "fund_name": _fund_monitor_config.fund_name,
        "base_investment": _fund_monitor_config.base_investment,
        "has_cost_info": _fund_monitor_config.cost_price is not None,
        "thresholds": {
            "daily_drop_triggers": [
                _fund_monitor_config.daily_drop_trigger_3,
                _fund_monitor_config.daily_drop_trigger_5,
                _fund_monitor_config.daily_drop_trigger_8,
                _fund_monitor_config.daily_drop_trigger_10,
            ],
            "daily_rise_triggers": [
                _fund_monitor_config.daily_rise_trigger_3,
                _fund_monitor_config.daily_rise_trigger_5,
                _fund_monitor_config.daily_rise_trigger_8,
            ],
            "profit_targets": [
                _fund_monitor_config.profit_50_pct,
                _fund_monitor_config.profit_100_pct,
                _fund_monitor_config.profit_150_pct,
                _fund_monitor_config.profit_200_pct,
            ],
            "drawdown_triggers": [
                _fund_monitor_config.drawdown_10_pct,
                _fund_monitor_config.drawdown_15_pct,
                _fund_monitor_config.drawdown_25_pct,
            ],
            "volatility_levels": [
                _fund_monitor_config.volatility_low,
                _fund_monitor_config.volatility_medium,
                _fund_monitor_config.volatility_high,
                _fund_monitor_config.volatility_extreme,
            ],
        },
    }


@app.post("/api/fund-monitor/update-cost")
async def update_fund_monitor_cost(
    cost_price: float = Query(..., description="持仓成本价（元/份）"),
    total_investment: float = Query(..., description="总投资金额（元）"),
):
    """更新基金持仓成本信息。"""
    global _fund_monitor_config
    _fund_monitor_config.cost_price = cost_price
    _fund_monitor_config.total_investment = total_investment
    if cost_price > 0:
        _fund_monitor_config.total_shares = total_investment / cost_price
    
    # 保存到配置文件
    try:
        config_dict = _fund_monitor_config.model_dump(exclude_none=True)
        with open(_fund_monitor_cache_path, "w") as f:
            json.dump(config_dict, f, ensure_ascii=False, indent=2)
        return {"success": True, "message": "持仓成本已更新"}
    except Exception as e:
        logger.error(f"Failed to save fund monitor config: {e}")
        return {"success": False, "message": f"保存失败: {e}"}

# ── 炒股的智慧深度分析 API ──────────────────────────────

@app.post("/api/wisdom/analyze")
async def run_wisdom_analysis_api(background_tasks: BackgroundTasks):
    """手动触发「炒股的智慧」深度分析。"""
    task_id = str(uuid.uuid4())[:8]
    _task_store[task_id] = {"status": "pending", "type": "wisdom_analysis"}
    _prune_task_store()
    background_tasks.add_task(_run_wisdom_analysis_task, task_id)
    return {"status": "accepted", "task_id": task_id, "message": "深度分析任务已提交"}


async def _run_wisdom_analysis_task(task_id: str):
    """执行炒股的智慧深度分析任务。"""
    try:
        _task_store[task_id]["status"] = "running"
        await _persist_task(task_id, "running", "wisdom_analysis")
        from services.wisdom_analyzer import run_wisdom_analysis, build_wisdom_card
        result = await run_wisdom_analysis()

        if result.get("status") == "skipped":
            _task_store[task_id] = {"status": "completed", "type": "wisdom_analysis",
                                    "result": "skipped", "reason": "市场平静，无需深度分析"}
            await _persist_task(task_id, "completed", "wisdom_analysis", result="skipped")
            # 跳过时也通知用户
            if settings.FEISHU_CHAT_ID:
                from services.feishu_service import send_card_message, get_tenant_token
                await get_tenant_token()
                skip_card = {
                    "header": {"template": "blue", "title": {"tag": "plain_text", "content": "🧠 炒股的智慧 · 平静模式"}},
                    "elements": [{"tag": "markdown", "content": "今日市场平稳，未触发深度分析条件。\n> 市场无重大异动，保持耐心即可。"}],
                }
                await send_card_message(settings.FEISHU_CHAT_ID, skip_card)
            return

        analysis = result.get("analysis", "")
        triggers = result.get("triggers", {})

        # 推送飞书卡片
        if settings.FEISHU_CHAT_ID and analysis:
            from services.feishu_service import send_card_message, get_tenant_token
            await get_tenant_token()
            card = build_wisdom_card(analysis, triggers)
            await send_card_message(settings.FEISHU_CHAT_ID, card)

        _task_store[task_id] = {"status": "completed", "type": "wisdom_analysis",
                                "triggers": triggers}
        await _persist_task(task_id, "completed", "wisdom_analysis", result="success")
        logger.info("Wisdom analysis completed and pushed")
    except Exception as e:
        _task_store[task_id] = {"status": "failed", "type": "wisdom_analysis", "error": str(e)}
        await _persist_task(task_id, "failed", "wisdom_analysis", error=str(e))
        logger.error(f"Wisdom analysis failed: {e}", exc_info=True)


# ── 应用启动时的 loguru 日志轮转配置 ──

import sys as _sys
# 仅在首次导入时配置 loguru 轮转
_loguru_configured = getattr(logger, "_rotation_configured", False)
if not _loguru_configured:
    logger.remove()
    logger.add(
        _sys.stderr,
        colorize=True,
        format="<green>{time:HH:mm:ss}</green> [<level>{level}</level>] <level>{message}</level>",
        level="INFO",
    )
    logger.add(
        settings.LOG_DIR + "/mingce_{time:YYYYMMDD}.log",
        rotation="10 MB",
        retention="30 days",
        compression="gz",
        encoding="utf-8",
        level="DEBUG",
        backtrace=True,
        diagnose=False,
    )
    logger._rotation_configured = True
