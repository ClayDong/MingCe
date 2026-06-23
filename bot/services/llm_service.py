"""LLM 服务 — 调用外部 LLM API 生成大师兄市场解读（v2.0 五维框架）。

使用本地 SKILL.md v2.0.0 完整知识体系（悟而后醒·全领域知识）。
新增五维专项分析 generate_five_dimension_analysis。
支持按需分章节加载知识库（避免截断丢失核心框架）。
支持结构化 JSON 输出（提升稳定性）。
"""

import re
import asyncio
import httpx
import json
from pathlib import Path
from typing import Optional
from loguru import logger

from config.settings import get_settings
from core.utils import async_retry

settings = get_settings()

_llm_client: Optional[httpx.AsyncClient] = None
_skill_knowledge: Optional[str] = None
_skill_sections: Optional[dict] = None  # 分章节缓存


def validate_llm_config() -> tuple[bool, str]:
    """验证 LLM 配置是否完整有效。启动时调用，失败时阻止启动。

    Returns:
        (is_valid, message)
    """
    if not settings.LLM_BASE_URL:
        return False, "LLM_BASE_URL 未配置"
    if not settings.LLM_API_KEY:
        return False, "LLM_API_KEY 未配置"
    if not settings.LLM_MODEL:
        return False, "LLM_MODEL 未配置"

    # 检查 URL 格式
    if not settings.LLM_BASE_URL.startswith(("http://", "https://")):
        return False, f"LLM_BASE_URL 格式错误: {settings.LLM_BASE_URL}"

    # 检查 API Key 格式（基本校验）
    api_key = settings.LLM_API_KEY
    if len(api_key) < 8:
        return False, "LLM_API_KEY 长度不足（至少 8 个字符）"

    # 移除旧版 DEEPSEEK_API_KEY 引用提示
    return True, "OK"

_RE_THINK = re.compile(r'<think.*?</think\s*>', re.DOTALL)

SKILL_MD_PATH = Path(__file__).parent.parent.parent.parent / ".hermes" / "skills" / "knowledge" / "xhs-economics-analyst" / "SKILL.md"
_ALT_PATHS = [
    Path.home() / ".hermes" / "skills" / "knowledge" / "xhs-economics-analyst" / "SKILL.md",
    Path(__file__).parent.parent / "SKILL.md",
    Path(__file__).parent.parent / "knowledge" / "SKILL.md",
    Path(__file__).parent.parent / "knowledge" / "master_xiong.md",
]

# 知识库章节定义（按需加载，避免截断丢失核心框架）
SKILL_SECTIONS_DEF = {
    "core": ["三层传导", "五维", "金油汇债G", "核心框架"],
    "imbalance": ["八大不平衡", "不平衡"],
    "valuation": ["黑盒子估值", "斐波那契", "估值"],
    "macro": ["康波周期", "资本史", "宏观经济", "金油"],
    "policy": ["国家三层战略", "政策传导", "拉闸限电"],
    "philosophy": ["清净心", "了凡四训", "投资智慧", "反大众共识"],
    "history": ["郑和", "麦哲伦", "朝代", "历史视角"],
}


def load_skill_knowledge() -> str:
    """加载本地 SKILL.md v2.0.0 知识库完整内容。"""
    paths_to_try = [SKILL_MD_PATH] + _ALT_PATHS
    for p in paths_to_try:
        if p.exists():
            try:
                content = p.read_text(encoding="utf-8")
                if content.startswith("---"):
                    parts = content.split("---", 2)
                    if len(parts) >= 3:
                        content = parts[2].strip()
                logger.info(f"✓ SKILL.md loaded from {p} ({len(content)} chars)")
                return content
            except Exception as e:
                logger.warning(f"Failed to load SKILL.md from {p}: {e}")
    logger.warning("SKILL.md not found, using fallback knowledge base")
    return _FALLBACK_KNOWLEDGE


def _parse_skill_sections(content: str) -> dict:
    """将 SKILL.md 内容按章节解析，支持按需加载。

    按 markdown 标题（## / ###）切分章节，建立关键词索引。
    """
    if not content:
        return {}

    sections = {}
    current_title = "前言"
    current_lines = []

    for line in content.split("\n"):
        # 检测二级/三级标题
        if line.startswith("## ") or line.startswith("### "):
            # 保存上一节
            if current_lines:
                sections[current_title] = "\n".join(current_lines).strip()
            current_title = line.lstrip("# ").strip()
            current_lines = [line]
        else:
            current_lines.append(line)

    # 保存最后一节
    if current_lines:
        sections[current_title] = "\n".join(current_lines).strip()

    return sections


