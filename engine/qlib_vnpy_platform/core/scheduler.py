import threading
import time
from datetime import datetime, timedelta
from loguru import logger
from qlib_vnpy_platform.core.feishu_notifier import get_notifier, send_daily_report


class Scheduler:
    TRADING_HOURS = {
        "morning_open": (9, 15),
        "morning_close": (11, 30),
        "afternoon_open": (13, 0),
        "afternoon_close": (15, 5),
    }
    LUNCH_BREAK_START = (11, 30)
    LUNCH_BREAK_END = (13, 0)

    def __init__(self, main_engine):
        self.engine = main_engine
        self._running = False
        self._thread = None
        self._watch_list = []
        self._scan_interval = 300
        self._daily_report_time = (15, 10)
        self._last_daily_report_date = None
        self._scan_count = 0
        self._last_scan_time = None
        self._auto_trade = False

    def configure(self, watch_list=None, scan_interval=300, daily_report_time=(15, 10), auto_trade=False):
        if watch_list:
            self._watch_list = watch_list
        self._scan_interval = max(60, scan_interval)
        self._daily_report_time = daily_report_time
        self._auto_trade = auto_trade
        logger.info(f"Scheduler configured: watch={self._watch_list}, interval={self._scan_interval}s, "
                    f"report={daily_report_time}, auto_trade={auto_trade}")

    def start(self):
        if self._running:
            logger.warning("Scheduler already running")
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("Scheduler started")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Scheduler stopped")

    @property
    def is_running(self):
        return self._running

    @property
    def status(self):
        return {
            "running": self._running,
            "watch_list": self._watch_list,
            "scan_interval": self._scan_interval,
            "scan_count": self._scan_count,
            "last_scan_time": str(self._last_scan_time) if self._last_scan_time else None,
            "auto_trade": self._auto_trade,
        }

    def _is_trading_time(self):
        now = datetime.now()
        weekday = now.weekday()
        if weekday >= 5:
            return False

        h, m = now.hour, now.minute
        current = h * 60 + m

        mo_h, mo_m = self.TRADING_HOURS["morning_open"]
        mc_h, mc_m = self.TRADING_HOURS["morning_close"]
        ao_h, ao_m = self.TRADING_HOURS["afternoon_open"]
        ac_h, ac_m = self.TRADING_HOURS["afternoon_close"]

        morning = mo_h * 60 + mo_m <= current < mc_h * 60 + mc_m
        afternoon = ao_h * 60 + ao_m <= current <= ac_h * 60 + ac_m
        return morning or afternoon

    def _run_loop(self):
        logger.info("Scheduler loop started")
        while self._running:
            try:
                now = datetime.now()

                if self._is_trading_time():
                    self._scan_markets()

                self._check_daily_report(now)

            except Exception as e:
                logger.error(f"Scheduler error: {e}")

            time.sleep(min(self._scan_interval, 60))

    def _scan_markets(self):
        now = datetime.now()
        if self._last_scan_time:
            elapsed = (now - self._last_scan_time).total_seconds()
            if elapsed < self._scan_interval:
                return

        self._last_scan_time = now
        self._scan_count += 1

        current_watch_list = list(self.engine._watch_list)
        if current_watch_list != self._watch_list:
            self._watch_list = current_watch_list

        logger.info(f"Scheduler scan #{self._scan_count} for {self._watch_list}")

        for symbol in self._watch_list:
            try:
                result = self.engine.analyze_stock(
                    symbol=symbol,
                    use_llm=True,
                    use_qlib=True,
                    auto_trade=self._auto_trade,
                )

                signal = result.get("signal", {})
                direction = signal.get("direction", "HOLD")
                confidence = signal.get("confidence", 0)

                logger.info(f"Scheduler scan {symbol}: {direction} (confidence={confidence:.2f})")

                if self._auto_trade and direction in ("BUY", "SELL"):
                    risk = result.get("risk_check", {})
                    if risk.get("approved"):
                        trade = result.get("trade_result")
                        if trade and trade.get("status") == "FILLED":
                            t = trade["trade"]
                            logger.info(f"Auto-trade executed: {t['direction']} {t['symbol']} "
                                        f"{t['volume']}@{t['price']:.2f}")

            except Exception as e:
                logger.error(f"Scheduler scan error for {symbol}: {e}")

    def _check_daily_report(self, now):
        """检查是否应该发送日报 - 更可靠的机制"""
        # 周末不发送
        if now.weekday() >= 5:
            return

        rh, rm = self._daily_report_time
        target_minutes = rh * 60 + rm
        current_minutes = now.hour * 60 + now.minute

        # 如果当前时间晚于目标时间，且今日未发送，则立即发送
        today_str = now.strftime("%Y-%m-%d")
        if current_minutes >= target_minutes and self._last_daily_report_date != today_str:
            self._last_daily_report_date = today_str
            logger.info(f"⏰ 到达日报发送时间 {rh:02d}:{rm:02d}，正在生成并发送日报...")
            self._generate_daily_report()

    def _generate_daily_report(self):
        logger.info("Generating daily report...")
        status = self.engine.get_status()

        account = status["account"]
        risk = status["risk_status"]
        positions = status.get("positions", {})
        trades = status.get("recent_trades", [])

        report_lines = [
            f"=== 每日交易报告 {datetime.now().strftime('%Y-%m-%d')} ===",
            f"",
            f"[账户概览]",
            f"  总资产: {account['total_capital']:,.2f}",
            f"  可用资金: {account['cash']:,.2f}",
            f"  持仓市值: {account['position_value']:,.2f}",
            f"  总盈亏: {account['total_pnl']:,.2f} ({account['total_pnl_pct']:.2%})",
            f"",
            f"[风控状态]",
            f"  风险等级: {risk['risk_level']}",
            f"  当日盈亏: {risk['daily_pnl']:,.2f}",
            f"  熔断状态: {'已触发' if risk.get('circuit_breaker_active') else '正常'}",
        ]

        if positions:
            report_lines.append(f"")
            report_lines.append(f"[持仓明细]")
            for sym, pos in positions.items():
                pnl = (pos["current_price"] - pos["avg_cost"]) * pos["volume"]
                report_lines.append(f"  {sym}: {pos['volume']}股 @ {pos['avg_cost']:.2f}, "
                                    f"现价={pos['current_price']:.2f}, 盈亏={pnl:+,.2f}")

        if trades:
            today_trades = [t for t in trades if t["timestamp"].startswith(datetime.now().strftime("%Y-%m-%d"))]
            if today_trades:
                report_lines.append(f"")
                report_lines.append(f"[今日交易] ({len(today_trades)}笔)")
                for t in today_trades:
                    report_lines.append(f"  {t['direction']} {t['symbol']} {t['volume']}@{t['price']:.2f}")

        report = "\n".join(report_lines)
        logger.info(f"Daily report generated:\n{report}")
        
        self._send_daily_report_to_feishu(report)
        
        return report
    
    def _send_daily_report_to_feishu(self, report_text):
        """发送日报到飞书（使用统一模块）"""
        try:
            success = send_daily_report(report_text)
            if success:
                logger.info("Daily report sent to Feishu successfully")
            else:
                logger.warning("Daily report sending failed")
            return success
        except Exception as e:
            logger.error(f"Error sending daily report: {e}")
            return False
