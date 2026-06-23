"""炒股的智慧 · 深度分析模块。

基于 SKILL.md 知识体系（悟而后醒·全领域知识），在市场出现重大异动时
自动触发深度分析，输出三层传导解读 + 五维交叉验证 + 八大不平衡视角 + 操作建议。

触发条件：异动、背离、极端值等信号由 _detect_wisdom_triggers 检测。
"""

import json
from datetime import datetime
from loguru import logger

from config.settings import get_settings
from core.utils import async_retry
from services.llm_service import (
    _call_llm,
    _load_sections_by_keywords,
    _get_skill_sections,
    SKILL_SECTIONS_DEF,
    _enforce_rigor,
)

settings = get_settings()


# ── 触发条件检测 ──────────────────────────────────────

def _detect_wisdom_triggers(data: dict) -> dict:
    """从市场数据中检测需要启用哪些知识框架的触发条件。

    Returns:
        {
            "imbalance_trigger": bool,   # 八大不平衡（重大背离）
            "valuation_trigger": bool,   # 黑盒子估值（龙头股异动）
            "cycle_trigger": bool,       # 康波周期（宏观拐点信号）
            "philosophy_trigger": bool,  # 清净心/反大众共识（情绪极端）
            "policy_trigger": bool,      # 国家三层战略（明确政策事件）
            "trigger_reasons": list[str], # 触发原因列表
        }
    """
    triggers = {
        "imbalance_trigger": False,
        "valuation_trigger": False,
        "cycle_trigger": False,
        "philosophy_trigger": False,
        "policy_trigger": False,
        "trigger_reasons": [],
    }

    gm = data.get("global_macro", {}) or {}
    market = data.get("market", {}) or {}
    north = data.get("north_flow", {}) or {}
    crypto = data.get("crypto", {}) or {}
    monetary = data.get("monetary", {}) or {}
    leading = data.get("leading", {}) or {}
    alerts = data.get("alerts", []) or []

    # ── 八大不平衡触发条件 ──
    # 金银比 > 85 预示衰退风险
    gold_val = _safe_float(gm.get("gold"))
    silver_val = _safe_float(gm.get("silver"))
    if gold_val and silver_val and silver_val > 0:
        ratio = gold_val / silver_val
        if ratio > 85:
            triggers["imbalance_trigger"] = True
            triggers["trigger_reasons"].append(f"金银比{ratio:.1f}>85，预示衰退风险")

    # 北向资金大幅流出（>80亿）
    net_flow = _safe_float(north.get("net_flow"))
    if net_flow is not None and net_flow < -80:
        triggers["imbalance_trigger"] = True
        triggers["trigger_reasons"].append(f"北向大幅流出{abs(net_flow):.1f}亿")

    # 美债10Y-2Y倒挂
    us_10y = _safe_float(gm.get("us_10y_bond"))
    us_2y = _safe_float(gm.get("us_2y_bond"))
    if us_10y and us_2y and us_10y < us_2y:
        triggers["imbalance_trigger"] = True
        triggers["trigger_reasons"].append("美债10Y-2Y倒挂，衰退信号")

    # 金油背离（黄金涨+原油跌 = 滞胀信号）
    gold_alert = any("黄金" in a.get("title", "") for a in alerts)
    oil_alert = any("原油" in a.get("title", "") or "WTI" in a.get("title", "") for a in alerts)
    if gold_alert and oil_alert:
        triggers["imbalance_trigger"] = True
        triggers["trigger_reasons"].append("金油走势背离，关注滞胀风险")

    # ── 黑盒子估值触发条件 ──
    # 大市值个股异动（涨幅/跌幅 > 5%）
    headlines = leading.get("headlines", []) or []
    for h in headlines[:5]:
        chg = _safe_float(h.get("change_pct"))
        if chg is not None and abs(chg) >= 5:
            triggers["valuation_trigger"] = True
            triggers["trigger_reasons"].append(f"大市值异动: {h.get('name', '')} {chg:+.2f}%")
            break

    # ── 康波周期触发条件 ──
    # VIX > 25 或 BDI 大幅波动
    vix = _safe_float(gm.get("vix"))
    if vix and vix > 25:
        triggers["cycle_trigger"] = True
        triggers["trigger_reasons"].append(f"VIX={vix:.1f}>25，恐慌升温")

    bdi = _safe_float(gm.get("bdi"))
    if bdi and bdi < 500:
        triggers["cycle_trigger"] = True
        triggers["trigger_reasons"].append(f"BDI={bdi:.0f}<500，全球需求极弱")

    # M2 增速异常（大幅回落或转负）
    m2_growth = monetary.get("m2_growth", "")
    if m2_growth:
        try:
            m2_val = float(str(m2_growth).replace("%", ""))
            if m2_val < 6:
                triggers["cycle_trigger"] = True
                triggers["trigger_reasons"].append(f"M2增速{m2_val}%偏低，流动性收紧")
        except (ValueError, TypeError):
            pass

    # ── 清净心/反大众共识触发条件 ──
    # A股整体暴涨暴跌（涨跌幅 > 2%）
    for idx in market.get("indices", []):
        chg = _safe_float(idx.get("change_pct"))
        if chg is not None and abs(chg) >= 2:
            triggers["philosophy_trigger"] = True
            triggers["trigger_reasons"].append(f"{idx.get('name', '')} {chg:+.2f}%，情绪极端")
            break

    # BTC 暴涨暴跌（>8%）
    btc_chg = _safe_float(crypto.get("btc_change"))
    if btc_chg is not None and abs(btc_chg) >= 8:
        triggers["philosophy_trigger"] = True
        triggers["trigger_reasons"].append(f"BTC {btc_chg:+.2f}%，投机情绪极端")

    # ── 国家三层战略触发条件 ──
    # 通过 alerts 检测政策相关事件
    policy_keywords = ["政策", "央行", "证监会", "国务院", "降准", "降息", "LPR"]
    for a in alerts:
        title = a.get("title", "")
        if any(kw in title for kw in policy_keywords):
            triggers["policy_trigger"] = True
            triggers["trigger_reasons"].append(f"政策事件: {title}")
            break

    # 至少有2个触发条件才算真正需要深度分析
    active_count = sum([
        triggers["imbalance_trigger"],
        triggers["valuation_trigger"],
        triggers["cycle_trigger"],
        triggers["philosophy_trigger"],
        triggers["policy_trigger"],
    ])
    if active_count < 2:
        triggers["imbalance_trigger"] = False
        triggers["valuation_trigger"] = False
        triggers["cycle_trigger"] = False
        triggers["philosophy_trigger"] = False
        triggers["policy_trigger"] = False
        triggers["trigger_reasons"] = []

    return triggers