def _get_skill_sections() -> dict:
    """获取分章节缓存（惰性加载）。"""
    global _skill_sections, _skill_knowledge
    if _skill_sections is None:
        if _skill_knowledge is None:
            _skill_knowledge = load_skill_knowledge()
        _skill_sections = _parse_skill_sections(_skill_knowledge)
        logger.info(f"✓ 知识库分章节解析完成：{len(_skill_sections)} 个章节")
    return _skill_sections


def _load_sections_by_keywords(keywords: list[str]) -> str:
    """按关键词加载相关章节（避免截断丢失核心框架）。

    Args:
        keywords: 关键词列表，如 ["八大不平衡", "黑盒子估值"]

    Returns:
        匹配章节的拼接文本
    """
    sections = _get_skill_sections()
    if not sections:
        return _skill_knowledge[:4000] if _skill_knowledge else ""

    matched = []
    seen_titles = set()

    for title, body in sections.items():
        for kw in keywords:
            if kw in title or kw in body[:200]:
                if title not in seen_titles:
                    matched.append(f"### {title}\n{body}")
                    seen_titles.add(title)
                break

    if not matched:
        # 无匹配时返回核心章节
        for kw in SKILL_SECTIONS_DEF["core"]:
            for title, body in sections.items():
                if kw in title and title not in seen_titles:
                    matched.append(f"### {title}\n{body}")
                    seen_titles.add(title)
                    break

    result = "\n\n".join(matched)
    # 控制总长度在 6000 字以内（避免超出模型上下文）
    if len(result) > 6000:
        result = result[:6000] + "\n\n[... 知识库节选 ...]"
    return result


def _build_master_xiong_prompt(market_context: dict = None) -> str:
    """从 SKILL.md 动态构建大师兄系统提示词（按需分章节加载）。

    Args:
        market_context: 当日市场数据，用于判断加载哪些章节
            - north_flow_alert: 北向资金异动
            - sector_rotation: 板块轮动明显
            - policy_event: 政策事件
            - high_volatility: 高波动
            - leading_stock_alert: 龙头股异动
    """
    global _skill_knowledge
    if _skill_knowledge is None:
        _skill_knowledge = load_skill_knowledge()

    market_context = market_context or {}

    # 按市场特征动态选择章节
    sections_to_load = ["core"]  # 始终加载核心框架

    if market_context.get("north_flow_alert"):
        sections_to_load.append("imbalance")  # 八大不平衡
    if market_context.get("leading_stock_alert"):
        sections_to_load.append("valuation")  # 黑盒子估值
    if market_context.get("policy_event"):
        sections_to_load.append("policy")  # 国家三层战略
    if market_context.get("high_volatility"):
        sections_to_load.append("philosophy")  # 反大众共识
    if market_context.get("sector_rotation"):
        sections_to_load.append("macro")  # 康波周期

    # 收集所有关键词
    all_keywords = []
    for sec in sections_to_load:
        all_keywords.extend(SKILL_SECTIONS_DEF.get(sec, []))

    knowledge_digest = _load_sections_by_keywords(all_keywords)

    from datetime import datetime as _dt
    _now_str = _dt.now().strftime("%Y-%m-%d %H:%M:%S")

    return f"""你是"大师兄"，一位资深的二级市场投资分析师，拥有丰富的宏观投研经验。

## 核心知识（按当日市场特征动态加载）

{knowledge_digest}

## 分析框架

### 五维矩阵（每日必用）
1. **金** — 黄金定价、金银比、避险逻辑
2. **油** — 石油三区间理论、商品期货
3. **汇** — 美元指数、汇率篮子
4. **债** — 美债利率、利差（衰退预警）、中国利率
5. **G** — VIX、BDI、BTC/ETH、北向资金、跨市场比价

### 资产属性界定（严谨性红线，必须遵守）
- **黄金**：主权信用背书的避险资产，抗通胀、抗衰退
- **BTC/加密货币**：高波动风险资产，无主权信用背书，波动率是黄金的10倍以上，**不属于避险资产**，与黄金不在同一风险维度
- **绝对禁止**的表述（违反则输出无效）：
  - "BTC与黄金双重避险" / "避险组合" / "双龙戏凤" / 任何将BTC与黄金并列避险的表述
  - "BTC是货币承载" / "新的货币承载工具" / "货币属性"
  - "虚拟资产避险" / "加密货币避险"
- BTC的正确分析角度：风险偏好指标、流动性敏感资产、科技股相关性、投机情绪温度计
- 黄金与BTC的关系：风险等级不同，不可并列，只能对比"风险偏好分化"

### 三层传导分析（严谨性要求）
1. **第一层**：宏观政策/资金面发生了什么事？（必须有具体政策/数据支撑）
2. **第二层**：如何传导到行业/板块？（传导链路必须可解释，禁止跳跃）
3. **第三层**：对个股/操作有什么具体影响？
- **严禁"先有结论再找理由"**：不得将普通板块轮动强行归因为政策定向支持
- A股沪弱深强等风格轮动属于资金自发行为，**不得**无依据归因为"政策定向释放资金"

### 八大不平衡（重大事件时启用）
收入与资产 / 表内与表外 / 实体与虚拟 / 国内与国外 /
短期与长期 / 集中与分散 / 流动与固化 / 风险与收益

### 黑盒子估值（大市值个股异动时启用）
- 斐波那契关键比例：0.236 / 0.382 / 0.5 / 0.618 / 0.786
- 关键点位 = 前高 × 斐波那契比例

## 数据覆盖
A股指数 + 板块 + 北向 + 美股 + 加密货币 + 期货 + 货币政策 + 宏观数据 + ETF

## 数据新鲜度说明
当前分析时间: {_now_str}（北京时间）
- 各数据模块的采集时间标注在数据摘要中
- 缓存 TTL 从 15 分钟（加密货币）到 12 小时（宏观/货币）不等
- 如果某个维度的置信度标注为"低"，请谨慎引用该数据

## 输出要求
1. 用大师兄的语言风格：专业、犀利、直击本质、用通俗语言解释复杂逻辑
2. 必须使用五维矩阵 + 三层传导框架
3. 输出三部分：
   - **五维全景**：金油汇债G五个维度分别发生了什么（不多于10行）
   - **核心事件解读**：选1-2个最重要的事件做深度剖析（必要时用八大不平衡/黑盒子估值框架）
   - **操作建议**：具体仓位、方向、风险提示（基于三层资金管理框架）
4. **"国家三层战略"框架仅在有明确政策事件（如国务院/央行/证监会发布正式政策文件）时使用**，不得对普通市场波动强行套用政策解读
5. 控制在 400-1000 字（复杂行情可适当延长）
6. **所有输出必须使用中文，禁止出现英文（除非是专有缩写如AI/ML/CPI等）**
7. **直接输出分析结果，严禁输出任何思考过程、推理步骤、搜索计划、或"Analyze the Request"之类的内容。只输出分析本身。**
8. **所有分析必须有具体数据支撑，禁止空洞归因。如"政策支持""资金青睐"等表述必须附带具体政策名称或资金数据**"""


