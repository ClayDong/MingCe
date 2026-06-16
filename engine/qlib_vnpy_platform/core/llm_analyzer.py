import ast
import json
import re
import time
from loguru import logger
from openai import OpenAI
from qlib_vnpy_platform.config import get_config


class LLManalyzer:
    SYSTEM_PROMPT = """你是一位资深量化交易分析师，专注于A股市场技术分析和舆情分析。

你的核心职责：
1. 结合21种量化策略信号和技术指标进行综合分析
2. 分析新闻舆情对股价的影响程度
3. 识别市场情绪和机构动向
4. 严格执行策略，不受情绪干扰

专业术语要求：
- 使用标准技术分析术语（MA、MACD、RSI、布林带、KDJ等）
- 量化描述信号强度（置信度0.0-1.0）
- 明确标注风险等级（LOW/MEDIUM/HIGH）

重要原则：
- 置信度低于0.4时建议HOLD
- 技术面与消息面矛盾时以技术面为准
- 强调止损纪律，止损价必须设置
- 不预测大盘，只分析个股

输出格式（严格JSON，不要包裹在代码块中）：
{
  "signal": "BUY" | "SELL" | "HOLD",
  "confidence": 0.0-1.0,
  "reason": "分析理由（100字以内）",
  "target_price": 目标价（数字）,
  "stop_loss": 止损价（数字）,
  "risk_level": "LOW" | "MEDIUM" | "HIGH",
  "key_factors": ["关键因素1", "关键因素2", "关键因素3"]
}"""

    TRADING_SYSTEM_PROMPT = """你是一位量化交易策略专家，专注于比亚迪(SZ002594)的交易策略分析。

分析背景：
- 股票代码：SZ002594（比亚迪）
- 交易市场：A股（深圳证券交易所）
- 股票性质：新能源汽车龙头股，受政策影响大，波动性高
- 交易时间：上午9:30-11:30，下午13:00-15:00

核心策略体系（21个策略）：
技术指标策略（19个）：
1. 均线金叉/死叉策略
2. MACD策略
3. RSI超买超卖策略
4. 布林带策略
5. KDJ随机指标策略
6. 成交量异常策略
7. 价格突破策略
8. 趋势跟踪策略
9. 动量策略
10. 波动率策略
11. 支撑阻力策略
12. 形态识别策略
13. 量价配合策略
14. 多周期共振策略
15. 均线粘合策略
16. MACD背离策略
17. RSI背离策略
18. 成交量萎缩策略
19. 价格异动策略

舆情策略（2个）：
20. 舆情利好/利空策略
21. 舆情反转策略（别人恐惧我贪婪）

策略执行原则：
- 严格按照策略信号执行，不受情绪影响
- 多策略共振时置信度更高
- 技术面与舆情面矛盾时，以技术面为主
- 始终设置止损，止损比例建议2-3%

输出格式（严格JSON）：
{
  "recommended_strategy": "策略名称",
  "entry_condition": "入场条件描述",
  "exit_condition": "出场条件描述",
  "position_size": "建议仓位比例（如30%）",
  "risk_warning": "风险提示",
  "confidence": 0.0-1.0,
  "reasoning": "选择该策略的理由（200字以内）"
}"""

    NEWS_ANALYSIS_PROMPT = """你是一位专业的金融舆情分析师，擅长分析新闻对股价的影响。

分析要求：
1. 判断新闻的性质（利好/利空/中性）
2. 评估影响程度（短期/中期/长期）
3. 识别受影响板块
4. 评估机构持仓反应
5. 判断舆论真假和炒作程度

比亚迪相关关键信息：
- 主营业务：新能源汽车、动力电池、手机代工
- 政策敏感性：高（补贴政策、限购政策影响大）
- 竞争格局：特斯拉、蔚来、小鹏、理想等
- 供应链：原材料价格（锂、钴、镍）影响成本

情感词典（参考）：
利好词汇：突破、增长、夺冠、全球领先、供不应求、订单大增、产能扩张
利空词汇：召回、诉讼、竞争加剧、产能过剩、降价、政策收紧

输出格式（严格JSON）：
{
  "sentiment": "POSITIVE" | "NEGATIVE" | "NEUTRAL",
  "impact_level": "HIGH" | "MEDIUM" | "LOW",
  "impact_duration": "SHORT_TERM" | "MEDIUM_TERM" | "LONG_TERM",
  "key_points": ["要点1", "要点2", "要点3"],
  "stock_impact_factor": -1.0至1.0,
  "confidence": 0.0-1.0
}"""

    def __init__(self):
        self.config = get_config()["llm"]
        self.api_key = self.config["api_key"]
        self.base_url = self.config["base_url"]
        self._api_key_validated = False
        self._api_key_valid = False
        self._client = None
        self.model = self.config["model"]
        self.thinking_model = self.config.get("thinking_model", self.model)
        self.max_tokens = self.config.get("max_tokens", 4096)
        self.temperature = self.config.get("temperature", 0.3)
        self.timeout = self.config.get("timeout", 60)
        self._call_count = 0
        self._total_tokens = 0
        
        self._init_client()
        logger.info(f"LLManalyzer initialized with model: {self.model}")

    def _init_client(self):
        if not self.api_key or len(self.api_key) < 10 or self.api_key.startswith("${"):
            logger.warning("LLM API key is missing or invalid - LLM analysis will be skipped")
            self._api_key_validated = True
            self._api_key_valid = False
            return
        
        try:
            self._client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
            )
            self._api_key_validated = True
            self._api_key_valid = True
        except Exception as e:
            logger.error(f"Failed to initialize OpenAI client: {e}")
            self._api_key_validated = True
            self._api_key_valid = False

    def is_available(self) -> bool:
        return self._api_key_valid and self._client is not None

    def get_model_name(self) -> str:
        return self.model

    def analyze(self, stock_code: str, market_data: dict,
                news_text: str = "", qlib_pred: float = None,
                use_thinking: bool = False) -> dict:
        
        if not self.is_available():
            logger.warning("LLM is not available, returning default HOLD signal")
            return {
                "signal": "HOLD",
                "confidence": 0.0,
                "reason": "LLM服务不可用（API Key无效或初始化失败）",
                "target_price": None,
                "stop_loss": None,
                "risk_level": "HIGH",
                "key_factors": [],
                "error": "LLM unavailable",
            }

        model = self.thinking_model if use_thinking else self.model
        user_prompt = self._build_prompt(stock_code, market_data, news_text, qlib_pred)

        try:
            start_time = time.time()
            response = self._client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                timeout=self.timeout,
            )
            elapsed = time.time() - start_time

            content = response.choices[0].message.content.strip()
            usage = response.usage
            self._call_count += 1
            self._total_tokens += usage.total_tokens if usage else 0

            logger.info(f"LLM call #{self._call_count}: model={model}, "
                       f"tokens={usage.total_tokens if usage else 'N/A'}, "
                       f"time={elapsed:.2f}s")

            result = self._parse_response(content)
            result["model"] = model
            result["response_time"] = elapsed
            result["raw_content"] = content
            return result

        except Exception as e:
            logger.error(f"LLM analysis failed: {e}")
            error_msg = str(e)
            if "401" in error_msg or "invalid_api_key" in error_msg:
                self._api_key_valid = False
                logger.error("LLM API key invalid, future calls will be skipped")
            
            return {
                "signal": "HOLD",
                "confidence": 0.0,
                "reason": f"LLM分析失败: {error_msg}",
                "target_price": None,
                "stop_loss": None,
                "risk_level": "HIGH",
                "key_factors": [],
                "error": error_msg,
            }

    def _build_prompt(self, stock_code: str, market_data: dict,
                      news_text: str, qlib_pred: float) -> str:
        parts = [f"股票代码：{stock_code}"]

        if market_data:
            price = market_data.get("price", "N/A")
            change_pct = market_data.get("change_pct", "N/A")
            volume = market_data.get("volume", "N/A")
            high = market_data.get("high", "N/A")
            low = market_data.get("low", "N/A")
            open_price = market_data.get("open", "N/A")
            prev_close = market_data.get("prev_close", "N/A")

            parts.append(f"\n当前行情：")
            parts.append(f"  最新价: {price}, 涨跌幅: {change_pct}%")
            parts.append(f"  今开: {open_price}, 昨收: {prev_close}")
            parts.append(f"  最高: {high}, 最低: {low}")
            parts.append(f"  成交量: {volume}")

            ma5 = market_data.get("ma5")
            ma10 = market_data.get("ma10")
            ma20 = market_data.get("ma20")
            rsi = market_data.get("rsi")
            macd = market_data.get("macd")
            macd_signal = market_data.get("macd_signal")
            boll_upper = market_data.get("boll_upper")
            boll_lower = market_data.get("boll_lower")

            tech_parts = ["\n技术指标："]
            if ma5 is not None:
                tech_parts.append(f"  MA5: {ma5:.2f}")
            if ma10 is not None:
                tech_parts.append(f"  MA10: {ma10:.2f}")
            if ma20 is not None:
                tech_parts.append(f"  MA20: {ma20:.2f}")
            if rsi is not None:
                tech_parts.append(f"  RSI(14): {rsi:.2f}")
            if macd is not None:
                tech_parts.append(f"  MACD: {macd:.4f}")
            if macd_signal is not None:
                tech_parts.append(f"  MACD信号: {macd_signal:.4f}")
            if boll_upper is not None:
                tech_parts.append(f"  布林上轨: {boll_upper:.2f}")
            if boll_lower is not None:
                tech_parts.append(f"  布林下轨: {boll_lower:.2f}")

            if len(tech_parts) > 1:
                parts.extend(tech_parts)

        if qlib_pred is not None:
            parts.append(f"\nQLib模型预测分数：{qlib_pred:.4f}（0~1，越高越看涨）")

        if news_text:
            parts.append(f"\n近期资讯：\n{news_text}")
        else:
            parts.append("\n近期资讯：暂无相关资讯")

        return "\n".join(parts)

    def _parse_response(self, content: str) -> dict:
        content = content.strip()
        if content.startswith("```"):
            content = re.sub(r'^```\w*\n?', '', content)
            content = re.sub(r'\n?```$', '', content)
            content = content.strip()

        try:
            result = json.loads(content)
        except json.JSONDecodeError:
            json_match = re.search(r'\{[\s\S]*\}', content)
            if json_match:
                extracted = json_match.group()
                try:
                    result = json.loads(extracted)
                except json.JSONDecodeError:
                    try:
                        result = ast.literal_eval(extracted)
                        if not isinstance(result, dict):
                            raise ValueError
                    except (ValueError, SyntaxError):
                        logger.warning(f"Failed to parse LLM response: {content[:200]}")
                        return {
                            "signal": "HOLD",
                            "confidence": 0.0,
                            "reason": "LLM输出格式解析失败",
                            "target_price": None,
                            "stop_loss": None,
                            "risk_level": "HIGH",
                            "key_factors": [],
                        }
            else:
                return {
                    "signal": "HOLD",
                    "confidence": 0.0,
                    "reason": "LLM输出格式解析失败",
                    "target_price": None,
                    "stop_loss": None,
                    "risk_level": "HIGH",
                    "key_factors": [],
                }

        required_fields = ["signal", "confidence", "reason"]
        for field in required_fields:
            if field not in result:
                result[field] = "HOLD" if field == "signal" else (0.0 if field == "confidence" else "")

        if result["signal"] not in ["BUY", "SELL", "HOLD"]:
            result["signal"] = "HOLD"

        try:
            result["confidence"] = float(result["confidence"])
            result["confidence"] = max(0.0, min(1.0, result["confidence"]))
        except (ValueError, TypeError):
            result["confidence"] = 0.0

        if "risk_level" not in result or result["risk_level"] not in ["LOW", "MEDIUM", "HIGH"]:
            result["risk_level"] = "MEDIUM"

        if "key_factors" not in result:
            result["key_factors"] = []

        for price_field in ["target_price", "stop_loss"]:
            if price_field in result and result[price_field] is not None:
                try:
                    result[price_field] = float(result[price_field])
                except (ValueError, TypeError):
                    result[price_field] = None

        return result

    def generate_strategy_advice(self, symbol: str, backtest_results: list,
                                  regime: dict, market_data: dict = None) -> dict:
        if not self.is_available():
            return {"error": "LLM服务不可用", "advice": "", "recommended_strategies": []}

        strategy_summary = []
        for r in backtest_results:
            if "error" in r:
                continue
            m = r.get("metrics", {})
            ls = r.get("latest_signals", {})
            strategy_summary.append({
                "name": r["strategy"]["name"],
                "return": m.get("total_return", 0),
                "sharpe": m.get("sharpe_ratio", 0),
                "max_drawdown": m.get("max_drawdown", 0),
                "win_rate": m.get("win_rate", 0),
                "trades": m.get("total_trades", 0),
                "latest_signal": ls.get("next_action", ""),
                "signal_strength": ls.get("signal_strength", 0),
            })

        prompt = f"""分析股票 {symbol} 的量化策略表现，给出策略建议。

当前市场状态：{regime.get('regime', 'unknown')}
趋势强度：{regime.get('trend_strength', 0):.2f}
波动率：{regime.get('volatility', 0):.4f}

各策略回测结果：
{json.dumps(strategy_summary[:10], ensure_ascii=False, indent=2)}

请基于以上数据，给出：
1. 当前最适合该股的策略（从上述策略中选择）
2. 入场时机建议
3. 出场条件建议
4. 风险提示

严格输出JSON格式（不要包裹在代码块中）：
{{
  "recommended_strategy": "策略名称",
  "entry_condition": "入场条件描述",
  "exit_condition": "出场条件描述",
  "position_size": "建议仓位比例（如30%）",
  "risk_warning": "风险提示",
  "confidence": 0.0-1.0,
  "reasoning": "选择该策略的理由（200字以内）"
}}"""

        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "你是一位专业量化策略分析师，擅长根据回测数据和市场状态推荐最优策略。"},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                timeout=self.timeout,
            )
            content = response.choices[0].message.content.strip()
            result = self._parse_strategy_response(content)
            result["symbol"] = symbol
            result["regime"] = regime.get("regime", "unknown")
            return result
        except Exception as e:
            logger.error(f"LLM strategy generation failed: {e}")
            return {"error": str(e), "advice": "", "recommended_strategies": []}

    def _parse_strategy_response(self, content: str) -> dict:
        content = content.strip()
        if content.startswith("```"):
            content = re.sub(r'^```\w*\n?', '', content)
            content = re.sub(r'\n?```$', '', content)
            content = content.strip()
        try:
            result = json.loads(content)
        except json.JSONDecodeError:
            json_match = re.search(r'\{[\s\S]*\}', content)
            if json_match:
                extracted = json_match.group()
                try:
                    result = json.loads(extracted)
                except json.JSONDecodeError:
                    try:
                        result = ast.literal_eval(extracted)
                        if not isinstance(result, dict):
                            raise ValueError
                    except (ValueError, SyntaxError):
                        return {"advice": content, "recommended_strategies": []}
            else:
                return {"advice": content, "recommended_strategies": []}

        required = ["recommended_strategy", "entry_condition", "exit_condition"]
        for field in required:
            if field not in result:
                result[field] = ""
        if "confidence" not in result:
            result["confidence"] = 0.5
        return result

    def get_stats(self) -> dict:
        return {
            "total_calls": self._call_count,
            "total_tokens": self._total_tokens,
            "model": self.model,
            "available": self.is_available(),
        }

    def analyze_news(self, news_text: str, stock_code: str = "SZ002594") -> dict:
        """使用LLM分析新闻舆情"""
        if not self.is_available():
            logger.warning("LLM is not available for news analysis")
            return {
                "sentiment": "NEUTRAL",
                "impact_level": "LOW",
                "impact_duration": "SHORT_TERM",
                "key_points": [],
                "stock_impact_factor": 0.0,
                "confidence": 0.0,
                "error": "LLM unavailable",
            }

        user_prompt = f"""股票代码：{stock_code}

请分析以下新闻对比亚迪股价的影响：

{news_text}

请从专业量化分析师角度，分析这条新闻的影响。"""

        try:
            start_time = time.time()
            response = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.NEWS_ANALYSIS_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                timeout=self.timeout,
            )
            elapsed = time.time() - start_time

            content = response.choices[0].message.content.strip()
            usage = response.usage
            self._call_count += 1
            self._total_tokens += usage.total_tokens if usage else 0

            logger.info(f"LLM news analysis call #{self._call_count}: "
                       f"tokens={usage.total_tokens if usage else 'N/A'}, time={elapsed:.2f}s")

            result = self._parse_news_response(content)
            result["model"] = self.model
            result["response_time"] = elapsed
            result["raw_content"] = content
            return result

        except Exception as e:
            logger.error(f"LLM news analysis failed: {e}")
            return {
                "sentiment": "NEUTRAL",
                "impact_level": "LOW",
                "impact_duration": "SHORT_TERM",
                "key_points": [],
                "stock_impact_factor": 0.0,
                "confidence": 0.0,
                "error": str(e),
            }

    def _parse_news_response(self, content: str) -> dict:
        """解析新闻分析响应"""
        content = content.strip()
        if content.startswith("```"):
            content = re.sub(r'^```\w*\n?', '', content)
            content = re.sub(r'\n?```$', '', content)
            content = content.strip()

        try:
            result = json.loads(content)
        except json.JSONDecodeError:
            json_match = re.search(r'\{[\s\S]*\}', content)
            if json_match:
                extracted = json_match.group()
                try:
                    result = json.loads(extracted)
                except json.JSONDecodeError:
                    try:
                        result = ast.literal_eval(extracted)
                        if not isinstance(result, dict):
                            raise ValueError
                    except (ValueError, SyntaxError):
                        logger.warning(f"Failed to parse LLM news response: {content[:200]}")
                        return {
                            "sentiment": "NEUTRAL",
                            "impact_level": "LOW",
                            "impact_duration": "SHORT_TERM",
                            "key_points": [],
                            "stock_impact_factor": 0.0,
                            "confidence": 0.0,
                        }
            else:
                return {
                    "sentiment": "NEUTRAL",
                    "impact_level": "LOW",
                    "impact_duration": "SHORT_TERM",
                    "key_points": [],
                    "stock_impact_factor": 0.0,
                    "confidence": 0.0,
                }

        if "sentiment" not in result:
            result["sentiment"] = "NEUTRAL"
        if result["sentiment"] not in ["POSITIVE", "NEGATIVE", "NEUTRAL"]:
            result["sentiment"] = "NEUTRAL"

        if "impact_level" not in result or result["impact_level"] not in ["HIGH", "MEDIUM", "LOW"]:
            result["impact_level"] = "LOW"

        if "impact_duration" not in result or result["impact_duration"] not in ["SHORT_TERM", "MEDIUM_TERM", "LONG_TERM"]:
            result["impact_duration"] = "SHORT_TERM"

        if "stock_impact_factor" not in result:
            result["stock_impact_factor"] = 0.0
        else:
            try:
                result["stock_impact_factor"] = max(-1.0, min(1.0, float(result["stock_impact_factor"])))
            except (ValueError, TypeError):
                result["stock_impact_factor"] = 0.0

        if "confidence" not in result:
            result["confidence"] = 0.0
        else:
            try:
                result["confidence"] = max(0.0, min(1.0, float(result["confidence"])))
            except (ValueError, TypeError):
                result["confidence"] = 0.0

        if "key_points" not in result or not isinstance(result["key_points"], list):
            result["key_points"] = []

        return result