def _safe_float(val) -> float | None:
    """安全转换为 float，失败返回 None。"""
    if val is None:
        return None
    try:
        v = float(val)
        return v if not (v != v or abs(v) == float("inf")) else None  # NaN/Inf 检查
    except (ValueError, TypeError):
        return None


# ── 提示词构建 ──────────────────────────────────────

def _build_wisdom_prompt(market_context: dict) -> str:
    """构建"炒股的智慧"深度分析专用提示词。

    根据触发条件动态加载 SKILL.md 中匹配的章节，
    要求 LLM 以"悟而后醒"视角做深度分析。

    Args:
        market_context: 触发条件 dict（来自 _detect_wisdom_triggers）
    """
    # 按触发条件动态选择知识库章节
    sections_to_load = ["core"]  # 始终加载核心框架

    if market_context.get("imbalance_trigger"):
        sections_to_load.append("imbalance")
    if market_context.get("valuation_trigger"):
        sections_to_load.append("valuation")
    if market_context.get("cycle_trigger"):
        sections_to_load.append("macro")
    if market_context.get("philosophy_trigger"):
        sections_to_load.append("philosophy")
    if market_context.get("policy_trigger"):
        sections_to_load.append("policy")

    # 收集所有关键词
    all_keywords = []
    for sec in sections_to_load:
        all_keywords.extend(SKILL_SECTIONS_DEF.get(sec, []))

    knowledge_digest = _load_sections_by_keywords(all_keywords)

    _now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 触发原因摘要
    reasons = market_context.get("trigger_reasons", [])
    reasons_text = "\n".join(f"- {r}" for r in reasons) if reasons else "- 无特殊触发"

    return f"""你是"悟而后醒"——一位经历多轮牛熊、深谙资本史与人性博弈的资深投资思想家。

## 今日触发条件
{reasons_text}

## 核心知识（按触发条件动态加载）

{knowledge_digest}

## 分析框架与输出要求

### 一、三层传导解读
1. **第一层（宏观）**：当前宏观政策/资金面发生了什么？（必须有具体数据支撑）
2. **第二层（行业）**：如何传导到行业/板块？（传导链路必须可解释，禁止跳跃）
3. **第三层（个股/操作）**：对具体操作有什么影响？

### 二、五维交叉验证
- **金**：黄金/白银/金银比 → 避险还是滞胀？
- **油**：原油/商品期货 → 需求强弱信号
- **汇**：美元/汇率 → 资本流动方向
- **债**：美债/利差 → 衰退/宽松信号
- **G**：VIX/BDI/北向/加密 → 风险偏好与流动性
- **关键**：五维之间是否出现背离？背离往往意味着拐点

### 三、八大不平衡视角
（仅在触发时启用）从八大不平衡中选取与当前市场最相关的2-3个维度做深度剖析

### 四、操作建议
- 基于三层资金管理框架（底仓50%/机动仓30%/现金20%）
- 给出具体仓位调整建议和方向
- 明确风险提示

## 严谨性红线（必须遵守）
1. **BTC不是避险资产**，严禁与黄金并列避险，严禁"双重避险""避险组合"等表述
2. BTC的正确分析角度：风险偏好指标、流动性敏感资产、投机情绪温度计
3. **板块轮动不得无依据归因政策**：A股风格轮动属资金自发行为，政策归因必须有具体政策文件支撑
4. **所有分析必须引用具体数据**，禁止"政策支持""资金青睐"等空洞归因
5. **严禁"先有结论再找理由"**：不得将普通波动强行套用框架

## 数据新鲜度
分析时间: {_now_str}（北京时间）

## 出处标注要求（必须遵守）
1. **数据出处**：每个关键论据后必须标注数据来源，格式：`[数据: 来源]`
   - A股指数/板块/北向 → `[数据: akshare实时行情]`
   - 黄金/原油/美元/美债 → `[数据: akshare全球宏观]`
   - VIX/BDI → `[数据: akshare衍生品]`
   - BTC/ETH → `[数据: akshare+CoinGecko]`
   - M2/社融/存准率 → `[数据: 央行官方]`
   - CPI/PPI/PMI → `[数据: 国家统计局]`
   - 期货品种 → `[数据: 国内期货交易所]`
   - ETF/龙头股 → `[数据: akshare实时]`
2. **知识框架出处**：使用某个分析框架时必须标注来源，格式：`[框架: 来源]`
   - 三层传导 → `[框架: 悟而后醒·三层传导元方法论]`
   - 五维矩阵 → `[框架: 悟而后醒·五维分析框架]`
   - 八大不平衡 → `[框架: 悟而后醒·八大不平衡]`
   - 黑盒子估值/斐波那契 → `[框架: 悟而后醒·黑盒子估值]`
   - 康波周期 → `[框架: 悟而后醒·康波周期]`
   - 国家三层战略 → `[框架: 悟而后醒·国家三层战略]`
   - 清净心/反大众共识 → `[框架: 悟而后醒·清净心投资哲学]`
   - 三层资金管理 → `[框架: 悟而后醒·三层资金管理]`
3. **示例**：
   - "黄金站上3300美元/盎司，金银比升至88 `[数据: akshare全球宏观]`，根据五维矩阵 `[框架: 悟而后醒·五维分析框架]`，金油背离预示滞胀风险"
   - "深证成指单日跌超3% `[数据: akshare实时行情]`，按照反大众共识原则 `[框架: 悟而后醒·清净心投资哲学]`，恐慌时反而应保持冷静"

## 输出格式
1. 使用"悟而后醒"的语言风格：深邃、犀利、直击本质，用通俗语言解释复杂逻辑
2. 控制在 800-1500 字
3. 必须使用中文，禁止英文（专有缩写如CPI/VIX等除外）
4. **直接输出分析结果，严禁输出思考过程、推理步骤或"Analyze the Request"之类的内容**
5. 四个部分用明确的标题分隔
6. **每个关键论据必须标注出处**（数据来源和知识框架来源），这是硬性要求，未标注出处的分析视为无效"""