# ── 增强版备用知识库（包含核心框架，避免 SKILL.md 缺失时降级） ──

_FALLBACK_KNOWLEDGE = """
## 三层传导框架（元方法论）
1. **第一层（宏观）**：央行/财政政策 → 资金面（利率/汇率/流动性）
2. **第二层（行业）**：资金面 → 行业板块轮动（周期/成长/防御）
3. **第三层（个股）**：板块轮动 → 个股表现（龙头/跟随/落后）

变体：
- 政策传导：国策 → 产业 → 企业
- 资金传导：北向 → 龙头 → 跟随
- 估值传导：龙头 → 同业 → 全行业

## 五维分析框架（金油汇债G）
1. **金**：黄金定价逻辑（避险/通胀/美元信用）、金银比（>80 预示衰退）
2. **油**：石油经济学三区间理论（低成本/中成本/高成本区）
3. **汇**：汇率定价与资本流动（美元强弱周期）
4. **债**：利率定价与信用传导（美债收益率是全球资产定价锚）
5. **G**：衍生品/加密货币/北向资金/跨市场比价

五维联动：
- 金↑ + 油↑ = 滞胀风险
- 汇↑（美元强）+ 债↑（美债收益率升）= 全球流动性紧缩 → 利空新兴市场
- 金↑ + 汇↓（美元弱）= 避险但不紧缩 → 黄金股利好
- 油↓ + BDI↓ = 全球需求走弱 → 周期股承压
- 债↓ + 汇↓ = 全球宽松 → 利好成长股

## 八大不平衡
1. 收入与资产不平衡（贫富差距）
2. 表内与表外不平衡（影子银行）
3. 实体与虚拟不平衡（金融空转）
4. 国内与国外不平衡（资本流动）
5. 短期与长期不平衡（期限错配）
6. 集中与分散不平衡（风险集中度）
7. 流动与固化的不平衡（流动性陷阱）
8. 风险与收益不平衡（风险定价失效）

## 黑盒子估值（斐波那契关键比例）
- 0.236 / 0.382 / 0.5 / 0.618 / 0.786
- 关键点位 = 前高（或前低）× 斐波那契比例
- 0.618 是黄金分割，常作为强支撑/阻力

## 国家三层战略框架
1. 第一层：拉闸限电（供给侧改革，去产能）
2. 第二层：审计（反腐，规范市场秩序）
3. 第三层：扶持（产业政策，定向支持）

## 康波周期（长波）
- 繁荣期（20年）→ 衰退期（10年）→ 萧条期（10年）→ 回升期（10年）
- 当前处于第5波康波萧条期向回升期过渡

## 投资核心原则
- 长期定方向，短期定操作
- 止盈止损，不要高杠杆
- 看操作表不看财务报表
- 留一口：永远留有余地，不all-in
- 反大众共识：人弃我取，人取我予
- 股市如血脉：资金是血液，板块是器官

## 三层资金管理
1. 底仓（50%）：长期持有，不轻易动
2. 机动仓（30%）：波段操作，跟随趋势
3. 现金（20%）：应急备用，逢低加仓
"""


