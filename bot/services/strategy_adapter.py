"""策略信号适配器 — HTTP 调用（优先）+ subprocess 回退。

market-daily-bot 与 MakingMoney 位于不同 venv，因此不能直接 import。
此适配器默认通过 HTTP 调用 MakingMoney 的信号服务（signal_service），
如果 HTTP 调用失败则回退到 subprocess 方式。

使用方式:
    adapter = StrategySignalAdapter()
    signals = adapter.get_signals(["SZ002594", "SH600519"])
    all_signals = adapter.get_all_signals()

环境变量:
    SIGNAL_SERVICE_URL  — 信号服务地址（默认 http://127.0.0.1:8765）
    SIGNAL_SERVICE_TIMEOUT — HTTP 请求超时秒数（默认 30）
    FALLBACK_MODE       — 设为 "1" 或 "true" 强制使用 subprocess 回退模式
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

from loguru import logger

# ── HTTP 模式配置 ──────────────────────────────────────
_SIGNAL_SERVICE_URL = os.environ.get(
    "SIGNAL_SERVICE_URL", "http://127.0.0.1:8765"
)
_SIGNAL_SERVICE_TIMEOUT = int(os.environ.get("SIGNAL_SERVICE_TIMEOUT", "30"))
_FALLBACK_MODE = os.environ.get("FALLBACK_MODE", "").lower() in ("1", "true", "yes")

# ── subprocess 回退路径配置 ────────────────────────────
_MAKINGMONEY_DIR_ENV = os.environ.get("MAKINGMONEY_DIR", "")
if _MAKINGMONEY_DIR_ENV:
    _MAKINGMONEY_DIR = Path(_MAKINGMONEY_DIR_ENV)
else:
    _MAKINGMONEY_DIR = Path(__file__).resolve().parent.parent / "MakingMoney"
_ENTRY_SCRIPT = _MAKINGMONEY_DIR / "get_strategy_signals.py"
_MAKINGMONEY_PYTHON = str(_MAKINGMONEY_DIR / "venv" / "bin" / "python")

# 兜底：如果 venv 的 python 不存在，尝试系统 python
if not Path(_MAKINGMONEY_PYTHON).exists():
    _MAKINGMONEY_PYTHON = sys.executable
    logger.warning(
        f"MakingMoney venv python not found at {_MAKINGMONEY_PYTHON}, "
        f"using current interpreter"
    )


class StrategySignalAdapter:
    """策略信号适配器 — HTTP 调用（优先）+ subprocess 回退"""

    def __init__(self, timeout: int = 60):
        self.timeout = timeout
        self._client: Optional["httpx.AsyncClient"] = None
        self._http_mode = not _FALLBACK_MODE
        if _FALLBACK_MODE:
            logger.info("策略信号适配器: 强制使用 subprocess 回退模式 (FALLBACK_MODE=1)")
        else:
            logger.info(
                f"策略信号适配器: HTTP 模式 (服务地址: {_SIGNAL_SERVICE_URL}, "
                f"超时: {_SIGNAL_SERVICE_TIMEOUT}s)"
            )
        self._check_entrypoint()

    def _check_entrypoint(self) -> bool:
        """确保 subprocess 回退入口脚本存在"""
        if not _ENTRY_SCRIPT.exists():
            logger.warning(f"MakingMoney 策略入口不存在: {_ENTRY_SCRIPT}")
            return False
        return True

    # ── HTTP 调用 ──────────────────────────────────────

    def _run_http_sync(self, symbols: list[str]) -> Optional[dict]:
        """通过 HTTP 调用信号服务（同步封装）"""
        try:
            import httpx

            payload = {"symbols": symbols}
            with httpx.Client(timeout=_SIGNAL_SERVICE_TIMEOUT) as client:
                resp = client.post(
                    f"{_SIGNAL_SERVICE_URL}/analyze",
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
                logger.debug(
                    f"HTTP 信号服务返回 {len(data.get('results', {}))} 只股票结果"
                )
                return data
        except Exception as e:
            logger.warning(f"HTTP 调用信号服务失败: {e}")
            return None

    def _run_http_all_sync(self) -> Optional[dict]:
        """通过 HTTP 获取所有自选股信号（实际调用 analyze 后由 adapter 组装）"""
        try:
            import httpx

            with httpx.Client(timeout=_SIGNAL_SERVICE_TIMEOUT) as client:
                # 先获取自选股列表
                symbols = self._get_watchlist_from_signals()
                if not symbols:
                    logger.warning("无法获取自选股列表，HTTP 模式回退到 subprocess")
                    return None
                return self._run_http_sync(symbols)
        except Exception as e:
            logger.warning(f"HTTP 获取全部信号失败: {e}")
            return None

    def _get_watchlist_from_signals(self) -> list[str]:
        """尝试从信号服务获取自选股列表"""
        try:
            import httpx

            # 先尝试调用 --list 风格的接口通过 health 获取信息
            # 实际使用：直接返回常用自选股（策略服务目前不暴露 list 接口）
            # 改为从 portfolio.db 读取
            portfolio_db = _MAKINGMONEY_DIR.parent / "news/market-daily-bot/data/portfolio.db"
            if portfolio_db.exists():
                import sqlite3
                conn = sqlite3.connect(str(portfolio_db))
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT symbol FROM watchlist WHERE active = 1"
                ).fetchall()
                conn.close()
                if rows:
                    return [r["symbol"] for r in rows]
        except Exception as e:
            logger.debug(f"读取自选股列表失败: {e}")

        # 默认自选股
        return ["SZ002594", "SH600519", "SZ300750"]

    # ── subprocess 调用（回退） ─────────────────────────

    def _run_subprocess(self, *args) -> Optional[dict]:
        """通过 subprocess 调用 MakingMoney 入口脚本（回退路径）"""
        if not self._check_entrypoint():
            return None

        cmd = [_MAKINGMONEY_PYTHON, str(_ENTRY_SCRIPT)] + list(args)
        logger.debug(f"[subprocess] Running: {' '.join(cmd)}")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                cwd=str(_MAKINGMONEY_DIR),
            )
        except subprocess.TimeoutExpired:
            logger.error(f"[subprocess] MakingMoney 策略分析超时 ({self.timeout}s)")
            return None
        except Exception as e:
            logger.error(f"[subprocess] MakingMoney 调用失败: {e}")
            return None

        if result.returncode != 0:
            logger.error(
                f"[subprocess] MakingMoney 进程退出码 {result.returncode}: "
                f"{result.stderr[:500]}"
            )
            return None

        # 记录 stderr 日志（策略日志输出到 stderr）
        if result.stderr:
            for line in result.stderr.strip().split("\n"):
                if line.strip():
                    logger.debug(f"[MakingMoney] {line.strip()}")

        # 解析 stdout JSON
        try:
            data = json.loads(result.stdout)
            return data
        except json.JSONDecodeError as e:
            logger.error(f"[subprocess] MakingMoney JSON 解析失败: {e}")
            logger.debug(f"[subprocess] Raw stdout: {result.stdout[:1000]}")
            return None

    # ── 统一入口（HTTP 优先，subprocess 回退） ───────────

    def _run(self, *args) -> Optional[dict]:
        """运行策略分析

        HTTP 模式（默认）: 通过 POST /analyze 调用信号服务
        subprocess 回退:  调用 get_strategy_signals.py 入口脚本

        自动检测参数格式：
        - 单个参数 "SZ002594,SH600519" → 多只股票
        - 单个参数 "SZ002594" → 单只股票
        - 参数 "--list" → 全部自选股
        """
        if _FALLBACK_MODE:
            logger.debug("使用 subprocess 回退模式")
            return self._run_subprocess(*args)

        # 解析参数，组织 HTTP 请求
        symbols: list[str] = []
        is_list_mode = False

        for arg in args:
            if arg == "--list":
                is_list_mode = True
            elif "," in arg:
                symbols.extend(s.strip() for s in arg.split(",") if s.strip())
            else:
                symbols.append(arg)

        if is_list_mode or not symbols:
            # 获取全部自选股信号
            watchlist = self._get_watchlist_from_signals()
            if not watchlist:
                logger.warning("无自选股列表，回退到 subprocess")
                return self._run_subprocess(*args)
            http_result = self._run_http_sync(watchlist)
            if http_result is not None:
                logger.info("✅ 使用 HTTP 模式获取全部信号成功")
                return self._format_list_response(http_result)
            logger.warning("HTTP 模式获取全部信号失败，回退到 subprocess")
            return self._run_subprocess(*args)

        # 指定股票列表
        http_result = self._run_http_sync(symbols)
        if http_result is not None:
            logger.info(f"✅ 使用 HTTP 模式分析 {len(symbols)} 只股票成功")
            return self._format_analyze_response(http_result, symbols)
        logger.warning("HTTP 模式分析失败，回退到 subprocess")
        return self._run_subprocess(*args)

    def _format_analyze_response(
        self, http_data: dict, symbols: list[str]
    ) -> dict:
        """将 HTTP /analyze 响应格式化为与 subprocess 输出兼容的格式"""
        results = http_data.get("results", {})

        if len(symbols) == 1:
            # 单只股票格式
            sym = symbols[0]
            single = results.get(sym, {})
            if single and "error" not in single:
                return single
            return single

        # 多只股票格式
        return {
            "results": [
                r for r in results.values() if "error" not in r
            ]
        }

    def _format_list_response(self, http_data: dict) -> dict:
        """将 HTTP /analyze 响应格式化为 list 兼容格式"""
        from datetime import datetime

        results = http_data.get("results", {})
        return {
            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "symbols": results,
            "total_symbols": len(results),
        }

    # ── 公开接口（保持兼容） ────────────────────────────

    def get_signals(self, symbols: list[str]) -> dict:
        """获取指定股票列表的策略信号

        Args:
            symbols: 股票代码列表，如 ["SZ002594", "SH600519"]

        Returns:
            dict: {symbol: signal_data, ...}
        """
        if not symbols:
            return {}

        # 多个股票用逗号合并（与 subprocess 入口兼容）
        symbols_str = ",".join(symbols)
        result = self._run(symbols_str)

        if result is None:
            return {}

        # 单只股票
        if "symbol" in result and "all_signals" in result:
            return {result["symbol"]: result}

        # 多只股票
        if "results" in result:
            return {r["symbol"]: r for r in result["results"] if "error" not in r}

        return result

    def get_all_signals(self) -> dict:
        """获取所有自选股的策略信号

        Returns:
            dict: {"symbols": {symbol: data}, "date": ..., "total_symbols": N}
        """
        result = self._run("--list")
        if result is None:
            return {"symbols": {}, "date": "", "total_symbols": 0}

        return result

    def format_signals_for_markdown(self, signals: dict) -> str:
        """将策略信号格式化为 Markdown 文本（用于飞书卡片）"""
        if not signals or not signals.get("symbols"):
            return "暂无策略信号数据"

        parts = [f"## 🎯 自选股策略信号"]
        parts.append(f"📅 更新: {signals.get('date', '')}")
        parts.append("")

        symbols = signals.get("symbols", {})
        for sym, data in symbols.items():
            if "error" in data:
                parts.append(
                    f"**{data.get('stock_name', sym)}** ({sym}) — ❌ {data['error']}"
                )
                continue

            stock_name = data.get("stock_name", sym)
            price = data.get("price", 0)
            change_pct = data.get("change_pct", 0)
            change_icon = "🟢" if change_pct >= 0 else "🔴"
            buy_n = data.get("buy_count", 0)
            sell_n = data.get("sell_count", 0)

            parts.append(f"**{stock_name}** ({sym})")
            parts.append(f"{change_icon} {price:.2f} ({change_pct:+.2f}%)")

            # 买卖信号汇总
            signal_summary = []
            if buy_n > 0:
                signal_summary.append(f"🟢买入{buy_n}")
            if sell_n > 0:
                signal_summary.append(f"🔴卖出{sell_n}")
            if signal_summary:
                parts.append("  " + " | ".join(signal_summary))

            # 买入信号详情
            buy_signals = data.get("buy_signals", [])
            for sig in buy_signals[:5]:
                strength = sig.get("signal_strength", 0)
                bar = (
                    "▓" * min(int(strength * 10), 10)
                    + "░" * (10 - min(int(strength * 10), 10))
                )
                parts.append(f"  🟢 {sig['strategy_name']} {bar} {strength:.0%}")

            # 卖出信号详情
            sell_signals = data.get("sell_signals", [])
            for sig in sell_signals[:5]:
                strength = sig.get("signal_strength", 0)
                bar = (
                    "▓" * min(int(strength * 10), 10)
                    + "░" * (10 - min(int(strength * 10), 10))
                )
                parts.append(f"  🔴 {sig['strategy_name']} {bar} {strength:.0%}")

            # 综合建议
            net_signal = buy_n - sell_n
            if net_signal > 2:
                parts.append("  ✅ **综合: 偏多**")
            elif net_signal < -2:
                parts.append("  ⚠️ **综合: 偏空**")
            else:
                parts.append("  ➖ **综合: 中性**")

            parts.append("")

        total = signals.get("total_symbols", 0)
        parts.append(f"---\n📊 共扫描 {total} 只股票 | {len(symbols)} 项有数据")
        parts.append("*以上信号基于 18 个核心策略，仅供参考*")

        return "\n".join(parts)


# 全局单例
_adapter: Optional[StrategySignalAdapter] = None


def get_adapter() -> StrategySignalAdapter:
    """获取全局适配器单例"""
    global _adapter
    if _adapter is None:
        _adapter = StrategySignalAdapter()
    return _adapter
