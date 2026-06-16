#!/usr/bin/env python3
"""
实时监控系统
- 每5分钟检查一次策略信号
- 实时监控舆情，发现重大新闻立即预警
- 自动发送飞书通知
"""

import sys
import time
import json
import requests
from pathlib import Path
from datetime import datetime, time as dtime
from threading import Thread
import signal
import logging

sys.path.insert(0, str(Path(__file__).parent))

from qlib_vnpy_platform.core.data_bridge import DataBridge
from qlib_vnpy_platform.core.strategies import STRATEGY_REGISTRY, get_strategy
from qlib_vnpy_platform.core.news_fetcher import NewsFetcher
from qlib_vnpy_platform.core.sentiment_analyzer import SentimentAnalyzer, SentimentSystem
from qlib_vnpy_platform.core.llm_analyzer import LLManalyzer

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class RealTimeMonitor:
    """实时监控系统"""
    
    def __init__(self):
        self.symbol = "SZ002594"
        self.stock_name = "比亚迪"
        self.config = self._load_feishu_config()
        self.chat_id = self.config.get("chat_id", "oc_599b2776ddd142e49fa2b22aac449c3b")
        
        self.data_bridge = DataBridge()
        self.news_fetcher = NewsFetcher()
        self.sentiment_analyzer = SentimentAnalyzer()
        self.sentiment_system = SentimentSystem()
        self.llm_analyzer = LLManalyzer()
        
        self.check_interval = 300  # 5分钟检查一次
        self.last_news_check = None
        self.last_alert_ids = set()  # 避免重复发送
        
        self.running = True
        
        logger.info("实时监控系统初始化完成")
        logger.info(f"监控标的: {self.stock_name} ({self.symbol})")
        logger.info(f"检查间隔: {self.check_interval}秒 (5分钟)")
    
    def _load_feishu_config(self):
        """加载飞书配置"""
        config_file = Path(__file__).parent / 'feishu_config.json'
        if config_file.exists():
            with open(config_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}
    
    def _send_to_feishu(self, message):
        """发送飞书消息 - 使用统一 FeishuOutput 适配器"""
        from qlib_vnpy_platform.strategy_monitor_pkg import FeishuOutput
        feishu = FeishuOutput()
        success = feishu.send_message(message)
        if success:
            logger.info("飞书消息发送成功 (via relay API)")
            return True

        # fallback到飞书API直连
        logger.warning("中转API发送失败，尝试飞书API直连...")
        app_id = self.config.get('app_id')
        app_secret = self.config.get('app_secret')

        if not app_id or not app_secret:
            logger.error("飞书配置缺失")
            return False

        try:
            token_resp = requests.post(
                'https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal',
                json={'app_id': app_id, 'app_secret': app_secret},
                timeout=10
            )
            token_data = token_resp.json()
            if token_data.get('code') != 0:
                logger.error(f"获取token失败: {token_data}")
                return False

            token = token_data['tenant_access_token']
            body = {
                'zh_cn': {
                    'title': '实时监控预警',
                    'content': [[{'tag': 'md', 'text': message}]]
                }
            }

            msg_resp = requests.post(
                'https://open.feishu.cn/open-apis/im/v1/messages',
                params={'receive_id_type': 'chat_id'},
                headers={
                    'Authorization': f'Bearer {token}',
                    'Content-Type': 'application/json'
                },
                json={
                    'receive_id': self.chat_id,
                    'msg_type': 'post',
                    'content': json.dumps(body, ensure_ascii=False)
                },
                timeout=15
            )

            result = msg_resp.json()
            if result.get('code') == 0:
                logger.info("飞书消息发送成功 (via API)")
                return True
            else:
                logger.error(f"飞书发送失败: {result}")
                return False

        except Exception as e:
            logger.error(f"发送飞书消息异常: {e}")
            return False
    
    def _is_trading_hours(self):
        """检查是否在交易时间"""
        now = datetime.now()
        current_time = now.time()
        
        # 工作日
        if now.weekday() >= 5:
            return False
        
        # 上午: 9:30 - 11:30
        morning_start = dtime(9, 30)
        morning_end = dtime(11, 30)
        
        # 下午: 13:00 - 15:00
        afternoon_start = dtime(13, 0)
        afternoon_end = dtime(15, 0)
        
        in_morning = morning_start <= current_time <= morning_end
        in_afternoon = afternoon_start <= current_time <= afternoon_end
        
        return in_morning or in_afternoon
    
    def _check_strategy_signals(self):
        """检查策略信号"""
        logger.info("检查策略信号...")
        
        try:
            # 获取最新数据
            data = self.data_bridge.fetch_stock_daily(self.symbol)
            if data is None or data.empty:
                logger.warning("无法获取数据")
                return
            
            latest = data.iloc[-1]
            latest_price = latest['close']
            latest_date = str(latest.name)[:10] if hasattr(latest.name, '__str__') else str(latest.get('date', ''))[:10]
            
            signals = []
            
            # 检查所有策略
            for strategy_key in STRATEGY_REGISTRY.keys():
                try:
                    strategy = get_strategy(strategy_key)
                    result_df = strategy.generate_signals(data.copy())
                    
                    if result_df is None or result_df.empty:
                        continue
                    
                    last_row = result_df.iloc[-1]
                    signal_value = int(last_row.get("signal", 0))
                    signal_strength = float(last_row.get("signal_strength", 0))
                    
                    if signal_value == 1:
                        signal_type = "买入"
                    elif signal_value == -1:
                        signal_type = "卖出"
                    else:
                        signal_type = None
                    
                    if signal_type:
                        signals.append({
                            'strategy': strategy.name,
                            'type': signal_type,
                            'price': latest_price,
                            'strength': signal_strength
                        })
                        
                except Exception as e:
                    logger.debug(f"策略 {strategy_key} 检查失败: {e}")
            
            # 如果有信号，发送预警
            if signals:
                message = self._format_signal_alert(signals, latest_price, latest_date)
                self._send_to_feishu(message)
                logger.info(f"发送策略信号预警: {len(signals)}个")
            
            # 使用LLM进行综合分析
            if signals and self.llm_analyzer.is_available():
                self._analyze_with_llm(signals, data, news_text="")
            
            return signals
            
        except Exception as e:
            logger.error(f"检查策略信号失败: {e}")
            return []
    
    def _check_news_sentiment(self):
        """检查舆情（仅交易时间每小时检查）"""
        logger.info("检查舆情...")
        
        try:
            # 获取最新新闻
            news_list = self.news_fetcher.fetch_stock_news(self.symbol, max_news=20)
            
            if not news_list:
                return []
            
            # 检查是否有新新闻
            new_alerts = []
            for news in news_list[:5]:  # 只检查最新5条
                news_id = f"{news.get('title', '')}_{news.get('publish_time', '')}"
                
                if news_id in self.last_alert_ids:
                    continue
                
                self.last_alert_ids.add(news_id)
                
                # 分析情感
                text = news.get('title', '') + ' ' + news.get('content', '')
                sentiment = self.sentiment_analyzer.analyze(text)
                
                # 只对重大舆情发送预警
                if abs(sentiment['sentiment_score']) > 0.5 or sentiment['sentiment_strength'] >= 4:
                    alert = {
                        'news': news,
                        'sentiment': sentiment
                    }
                    new_alerts.append(alert)
            
            # 发送舆情预警
            if new_alerts:
                message = self._format_sentiment_alert(new_alerts)
                self._send_to_feishu(message)
                logger.info(f"发送舆情预警: {len(new_alerts)}条")
            
            # 使用LLM进行深度舆情分析
            if news_list and self.llm_analyzer.is_available():
                self._analyze_news_with_llm(news_list[:5])
            
            return new_alerts
            
        except Exception as e:
            logger.error(f"检查舆情失败: {e}")
            return []
    
    def _format_signal_alert(self, signals, price, date):
        """格式化策略信号预警"""
        lines = []
        lines.append(f"🚨 **策略信号预警**")
        lines.append(f"📅 时间: {date} {datetime.now().strftime('%H:%M:%S')}")
        lines.append(f"📈 {self.stock_name} 当前价: {price:.2f}")
        lines.append("")
        lines.append("━" * 25)
        
        buy_signals = [s for s in signals if s['type'] == '买入']
        sell_signals = [s for s in signals if s['type'] == '卖出']
        
        if buy_signals:
            lines.append(f"🟢 **买入信号 ({len(buy_signals)}个)**")
            for s in buy_signals:
                strength = '▓' * int(s['strength'] * 10)
                lines.append(f"• {s['strategy']} {strength}")
            lines.append("")
        
        if sell_signals:
            lines.append(f"🔴 **卖出信号 ({len(sell_signals)}个)**")
            for s in sell_signals:
                strength = '▓' * int(s['strength'] * 10)
                lines.append(f"• {s['strategy']} {strength}")
            lines.append("")
        
        lines.append("━" * 25)
        lines.append("⚠️ 请及时查看并决策")
        
        return "\n".join(lines)
    
    def _format_sentiment_alert(self, alerts):
        """格式化舆情预警"""
        lines = []
        lines.append(f"📰 **舆情重大预警**")
        lines.append(f"📅 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("")
        lines.append("━" * 25)
        
        for i, alert in enumerate(alerts, 1):
            news = alert['news']
            sentiment = alert['sentiment']
            
            emoji = "🟢" if sentiment['sentiment'] == 'positive' else "🔴" if sentiment['sentiment'] == 'negative' else "🟡"
            
            lines.append(f"{emoji} **{news.get('title', '无标题')[:40]}...**")
            lines.append(f"   来源: {news.get('source', '未知')}")
            lines.append(f"   情感: {sentiment['sentiment']} ({sentiment['sentiment_score']:.2f})")
            if sentiment['key_words']:
                lines.append(f"   关键词: {', '.join(sentiment['key_words'][:3])}")
            lines.append("")
        
        lines.append("━" * 25)
        lines.append("⚠️ 重大舆情，请密切关注")
        
        return "\n".join(lines)
    
    def _analyze_with_llm(self, signals, data, news_text=""):
        """使用LLM进行综合分析"""
        logger.info("使用LLM进行综合分析...")
        
        try:
            # 构建市场数据
            latest = data.iloc[-1]
            market_data = {
                "price": float(latest.get('close', 0)),
                "change_pct": float(latest.get('change_pct', 0)),
                "volume": int(latest.get('volume', 0)),
                "high": float(latest.get('high', 0)),
                "low": float(latest.get('low', 0)),
                "open": float(latest.get('open', 0)),
                "prev_close": float(latest.get('prev_close', 0)),
                "ma5": float(latest.get('ma5', 0)) if 'ma5' in latest else None,
                "ma10": float(latest.get('ma10', 0)) if 'ma10' in latest else None,
                "ma20": float(latest.get('ma20', 0)) if 'ma20' in latest else None,
                "rsi": float(latest.get('rsi', 0)) if 'rsi' in latest else None,
                "macd": float(latest.get('macd', 0)) if 'macd' in latest else None,
            }
            
            # 调用LLM分析
            result = self.llm_analyzer.analyze(
                stock_code=self.symbol,
                market_data=market_data,
                news_text=news_text,
                use_thinking=False
            )
            
            # 发送LLM分析结果
            if result.get('confidence', 0) >= 0.4:
                message = self._format_llm_analysis(result, signals)
                self._send_to_feishu(message)
                logger.info("LLM分析结果已发送")
        
        except Exception as e:
            logger.error(f"LLM分析失败: {e}")
    
    def _analyze_news_with_llm(self, news_list):
        """使用LLM分析新闻舆情"""
        logger.info("使用LLM分析新闻舆情...")
        
        if not self.llm_analyzer.is_available():
            return
        
        try:
            # 合并最新的新闻
            news_text = "\n\n".join([f"{news.get('title', '')}\n{news.get('content', '')[:200]}..." 
                                    for news in news_list[:3]])
            
            if not news_text:
                return
            
            # 调用LLM分析
            result = self.llm_analyzer.analyze_news(
                news_text=news_text,
                stock_code=self.symbol
            )
            
            # 如果影响因子较大，发送预警
            impact_factor = result.get('stock_impact_factor', 0)
            if abs(impact_factor) >= 0.5:
                message = self._format_llm_news_analysis(result, news_list[:3])
                self._send_to_feishu(message)
                logger.info("LLM舆情分析结果已发送")
        
        except Exception as e:
            logger.error(f"LLM新闻分析失败: {e}")
    
    def _format_llm_analysis(self, analysis, signals):
        """格式化LLM分析结果"""
        lines = []
        lines.append(f"🤖 **LLM智能分析报告**")
        lines.append(f"📅 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"🎯 标的: {self.stock_name} ({self.symbol})")
        lines.append("")
        lines.append("━" * 30)
        
        # 分析信号
        signal = analysis.get('signal', 'HOLD')
        confidence = analysis.get('confidence', 0)
        emoji = "🟢" if signal == "BUY" else "🔴" if signal == "SELL" else "🟡"
        
        lines.append(f"{emoji} **综合信号: {signal}**")
        lines.append(f"   置信度: {'▓' * int(confidence * 10)}{'░' * (10 - int(confidence * 10))} {confidence:.2f}")
        lines.append("")
        
        # 目标价和止损价
        target_price = analysis.get('target_price')
        stop_loss = analysis.get('stop_loss')
        
        if target_price:
            lines.append(f"🎯 目标价: {target_price:.2f}")
        if stop_loss:
            lines.append(f"🛡️ 止损价: {stop_loss:.2f}")
        
        # 风险等级
        risk_level = analysis.get('risk_level', 'MEDIUM')
        risk_emoji = "🟢" if risk_level == "LOW" else "🟡" if risk_level == "MEDIUM" else "🔴"
        lines.append(f"{risk_emoji} 风险等级: {risk_level}")
        lines.append("")
        
        # 分析理由
        reason = analysis.get('reason', '')
        if reason:
            lines.append(f"📝 分析理由:")
            lines.append(f"   {reason}")
            lines.append("")
        
        # 关键因素
        key_factors = analysis.get('key_factors', [])
        if key_factors:
            lines.append(f"🔑 关键因素:")
            for i, factor in enumerate(key_factors, 1):
                lines.append(f"   {i}. {factor}")
            lines.append("")
        
        # 触发策略
        lines.append(f"📊 触发策略 ({len(signals)}个):")
        for s in signals[:5]:
            signal_emoji = "🟢" if s['type'] == '买入' else "🔴"
            lines.append(f"   {signal_emoji} {s['strategy']}")
        
        lines.append("")
        lines.append("━" * 30)
        lines.append("⚠️ 以上分析仅供参考，投资有风险")
        
        return "\n".join(lines)
    
    def _format_llm_news_analysis(self, analysis, news_list):
        """格式化LLM新闻分析结果"""
        lines = []
        lines.append(f"🧠 **LLM舆情深度分析**")
        lines.append(f"📅 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"🎯 标的: {self.stock_name}")
        lines.append("")
        lines.append("━" * 30)
        
        # 情感分析结果
        sentiment = analysis.get('sentiment', 'NEUTRAL')
        impact_level = analysis.get('impact_level', 'LOW')
        impact_factor = analysis.get('stock_impact_factor', 0)
        confidence = analysis.get('confidence', 0)
        
        sentiment_emoji = "🟢" if sentiment == "POSITIVE" else "🔴" if sentiment == "NEGATIVE" else "🟡"
        impact_emoji = "🔥" if impact_level == "HIGH" else "⚡" if impact_level == "MEDIUM" else "💧"
        
        lines.append(f"{sentiment_emoji} **情感倾向: {sentiment}**")
        lines.append(f"{impact_emoji} **影响程度: {impact_level}**")
        lines.append(f"📈 股价影响因子: {impact_factor:+.2f}")
        lines.append(f"🎯 分析置信度: {confidence:.2f}")
        lines.append("")
        
        # 影响时长
        duration = analysis.get('impact_duration', 'SHORT_TERM')
        duration_map = {
            'SHORT_TERM': '短期（1-3天）',
            'MEDIUM_TERM': '中期（1-2周）',
            'LONG_TERM': '长期（2周以上）'
        }
        lines.append(f"⏱️ 影响时长: {duration_map.get(duration, duration)}")
        lines.append("")
        
        # 关键要点
        key_points = analysis.get('key_points', [])
        if key_points:
            lines.append(f"🔍 核心要点:")
            for i, point in enumerate(key_points, 1):
                lines.append(f"   {i}. {point}")
            lines.append("")
        
        # 相关新闻
        lines.append(f"📰 相关新闻 ({len(news_list)}条):")
        for news in news_list:
            lines.append(f"   • {news.get('title', '无标题')[:50]}...")
        
        lines.append("")
        lines.append("━" * 30)
        lines.append("⚠️ 舆情分析仅供参考，决策需谨慎")
        
        return "\n".join(lines)
    
    def _run_trading_hours_monitor(self):
        """交易时间监控主循环"""
        logger.info("启动交易时间监控...")
        
        while self.running:
            if self._is_trading_hours():
                # 检查策略信号
                self._check_strategy_signals()
                
                # 每小时检查一次舆情
                current_hour = datetime.now().hour
                if self.last_news_check != current_hour:
                    self._check_news_sentiment()
                    self.last_news_check = current_hour
                
                # 等待下次检查
                logger.info(f"下次检查在 {self.check_interval}秒 后...")
                for _ in range(self.check_interval):
                    if not self.running:
                        break
                    time.sleep(1)
            else:
                logger.debug("非交易时间，等待中...")
                time.sleep(60)  # 非交易时间每分钟检查一次
    
    def _run_full_day_monitor(self):
        """全天监控（舆情）"""
        logger.info("启动全天舆情监控...")
        
        while self.running:
            # 每30分钟检查一次舆情
            logger.info("检查舆情（盘后/盘前）...")
            self._check_news_sentiment()
            time.sleep(1800)  # 30分钟
    
    def start(self, trading_hours_only=False):
        """启动监控"""
        logger.info("=" * 60)
        logger.info("🤖 实时监控系统启动")
        logger.info("=" * 60)
        
        # 发送启动通知
        self._send_to_feishu(
            f"✅ 实时监控系统已启动\n"
            f"📅 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"🎯 监控标的: {self.stock_name}\n"
            f"⏰ 检查间隔: 每{self.check_interval // 60}分钟"
        )
        
        if trading_hours_only:
            self._run_trading_hours_monitor()
        else:
            # 同时启动交易时间监控和全天舆情监控
            strategy_thread = Thread(target=self._run_trading_hours_monitor, daemon=True)
            sentiment_thread = Thread(target=self._run_full_day_monitor, daemon=True)
            
            strategy_thread.start()
            sentiment_thread.start()
            
            try:
                while self.running:
                    time.sleep(10)
            except KeyboardInterrupt:
                self.stop()
    
    def stop(self):
        """停止监控"""
        logger.info("正在停止监控系统...")
        self.running = False
        self._send_to_feishu(
            f"🛑 实时监控系统已停止\n"
            f"📅 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )


def signal_handler(signum, frame):
    """处理退出信号"""
    print("\n收到退出信号，正在停止...")
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    monitor = RealTimeMonitor()
    
    # 全天监控（包括盘前盘后）
    monitor.start(trading_hours_only=False)