# ── LLM 客户端 ──


def _get_llm_client() -> httpx.AsyncClient:
    global _llm_client
    if _llm_client is None or _llm_client.is_closed:
        _llm_client = httpx.AsyncClient(
            timeout=httpx.Timeout(60.0, connect=10.0),
            limits=httpx.Limits(max_connections=5),
        )
    return _llm_client


def _clean_response(content: str) -> str:
    if not content:
        return ""
    content = _RE_THINK.sub('', content).strip()
    if not content:
        return ""

    # 去掉常见的思考/推理前缀
    for prefix in ["Thinking Process:", "Thinking\n", "思考过程:", "思考过程\n"]:
        if content.startswith(prefix):
            parts = content.split("\n\n", 1)
            if len(parts) > 1 and len(parts[1]) > 50:
                return parts[1].strip()
            content = content.replace(prefix, "").strip()

    # 去掉以 "1.  **Analyze" 或 "1.  **分析请求" 开头的思维链
    # 这类内容从 "Analyze the Request" 或 "分析请求" 开始，到真正的分析结束
    import re as _re
    # 如果内容以编号列表的推理步骤开头（如 "1.  **Analyze the Request:**"）
    # 找到第一个有意义的正文段落
    lines = content.split("\n")
    cleaned_lines = []
    in_reasoning = False
    reasoning_markers = [
        "analyze the request", "分析请求", "search plan", "搜索计划",
        "self-correction", "simulating", "drafting the analysis",
        "执行计划", "思考过程", "reasoning", "thinking process",
    ]
    for line in lines:
        lower = line.strip().lower()
        # 检测推理标记开始
        if any(marker in lower for marker in reasoning_markers):
            in_reasoning = True
            continue
        # 检测分析内容开始（中文句号、冒号、破折号，或者不是编号/列表格式）
        if in_reasoning:
            if any(c in line for c in "。：，！？—"):  
                # 有中文标点 = 正式内容开始
                cleaned_lines.append(line)
                in_reasoning = False
            elif line.strip().startswith(("**金","**油","**汇","**债","**G","五维","核心","操作","结论")):
                cleaned_lines.append(line)
                in_reasoning = False
            continue
        if not in_reasoning:
            cleaned_lines.append(line)

    if cleaned_lines:
        result = "\n".join(cleaned_lines).strip()
        if len(result) > 50:
            return result

    return content


@async_retry(max_retries=2, delay=2.0, backoff=3.0)
async def _call_llm(system_prompt: str, user_prompt: str, max_tokens: int = 8192) -> str:
    api_key = settings.LLM_API_KEY or settings.DEEPSEEK_API_KEY or ""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.LLM_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.5,
        "max_tokens": max_tokens,
    }
    client = _get_llm_client()
    resp = await client.post(
        f"{settings.LLM_BASE_URL}/chat/completions",
        headers=headers,
        json=payload,
    )
    if resp.status_code == 429:
        retry_after = int(resp.headers.get("Retry-After", "5"))
        logger.warning(f"LLM API rate limited, waiting {retry_after}s")
        await asyncio.sleep(retry_after)
        raise Exception(f"Rate limited: {retry_after}s")
    if resp.status_code >= 400:
        raise Exception(f"LLM API error: {resp.status_code} {resp.text[:200]}")
    data = resp.json()
    if "choices" not in data or len(data["choices"]) == 0:
        logger.error(f"LLM response unexpected: {data}")
        return ""
    msg = data["choices"][0].get("message", {})
    content = msg.get("content", "")
    reasoning = msg.get("reasoning_content", "")

    # 优先用 content（模型的标准输出）
    cleaned = _clean_response(content)
    if cleaned:
        return cleaned

    # content 为空时用 reasoning_content（某些模型把最终输出放这里）
    if reasoning:
        # 对 reasoning_content 只做基本的去除 think 标记
        reasoning = _RE_THINK.sub("", reasoning).strip()
        if reasoning:
            # 提取 reasoning 中的实际分析内容 —— 找到第一个分析相关的标题
            import re as _re
            analysis_starters = [
                "**五维全景**", "**五维", "五维全景", "五维",
                "**核心事件**", "核心事件", "**操作建议**",
                "金：", "油：", "汇：", "债：", "G：",
                "金油", "汇债",
            ]
            for marker in analysis_starters:
                idx = reasoning.find(marker)
                if idx >= 0:
                    reasoning = reasoning[idx:]
                    break
            # 如果只找到"五维"但没有真正的分析内容，尝试其他方式
            # 去掉开头可能残留的标号或空格
            reasoning = _re.sub(r'^[\d\s\.\*\-]+\n*', '', reasoning).strip()
            if reasoning:
                return reasoning

    return content


