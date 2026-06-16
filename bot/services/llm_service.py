"""LLM 服务 — 调用外部 LLM API 生成大师兄市场解读（v2.0 五维框架）。

使用本地 SKILL.md v2.0.0 完整知识体系（悟而后醒·全领域知识）。
新增五维专项分析 generate_five_dimension_analysis。
"""

import re
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

_RE_THINK = re.compile(r'<think.*?</think\s*>', re.DOTALL)

SKILL_MD_PATH = Path(__file__).parent.parent.parent.parent / ".hermes" / "skills" / "knowledge" / "xhs-economics-analyst" / "SKILL.md"
_ALT_PATHS = [
    Path.home() / ".hermes" / "skills" / "knowledge" / "xhs-economics-analyst" / "SKILL.md",
    Path(__file__).parent.parent / "SKILL.md",
]


def load_skill_knowledge() -> str:
    """加载本地 SKILL.md v2.0.0 知识库内容。"""
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


def _build_master_xiong_prompt() -> str:
    """从 SKILL.md 动态构建大师兄系统提示词（精简版）。"""
    global _skill_knowledge
    if _skill_knowledge is None:
        _skill_knowledge = load_skill_knowledge()
    # 只取知识库前 2500 字（框架部分），去掉过长的细节
    knowledge_digest = _skill_knowledge[:2500] if _skill_knowledge else ""

    return f"""你是"大师兄"，一位资深的二级市场投资分析师，拥有丰富的宏观投研经验。

## 核心知识（精简）

{knowledge_digest}

## 分析框架

### 五维矩阵（每日必用）
1. **金** — 黄金定价、金银比、避险逻辑
2. **油** — 石油三区间理论、商品期货
3. **汇** — 美元指数、汇率篮子
4. **债** — 美债利率、利差（衰退预警）、中国利率
5. **G** — VIX、BDI、BTC/ETH、北向资金、跨市场比价

### 三层传导分析
1. **第一层**：宏观政策/资金面发生了什么事？
2. **第二层**：如何传导到行业/板块？
3. **第三层**：对个股/操作有什么具体影响？

## 数据覆盖
A股指数 + 板块 + 北向 + 美股 + 加密货币 + 期货 + 货币政策 + 宏观数据 + ETF

## 输出要求
1. 用大师兄的语言风格：专业、犀利、直击本质
2. 必须使用五维矩阵 + 三层传导框架
3. 输出三部分：
   - **五维全景**：金油汇债G五个维度分别发生了什么（不多于10行）
   - **核心事件解读**：选1-2个最重要的事件做深度剖析
   - **操作建议**：具体仓位、方向、风险提示
4. 遇到政策事件，用"国家三层战略"框架解读
5. 控制在不低于200字，不超过600字
6. **所有输出必须使用中文，禁止出现英文（除非是专有缩写如AI/ML/CPI等）**
7. **直接输出分析结果，严禁输出任何思考过程、推理步骤、搜索计划、或"Analyze the Request"之类的内容。只输出分析本身。**"""


# ── 备用知识库 ──

_FALLBACK_KNOWLEDGE = """
### 三层传导框架（A股专用）
1. 第一层：宏观政策（央行、财政）→ 资金面
2. 第二层：资金面 → 行业板块轮动
3. 第三层：板块轮动 → 个股表现

### 五维分析框架
1. 金：黄金定价逻辑
2. 油：石油经济学三区间理论
3. 汇：汇率定价与资本流动
4. 债：利率定价与信用传导
5. G：衍生品/加密货币/北向资金/跨市场

### 投资核心原则
- 长期定方向，短期定操作
- 止盈止损，不要高杠杆
- 看操作表不看财务报表
- 留一口：永远留有余地，不all-in
"""


# ── LLM 客户端 ──


def _get_llm_client() -> httpx.AsyncClient:
    global _llm_client
    if _llm_client is None:
        _llm_client = httpx.AsyncClient(timeout=60.0)
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


# ── 公开 API ──


async def generate_commentary(market_summary: str) -> str:
    """生成大师兄每日市场解读（使用 SKILL.md v2.0.0 + 五维框架）。"""
    if not market_summary or len(market_summary) < 20:
        logger.warning("Market summary too short, skipping LLM commentary")
        return ""
    try:
        system_prompt = _build_master_xiong_prompt()
        return await _call_llm(system_prompt,
                               f"请基于以下当日市场全景数据，用五维框架 + 三层传导进行深度解读：\n\n{market_summary}",
                               max_tokens=1024)
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


async def generate_five_dimension_analysis(data: dict) -> str:
    """生成五维专项分析：金油汇债G 各个维度的深层解读。"""
    try:
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
6. 控制在 600 字以内。
7. **直接输出分析结果，严禁输出任何思考过程、推理步骤、搜索计划、JSON解析、或"Analyze the Request"之类的内容。只输出分析本身。**
8. **全文必须使用中文，禁止出现任何英文单词（专有名词缩写如AI/ML/CPI除外）。**"""

        system_prompt = _build_master_xiong_prompt().replace(
            "输出三部分", "输出金油汇债G五维交叉分析（600字以内）"
        )
        return await _call_llm(system_prompt, dim_prompt, max_tokens=4096)
    except Exception as e:
        logger.error(f"Failed to generate five-dimension analysis: {e}")
        return ""


# ── 启动验证 ──

if _skill_knowledge is None:
    _skill_knowledge = load_skill_knowledge()
    if _skill_knowledge:
        logger.info(f"大师兄知识库已加载（{len(_skill_knowledge)} 字符）")
    else:
        logger.warning("大师兄知识库加载失败，使用备用知识")
