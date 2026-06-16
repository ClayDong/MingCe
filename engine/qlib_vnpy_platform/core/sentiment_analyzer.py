#!/usr/bin/env python3
"""
舆情分析系统
包含：情感分析引擎、股价影响因子分析、历史案例库、舆情报告生成
"""

import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
import numpy as np
from loguru import logger

sys.path.insert(0, str(Path(__file__).parent.parent))

from qlib_vnpy_platform.core.data_bridge import DataBridge


class SentimentAnalyzer:
    """情感分析引擎"""
    
    def __init__(self):
        self.pos_words = self._load_positive_words()
        self.neg_words = self._load_negative_words()
        self.degree_words = self._load_degree_words()
        self.negation_words = ["不", "没", "无", "非", "未", "别", "莫", "勿"]
        
    def _load_positive_words(self) -> List[str]:
        """加载金融正向情感词"""
        words = [
            "利好", "上涨", "增长", "提升", "突破", "创新高", "盈利",
            "超预期", "优秀", "强劲", "向好", "乐观", "积极",
            "增持", "推荐", "买入", "看好", "成长", "发展",
            "新高", "暴涨", "涨停", "大幅上涨", "业绩增长", "营收增长",
            "利润增长", "盈利能力", "市场份额", "竞争力", "领先",
            "利好消息", "重大利好", "重磅利好", "政策利好", "业绩利好"
        ]
        return list(dict.fromkeys(words))
    
    def _load_negative_words(self) -> List[str]:
        """加载金融负向情感词"""
        words = [
            "利空", "下跌", "下降", "暴跌", "跌停", "亏损", "下滑",
            "低于预期", "恶化", "悲观", "负面", "风险", "危机", "问题",
            "减持", "卖出", "不看好", "衰退", "停滞",
            "业绩下滑", "营收下降", "利润下降", "大幅下跌",
            "利空消息", "重大利空", "政策利空", "业绩利空", "爆雷",
            "债务", "违约", "诉讼", "处罚", "调查", "负面新闻"
        ]
        return list(dict.fromkeys(words))
    
    def _load_degree_words(self) -> Dict[str, float]:
        """加载程度副词权重（仅包含修饰词，不含情感词本身）"""
        return {
            "非常": 2.0, "极其": 2.5, "十分": 1.8, "特别": 1.8,
            "大幅": 2.0, "明显": 1.5, "显著": 1.8, "略微": 0.5,
            "小幅": 0.5, "轻微": 0.3, "重大": 2.5, "重磅": 2.8, "超级": 3.0
        }
    
    def analyze(self, text: str) -> Dict:
        """对文本进行情感分析"""
        if not text or len(text.strip()) < 5:
            return {
                "sentiment": "neutral",
                "sentiment_score": 0.0,
                "sentiment_strength": 0,
                "key_words": [],
                "analysis_method": "dictionary"
            }
        
        score = 0.0
        key_words = []
        negation = False
        
        # 先检查完整词匹配
        # 正向词检查
        for pos_word in sorted(self.pos_words, key=lambda x: -len(x)):
            if pos_word in text:
                count = text.count(pos_word)
                score += 1.0 * count
                key_words.append(pos_word)
                
        # 负向词检查
        for neg_word in sorted(self.neg_words, key=lambda x: -len(x)):
            if neg_word in text:
                count = text.count(neg_word)
                score -= 1.0 * count
                key_words.append(neg_word)
        
        # 检查程度副词
        degree_multiplier = 1.0
        for degree_word, weight in self.degree_words.items():
            if degree_word in text:
                degree_multiplier *= weight
        
        if degree_multiplier > 1.0:
            degree_multiplier = min(degree_multiplier, 5.0)
            score *= degree_multiplier
        
        # 检查否定词
        negation_count = 0
        for neg_word in self.negation_words:
            if neg_word in text:
                for kw in key_words:
                    idx = text.find(kw)
                    if idx > 0:
                        before = text[max(0, idx - 3):idx]
                        if neg_word in before:
                            negation_count += 1
                            break
        
        if negation_count % 2 == 1:
            score = -score
        
        # 归一化分数
        normalized_score = max(-1.0, min(1.0, score / 5.0))
        
        # 确定情感极性
        if normalized_score > 0.1:
            sentiment = "positive"
        elif normalized_score < -0.1:
            sentiment = "negative"
        else:
            sentiment = "neutral"
        
        # 计算情感强度
        strength = min(5, max(1, int(abs(normalized_score) * 5 + 1)))
        
        return {
            "sentiment": sentiment,
            "sentiment_score": normalized_score,
            "sentiment_strength": strength,
            "key_words": list(set(key_words)),  # 去重
            "analysis_method": "dictionary"
        }