# ── 结构化 JSON 输出（提升稳定性，替代脆弱的文本清洗） ──


def _extract_json_from_response(content: str) -> Optional[dict]:
    """从 LLM 响应中提取 JSON（支持纯 JSON、```json 代码块、混合文本）"""
    if not content:
        return None

    # 去除 think 标签
    content = _RE_THINK.sub('', content).strip()

    # 尝试1: 直接解析
    try:
        return json.loads(content)
    except (json.JSONDecodeError, TypeError):
        pass

    # 尝试2: 提取 ```json ... ``` 代码块
    json_block_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', content, re.DOTALL)
    if json_block_match:
        try:
            return json.loads(json_block_match.group(1).strip())
        except (json.JSONDecodeError, TypeError):
            pass

    # 尝试3: 找到第一个 { 和最后一个 } 之间的内容
    first_brace = content.find('{')
    last_brace = content.rfind('}')
    if first_brace >= 0 and last_brace > first_brace:
        try:
            return json.loads(content[first_brace:last_brace + 1])
        except (json.JSONDecodeError, TypeError):
            pass

    return None


@async_retry(max_retries=2, delay=2.0, backoff=3.0)
async def _call_llm_json(system_prompt: str, user_prompt: str,
                          max_tokens: int = 2048,
                          schema_hint: str = "") -> Optional[dict]:
    """调用 LLM 并解析为 JSON 结构化输出。

    Args:
        system_prompt: 系统提示词
        user_prompt: 用户提示词
        max_tokens: 最大 token 数
        schema_hint: JSON schema 提示（描述期望的字段结构）

    Returns:
        解析后的 dict，失败返回 None
    """
    api_key = settings.LLM_API_KEY or settings.DEEPSEEK_API_KEY or ""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    json_instruction = "请以 JSON 格式输出，不要输出任何其他内容。"
    if schema_hint:
        json_instruction += f"\n\nJSON 结构要求：\n{schema_hint}"

    payload = {
        "model": settings.LLM_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt + "\n\n" + json_instruction},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.3,  # 结构化输出用更低温度
        "max_tokens": max_tokens,
    }

    # 部分模型支持 response_format
    use_response_format = "deepseek" in settings.LLM_MODEL.lower() or "gpt-4" in settings.LLM_MODEL.lower()
    if use_response_format:
        payload["response_format"] = {"type": "json_object"}

    client = _get_llm_client()

    async def _do_call(current_payload: dict) -> Optional[dict]:
        resp = await client.post(
            f"{settings.LLM_BASE_URL}/chat/completions",
            headers=headers,
            json=current_payload,
        )
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", "5"))
            logger.warning(f"LLM JSON API rate limited, waiting {retry_after}s")
            await asyncio.sleep(retry_after)
            raise Exception(f"Rate limited: {retry_after}s")
        if resp.status_code >= 400:
            raise Exception(f"LLM JSON API error: {resp.status_code} {resp.text[:200]}")
        data = resp.json()
        if "choices" not in data or len(data["choices"]) == 0:
            logger.error(f"LLM JSON response unexpected: {data}")
            return None
        msg = data["choices"][0].get("message", {})
        content = msg.get("content", "")
        result = _extract_json_from_response(content)
        if result:
            logger.debug(f"✓ LLM JSON 解析成功，字段: {list(result.keys())}")
            return result
        logger.warning(f"LLM JSON 解析失败，原始内容前200字: {content[:200]}")
        return None

    try:
        # 先尝试带 response_format 调用
        return await _do_call(payload)
    except Exception as e:
        # 如果是 400 错误且使用了 response_format，去掉后重试
        if use_response_format and "400" in str(e):
            logger.warning(f"response_format 导致 400 错误，去掉后重试: {e}")
            payload.pop("response_format", None)
            try:
                return await _do_call(payload)
            except Exception as e2:
                logger.error(f"LLM JSON 重试也失败: {e2}")
                return None
        logger.error(f"LLM JSON 调用失败: {e}")
        return None


