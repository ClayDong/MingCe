"""基金监控模块 — 监控财通成长优选混合 A (001480) 基金。

基于专家对话内容，实现涨跌幅、止盈、回撤和波动率监控。
"""

import asyncio
from pathlib import Path

import akshare as ak
import pandas as pd
import numpy as np
import aiosqlite
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from loguru import logger
from pydantic import BaseModel

from config.settings import get_settings

settings = get_settings()


class FundMonitorConfig(BaseModel):
    """基金监控配置"""
    fund_code: str = "001480"
    fund_name: str = "财通成长优选混合 A"
    
    # 持仓信息（需要用户补充）
    cost_price: Optional[float] = None  # 成本价（元/份）
    total_shares: Optional[float] = None  # 总份额
    total_investment: Optional[float] = None  # 总投资金额
    
    # 涨跌幅监控阈值
    daily_drop_trigger_3: float = -3.0  # 日跌幅超过-3%，定投金额×1.2
    daily_drop_trigger_5: float = -5.0  # 日跌幅超过-5%，定投金额×1.5
    daily_drop_trigger_8: float = -8.0  # 日跌幅超过-8%，定投金额×2.0
    daily_drop_trigger_10: float = -10.0  # 日跌幅超过-10%，定投金额×3.0
    
    daily_rise_trigger_3: float = 3.0  # 日涨幅超过+3%，定投金额×0.8
    daily_rise_trigger_5: float = 5.0  # 日涨幅超过+5%，定投金额×0.6
    daily_rise_trigger_8: float = 8.0  # 日涨幅超过+8%，暂停定投
    
    # 止盈阈值
    profit_50_pct: float = 50.0  # 累计收益+50%，止盈30%
    profit_100_pct: float = 100.0  # 累计收益+100%，止盈30%
    profit_150_pct: float = 150.0  # 累计收益+150%，止盈40%
    profit_200_pct: float = 200.0  # 累计收益+200%，全部止盈
    
    # 回撤监控阈值
    drawdown_10_pct: float = -10.0  # 回撤-10%至-15%，增加50%定投金额
    drawdown_15_pct: float = -15.0  # 回撤-15%至-25%，增加100%定投金额
    drawdown_25_pct: float = -25.0  # 回撤-25%以上，增加150%定投金额
    
    # 波动率监控阈值
    volatility_low: float = 30.0  # 低波动（<30%），正常定投
    volatility_medium: float = 40.0  # 中波动（30-40%），增加20%定投金额
    volatility_high: float = 50.0  # 高波动（40-50%），增加50%定投金额
    volatility_extreme: float = 60.0  # 极高风险（>50%），暂停定投
    
    # 基础定投金额（元）
    base_investment: float = 1000.0


class FundData(BaseModel):
    """基金数据"""
    date: str
    net_value: float  # 单位净值
    accumulated_value: float  # 累计净值
    daily_change_pct: float  # 日涨跌幅
    weekly_change_pct: Optional[float] = None  # 周涨跌幅
    monthly_change_pct: Optional[float] = None  # 月涨跌幅
    quarterly_change_pct: Optional[float] = None  # 季度涨跌幅
    yearly_change_pct: Optional[float] = None  # 年涨跌幅


class MonitorAlert(BaseModel):
    """监控告警"""
    alert_type: str  # 类型：daily_change, profit, drawdown, volatility
    level: str  # 级别：info, warning, danger
    title: str
    content: str
    action: Optional[str] = None  # 建议操作
    timestamp: str