class ImpactAnalyzer:
    """股价影响因子分析引擎"""
    
    def __init__(self, data_dir: Optional[Path] = None):
        if data_dir:
            self.data_dir = Path(data_dir)
        else:
            # 默认路径
            self.data_dir = Path(__file__).parent.parent / "data"
        
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.history_db = self.data_dir / "sentiment_history.json"
        self._init_history_db()
        self.data_bridge = DataBridge()
        
    def _init_history_db(self):
        """初始化历史数据库"""
        if not self.history_db.exists():
            initial_data = {
                "historical_cases": [],
                "impact_statistics": {
                    "positive": {
                        "day_1": 0.015,
                        "day_3": 0.025,
                        "day_5": 0.035,
                        "day_10": 0.040
                    },
                    "negative": {
                        "day_1": -0.012,
                        "day_3": -0.022,
                        "day_5": -0.030,
                        "day_10": -0.035
                    }
                },
                "media_weights": {
                    "证券时报": 1.5,
                    "中国证券报": 1.5,
                    "上海证券报": 1.5,
                    "证券日报": 1.5,
                    "21世纪经济报道": 1.4,
                    "第一财经": 1.4,
                    "东方财富网": 1.2,
                    "新浪财经": 1.1,
                    "搜狐财经": 1.0,
                    "网易财经": 1.0
                }
            }
            with open(self.history_db, "w", encoding="utf-8") as f:
                json.dump(initial_data, f, ensure_ascii=False, indent=2)
    
    def calculate_impact_score(self, sentiment_result: Dict, source: str = "未知") -> Dict:
        """计算舆情影响分数"""
        sentiment_score = sentiment_result.get("sentiment_score", 0)
        strength = sentiment_result.get("sentiment_strength", 1)
        
        # 获取媒体权重
        with open(self.history_db, "r", encoding="utf-8") as f:
            history = json.load(f)
        media_weights = history.get("media_weights", {})
        media_weight = media_weights.get(source, 1.0)
        
        # 获取历史影响系数
        impact_stats = history.get("impact_statistics", {})
        sentiment = sentiment_result.get("sentiment", "neutral")
        
        if sentiment == "positive":
            historical_impact = impact_stats.get("positive", {"day_1": 0.015})
        elif sentiment == "negative":
            historical_impact = impact_stats.get("negative", {"day_1": -0.012})
        else:
            historical_impact = {"day_1": 0}
        
        # 计算综合影响分数
        overall_impact = sentiment_score * strength * media_weight
        
        # 计算时效性衰减因子
        time_decay_factors = {}
        for day in [1, 3, 5, 10]:
            decay = np.exp(-0.1 * (day - 1))  # 指数衰减
            time_decay_factors[f"day_{day}"] = decay
        
        return {
            "overall_impact_score": overall_impact,
            "sentiment_impact": sentiment_score * strength,
            "media_weight": media_weight,
            "historical_impact": historical_impact,
            "time_decay_factors": time_decay_factors,
            "time_horizon_impact": {
                f"day_{d}": overall_impact * historical_impact.get(f"day_{d}", 0) 
                for d in [1, 3, 5, 10]
            }
        }
    
    def find_similar_cases(self, sentiment_result: Dict, top_k: int = 5) -> List[Dict]:
        """查找历史类似案例"""
        with open(self.history_db, "r", encoding="utf-8") as f:
            history = json.load(f)
        
        cases = history.get("historical_cases", [])
        target_score = sentiment_result.get("sentiment_score", 0)
        target_strength = sentiment_result.get("sentiment_strength", 1)
        
        # 简单相似度计算
        similar_cases = []
        for case in cases:
            score_diff = abs(case.get("sentiment_score", 0) - target_score)
            strength_diff = abs(case.get("sentiment_strength", 1) - target_strength)
            similarity = 1.0 - (score_diff * 0.8 + strength_diff * 0.2)
            case["similarity"] = similarity
            similar_cases.append(case)
        
        # 排序并返回前top_k
        similar_cases.sort(key=lambda x: x.get("similarity", 0), reverse=True)
        return similar_cases[:top_k]
    
    def add_case_to_history(self, news_data: Dict, sentiment_result: Dict, 
                           price_changes: Dict):
        """添加案例到历史库"""
        with open(self.history_db, "r", encoding="utf-8") as f:
            history = json.load(f)
        
        new_case = {
            "id": len(history.get("historical_cases", [])) + 1,
            "date": datetime.now().strftime("%Y-%m-%d"),
            "title": news_data.get("title", ""),
            "content": news_data.get("content", ""),
            "source": news_data.get("source", ""),
            "publish_time": news_data.get("publish_time", ""),
            "sentiment": sentiment_result.get("sentiment", "neutral"),
            "sentiment_score": sentiment_result.get("sentiment_score", 0),
            "sentiment_strength": sentiment_result.get("sentiment_strength", 1),
            "key_words": sentiment_result.get("key_words", []),
            "price_changes": price_changes
        }
        
        history["historical_cases"].append(new_case)
        
        # 保留最近100条案例
        if len(history["historical_cases"]) > 100:
            history["historical_cases"] = history["historical_cases"][-100:]
        
        with open(self.history_db, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)