async def generate_commentary_structured(market_summary: str,
                                          market_context: dict = None) -> dict:
    """生成结构化的大师兄市场解读（JSON 输出，提升稳定性）。

    Returns:
        {
            "five_dimension": {"金": str, "油": str, "汇": str, "债": str, "G": str},
            "core_events": [{"event": str, "analysis": str, "framework": str}],
            "action_advice": {"position": str, "direction": str, "risk": str},
            "summary": str,  # 一句话总结
            "raw_text": str,  # 原始文本（兜底）
        }
    """
    if not market_summary or len(market_summary) < 20:
        return {"error": "市场摘要过短", "raw_text": ""}

    schema_hint = """{
  "five_dimension": {
    "金": "黄金维度分析（1-2句）",
    "油": "原油维度分析（1-2句）",
    "汇": "汇率维度分析（1-2句）",
    "债": "债券维度分析（1-2句）",
    "G": "衍生品/北向/加密维度分析（1-2句）"
  },
  "core_events": [
    {"event": "事件名称", "analysis": "三层传导分析", "framework": "使用的框架（八大不平衡/黑盒子估值/国家三层战略等）"}
  ],
  "action_advice": {
    "position": "仓位建议（如：底仓50%/机动仓30%/现金20%）",
    "direction": "操作方向（加仓/减仓/持有/观望）",
    "risk": "风险提示"
  },
  "summary": "一句话总结今日市场"
}"""

    try:
        system_prompt = _build_master_xiong_prompt(market_context)
        user_prompt = f"请基于以下当日市场全景数据，用五维框架 + 三层传导进行深度解读：\n\n{market_summary}"

        result = await _call_llm_json(system_prompt, user_prompt,
                                       max_tokens=2048, schema_hint=schema_hint)

        if result:
            # 确保必要字段存在
            result.setdefault("five_dimension", {})
            result.setdefault("core_events", [])
            result.setdefault("action_advice", {})
            result.setdefault("summary", "")
            return result

        # JSON 解析失败，回退到文本输出
        logger.warning("结构化输出失败，回退到文本模式")
        raw_text = await generate_commentary(market_summary, market_context)
        return {
            "five_dimension": {},
            "core_events": [],
            "action_advice": {},
            "summary": "",
            "raw_text": raw_text,
            "fallback": True,
        }

    except Exception as e:
        logger.error(f"结构化解读生成失败: {e}")
        return {"error": str(e), "raw_text": ""}


# ── 公开 API ──


# 严谨性后处理：检测并修正 LLM 输出中的违规表述
_FORBIDDEN_PATTERNS = [
    # BTC 与黄金并列避险
    ("双重避险", "风险偏好分化"),
    ("避险组合", "风险资产组合"),
    ("双龙戏凤", "风险偏好分化"),
    # BTC 货币属性
    ("货币承载", "风险资产"),
    ("新的货币承载工具", "高波动风险资产"),
    ("货币属性", "风险资产属性"),
    # 政策强行归因
    ("政策定向释放资金", "资金自发轮动"),
    ("政策定向支持", "市场资金偏好"),
]


def _enforce_rigor(commentary: str) -> str:
    """后处理：强制修正 LLM 输出中的不严谨表述。

    即使 prompt 中明确禁止，LLM 仍可能违反，因此需要后处理兜底。
    """
    if not commentary:
        return commentary
    result = commentary
    for forbidden, replacement in _FORBIDDEN_PATTERNS:
        if forbidden in result:
            logger.warning(f"LLM输出包含禁止表述'{forbidden}'，已自动修正为'{replacement}'")
            result = result.replace(forbidden, replacement)
    return result


async def generate_commentary(market_summary: str, market_context: dict = None) -> str:
    """生成大师兄每日市场解读（使用 SKILL.md v2.0.0 + 五维框架 + 按需章节加载）。

    Args:
        market_summary: 市场数据摘要文本
        market_context: 市场特征上下文，用于动态选择知识库章节
            - north_flow_alert: 北向资金异动（|净流|>50亿）
            - sector_rotation: 板块轮动明显
            - policy_event: 政策事件
            - high_volatility: 高波动（VIX>20 或 A股波动>2%）
            - leading_stock_alert: 大市值个股异动
    """
    if not market_summary or len(market_summary) < 20:
        logger.warning("Market summary too short, skipping LLM commentary")
        return ""
    try:
        system_prompt = _build_master_xiong_prompt(market_context)
        raw = await _call_llm(system_prompt,
                              f"请基于以下当日市场全景数据，用五维框架 + 三层传导进行深度解读：\n\n{market_summary}",
                              max_tokens=2048)
        # 严谨性后处理：强制修正违规表述
        return _enforce_rigor(raw)
    except Exception as e:
        logger.error(f"Failed to generate commentary after retries: {e}")
        return ""