# ── 深度分析生成 ──────────────────────────────────────

@async_retry(max_retries=2, delay=2.0, backoff=3.0)
async def generate_wisdom_analysis(data: dict) -> str:
    """生成"炒股的智慧"深度分析。

    Args:
        data: generate_daily_report() 生成的完整市场数据 dict

    Returns:
        深度分析文本
    """
    # 检测触发条件
    triggers = _detect_wisdom_triggers(data)

    if not triggers.get("trigger_reasons"):
        logger.info("市场平静，无需深度分析")
        return ""

    logger.info(f"检测到 {len(triggers['trigger_reasons'])} 个触发条件，启动深度分析")

    # 构建市场数据摘要
    market_summary = _build_wisdom_data_summary(data)

    # 构建专用提示词
    system_prompt = _build_wisdom_prompt(triggers)
    user_prompt = f"请基于以下当日市场全景数据，用三层传导 + 五维交叉验证进行深度分析：\n\n{market_summary}"

    try:
        raw = await _call_llm(system_prompt, user_prompt, max_tokens=4096)
        analysis = _enforce_rigor(raw)
        if analysis:
            logger.info(f"深度分析生成完成（{len(analysis)}字）")
        return analysis
    except Exception as e:
        logger.error(f"深度分析生成失败: {e}")
        return ""