class SentimentReport:
    """舆情报告生成器"""
    
    def __init__(self, symbol: str = "SZ002594", stock_name: str = "比亚迪"):
        self.symbol = symbol
        self.stock_name = stock_name
        self.sentiment_analyzer = SentimentAnalyzer()
        data_dir = Path(__file__).parent.parent / "data"
        self.impact_analyzer = ImpactAnalyzer(data_dir=data_dir)
        self.data_bridge = DataBridge()
        
    def generate_daily_report(self, news_list: List[Dict]) -> Dict:
        """生成每日舆情报告"""
        if not news_list:
            return {
                "date": datetime.now().strftime("%Y-%m-%d"),
                "stock_name": self.stock_name,
                "symbol": self.symbol,
                "news_count": 0,
                "summary": "今日无相关新闻",
                "overall_sentiment": "neutral",
                "risk_level": 0
            }
        
        # 分析每条新闻
        analyzed_news = []
        total_score = 0
        pos_count = 0
        neg_count = 0
        neu_count = 0
        
        for news in news_list:
            text = news.get("title", "") + " " + news.get("content", "")
            sentiment = self.sentiment_analyzer.analyze(text)
            impact = self.impact_analyzer.calculate_impact_score(
                sentiment, news.get("source", "未知")
            )
            
            analyzed_news.append({
                "title": news.get("title", ""),
                "content": news.get("content", ""),
                "source": news.get("source", ""),
                "publish_time": news.get("publish_time", ""),
                "sentiment": sentiment,
                "impact": impact
            })
            
            score = sentiment["sentiment_score"]
            total_score += score
            
            if sentiment["sentiment"] == "positive":
                pos_count += 1
            elif sentiment["sentiment"] == "negative":
                neg_count += 1
            else:
                neu_count += 1
        
        avg_score = total_score / len(news_list) if news_list else 0
        
        # 确定整体情感
        if avg_score > 0.1:
            overall_sentiment = "positive"
        elif avg_score < -0.1:
            overall_sentiment = "negative"
        else:
            overall_sentiment = "neutral"
        
        # 风险评估
        risk_level = self._assess_risk(avg_score, neg_count, len(news_list))
        
        # 查找类似历史案例
        sample_sentiment = {"sentiment_score": avg_score, "sentiment_strength": 3}
        similar_cases = self.impact_analyzer.find_similar_cases(sample_sentiment)
        
        # 操作建议
        suggestion = self._generate_suggestion(overall_sentiment, avg_score, risk_level)
        
        return {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "stock_name": self.stock_name,
            "symbol": self.symbol,
            "news_count": len(news_list),
            "positive_news": pos_count,
            "negative_news": neg_count,
            "neutral_news": neu_count,
            "overall_sentiment_score": avg_score,
            "overall_sentiment": overall_sentiment,
            "risk_level": risk_level,
            "analyzed_news": analyzed_news,
            "similar_cases": similar_cases,
            "suggestion": suggestion
        }
    
    def _assess_risk(self, avg_score: float, neg_count: int, total_count: int) -> int:
        """评估风险等级 (1-5)"""
        risk = 3  # 默认中等风险
        
        if avg_score > 0.3:
            risk = 1
        elif avg_score > 0.1:
            risk = 2
        elif avg_score < -0.3:
            risk = 5
        elif avg_score < -0.1:
            risk = 4
        
        if total_count > 0 and neg_count / total_count > 0.5:
            risk = min(5, risk + 1)
        
        return risk
    
    def _generate_suggestion(self, sentiment: str, score: float, risk: int) -> Dict:
        """生成操作建议"""
        if sentiment == "positive" and score > 0.3:
            action = "buy"
            message = "舆情积极向好，可考虑加仓"
        elif sentiment == "positive":
            action = "hold"
            message = "舆情偏正面，建议继续持有"
        elif sentiment == "negative" and score < -0.3:
            action = "sell"
            message = "舆情负面风险较大，建议减仓观望"
        elif sentiment == "negative":
            action = "hold"
            message = "舆情偏负面，建议保持观望"
        else:
            action = "hold"
            message = "舆情中性，维持原有策略"
        
        return {
            "action": action,
            "message": message,
            "confidence": min(5, max(1, int(abs(score) * 5) + 1))
        }
    
    def format_report_for_feishu(self, report: Dict) -> str:
        """格式化报告用于飞书发送"""
        lines = []
        lines.append(f"📊 【{report['stock_name']}】每日舆情分析报告")
        lines.append(f"📅 日期：{report['date']}")
        lines.append("━" * 30)
        
        # 整体情感
        sentiment_emoji = {
            "positive": "🟢",
            "negative": "🔴",
            "neutral": "🟡"
        }.get(report["overall_sentiment"], "⚪")
        
        lines.append(f"{sentiment_emoji} 整体情感：{report['overall_sentiment']}")
        lines.append(f"📈 情感评分：{report['overall_sentiment_score']:.2f}")
        lines.append(f"📰 新闻数量：{report['news_count']}")
        lines.append(f"  - 正面：{report['positive_news']}")
        lines.append(f"  - 负面：{report['negative_news']}")
        lines.append(f"  - 中性：{report['neutral_news']}")
        lines.append(f"⚠️ 风险等级：{'⭐' * report['risk_level']}")
        lines.append("━" * 30)
        
        # 操作建议
        suggestion = report["suggestion"]
        action_emoji = {
            "buy": "🟢",
            "sell": "🔴",
            "hold": "🟡"
        }.get(suggestion["action"], "⚪")
        
        lines.append(f"{action_emoji} 操作建议：{suggestion['message']}")
        lines.append(f"   置信度：{'★' * suggestion['confidence']}{'☆' * (5 - suggestion['confidence'])}")
        
        # 新闻详情
        analyzed_news = report.get("analyzed_news", [])
        if analyzed_news:
            lines.append("━" * 30)
            lines.append("📌 重要新闻详情：")
            
            # 先排个序，把负面和正面的突出
            sorted_news = sorted(
                analyzed_news,
                key=lambda x: abs(x["sentiment"].get("sentiment_score", 0)),
                reverse=True
            )
            
            for i, news in enumerate(sorted_news[:5], 1):
                title = news.get("title", "无标题")
                sentiment_data = news.get("sentiment", {})
                sentiment = sentiment_data.get("sentiment", "neutral")
                score = sentiment_data.get("sentiment_score", 0)
                strength = sentiment_data.get("sentiment_strength", 0)
                key_words = sentiment_data.get("key_words", [])
                
                emotion_icon = {
                    "positive": "🟢",
                    "negative": "🔴",
                    "neutral": "🟡"
                }.get(sentiment, "⚪")
                
                lines.append(f"{i}. {emotion_icon} {title}")
                lines.append(f"   来源：{news.get('source', '未知')}")
                lines.append(f"   情感强度：{'█' * int(strength * 5)}{'░' * (5 - int(strength * 5))} ({score:.2f})")
                
                if key_words:
                    lines.append(f"   关键词：{', '.join(key_words[:3])}")
                
                content = news.get("content", "")
                if content:
                    content_preview = content[:80] + "..." if len(content) > 80 else content
                    lines.append(f"   内容：{content_preview}")
                lines.append("")
            
            # 单独展示最正面和最负面
            positive_news = [n for n in analyzed_news if n["sentiment"].get("sentiment") == "positive"]
            negative_news = [n for n in analyzed_news if n["sentiment"].get("sentiment") == "negative"]
            
            if positive_news or negative_news:
                lines.append("━" * 30)
                if positive_news:
                    top_pos = max(positive_news, key=lambda x: x["sentiment"].get("sentiment_score", 0))
                    lines.append("✅ 最正面新闻：")
                    lines.append(f"  {top_pos.get('title', '')[:60]}...")
                if negative_news:
                    top_neg = max(negative_news, key=lambda x: -x["sentiment"].get("sentiment_score", 0))
                    lines.append("❌ 最负面新闻：")
                    lines.append(f"  {top_neg.get('title', '')[:60]}...")
        
        return "\n".join(lines)