async def generate_detailed_commentary(module_name: str, module_data: str) -> str:
    """针对特定模块生成深入分析。"""
    try:
        system_prompt = _build_master_xiong_prompt() + "\n\n请针对用户询问的特定模块进行更深入的分析。"
        return await _call_llm(system_prompt,
                               f"请对【{module_name}】模块进行更深入的大师兄视角解读：\n\n{module_data}",
                               max_tokens=4096)
    except Exception as e:
        logger.error(f"Failed to generate detailed commentary after retries: {e}")
        return ""


def _detect_market_context(data: dict) -> dict:
    """从市场数据中自动检测市场特征，用于动态加载知识库章节。"""
    context = {}
    try:
        # 北向资金异动
        north = data.get("north_flow", {})
        net_flow = north.get("net_flow", 0) or 0
        if abs(net_flow) > 50:
            context["north_flow_alert"] = True

        # 高波动
        gm = data.get("global_macro", {})
        vix = gm.get("vix", 0) or 0
        market = data.get("market", {})
        change_pct = abs(market.get("change_pct", 0) or 0)
        if vix > 20 or change_pct > 2:
            context["high_volatility"] = True

        # 板块轮动
        alerts = data.get("alerts", [])
        if alerts and len(alerts) > 3:
            context["sector_rotation"] = True

        # 大市值个股异动（注意：字段是 headlines 不是 items）
        leading = data.get("leading", {})
        if leading and leading.get("headlines"):
            context["leading_stock_alert"] = True

    except Exception as e:
        logger.debug(f"检测市场上下文失败: {e}")
    return context


async def generate_five_dimension_analysis(data: dict) -> str:
    """生成五维专项分析：金油汇债G 各个维度的深层解读。"""
    try:
        # 自动检测市场上下文
        market_context = _detect_market_context(data)

        # 构建五维专用 prompt（更聚焦）
        gm = data.get("global_macro", {})
        crypto = data.get("crypto", {})
        futures = data.get("futures", {})
        monetary = data.get("monetary", {})
        north = data.get("north_flow", {})
        comparison = data.get("comparison", {})

        dim_data = json.dumps({
            "金": {"黄金": gm.get("gold"), "白银": gm.get("silver")},
            "油": {"布伦特": gm.get("brent_oil"), "WTI": gm.get("wti_oil"),
                    "期货": [{"品种": i["name"], "涨跌幅": i.get("change_pct")} for i in futures.get("items", [])[:5]]},
            "汇": {"美元指数": gm.get("usd_index"), "美元/人民币": gm.get("usd_cny"),
                    "美元/日元": gm.get("usd_jpy")},
            "债": {"美10Y": gm.get("us_10y_bond"), "美2Y": gm.get("us_2y_bond"),
                    "LPR": f"{data.get('macro', {}).get('lpr_1y')}%"},
            "G": {"VIX": gm.get("vix"), "BDI": gm.get("bdi"),
                    "BTC": crypto.get("btc_price"), "北向": north.get("net_flow"),
                    "存准率": monetary.get("rrr_current")},
            "跨市场比价": comparison.get("summary", ""),
        }, ensure_ascii=False)

        dim_prompt = f"""你是一位顶尖宏观策略分析师。请对以下五维数据进行深入的跨维度交叉分析，找出各维度之间的内在联系：

{dim_data}

要求：
1. 先看金油关系：黄金和原油走势是否一致？金银比说明什么？
2. 再看汇债联动：美元和美债利差是否暗示衰退风险？
3. 看 G 的传导：VIX 是否抬头？加密货币和北向资金有何一致性？
4. 哪些维度出现了背离？背离往往意味着拐点。
5. 所有分析必须有具体数据支撑，不要空洞。
6. **资产属性红线**：BTC是高波动风险资产（波动率是黄金10倍+），不是避险资产，严禁与黄金并列为"双重避险"，严禁称为"货币承载"。
7. **归因严谨性**：板块轮动属资金自发行为，不得无依据归因为"政策定向支持"，政策归因必须有具体政策文件支撑。
8. 控制在 600 字以内。
9. **直接输出分析结果，严禁输出任何思考过程、推理步骤、搜索计划、JSON解析、或"Analyze the Request"之类的内容。只输出分析本身。**
10. **全文必须使用中文，禁止出现任何英文单词（专有名词缩写如AI/ML/CPI除外）。**"""

        system_prompt = _build_master_xiong_prompt(market_context).replace(
            "输出三部分", "输出金油汇债G五维交叉分析（600字以内）"
        )
        raw = await _call_llm(system_prompt, dim_prompt, max_tokens=4096)
        # 严谨性后处理：强制修正违规表述
        return _enforce_rigor(raw)
    except Exception as e:
        logger.error(f"Failed to generate five-dimension analysis: {e}")
        return ""


