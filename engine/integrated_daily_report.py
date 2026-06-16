#!/usr/bin/env python3
"""
每日策略报告 + 舆情分析 完整版本
"""

import sys
import json
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from daily_strategy_trade_report import DailyStrategyTradeReport
from qlib_vnpy_platform.core.sentiment_analyzer import SentimentSystem


class IntegratedDailyReport:
    """整合策略报告和舆情分析"""
    
    def __init__(self, symbol: str = "SZ002594", stock_name: str = "比亚迪"):
        self.symbol = symbol
        self.stock_name = stock_name
        self.strategy_report = DailyStrategyTradeReport()
        self.sentiment_system = SentimentSystem(symbol, stock_name)
        
    def generate_full_report(self) -> dict:
        """生成完整的每日报告"""
        print("=" * 60)
        print(f"开始生成{self.stock_name}完整每日报告...")
        print("=" * 60)
        
        # 1. 生成策略交易报告
        print("\n[1/3] 生成策略交易报告...")
        strategy_msg, strategy_report = self.strategy_report.generate_daily_report()
        
        # 2. 生成舆情分析报告
        print("\n[2/3] 生成舆情分析报告...")
        sentiment_report = self.sentiment_system.run_daily_analysis()
        
        # 3. 整合两个报告
        print("\n[3/3] 整合报告...")
        full_report = self._integrate_reports(strategy_report, sentiment_report)
        
        # 保存完整报告
        self._save_full_report(full_report)
        
        return full_report
    
    def _integrate_reports(self, strategy_report: dict, sentiment_report: dict) -> dict:
        """整合策略报告和舆情报告"""
        # 计算舆情信号对策略的影响
        sentiment_score = sentiment_report.get("overall_sentiment_score", 0)
        sentiment_impact = self._calculate_sentiment_impact(sentiment_score)
        
        return {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "stock_name": self.stock_name,
            "symbol": self.symbol,
            "strategy_report": strategy_report,
            "sentiment_report": sentiment_report,
            "sentiment_impact": sentiment_impact,
            "integrated_signal": self._generate_integrated_signal(strategy_report, sentiment_report)
        }
    
    def _calculate_sentiment_impact(self, sentiment_score: float) -> dict:
        """计算舆情对策略的影响"""
        if sentiment_score > 0.2:
            direction = 1  # 正向影响
            adjustment = 0.25  # 策略权重+25%
        elif sentiment_score < -0.2:
            direction = -1  # 负向影响
            adjustment = -0.25  # 策略权重-25%
        else:
            direction = 0  # 中性
            adjustment = 0
            
        return {
            "direction": direction,
            "adjustment_factor": adjustment,
            "impact_level": "high" if abs(sentiment_score) > 0.3 else "medium" if abs(sentiment_score) > 0.1 else "low"
        }
    
    def _generate_integrated_signal(self, strategy_report: dict, sentiment_report: dict) -> dict:
        """生成整合信号"""
        sentiment_impact = self._calculate_sentiment_impact(
            sentiment_report.get("overall_sentiment_score", 0)
        )
        
        return {
            "final_signal": self._weighted_signals(strategy_report, sentiment_report),
            "sentiment_contribution": sentiment_impact,
            "summary": "策略信号与舆情信号已融合"
        }
    
    def _weighted_signals(self, strategy_report: dict, sentiment_report: dict) -> str:
        """计算加权信号"""
        strategy_score = self._extract_strategy_score(strategy_report)
        sentiment_score = sentiment_report.get("overall_sentiment_score", 0)
        
        # 60% 策略信号，25% 舆情信号，15% 其他
        final_score = strategy_score * 0.6 + sentiment_score * 0.25
        
        if final_score > 0.2:
            return "buy"
        elif final_score < -0.2:
            return "sell"
        else:
            return "hold"
    
    def _extract_strategy_score(self, strategy_report: dict) -> float:
        """从策略报告中提取信号分数"""
        performance = strategy_report.get("performance_summary", [])
        if performance:
            top_strategy = performance[0]
            return top_strategy.get("pnl_pct", 0) / 100.0
        return 0
    
    def _save_full_report(self, report: dict):
        """保存完整报告"""
        report_dir = Path(__file__).parent / "qlib_vnpy_platform" / "data" / "integrated_reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        
        filename = report_dir / f"integrated_report_{datetime.now().strftime('%Y-%m-%d')}.json"
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        
        print(f"\n✅ 完整报告已保存到：{filename}")
    
    def format_feishu_message(self, full_report: dict) -> str:
        """格式化飞书消息"""
        lines = []
        
        lines.append("📊 【比亚迪】每日完整策略报告")
        lines.append(f"📅 日期：{full_report['date']}")
        lines.append("━" * 30)
        
        # 策略部分
        strategy_report = full_report['strategy_report']
        lines.append("📈 策略分析部分：")
        lines.append(f"  最新价格：{strategy_report['latest_price']:.2f}")
        lines.append(f"  涨跌：{strategy_report['change']:+.2f} ({strategy_report['change_pct']:+.2f}%)")
        lines.append(f"  今日操作：买入{strategy_report['buy_count']} 卖出{strategy_report['sell_count']}")
        
        lines.append("━" * 30)
        
        # 舆情部分
        sentiment_report = full_report['sentiment_report']
        sentiment_emoji = {
            "positive": "🟢",
            "negative": "🔴",
            "neutral": "🟡"
        }.get(sentiment_report['overall_sentiment'], "⚪")
        
        lines.append(f"{sentiment_emoji} 舆情分析部分：")
        lines.append(f"  整体情感：{sentiment_report['overall_sentiment']}")
        lines.append(f"  情感评分：{sentiment_report['overall_sentiment_score']:.2f}")
        lines.append(f"  新闻数量：{sentiment_report['news_count']}")
        lines.append(f"    - 正面：{sentiment_report['positive_news']}")
        lines.append(f"    - 负面：{sentiment_report['negative_news']}")
        
        suggestion = sentiment_report.get("suggestion", {})
        action_emoji = {
            "buy": "🟢",
            "sell": "🔴",
            "hold": "🟡"
        }.get(suggestion.get("action", "hold"), "⚪")
        
        lines.append(f"\n{action_emoji} 舆情建议：{suggestion.get('message', '')}")
        
        lines.append("━" * 30)
        
        # 整合信号
        impact = full_report['sentiment_impact']
        impact_desc = "正面" if impact['direction'] > 0 else "负面" if impact['direction'] < 0 else "中性"
        lines.append("🔗 整合分析：")
        lines.append(f"  舆情影响方向：{impact_desc}")
        lines.append(f"  影响级别：{impact['impact_level']}")
        lines.append(f"  最终信号：{full_report['integrated_signal']['final_signal']}")
        
        return "\n".join(lines)


def main():
    """主函数"""
    print("\n" + "=" * 60)
    print("比亚迪每日完整报告系统启动")
    print("=" * 60)
    
    # 初始化整合报告系统
    report_system = IntegratedDailyReport()
    
    # 生成完整报告
    full_report = report_system.generate_full_report()
    
    # 格式化并输出消息
    print("\n" + "=" * 60)
    print("📤 飞书消息预览：")
    print("=" * 60)
    print(report_system.format_feishu_message(full_report))


if __name__ == "__main__":
    main()
