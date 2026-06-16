"""API v1 路由 — 明策系统新版 API 入口。

所有 v1 端点保持与 main.py 中旧版端点相同的功能实现，
通过直接 import 旧版函数来复用业务逻辑。
"""
import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request

router = APIRouter(prefix="/v1", tags=["v1"])


# ── 日报 API ──────────────────────────────────────────


@router.post("/report/generate")
async def v1_manual_generate(
    background_tasks: BackgroundTasks,
    version: str = Query("close", description="报告版本: morning/noon/close"),
):
    """手动触发日报生成并推送（v1 版本）。"""
    # 延迟导入，复用 main.py 中的任务存储和执行函数
    from app.main import _task_store, _prune_task_store, _run_generate_and_push

    task_id = str(uuid.uuid4())[:8]
    _task_store[task_id] = {"status": "pending", "version": version}
    _prune_task_store()
    background_tasks.add_task(_run_generate_and_push, task_id, version)
    return {"status": "accepted", "task_id": task_id, "version": version, "message": "日报生成任务已提交"}


# ── 策略信号 API ──────────────────────────────────────


@router.get("/strategy-signals")
async def v1_get_strategy_signals(
    symbol: str = Query(None, description="股票代码，如 SZ002594。不传则返回所有自选股"),
    background_tasks: BackgroundTasks = None,
):
    """获取 MakingMoney 策略信号（v1 版本）。"""
    from app.main import get_adapter

    adapter = get_adapter()
    if symbol:
        result = adapter.get_signals([symbol])
        if result:
            data = result.get(symbol, result)
            return {"success": True, "data": data, "symbol": symbol}
        return {"success": False, "error": f"无法获取 {symbol} 的策略信号"}
    else:
        result = adapter.get_all_signals()
        if result and result.get("symbols"):
            return {
                "success": True,
                "symbols": result["symbols"],
                "total": result.get("total_symbols", 0),
                "date": result.get("date", ""),
            }
        return {"success": False, "error": "无法获取策略信号"}


@router.post("/strategy-signals/batch")
async def v1_batch_strategy_signals(request: Request):
    """批量获取多个股票的策略信号（v1 版本）。"""
    from app.main import get_adapter

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


@router.post("/strategy-signals/push")
async def v1_push_strategy_signals(
    background_tasks: BackgroundTasks,
    version: str = Query("opening", description="opening / early / morning / noon / close"),
):
    """手动触发策略信号推送（v1 版本）。"""
    from app.main import _task_store, _prune_task_store, _run_push_strategy_signals

    task_id = str(uuid.uuid4())[:8]
    _task_store[task_id] = {"status": "pending", "type": "strategy_signals_push", "version": version}
    _prune_task_store()
    background_tasks.add_task(_run_push_strategy_signals, task_id, version)
    return {"status": "accepted", "task_id": task_id, "version": version, "message": "策略信号推送任务已提交"}


# ── 任务状态 API ──────────────────────────────────


@router.get("/task/{task_id}")
async def v1_get_task_status(task_id: str):
    """查询异步任务状态（v1 版本）。"""
    from app.main import _task_store

    task = _task_store.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task