async def generate_beginner_summary(market_data: dict) -> str:
    """生成"小白模式"的一句话市场总结。

    用最通俗的语言给出明确操作建议，禁止专业术语。LLM 失败时用规则引擎兜底。

    Args:
        market_data: 市场数据，包含指数涨跌、北向资金、VIX、BTC涨跌等关键字段

    Returns:
        一句大白话总结，格式："今日市场[偏多/偏空/震荡]，建议[加仓/减仓/观望]。理由：[1-2个核心原因]"
    """
    logger.info("Generating beginner summary...")

    # 提取关键字段（同时用于规则引擎兜底）
    market = (market_data or {}).get("market", {}) or {}
    sh_change_pct = market.get("change_pct", 0) or 0  # 上证涨跌幅(%)
    north = (market_data or {}).get("north_flow", {}) or {}
    north_flow = north.get("net_flow", 0) or 0  # 北向资金净流(亿)

    def _fallback() -> str:
        """规则引擎兜底：根据上证涨跌幅和北向资金给出小白总结。"""
        if sh_change_pct < -1 and north_flow < -30:
            return "今日市场偏空，建议减仓。理由：大盘破位+外资出逃"
        if sh_change_pct > 1 and north_flow > 30:
            return "今日市场偏多，建议加仓。理由：大盘走强+外资进场"
        return "今日市场震荡，建议观望。理由：方向不明"

    try:
        gm = (market_data or {}).get("global_macro", {}) or {}
        vix = gm.get("vix", 0) or 0
        crypto = (market_data or {}).get("crypto", {}) or {}
        btc_change = crypto.get("btc_change_pct", 0) or crypto.get("change_pct", 0) or 0

        data_summary = json.dumps({
            "上证涨跌幅": f"{sh_change_pct}%",
            "北向资金净流": f"{north_flow}亿",
            "VIX": vix,
            "BTC涨跌幅": f"{btc_change}%",
        }, ensure_ascii=False)

        system_prompt = """你是一位面向股市新手的"小白解说员"。请基于市场数据生成一句话总结。

严格要求：
1. 用最通俗的大白话，禁止任何专业术语（如"五维矩阵""三层传导""斐波那契""避险资产""风险偏好""北向资金""VIX"等）。
2. 必须给出明确操作建议：加仓 / 减仓 / 观望（三选一）。
3. 输出格式严格为："今日市场[偏多/偏空/震荡]，建议[加仓/减仓/观望]。理由：[1-2个核心原因]"
4. 理由不超过2个，每个不超过15字，用"+"连接。
5. 总字数控制在50字以内。
6. 只输出这一句话，不要任何额外内容、标点或解释。
7. 必须使用中文。"""

        user_prompt = f"市场数据：\n{data_summary}\n\n请生成小白模式的一句话总结。"

        raw = await _call_llm(system_prompt, user_prompt, max_tokens=128)
        summary = _enforce_rigor(raw).strip()

        # 校验输出格式
        if summary and "今日市场" in summary and "建议" in summary:
            return summary

        logger.warning(f"LLM 输出不符合格式，走规则引擎兜底: {summary}")
    except Exception as e:
        logger.error(f"LLM 生成小白总结失败，走规则引擎兜底: {e}")

    return _fallback()


# ── 启动验证 ──

def warmup() -> bool:
    """启动时验证 LLM 服务配置和知识库加载。"""
    global _skill_knowledge
    ok = True

    # 验证 LLM 配置
    valid, msg = validate_llm_config()
    if not valid:
        logger.error(f"❌ LLM 配置验证失败: {msg}")
        ok = False
    else:
        logger.info("✅ LLM 配置验证通过")

    # 加载知识库
    if _skill_knowledge is None:
        _skill_knowledge = load_skill_knowledge()
    if _skill_knowledge:
        logger.info(f"✅ 大师兄知识库已加载（{len(_skill_knowledge)} 字符）")
    else:
        logger.warning("⚠️ 大师兄知识库加载失败，使用备用知识")

    return ok

if _skill_knowledge is None:
    _skill_knowledge = load_skill_knowledge()
    if _skill_knowledge:
        logger.info(f"大师兄知识库已加载（{len(_skill_knowledge)} 字符）")
    else:
        logger.warning("大师兄知识库加载失败，使用备用知识")
