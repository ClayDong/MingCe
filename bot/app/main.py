"""FastAPI 应用入口 — 定时任务 + HTTP API。

每天 08:00(early) / 09:10(morning) / 11:35(noon) / 15:10(close)
自动生成并推送市场日报。15:35 基金监控。
提供手动触发、健康检查、缓存管理等管理接口。
"""

# 中国法定节假日（A股休市日）
_CHINESE_HOLIDAYS: set[str] = {
    # 2026年
    "2026-01-01",  # 元旦
    "2026-01-28", "2026-01-29", "2026-01-30",
    "2026-01-31", "2026-02-01", "2026-02-02", "2026-02-03",  # 春节
    "2026-04-04", "2026-04-05", "2026-04-06",  # 清明节
    "2026-05-01", "2026-05-02", "2026-05-03", "2026-05-04", "2026-05-05",  # 劳动节
    "2026-06-25", "2026-06-26", "2026-06-27",  # 端午节
    "2026-10-01", "2026-10-02", "2026-10-03",
    "2026-10-04", "2026-10-05", "2026-10-06", "2026-10-07",  # 国庆+中秋
}

import json
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

_task_store: dict[str, dict] = {}
_MAX_TASKS = 100


def _prune_task_store():
    """清理超出限制的旧任务记录。"""
    while len(_task_store) > _MAX_TASKS:
        _task_store.pop(next(iter(_task_store)))


# ── 调度任务 ──────────────────────────────────────────────

async def scheduled_report(version: str):
    """定时任务：生成并推送日报。"""
    logger.info(f"Scheduled report triggered: {version}")
    task_id = f"sched_{version}_{date.today().isoformat()}"
    _task_store[task_id] = {"status": "running", "version": version}
    _prune_task_store()
    try:
        data = await generate_daily_report(version)
        await push_daily_report(data)
        _task_store[task_id] = {"status": "completed", "version": version}
        logger.info(f"Scheduled report {version} completed")
    except Exception as e:
        _task_store[task_id] = {"status": "failed", "version": version, "error": str(e)}
        logger.error(f"Scheduled report {version} failed: {e}", exc_info=True)
        await send_alert(
            f"📰 日报 [{version}] 生成失败\n```\n{str(e)[:300]}\n```",
            level="error",
        )


async def scheduled_fund_monitor():
    """定时任务：基金监控。"""
    logger.info("Scheduled fund monitor triggered")
    task_id = f"fund_monitor_{date.today().isoformat()}"
    _task_store[task_id] = {"status": "running", "type": "fund_monitor"}
    _prune_task_store()
    try:
        monitor = FundMonitor(_fund_monitor_config)
        result = monitor.run_monitor()
        
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
    scheduler.start()
    logger.info("Scheduler started: 08:00(early) / 09:10(morning) / 11:35(noon) / 15:10(close) / 15:35(fund_monitor) / 五维框架 v2.0")

    yield

    scheduler.shutdown(wait=False)
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


@app.get("/health")
async def health():
    """健康检查接口。"""
    db_ok = False
    try:
        db = await get_db()
        await db.fetchone("SELECT 1")
        db_ok = True
    except Exception:
        pass
    return {
        "status": "ok" if db_ok else "degraded",
        "timestamp": datetime.now().isoformat(),
        "db": "connected" if db_ok else "disconnected",
        "scheduler": "running" if scheduler.running else "stopped",
        "version": settings.VERSION,
    }


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
        result = adapter.get_signals([symbol])
        if result:
            # 返回单只股票数据
            data = result.get(symbol, result)
            return {"success": True, "data": data, "symbol": symbol}
        return {"success": False, "error": f"无法获取 {symbol} 的策略信号"}
    else:
        result = adapter.get_all_signals()
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
    result = adapter.get_signals(symbols)
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
        adapter = get_adapter()
        signals_data = adapter.get_all_signals()
        if signals_data and signals_data.get("symbols"):
            from services.feishu_service import send_card_message, get_tenant_token
            await get_tenant_token()
            card = build_strategy_signals_card(signals_data, version=version)
            ok = await send_card_message(settings.FEISHU_CHAT_ID, card)
            if ok:
                _task_store[task_id] = {"status": "completed", "type": "strategy_signals_push",
                                        "stocks": len(signals_data.get("symbols", {}))}
            else:
                _task_store[task_id] = {"status": "failed", "type": "strategy_signals_push", "error": "send failed"}
        else:
            _task_store[task_id] = {"status": "failed", "type": "strategy_signals_push", "error": "no signal data"}
    except Exception as e:
        _task_store[task_id] = {"status": "failed", "type": "strategy_signals_push", "error": str(e)}
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
        data = await generate_daily_report(version)
        await push_daily_report(data)
        _task_store[task_id]["status"] = "completed"
    except Exception as e:
        _task_store[task_id]["status"] = "failed"
        _task_store[task_id]["error"] = str(e)
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
            "content": json.loads(row["content"]),
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
        monitor = FundMonitor(_fund_monitor_config)
        result = monitor.run_monitor()
        
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
        else:
            _task_store[task_id] = {"status": "failed", "type": "fund_monitor", "error": result.get("message")}
    except Exception as e:
        _task_store[task_id] = {"status": "failed", "type": "fund_monitor", "error": str(e)}
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