class FundMonitor:
    """基金监控器"""
    
    def __init__(self, config: Optional[FundMonitorConfig] = None):
        self.config = config or FundMonitorConfig()
        self.fund_data: Optional[FundData] = None
        self.history_data: Optional[pd.DataFrame] = None
        self.alerts: List[MonitorAlert] = []
        
    def fetch_fund_data(self) -> Optional[FundData]:
        """获取基金净值数据"""
        logger.info(f"Fetching fund data for {self.config.fund_code}...")

        try:
            # 获取基金历史净值数据
            # akshare API 变更：fund_open_fund_daily_em 不再接受 symbol 参数
            # 改用 fund_open_fund_info_em 获取单只基金净值走势
            df = ak.fund_open_fund_info_em(symbol=self.config.fund_code, indicator="单位净值走势")
            if df is None or df.empty:
                logger.warning(f"No data found for fund {self.config.fund_code}")
                return None

            # 按日期降序排序
            df = df.sort_values("净值日期", ascending=False)

            # 获取最新数据
            latest = df.iloc[0]
            date = str(latest.get("净值日期", ""))
            net_value = float(latest.get("单位净值", 0))
            # fund_open_fund_info_em 不返回累计净值，用单位净值作为回退
            accumulated_value = net_value

            # 计算日涨跌幅
            if len(df) >= 2:
                prev_net_value = float(df.iloc[1].get("单位净值", 0))
                if prev_net_value > 0:
                    daily_change_pct = ((net_value - prev_net_value) / prev_net_value) * 100
                else:
                    daily_change_pct = 0
            else:
                daily_change_pct = 0
            
            # 计算周、月、季度、年涨跌幅
            weekly_change_pct = self._calculate_period_change(df, 5)
            monthly_change_pct = self._calculate_period_change(df, 20)
            quarterly_change_pct = self._calculate_period_change(df, 60)
            yearly_change_pct = self._calculate_period_change(df, 250)
            
            self.history_data = df
            self.fund_data = FundData(
                date=date,
                net_value=net_value,
                accumulated_value=accumulated_value,
                daily_change_pct=daily_change_pct,
                weekly_change_pct=weekly_change_pct,
                monthly_change_pct=monthly_change_pct,
                quarterly_change_pct=quarterly_change_pct,
                yearly_change_pct=yearly_change_pct,
            )
            
            logger.info(f"Fund data fetched: {self.fund_data.date}, net_value={self.fund_data.net_value:.4f}, daily_change={self.fund_data.daily_change_pct:.2f}%")
            return self.fund_data
            
        except Exception as e:
            logger.error(f"Failed to fetch fund data: {e}")
            return None
    
    def _calculate_period_change(self, df: pd.DataFrame, days: int) -> Optional[float]:
        """计算指定周期的涨跌幅"""
        if len(df) < days:
            return None
        
        try:
            current_value = float(df.iloc[0].get("单位净值", 0))
            past_value = float(df.iloc[days].get("单位净值", 0))
            if past_value > 0:
                return ((current_value - past_value) / past_value) * 100
        except Exception as e:
            logger.debug(f"Failed to calculate {days}-day change: {e}")
        
        return None
    
    def calculate_profit(self) -> Optional[float]:
        """计算累计收益率"""
        if self.fund_data is None or not self.config.cost_price:
            return None
        
        if self.config.cost_price <= 0:
            return None
        
        profit_pct = ((self.fund_data.net_value - self.config.cost_price) / self.config.cost_price) * 100
        return profit_pct
    
    def calculate_drawdown(self) -> Optional[float]:
        """计算当前回撤率"""
        if self.history_data is None or self.history_data.empty:
            return None
        
        try:
            # 找到历史最高净值
            max_net_value = float(self.history_data["单位净值"].max())
            current_net_value = self.fund_data.net_value
            
            if max_net_value > 0:
                drawdown_pct = ((current_net_value - max_net_value) / max_net_value) * 100
                return drawdown_pct
        except Exception as e:
            logger.debug(f"Failed to calculate drawdown: {e}")
        
        return None
    
    def calculate_volatility(self, days: int = 20) -> Optional[float]:
        """计算波动率（标准差）。"""
        if self.history_data is None or len(self.history_data) < days:
            return None
        
        try:
            # 取最近 days 天的净值数据
            recent_data = self.history_data.head(days)
            net_values = recent_data["单位净值"].astype(float)
            
            # 计算日收益率
            daily_returns = net_values.pct_change().dropna()
            
            # 数据点数量检查
            min_points = getattr(settings, 'RISK_FUND_VOLATILITY_MIN_POINTS', 20)
            if len(daily_returns) < min_points:
                logger.warning(f"波动率数据点不足: {len(daily_returns)} < {min_points}")
                return 0.0
            
            # 计算波动率（标准差）
            volatility = daily_returns.std() * 100 * np.sqrt(250)  # 年化波动率
            return volatility
        except Exception as e:
            logger.debug(f"Failed to calculate volatility: {e}")
        
        return None
    
    def monitor_daily_change(self) -> List[MonitorAlert]:
        """监控日涨跌幅"""
        alerts = []

        if self.fund_data is None:
            return alerts
        
        daily_change = self.fund_data.daily_change_pct
        
        # 下跌触发
        if daily_change <= self.config.daily_drop_trigger_10:
            alerts.append(MonitorAlert(
                alert_type="daily_change",
                level="danger",
                title=f"日跌幅超10%：{daily_change:.2f}%",
                content=f"建议定投金额×3.0（{self.config.base_investment * 3:.0f}元）",
                action="加仓",
                timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ))
        elif daily_change <= self.config.daily_drop_trigger_8:
            alerts.append(MonitorAlert(
                alert_type="daily_change",
                level="danger",
                title=f"日跌幅超8%：{daily_change:.2f}%",
                content=f"建议定投金额×2.0（{self.config.base_investment * 2:.0f}元）",
                action="加仓",
                timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ))
        elif daily_change <= self.config.daily_drop_trigger_5:
            alerts.append(MonitorAlert(
                alert_type="daily_change",
                level="warning",
                title=f"日跌幅超5%：{daily_change:.2f}%",
                content=f"建议定投金额×1.5（{self.config.base_investment * 1.5:.0f}元）",
                action="加仓",
                timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ))
        elif daily_change <= self.config.daily_drop_trigger_3:
            alerts.append(MonitorAlert(
                alert_type="daily_change",
                level="warning",
                title=f"日跌幅超3%：{daily_change:.2f}%",
                content=f"建议定投金额×1.2（{self.config.base_investment * 1.2:.0f}元）",
                action="加仓",
                timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ))
        
        # 上涨触发
        if daily_change >= self.config.daily_rise_trigger_8:
            alerts.append(MonitorAlert(
                alert_type="daily_change",
                level="info",
                title=f"日涨幅超8%：{daily_change:.2f}%",
                content="建议暂停定投1-2日",
                action="暂停定投",
                timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ))
        elif daily_change >= self.config.daily_rise_trigger_5:
            alerts.append(MonitorAlert(
                alert_type="daily_change",
                level="info",
                title=f"日涨幅超5%：{daily_change:.2f}%",
                content=f"建议定投金额×0.6（{self.config.base_investment * 0.6:.0f}元）",
                action="减仓",
                timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ))
        elif daily_change >= self.config.daily_rise_trigger_3:
            alerts.append(MonitorAlert(
                alert_type="daily_change",
                level="info",
                title=f"日涨幅超3%：{daily_change:.2f}%",
                content=f"建议定投金额×0.8（{self.config.base_investment * 0.8:.0f}元）",
                action="减仓",
                timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ))
        
        return alerts
    
    def monitor_profit(self) -> List[MonitorAlert]:
        """监控止盈信号"""
        alerts = []
        
        profit_pct = self.calculate_profit()
        if profit_pct is None:
            return alerts
        
        if profit_pct >= self.config.profit_200_pct:
            alerts.append(MonitorAlert(
                alert_type="profit",
                level="danger",
                title=f"累计收益超200%：{profit_pct:.2f}%",
                content="建议全部止盈",
                action="全部止盈",
                timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ))
        elif profit_pct >= self.config.profit_150_pct:
            alerts.append(MonitorAlert(
                alert_type="profit",
                level="warning",
                title=f"累计收益超150%：{profit_pct:.2f}%",
                content="建议止盈40%，保留60%",
                action="分批止盈",
                timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ))
        elif profit_pct >= self.config.profit_100_pct:
            alerts.append(MonitorAlert(
                alert_type="profit",
                level="warning",
                title=f"累计收益超100%：{profit_pct:.2f}%",
                content="建议止盈30%，保留70%",
                action="分批止盈",
                timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ))
        elif profit_pct >= self.config.profit_50_pct:
            alerts.append(MonitorAlert(
                alert_type="profit",
                level="info",
                title=f"累计收益超50%：{profit_pct:.2f}%",
                content="建议止盈30%，保留70%",
                action="分批止盈",
                timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ))
        
        return alerts
    
    def monitor_drawdown(self) -> List[MonitorAlert]:
        """监控回撤信号"""
        alerts = []
        
        drawdown_pct = self.calculate_drawdown()
        if drawdown_pct is None:
            return alerts
        
        if drawdown_pct <= self.config.drawdown_25_pct:
            alerts.append(MonitorAlert(
                alert_type="drawdown",
                level="danger",
                title=f"回撤超25%：{drawdown_pct:.2f}%",
                content=f"建议增加150%定投金额（{self.config.base_investment * 2.5:.0f}元）",
                action="加仓",
                timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ))
        elif drawdown_pct <= self.config.drawdown_15_pct:
            alerts.append(MonitorAlert(
                alert_type="drawdown",
                level="warning",
                title=f"回撤超15%：{drawdown_pct:.2f}%",
                content=f"建议增加100%定投金额（{self.config.base_investment * 2:.0f}元）",
                action="加仓",
                timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ))
        elif drawdown_pct <= self.config.drawdown_10_pct:
            alerts.append(MonitorAlert(
                alert_type="drawdown",
                level="warning",
                title=f"回撤超10%：{drawdown_pct:.2f}%",
                content=f"建议增加50%定投金额（{self.config.base_investment * 1.5:.0f}元）",
                action="加仓",
                timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ))
        
        return alerts
    
    def monitor_volatility(self) -> List[MonitorAlert]:
        """监控波动率"""
        alerts = []
        
        volatility = self.calculate_volatility()
        if volatility is None:
            return alerts
        
        if volatility >= self.config.volatility_extreme:
            alerts.append(MonitorAlert(
                alert_type="volatility",
                level="danger",
                title=f"波动率极高：{volatility:.2f}%（衡量基金净值波动幅度，越高意味着短期内涨跌越剧烈）",
                content="建议暂停定投，观察市场",
                action="暂停定投",
                timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ))
        elif volatility >= self.config.volatility_high:
            alerts.append(MonitorAlert(
                alert_type="volatility",
                level="warning",
                title=f"波动率高：{volatility:.2f}%（衡量基金净值波动幅度，越高意味着短期内涨跌越剧烈）",
                content=f"建议增加50%定投金额（{self.config.base_investment * 1.5:.0f}元）",
                action="加仓",
                timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ))
        elif volatility >= self.config.volatility_medium:
            alerts.append(MonitorAlert(
                alert_type="volatility",
                level="info",
                title=f"波动率中等：{volatility:.2f}%（衡量基金净值波动幅度，越高意味着短期内涨跌越剧烈）",
                content=f"建议增加20%定投金额（{self.config.base_investment * 1.2:.0f}元）",
                action="加仓",
                timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ))
        elif volatility <= self.config.volatility_low:
            alerts.append(MonitorAlert(
                alert_type="volatility",
                level="info",
                title=f"波动率低：{volatility:.2f}%（衡量基金净值波动幅度，越高意味着短期内涨跌越剧烈）",
                content="建议正常定投",
                action="正常定投",
                timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ))
        
        return alerts
    
    async def run_monitor(self) -> Dict:
        """运行完整监控（异步版本）"""
        logger.info("Running fund monitor...")
        
        # 获取数据（通过线程池避免阻塞）
        import asyncio
        await asyncio.get_event_loop().run_in_executor(None, self.fetch_fund_data)
        if self.fund_data is None:
            logger.warning("No fund data available, monitor skipped")
            return {"status": "error", "message": "无法获取基金数据"}
        
        # 清空告警列表
        self.alerts = []
        
        # 执行各项监控
        self.alerts.extend(self.monitor_daily_change())
        self.alerts.extend(self.monitor_profit())
        self.alerts.extend(self.monitor_drawdown())
        self.alerts.extend(self.monitor_volatility())
        
        # 按级别排序
        self.alerts.sort(key=lambda x: {"danger": 0, "warning": 1, "info": 2}.get(x.level, 3))
        
        # 构建监控结果
        result = {
            "status": "success",
            "fund_code": self.config.fund_code,
            "fund_name": self.config.fund_name,
            "date": self.fund_data.date,
            "net_value": self.fund_data.net_value,
            "daily_change_pct": self.fund_data.daily_change_pct,
            "weekly_change_pct": self.fund_data.weekly_change_pct,
            "monthly_change_pct": self.fund_data.monthly_change_pct,
            "quarterly_change_pct": self.fund_data.quarterly_change_pct,
            "yearly_change_pct": self.fund_data.yearly_change_pct,
            "profit_pct": self.calculate_profit(),
            "drawdown_pct": self.calculate_drawdown(),
            "volatility": self.calculate_volatility(),
            "alerts": [alert.model_dump() for alert in self.alerts],
            "alert_count": len(self.alerts),
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        
        # 提示用户配置成本价
        cost_hints = []
        if self.config.cost_price is None:
            cost_hints.append(self.config.fund_name)
        
        result["warnings"] = []
        if cost_hints:
            hints_text = "、".join(cost_hints[:3])
            if len(cost_hints) > 3:
                hints_text += f"等{len(cost_hints)}只基金"
            result["warnings"].append(f"💡 以下基金未配置成本价（无法计算盈亏）: {hints_text}")
        
        logger.info(f"Monitor completed: {len(self.alerts)} alerts generated")
        return result


def build_fund_monitor_card(monitor_result: Dict) -> Dict:
    """构建基金监控飞书卡片"""
    
    fund_name = monitor_result.get("fund_name", "")
    fund_code = monitor_result.get("fund_code", "")
    date = monitor_result.get("date", "")
    net_value = monitor_result.get("net_value", 0)
    daily_change = monitor_result.get("daily_change_pct", 0)
    weekly_change = monitor_result.get("weekly_change_pct")
    monthly_change = monitor_result.get("monthly_change_pct")
    quarterly_change = monitor_result.get("quarterly_change_pct")
    yearly_change = monitor_result.get("yearly_change_pct")
    profit_pct = monitor_result.get("profit_pct")
    drawdown_pct = monitor_result.get("drawdown_pct")
    volatility = monitor_result.get("volatility")
    alerts = monitor_result.get("alerts", [])
    timestamp = monitor_result.get("timestamp", "")
    
    # 格式化涨跌幅
    def fmt_pct(val):
        if val is None:
            return "--"
        return f"{val:+.2f}%"
    
    # 构建卡片内容
    sections = []
    
    # 基金基本信息
    icon = "🟢" if daily_change >= 0 else "🔴"
    market_status = "上涨" if daily_change >= 0 else "下跌"
    sections.append(f"## 📊 {fund_name} ({fund_code})")
    sections.append(f"**净值日期**：{date}")
    sections.append(f"**单位净值**：{net_value:.4f} {icon} {fmt_pct(daily_change)} ({market_status})")
    
    # 周期涨跌幅 - 使用更直观的格式
    period_lines = []
    if weekly_change is not None:
        icon_w = "📈" if weekly_change >= 0 else "📉"
        period_lines.append(f"{icon_w} 近1周：{fmt_pct(weekly_change)}")
    if monthly_change is not None:
        icon_m = "📈" if monthly_change >= 0 else "📉"
        period_lines.append(f"{icon_m} 近1月：{fmt_pct(monthly_change)}")
    if quarterly_change is not None:
        icon_q = "📈" if quarterly_change >= 0 else "📉"
        period_lines.append(f"{icon_q} 近3月：{fmt_pct(quarterly_change)}")
    if yearly_change is not None:
        icon_y = "📈" if yearly_change >= 0 else "📉"
        period_lines.append(f"{icon_y} 近1年：{fmt_pct(yearly_change)}")
    
    if period_lines:
        sections.append("### 📅 周期表现\n" + "\n".join(period_lines))
    
    # 持仓收益（如果有），未配置成本价时提示
    if profit_pct is None:
        sections.append("💡 **未配置成本价**：请使用基金管理功能设置成本价以查看盈亏")
    elif profit_pct >= 0:
        if profit_pct >= 0:
            profit_icon = "💰"
            profit_color = "盈利"
        else:
            profit_icon = "📉"
            profit_color = "亏损"
        sections.append(f"{profit_icon} **累计{profit_color}**：{fmt_pct(profit_pct)}")
    
    # 回撤信息 - 增加风险提示
    if drawdown_pct is not None:
        if drawdown_pct <= -25:
            drawdown_icon = "🔴"
            risk_level = "高风险"
        elif drawdown_pct <= -15:
            drawdown_icon = "🟡"
            risk_level = "中等风险"
        elif drawdown_pct <= -10:
            drawdown_icon = "🟢"
            risk_level = "低风险"
        else:
            drawdown_icon = "⚪"
            risk_level = "正常"
        sections.append(f"{drawdown_icon} **当前回撤**：{fmt_pct(drawdown_pct)} ({risk_level})")
    
    # 波动率 - 增加操作建议
    if volatility is not None:
        if volatility >= 60:
            volatility_icon = "🔴"
            vol_suggestion = "暂停定投"
        elif volatility >= 50:
            volatility_icon = "🟡"
            vol_suggestion = "增加50%"
        elif volatility >= 40:
            volatility_icon = "🟢"
            vol_suggestion = "增加20%"
        else:
            volatility_icon = "⚪"
            vol_suggestion = "正常定投"
        sections.append(f"{volatility_icon} **波动率**：{volatility:.2f}% → 建议{vol_suggestion}")
    
    # 告警信息
    if alerts:
        alert_lines = []
        danger_count = sum(1 for a in alerts if a.get("level") == "danger")
        warning_count = sum(1 for a in alerts if a.get("level") == "warning")
        info_count = sum(1 for a in alerts if a.get("level") == "info")
        
        # 告警摘要
        summary_parts = []
        if danger_count > 0:
            summary_parts.append(f"🔴 {danger_count}个")
        if warning_count > 0:
            summary_parts.append(f"🟡 {warning_count}个")
        if info_count > 0:
            summary_parts.append(f"🟢 {info_count}个")
        
        if summary_parts:
            sections.append(f"### 🚨 告警摘要（{' '.join(summary_parts)}）\n")
        
        # 详细告警
        for alert in alerts[:5]:  # 只显示前5个告警
            level_icon = {"danger": "🔴", "warning": "🟡", "info": "🟢"}.get(alert.get("level", "info"), "⚪")
            title = alert.get("title", "")
            content = alert.get("content", "")
            action = alert.get("action", "")
            alert_lines.append(f"{level_icon} **{title}**\n   {content}")
            if action:
                alert_lines.append(f"   👉 执行：{action}")
        
        sections.append("\n".join(alert_lines))
    
    # 操作建议
    if alerts:
        # 提取最紧急的action
        urgent_actions = [a.get("action", "") for a in alerts if a.get("level") in ["danger", "warning"]]
        if urgent_actions:
            sections.append(f"\n### 🎯 本次建议\n基于当前监控结果，建议：**{' / '.join(set(urgent_actions[:3]))}**")
    
    # 卡片底部
    sections.append(f"\n---\n📈 数据更新：{timestamp}\n⚠️ 仅供参考，不构成投资建议")
    
    # 构建卡片
    card = {
        "header": {
            "template": "blue" if daily_change >= 0 else "red",
            "title": {"tag": "plain_text", "content": f"📊 {fund_name} 监控报告"},
        },
        "elements": [{"tag": "markdown", "content": "\n\n".join(sections)}],
    }
    
    return card


class FundMonitorManager:
    """多基金监控管理器。

    使用 SQLite（复用 portfolio_manager 的 data/portfolio.db）存储多只基金的监控配置，
    通过 aiosqlite + asyncio.Lock 保证并发安全。每只基金用现有的 FundMonitor 类监控。
    """

    _DB_PATH = Path(__file__).parent.parent / "data" / "portfolio.db"

    def __init__(self):
        self._db_conn: Optional[aiosqlite.Connection] = None
        self._lock = asyncio.Lock()

    async def _get_db(self) -> aiosqlite.Connection:
        """获取数据库连接（双重检查锁定，确保只创建一次）。"""
        if self._db_conn is None:
            async with self._lock:
                if self._db_conn is None:
                    Path(self._DB_PATH).parent.mkdir(parents=True, exist_ok=True)
                    self._db_conn = await aiosqlite.connect(str(self._DB_PATH))
                    self._db_conn.row_factory = aiosqlite.Row
                    await self._db_conn.execute("PRAGMA journal_mode=WAL")
                    await self._db_conn.execute("PRAGMA busy_timeout=5000")
                    await self._db_conn.execute("PRAGMA synchronous=NORMAL")
                    await self._init_db()
        return self._db_conn

    async def _init_db(self):
        """初始化表结构，并自动迁移现有 _fund_monitor_config（001480）到数据库。"""
        db = self._db_conn
        await db.execute("""
            CREATE TABLE IF NOT EXISTS fund_configs (
                fund_code TEXT PRIMARY KEY,
                fund_name TEXT NOT NULL,
                cost_price REAL,
                total_shares REAL,
                total_investment REAL,
                base_investment REAL NOT NULL DEFAULT 1000,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        await db.commit()

        # 自动迁移现有的 _fund_monitor_config（001480）到数据库
        async with db.execute("SELECT COUNT(*) FROM fund_configs") as cursor:
            row = await cursor.fetchone()
            count = row[0] if row else 0

        if count == 0:
            default_config = FundMonitorConfig()
            await db.execute(
                """INSERT OR IGNORE INTO fund_configs
                   (fund_code, fund_name, cost_price, total_shares, total_investment, base_investment, active)
                   VALUES (?, ?, ?, ?, ?, ?, 1)""",
                (
                    default_config.fund_code,
                    default_config.fund_name,
                    default_config.cost_price,
                    default_config.total_shares,
                    default_config.total_investment,
                    default_config.base_investment,
                ),
            )
            await db.commit()
            logger.info(
                f"Migrated default fund config to DB: {default_config.fund_code} ({default_config.fund_name})"
            )

    async def add_fund(
        self,
        fund_code: str,
        fund_name: str,
        cost_price: Optional[float] = None,
        total_investment: Optional[float] = None,
        base_investment: float = 1000,
    ) -> Dict:
        """添加基金配置（若已存在则更新）。"""
        db = await self._get_db()
        try:
            await db.execute(
                """INSERT OR REPLACE INTO fund_configs
                   (fund_code, fund_name, cost_price, total_shares, total_investment, base_investment, active)
                   VALUES (?, ?, ?, NULL, ?, ?, 1)""",
                (fund_code, fund_name, cost_price, total_investment, base_investment),
            )
            await db.commit()
            logger.info(f"Fund added: {fund_name} ({fund_code})")
            return {"success": True, "fund_code": fund_code, "fund_name": fund_name}
        except Exception as e:
            logger.error(f"Failed to add fund {fund_code}: {e}")
            return {"success": False, "error": str(e)}

    async def remove_fund(self, fund_code: str) -> Dict:
        """移除基金配置。"""
        db = await self._get_db()
        try:
            await db.execute("DELETE FROM fund_configs WHERE fund_code = ?", (fund_code,))
            await db.commit()
            logger.info(f"Fund removed: {fund_code}")
            return {"success": True, "fund_code": fund_code}
        except Exception as e:
            logger.error(f"Failed to remove fund {fund_code}: {e}")
            return {"success": False, "error": str(e)}

    async def get_all_funds(self) -> List[Dict]:
        """获取所有活跃基金配置。"""
        db = await self._get_db()
        async with db.execute(
            """SELECT fund_code, fund_name, cost_price, total_shares, total_investment, base_investment, created_at
               FROM fund_configs WHERE active = 1 ORDER BY created_at"""
        ) as cursor:
            rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def run_all_monitors(self) -> Dict:
        """运行所有活跃基金的监控。

        返回: {"results": [...], "date": "..."}
        """
        funds = await self.get_all_funds()
        if not funds:
            logger.warning("No active funds to monitor")
            return {"results": [], "date": datetime.now().strftime("%Y-%m-%d")}

        results = []
        latest_date = ""

        for fund in funds:
            base_inv = fund["base_investment"]
            if base_inv is None:
                base_inv = 1000.0

            config = FundMonitorConfig(
                fund_code=fund["fund_code"],
                fund_name=fund["fund_name"],
                cost_price=fund["cost_price"],
                total_shares=fund["total_shares"],
                total_investment=fund["total_investment"],
                base_investment=base_inv,
            )
            monitor = FundMonitor(config=config)
            try:
                result = await monitor.run_monitor()
                results.append(result)
                if result.get("status") == "success" and result.get("date"):
                    latest_date = result["date"]
            except Exception as e:
                logger.error(f"Failed to monitor fund {fund['fund_code']}: {e}")
                results.append({
                    "status": "error",
                    "fund_code": fund["fund_code"],
                    "fund_name": fund["fund_name"],
                    "message": str(e),
                })

        return {
            "results": results,
            "date": latest_date or datetime.now().strftime("%Y-%m-%d"),
        }


_fund_manager: Optional[FundMonitorManager] = None


def get_fund_manager() -> FundMonitorManager:
    """获取全局 FundMonitorManager 单例。"""
    global _fund_manager
    if _fund_manager is None:
        _fund_manager = FundMonitorManager()
    return _fund_manager