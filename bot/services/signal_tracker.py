"""信号生命周期追踪服务 — 记录、评估、统计信号准确率。

信号生命周期：
1. 产生（active）：策略给出 BUY/SELL 信号时记录
2. 评估（evaluated）：7 日后自动回测，30 日后统计胜率
3. 结束（closed）：命中目标 / 触发止损 / 过期

使用方式:
    from services.signal_tracker import SignalTracker
    tracker = SignalTracker()
    await tracker.record_signal(symbol, direction, confidence, entry_price, ...)
    await tracker.evaluate_active_signals()  # 定时任务调用
    stats = await tracker.get_accuracy_stats(days=30)
"""

import asyncio
import json
import uuid
from datetime import datetime, date, timedelta
from typing import Optional
from loguru import logger

from core.database import get_db


class SignalTracker:
    """信号生命周期追踪器。"""

    # 信号评估周期
    EVALUATE_AFTER_DAYS = 7   # 7 日后开始评估
    EXPIRE_AFTER_DAYS = 30    # 30 日后强制结束
    TARGET_RETURN_PCT = 5.0   # 目标收益率 5%
    STOP_LOSS_PCT = -3.0      # 止损收益率 -3%

    async def record_signal(
        self,
        symbol: str,
        direction: str,
        confidence: float,
        entry_price: float,
        strategy_source: str = "fusion",
        market_regime: str = "neutral",
        target_price: Optional[float] = None,
        stop_loss: Optional[float] = None,
        signal_date: Optional[str] = None,
    ) -> str:
        """记录一个新信号。

        Returns:
            signal_id（uuid）
        """
        signal_id = str(uuid.uuid4())[:8]
        signal_date = signal_date or date.today().isoformat()

        # 如果没有提供目标价/止损价，按默认比例计算
        if target_price is None and entry_price > 0:
            if direction == "BUY":
                target_price = entry_price * (1 + self.TARGET_RETURN_PCT / 100)
            elif direction == "SELL":
                target_price = entry_price * (1 - self.TARGET_RETURN_PCT / 100)

        if stop_loss is None and entry_price > 0:
            if direction == "BUY":
                stop_loss = entry_price * (1 + self.STOP_LOSS_PCT / 100)
            elif direction == "SELL":
                stop_loss = entry_price * (1 - self.STOP_LOSS_PCT / 100)

        db = await get_db()
        await db.execute(
            """INSERT INTO signal_lifecycle
               (signal_id, symbol, signal_date, direction, confidence,
                entry_price, strategy_source, market_regime,
                status, target_price, stop_loss)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)""",
            (signal_id, symbol, signal_date, direction, confidence,
             entry_price, strategy_source, market_regime,
             target_price, stop_loss),
        )

        logger.info(
            f"📊 信号记录: {symbol} {direction} @ {entry_price} "
            f"(置信度={confidence:.2f}, 目标={target_price}, 止损={stop_loss})"
        )
        return signal_id

    async def evaluate_active_signals(self) -> dict:
        """评估所有活跃信号（定时任务调用，建议每日收盘后）。

        Returns:
            {"evaluated": N, "hit_target": N, "hit_stop": N, "expired": N}
        """
        db = await get_db()
        today = date.today()

        # 查询所有活跃信号
        rows = await db.fetchall(
            """SELECT * FROM signal_lifecycle
               WHERE status = 'active'
               ORDER BY signal_date ASC""",
        )

        stats = {"evaluated": 0, "hit_target": 0, "hit_stop": 0, "expired": 0}

        for row in rows:
            signal = dict(row)
            signal_date_obj = datetime.strptime(signal["signal_date"], "%Y-%m-%d").date()
            holding_days = (today - signal_date_obj).days

            # 获取当前价格（通过 decision_engine 的 fetch_stock_data）
            current_price = await self._get_current_price(signal["symbol"])
            if current_price <= 0:
                continue

            entry_price = signal["entry_price"]
            direction = signal["direction"]

            # 计算收益率
            if direction == "BUY":
                return_pct = (current_price - entry_price) / entry_price * 100
            elif direction == "SELL":
                return_pct = (entry_price - current_price) / entry_price * 100
            else:
                continue  # HOLD 信号不追踪

            stats["evaluated"] += 1

            # 判断是否命中目标 / 止损
            target_price = signal.get("target_price")
            stop_loss = signal.get("stop_loss")

            hit_target = False
            hit_stop = False

            if direction == "BUY":
                if target_price and current_price >= target_price:
                    hit_target = True
                elif stop_loss and current_price <= stop_loss:
                    hit_stop = True
            elif direction == "SELL":
                if target_price and current_price <= target_price:
                    hit_target = True
                elif stop_loss and current_price >= stop_loss:
                    hit_stop = True

            # 过期判断
            expired = holding_days >= self.EXPIRE_AFTER_DAYS

            # 更新状态
            new_status = "active"
            if hit_target:
                new_status = "hit_target"
                stats["hit_target"] += 1
            elif hit_stop:
                new_status = "hit_stop"
                stats["hit_stop"] += 1
            elif expired:
                new_status = "expired"
                stats["expired"] += 1

            if new_status != "active":
                await db.execute(
                    """UPDATE signal_lifecycle
                       SET status = ?, exit_price = ?, exit_date = ?,
                           holding_days = ?, return_pct = ?,
                           hit_target = ?, hit_stop = ?,
                           evaluated_at = ?, updated_at = ?
                       WHERE signal_id = ?""",
                    (new_status, current_price, today.isoformat(),
                     holding_days, round(return_pct, 2),
                     1 if hit_target else 0, 1 if hit_stop else 0,
                     datetime.now().isoformat(), datetime.now().isoformat(),
                     signal["signal_id"]),
                )
            else:
                # 仍然活跃，更新持有天数和当前收益
                await db.execute(
                    """UPDATE signal_lifecycle
                       SET holding_days = ?, return_pct = ?, updated_at = ?
                       WHERE signal_id = ?""",
                    (holding_days, round(return_pct, 2),
                     datetime.now().isoformat(), signal["signal_id"]),
                )

        logger.info(f"📊 信号评估完成: {stats}")
        return stats

    async def _get_current_price(self, symbol: str) -> float:
        """获取当前价格（异步，避免阻塞）"""
        try:
            # 用线程池调用同步函数
            from services.decision_engine import fetch_stock_data
            df = await asyncio.to_thread(fetch_stock_data, symbol, 5)
            if df is not None and not df.empty:
                return float(df.iloc[-1]["close"])
        except Exception as e:
            logger.debug(f"获取 {symbol} 当前价格失败: {e}")
        return 0.0

    async def get_accuracy_stats(self, days: int = 30) -> dict:
        """获取信号准确率统计。

        Args:
            days: 统计周期（天）

        Returns:
            {
                "total_signals": N,
                "closed_signals": N,
                "hit_target_count": N,
                "hit_stop_count": N,
                "expired_count": N,
                "win_rate": %,  # 命中目标 / 已结束
                "avg_return_pct": %,
                "avg_holding_days": N,
                "by_direction": {"BUY": {...}, "SELL": {...}},
            }
        """
        db = await get_db()
        start_date = (date.today() - timedelta(days=days)).isoformat()

        rows = await db.fetchall(
            """SELECT * FROM signal_lifecycle
               WHERE signal_date >= ?
               ORDER BY signal_date DESC""",
            (start_date,),
        )

        if not rows:
            return {
                "total_signals": 0, "closed_signals": 0,
                "hit_target_count": 0, "hit_stop_count": 0, "expired_count": 0,
                "win_rate": 0, "avg_return_pct": 0, "avg_holding_days": 0,
                "by_direction": {},
            }

        signals = [dict(r) for r in rows]
        total = len(signals)
        closed = [s for s in signals if s["status"] != "active"]
        hit_target = [s for s in closed if s["status"] == "hit_target"]
        hit_stop = [s for s in closed if s["status"] == "hit_stop"]
        expired = [s for s in closed if s["status"] == "expired"]

        win_rate = len(hit_target) / len(closed) * 100 if closed else 0
        avg_return = sum(s.get("return_pct", 0) or 0 for s in closed) / len(closed) if closed else 0
        avg_holding = sum(s.get("holding_days", 0) or 0 for s in closed) / len(closed) if closed else 0

        # 按方向统计
        by_direction = {}
        for direction in ("BUY", "SELL"):
            dir_signals = [s for s in closed if s["direction"] == direction]
            if dir_signals:
                dir_hit = len([s for s in dir_signals if s["status"] == "hit_target"])
                by_direction[direction] = {
                    "total": len(dir_signals),
                    "hit_target": dir_hit,
                    "win_rate": round(dir_hit / len(dir_signals) * 100, 1),
                    "avg_return": round(sum(s.get("return_pct", 0) or 0 for s in dir_signals) / len(dir_signals), 2),
                }

        return {
            "total_signals": total,
            "closed_signals": len(closed),
            "active_signals": total - len(closed),
            "hit_target_count": len(hit_target),
            "hit_stop_count": len(hit_stop),
            "expired_count": len(expired),
            "win_rate": round(win_rate, 1),
            "avg_return_pct": round(avg_return, 2),
            "avg_holding_days": round(avg_holding, 1),
            "by_direction": by_direction,
            "period_days": days,
        }

    async def get_recent_signals(self, limit: int = 20) -> list:
        """获取最近的信号列表"""
        db = await get_db()
        rows = await db.fetchall(
            """SELECT signal_id, symbol, signal_date, direction, confidence,
                      entry_price, status, return_pct, holding_days,
                      target_price, stop_loss
               FROM signal_lifecycle
               ORDER BY signal_date DESC, created_at DESC
               LIMIT ?""",
            (limit,),
        )
        return [dict(r) for r in rows]


# 单例
_tracker: Optional[SignalTracker] = None


def get_signal_tracker() -> SignalTracker:
    global _tracker
    if _tracker is None:
        _tracker = SignalTracker()
    return _tracker