def _build_wisdom_data_summary(data: dict) -> str:
    """为深度分析构建精简的市场数据摘要。"""
    gm = data.get("global_macro", {}) or {}
    market = data.get("market", {}) or {}
    north = data.get("north_flow", {}) or {}
    crypto = data.get("crypto", {}) or {}
    futures = data.get("futures", {}) or {}
    monetary = data.get("monetary", {}) or {}
    macro = data.get("macro", {}) or {}
    leading = data.get("leading", {}) or {}
    alerts = data.get("alerts", []) or []

    lines = [f"📊 深度分析数据摘要 | {data.get('report_date', '')}"]

    # A股核心
    lines.append("\n【A股核心】")
    for idx in market.get("indices", []):
        v = idx.get("value", 0)
        p = idx.get("change_pct", 0)
        lines.append(f"  {idx['name']}: {v:.2f} ({p:+.2f}%)")
    up = market.get("up_count", 0)
    down = market.get("down_count", 0)
    if up or down:
        lines.append(f"  涨跌比: {up}涨/{down}跌")

    # 五维数据
    lines.append("\n【五维数据】")
    if gm.get("gold"):
        lines.append(f"  金: 黄金{gm['gold']}美元/盎司")
    if gm.get("silver"):
        lines.append(f"  银: 白银{gm['silver']}美元/盎司")
    if gm.get("gold") and gm.get("silver"):
        try:
            ratio = float(gm["gold"]) / float(gm["silver"])
            lines.append(f"  金银比: {ratio:.1f}")
        except (ValueError, ZeroDivisionError):
            pass
    if gm.get("brent_oil") or gm.get("wti_oil"):
        parts = []
        if gm.get("brent_oil"):
            parts.append(f"布伦特{gm['brent_oil']}")
        if gm.get("wti_oil"):
            parts.append(f"WTI{gm['wti_oil']}")
        lines.append(f"  油: {' | '.join(parts)} 美元/桶")
    if gm.get("usd_index"):
        lines.append(f"  汇: 美元指数{gm['usd_index']}")
    if gm.get("usd_cny"):
        lines.append(f"  美元/人民币{gm['usd_cny']}")
    if gm.get("us_10y_bond") or gm.get("us_2y_bond"):
        parts = []
        if gm.get("us_10y_bond"):
            parts.append(f"10Y={gm['us_10y_bond']}%")
        if gm.get("us_2y_bond"):
            parts.append(f"2Y={gm['us_2y_bond']}%")
        lines.append(f"  债: {' | '.join(parts)}")
        if gm.get("us_10y_bond") and gm.get("us_2y_bond"):
            try:
                spread = float(gm["us_10y_bond"]) - float(gm["us_2y_bond"])
                flag = "⚠️倒挂" if spread < 0 else "✅正常"
                lines.append(f"  10Y-2Y利差: {spread:+.2f}% {flag}")
            except (ValueError, TypeError):
                pass
    if gm.get("vix"):
        lines.append(f"  G: VIX={gm['vix']}")
    if gm.get("bdi"):
        lines.append(f"  BDI={gm['bdi']}")

    # 北向资金
    net = north.get("net_flow")
    if net is not None and abs(net) > 0.01:
        direction = "流入" if net >= 0 else "流出"
        lines.append(f"\n【北向资金】{direction}{abs(net):.1f}亿")

    # 加密货币
    if crypto.get("btc_price"):
        btc_chg = crypto.get("btc_change", 0) or 0
        lines.append(f"\n【加密货币】BTC {crypto['btc_price']} ({btc_chg:+.2f}%)")

    # 货币政策
    mon_parts = []
    if monetary.get("m2_growth"):
        mon_parts.append(f"M2同比{monetary['m2_growth']}")
    if monetary.get("social_finance_growth"):
        mon_parts.append(f"社融增量{monetary['social_finance_growth']}")
    if monetary.get("rrr_current"):
        mon_parts.append(f"存准率{monetary['rrr_current']}%")
    if mon_parts:
        lines.append(f"\n【货币政策】{' | '.join(mon_parts)}")

    # 大市值异动
    headlines = leading.get("headlines", []) or []
    if headlines:
        lead_str = [f"{h['name']}{h.get('change_pct', 0):+.2f}%" for h in headlines[:3]]
        lines.append(f"\n【大市值涨幅榜】{' | '.join(lead_str)}")

    # 异动告警
    if alerts:
        lines.append("\n【异动告警】")
        for a in alerts[:5]:
            icon = "🔴" if a.get("level") == "danger" else "🟡"
            lines.append(f"  {icon} {a.get('title', '')}")

    # 期货
    futures_items = futures.get("items", []) or []
    if futures_items:
        f_str = [f"{i['name']}{i.get('change_pct', 0):+.2f}%" for i in futures_items[:5]]
        lines.append(f"\n【商品期货】{' | '.join(f_str)}")

    # 宏观数据
    macro_parts = []
    if macro.get("cpi"):
        macro_parts.append(f"CPI={macro['cpi']}")
    if macro.get("ppi"):
        macro_parts.append(f"PPI={macro['ppi']}")
    if macro.get("pmi"):
        macro_parts.append(f"PMI={macro['pmi']}")
    if macro_parts:
        lines.append(f"\n【宏观数据】{' | '.join(macro_parts)}")

    result = "\n".join(lines)
    result = result.replace("None", "暂无")
    return result