class SentimentSystem:
    """完整的舆情分析系统"""
    
    def __init__(self, symbol: str = "SZ002594", stock_name: str = "比亚迪"):
        self.symbol = symbol
        self.stock_name = stock_name
        self.sentiment_analyzer = SentimentAnalyzer()
        self.impact_analyzer = ImpactAnalyzer()
        self.report_generator = SentimentReport(symbol, stock_name)
        
        from qlib_vnpy_platform.core.news_fetcher import NewsFetcher
        self.news_fetcher = NewsFetcher()
        
    def run_daily_analysis(self) -> Dict:
        """运行每日分析"""
        logger.info(f"开始{self.stock_name}每日舆情分析...")
        
        # 1. 获取新闻
        news_list = self.news_fetcher.fetch_stock_news(self.symbol, max_news=10)
        logger.info(f"获取到{len(news_list)}条新闻")
        
        # 2. 生成报告
        report = self.report_generator.generate_daily_report(news_list)
        logger.info(f"分析完成，整体情感：{report['overall_sentiment']}")
        
        # 3. 保存报告
        self._save_report(report)
        
        return report
    
    def _save_report(self, report: Dict):
        """保存报告到文件"""
        report_dir = Path(__file__).parent.parent / "data" / "sentiment_reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        
        filename = report_dir / f"sentiment_report_{report['date']}.json"
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        
        logger.info(f"报告已保存到：{filename}")


def main():
    """测试舆情分析系统"""
    logger.info("=" * 50)
    logger.info("舆情分析系统测试")
    logger.info("=" * 50)
    
    system = SentimentSystem()
    report = system.run_daily_analysis()
    
    logger.info("\n" + system.report_generator.format_report_for_feishu(report))


if __name__ == "__main__":
    main()
