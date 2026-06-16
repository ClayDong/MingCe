#!/usr/bin/env python3
"""
MakingMoney 策略信号 HTTP 微服务
=====================================
暴露 RESTful API 供 market-daily-bot 通过 HTTP 调用，
替代原有的 subprocess 调用方式。

启动:
    uvicorn signal_service:app --host 127.0.0.1 --port 8765

接口:
    POST /analyze  — 策略信号分析
    POST /health   — 健康检查
"""

import asyncio
import json
import sys
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException
from loguru import logger
from pydantic import BaseModel, Field

# ── 确保可从项目根目录导入 ────────────────────────────
PROJECT_ROOT = str(Path(__file__).parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# ── 请求/响应模型 ─────────────────────────────────────


class AnalyzeRequest(BaseModel):
    symbols: list[str] = Field(
        ..., description="股票代码列表，例如 ['SZ002594', 'SH600519']"
    )


class AnalyzeResponse(BaseModel):
    results: dict[str, dict]


class HealthResponse(BaseModel):
    status: str
    version: str
    strategies_loaded: int


# ── 缓存 ──────────────────────────────────────────────
# {symbol: (timestamp, data)}
_cache: dict[str, tuple[float, dict]] = {}
_CACHE_TTL = 300  # 5 分钟


def _get_cached(symbol: str) -> Optional[dict]:
    """读取缓存（如果未过期）"""
    entry = _cache.get(symbol)
    if entry is None:
        return None
    ts, data = entry
    if time.time() - ts > _CACHE_TTL:
        del _cache[symbol]
        return None
    return data


def _set_cache(symbol: str, data: dict):
    """写入缓存"""
    _cache[symbol] = (time.time(), data)


# ── 策略分析引擎（懒加载） ──────────────────────────

_engine_instance = None
_engine_lock = asyncio.Lock()
_STRATEGIES_LOADED = 0


async def get_engine():
    """获取/初始化策略引擎（单例，惰性加载）"""
    global _engine_instance, _STRATEGIES_LOADED
    if _engine_instance is not None:
        return _engine_instance
    async with _engine_lock:
        if _engine_instance is not None:
            return _engine_instance
        loop = asyncio.get_running_loop()
        try:
            _engine_instance = await loop.run_in_executor(
                None, _init_engine
            )
            _STRATEGIES_LOADED = _count_strategies()
            logger.info(
                f"策略引擎预热完成，已加载 {_STRATEGIES_LOADED} 个策略"
            )
        except Exception as e:
            logger.error(f"策略引擎初始化失败: {e}")
            raise
    return _engine_instance


def _init_engine():
    """同步初始化策略引擎（在 executor 中运行）"""
    from qlib_vnpy_platform.core.main_engine import MainEngine

    engine = MainEngine()
    return engine


def _count_strategies() -> int:
    """统计已加载的策略数量"""
    try:
        from qlib_vnpy_platform.core.strategies import STRATEGY_REGISTRY
        return len(STRATEGY_REGISTRY)
    except Exception:
        return 18  # 默认值


# ── 单只股票分析（同步，在 executor 中运行） ──────────


def _analyze_single(symbol: str) -> dict:
    """分析单只股票，返回信号数据（同步函数）"""
    from qlib_vnpy_platform.strategy_monitor_pkg import BaseMonitor

    stock_name = symbol
    try:
        # 尝试从 monitor 获取股票名称（通过 fetch_latest_data 的自动识别）
        monitor = BaseMonitor(symbol=symbol, stock_name=symbol)
        data = monitor.fetch_latest_data(symbol=symbol, days=60)
        if data is None or data.empty:
            return {
                "symbol": symbol,
                "stock_name": symbol,
                "error": "无法获取数据",
            }

        change, change_pct, latest_price, latest_date = monitor.compute_change(
            data
        )
        results, signals = monitor.run_strategy_analysis(data)
        buy_signals, sell_signals, hold_signals = monitor.classify_signals(
            results
        )

        return {
            "symbol": symbol,
            "stock_name": stock_name,
            "date": str(latest_date),
            "price": float(latest_price),
            "change": float(change),
            "change_pct": float(change_pct),
            "total_strategies": len(results),
            "buy_count": len(buy_signals),
            "sell_count": len(sell_signals),
            "hold_count": len(hold_signals),
            "buy_signals": list(buy_signals.values()),
            "sell_signals": list(sell_signals.values()),
            "hold_signals": list(hold_signals.values()),
            "all_signals": {
                k: {
                    "strategy_name": v.get("strategy_name"),
                    "action": v.get("action"),
                    "signal_value": v.get("signal_value"),
                    "signal_strength": v.get("signal_strength"),
                    "price": v.get("price"),
                }
                for k, v in results.items()
            },
        }
    except Exception as e:
        logger.error(f"分析 {symbol} 失败: {e}\n{traceback.format_exc()}")
        return {
            "symbol": symbol,
            "stock_name": symbol,
            "error": f"分析异常: {str(e)}",
        }


# ── FastAPI 应用 ──────────────────────────────────────

app = FastAPI(
    title="MakingMoney 策略信号服务",
    version="1.0.0",
    description="为 market-daily-bot 提供 HTTP 策略信号接口",
)


@app.on_event("startup")
async def startup_event():
    """启动时预热策略引擎"""
    logger.info("🔄 策略信号服务启动中...")
    try:
        await get_engine()
        logger.info("✅ 策略引擎预热完成")
    except Exception as e:
        logger.warning(f"⚠️ 策略引擎预热失败（服务仍可启动，首次请求会重试）: {e}")


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """健康检查端点"""
    engine_ok = _engine_instance is not None
    return HealthResponse(
        status="ok" if engine_ok else "warming_up",
        version="1.0.0",
        strategies_loaded=_STRATEGIES_LOADED,
    )


@app.post("/analyze", response_model=AnalyzeResponse)
async def analyze(request: AnalyzeRequest):
    """策略信号分析

    对指定的股票列表运行策略引擎分析，返回每只股票的完整信号数据。
    - 单只股票失败不影响其他股票
    - 相同股票 5 分钟内复用缓存
    - 单次分析超时 60 秒
    """
    symbols = request.symbols
    if not symbols:
        return AnalyzeResponse(results={})

    # 确保引擎已加载
    try:
        await get_engine()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"策略引擎未就绪: {e}")

    loop = asyncio.get_running_loop()
    results: dict[str, dict] = {}

    for symbol in symbols:
        # 检查缓存
        cached = _get_cached(symbol)
        if cached is not None:
            logger.debug(f"使用缓存结果: {symbol}")
            results[symbol] = cached
            continue

        # 异步执行分析（带超时）
        try:
            result = await asyncio.wait_for(
                loop.run_in_executor(None, _analyze_single, symbol),
                timeout=60.0,
            )
            # 仅缓存成功结果（无 error 字段）
            if "error" not in result:
                _set_cache(symbol, result)
            results[symbol] = result
        except asyncio.TimeoutError:
            logger.error(f"分析 {symbol} 超时 (60s)")
            results[symbol] = {
                "symbol": symbol,
                "stock_name": symbol,
                "error": "分析超时",
            }
        except Exception as e:
            logger.error(f"分析 {symbol} 异常: {e}")
            results[symbol] = {
                "symbol": symbol,
                "stock_name": symbol,
                "error": f"分析异常: {str(e)}",
            }

    return AnalyzeResponse(results=results)


# ── 直接运行入口 ─────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "signal_service:app",
        host="127.0.0.1",
        port=8765,
        workers=1,
        log_level="info",
    )