# ── 飞书卡片构建 ──────────────────────────────────────

def build_wisdom_card(analysis: str, triggers: dict) -> dict:
    """构建"炒股的智慧"深度分析飞书卡片。

    Args:
        analysis: 深度分析文本
        triggers: 触发条件 dict

    Returns:
        飞书卡片 dict
    """
    # 触发条件摘要
    reasons = triggers.get("trigger_reasons", [])
    if reasons:
        reasons_text = "\n".join(f"- {r}" for r in reasons)
        trigger_section = f"## 🔍 今日触发条件\n{reasons_text}\n\n---"
    else:
        trigger_section = ""

    # 深度分析正文
    analysis_text = analysis.replace("None", "暂无")

    # 出处说明与免责声明
    source_note = (
        "---\n"
        "📌 **分析出处说明**\n"
        "- 数据来源：akshare（A股/全球宏观/期货/加密货币）、央行官方、国家统计局\n"
        "- 知识框架：悟而后醒（纽约）· 全领域知识体系（三层传导/五维矩阵/八大不平衡/黑盒子估值/康波周期/清净心投资哲学）\n"
        "- 分析引擎：DeepSeek LLM + SKILL.md 知识库\n"
    )
    disclaimer = (
        "⚠️ **风险提示**: 本分析由AI基于知识体系生成，仅供参考，不构成投资建议。"
        "投资有风险，入市需谨慎。"
    )

    # 组装卡片内容
    content_parts = []
    if trigger_section:
        content_parts.append(trigger_section)
    content_parts.append(analysis_text)
    content_parts.append(source_note)
    content_parts.append(disclaimer)
    card_content = "\n\n".join(content_parts)

    # 截断保护
    if len(card_content) > 8000:
        card_content = card_content[:8000] + "\n\n*内容过长已截断*"

    return {
        "header": {
            "template": "purple",
            "title": {"tag": "plain_text", "content": "🧠 炒股的智慧 · 深度分析"},
        },
        "elements": [
            {"tag": "markdown", "content": card_content},
        ],
    }


# ── 编排函数 ──────────────────────────────────────

async def run_wisdom_analysis(existing_data: dict | None = None) -> dict:
    """编排函数：获取数据 → 检测触发条件 → 生成分析 → 返回结果。

    Args:
        existing_data: 可选的已有日报数据，传入则复用，避免重复拉取。

    Returns:
        {"status": "success"/"skipped", "analysis": str, "triggers": dict}
    """
    logger.info("启动炒股的智慧深度分析...")

    try:
        # 获取日报数据
        if existing_data:
            data = existing_data
            logger.info("复用已有的日报数据执行深度分析")
        else:
            from services.report_generator import generate_daily_report
            data = await generate_daily_report("close")
            logger.info("已获取最新市场数据用于深度分析")

        # 检测触发条件
        triggers = _detect_wisdom_triggers(data)

        if not triggers.get("trigger_reasons"):
            logger.info("市场平静，跳过深度分析")
            return {
                "status": "skipped",
                "analysis": "今日市场平静，未触发深度分析条件。",
                "triggers": triggers,
            }

        logger.info(f"检测到 {len(triggers['trigger_reasons'])} 个触发条件: {triggers['trigger_reasons']}")

        # 生成深度分析
        analysis = await generate_wisdom_analysis(data)

        if not analysis:
            logger.warning("深度分析生成失败，返回空结果")
            return {
                "status": "skipped",
                "analysis": "",
                "triggers": triggers,
            }

        return {
            "status": "success",
            "analysis": analysis,
            "triggers": triggers,
        }

    except Exception as e:
        logger.error(f"深度分析编排失败: {e}")
        return {
            "status": "skipped",
            "analysis": f"深度分析执行异常: {e}",
            "triggers": {},
        }
