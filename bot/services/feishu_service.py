"""飞书消息服务 — 飞书卡片推送（v2.0 五维框架）。

卡片结构：
1. 异动提醒（置顶）
2. A 股核心行情
3. 五维矩阵：金 | 油 | 汇 | 债 | G
4. 美股 / 加密货币 / 国内期货
5. 货币政策量化
6. 跨市场比价
7. ETF / 龙头 / 北证
8. 大师兄解读
"""

import json
import time
import math
import httpx
from typing import Optional
from datetime import datetime
from loguru import logger

from config.settings import get_settings

settings = get_settings()

_token_cache: dict[str, str | float] = {"token": "", "expire_at": 0}
_http_client: Optional[httpx.AsyncClient] = None

MAX_CARD_CONTENT_LENGTH = 20000
FEISHU_MSG_URL = "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id"


def _get_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(timeout=15.0)
    return _http_client


async def close_client():
    global _http_client
    if _http_client:
        await _http_client.aclose()
        _http_client = None


def _is_chat_id_valid(chat_id: str) -> bool:
    return bool(chat_id and chat_id.startswith("oc_"))


def _fmt_pct(val):
    if val is None or (isinstance(val, float) and (math.isnan(val) or math.isinf(val))):
        return "--"
    try:
        return f"{float(val):+.2f}%"
    except (ValueError, TypeError):
        return "--"


def _fmt_val(val, default="--"):
    if val is None or (isinstance(val, float) and (math.isnan(val) or math.isinf(val))):
        return default
    try:
        return str(val)
    except (ValueError, TypeError):
        return default


def get_update_timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


async def get_tenant_token() -> str:
    now = time.time()
    if _token_cache["token"] and _token_cache["expire_at"] > now + 120:
        return _token_cache["token"]

    client = _get_client()
    resp = await client.post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        json={
            "app_id": settings.FEISHU_APP_ID,
            "app_secret": settings.FEISHU_APP_SECRET,
        },
    )
    data = resp.json()
    if data.get("code") != 0:
        logger.error(f"Failed to get tenant token: {data}")
        raise Exception(f"Feishu auth failed: {data.get('msg')}")
    _token_cache["token"] = data["tenant_access_token"]
    _token_cache["expire_at"] = now + data.get("expire", 7200)
    logger.debug("Feishu tenant token refreshed")
    return _token_cache["token"]


async def _post_message(payload: dict, token: str) -> dict:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    client = _get_client()
    resp = await client.post(FEISHU_MSG_URL, headers=headers, json=payload)
    return resp.json()


async def _send_message(payload: dict) -> dict:
    token = await get_tenant_token()
    data = await _post_message(payload, token)

    if data.get("code") == 99991663:
        logger.warning("Token expired, refreshing and retrying...")
        _token_cache["token"] = ""
        _token_cache["expire_at"] = 0
        token = await get_tenant_token()
        data = await _post_message(payload, token)

    return data


async def send_card_message(chat_id: str, card_json: dict) -> bool:
    if not _is_chat_id_valid(chat_id):
        logger.error(f"Invalid chat_id: {chat_id}")
        return False

    content_str = json.dumps(card_json, ensure_ascii=False)
    if len(content_str) > MAX_CARD_CONTENT_LENGTH:
        logger.warning(f"Card content too long ({len(content_str)} chars), truncating")
        for element in card_json.get("elements", []):
            if isinstance(element, dict) and element.get("tag") == "markdown":
                mc = element.get("content", "")
                max_md = MAX_CARD_CONTENT_LENGTH // 2
                if len(mc) > max_md:
                    element["content"] = mc[:max_md] + "\n\n*内容过长已截断*"
        content_str = json.dumps(card_json, ensure_ascii=False)

    payload = {"receive_id": chat_id, "msg_type": "interactive", "content": content_str}
    data = await _send_message(payload)
    if data.get("code") != 0:
        logger.error(f"Failed to send card message: {data}")
        return False
    logger.info(f"Card message sent to {chat_id}")
    return True


async def send_text_message(chat_id: str, text: str) -> bool:
    if not _is_chat_id_valid(chat_id):
        logger.error(f"Invalid chat_id: {chat_id}")
        return False

    payload = {"receive_id": chat_id, "msg_type": "text",
               "content": json.dumps({"text": text}, ensure_ascii=False)}
    data = await _send_message(payload)
    if data.get("code") != 0:
        logger.error(f"Failed to send text message: {data}")
        return False
    logger.info(f"Text message sent to {chat_id}")
    return True


async def send_processing_card(chat_id: str, message: str = "正在处理您的请求...") -> bool:
    """发送一张"正在处理..."反馈卡片，带动态更新时间戳。

    Args:
        chat_id: 飞书群聊/用户的 chat_id
        message: 自定义处理中提示文字

    Returns:
        是否发送成功
    """
    if not _is_chat_id_valid(chat_id):
        logger.error(f"Invalid chat_id: {chat_id}")
        return False

    update_time = get_update_timestamp()
    card = {
        "header": {
            "template": "blue",
            "title": {"tag": "plain_text", "content": "⏳ 处理中"},
        },
        "elements": [
            {
                "tag": "markdown",
                "content": (
                    f"**{message}**\n\n"
                    f"🕐 开始时间: {update_time}\n\n"
                    "请稍候，数据正在生成中..."
                ),
            },
            {
                "tag": "note",
                "elements": [
                    {
                        "tag": "plain_text",
                        "content": f"⏱️ {update_time} · 明策(MingCe)"
                    }
                ],
            },
        ],
    }
    return await send_card_message(chat_id, card)


async def send_error_notification(error_title: str, error_detail: str):
    if not settings.FEISHU_CHAT_ID or not _is_chat_id_valid(settings.FEISHU_CHAT_ID):
        return False
    safe_detail = error_detail.replace("`", "'").replace("```", "'''")
    card = {
        "header": {
            "template": "red",
            "title": {"tag": "plain_text", "content": f"❌ {error_title}"},
        },
        "elements": [
            {"tag": "markdown", "content": f"```\n{safe_detail[:1000]}\n```"}
        ],
    }
    return await send_card_message(settings.FEISHU_CHAT_ID, card)


# ═══════════════════════════════════════════════════════
# 五维卡片构建（v2.0）
# ═══════════════════════════════════════════════════════

def _build_index_section(market: dict) -> str:
    """A 股核心指数"""
    index_lines = []
    for idx in market.get("indices", []):
        name = idx["name"]
        val = idx.get("value", 0)
        pct = idx.get("change_pct", 0)
        if val and abs(val) >= settings.MIN_INDEX_VALUE_THRESHOLD:
            icon = "🟢" if pct >= 0 else "🔴"
            fire = " 🔥" if pct and abs(pct) >= 2 else ""
            index_lines.append(f"{icon} **{name}** {val:.2f} {_fmt_pct(pct)}{fire}")
        else:
            index_lines.append(f"⚪ **{name}** --")
    index_text = "\n".join(index_lines) if index_lines else "暂无数据"

    up = market.get("up_count", 0)
    down = market.get("down_count", 0)
    vol = market.get("total_volume", "")
    flow_line = ""
    if up > 0 or down > 0:
        flow_line = f"💰 成交{vol} · {up}涨{down}跌"
    elif vol:
        flow_line = f"💰 成交{vol}"

    top_sectors = market.get("top_sectors", [])
    bottom_sectors = market.get("bottom_sectors", [])
    sector_lines = []
    if top_sectors:
        strs = [f"{s['name']}{_fmt_pct(s.get('change_pct', 0))}" for s in top_sectors[:2]]
        sector_lines.append("🔥 最强：" + "、".join(strs))
    if bottom_sectors:
        strs = [f"{s['name']}{_fmt_pct(s.get('change_pct', 0))}" for s in bottom_sectors[:2]]
        sector_lines.append("❄️ 最弱：" + "、".join(strs))

    parts = ["## 📈 核心指数\n" + index_text]
    if flow_line:
        parts.append(flow_line)
    for sl in sector_lines:
        parts.append(sl)
    return "\n".join(parts)


def _build_gold_section_card(gm: dict) -> str:
    """金维度"""
    parts = []
    if gm.get("gold"):
        parts.append(f"🥇 黄金: {gm['gold']}美元")
    if gm.get("silver"):
        parts.append(f"🥈 白银: {gm['silver']}美元")
    if gm.get("gold") and gm.get("silver"):
        try:
            ratio = float(gm['gold']) / float(gm['silver'])
            parts.append(f"金银比: {ratio:.1f}")
        except Exception:
            pass
    return "\n".join(parts) if parts else "*暂无数据*"


def _build_oil_section_card(gm: dict, futures: dict) -> str:
    """油维度"""
    parts = []
    if gm.get("brent_oil"):
        parts.append(f"🛢️ 布伦特: {gm['brent_oil']}")
    if gm.get("wti_oil"):
        parts.append(f"🛢️ WTI: {gm['wti_oil']}")
    futures_items = futures.get("items", [])
    if futures_items:
        futures_text = []
        for item in futures_items[:5]:
            chg = item.get("change_pct", 0) or 0
            icon = "🟢" if chg >= 0 else "🔴"
            futures_text.append(f"{icon}{item['name']} {item.get('price', '')} {_fmt_pct(chg)}")
        parts.append("**国内期货**\n" + "\n".join(futures_text))
    if not parts:
        return "*暂无数据*"
    return "\n".join(parts)


def _build_fx_section_card(gm: dict) -> str:
    """汇维度"""
    parts = []
    if gm.get("usd_index"):
        parts.append(f"💵 美元指数: {gm['usd_index']}")
    if gm.get("usd_cny"):
        parts.append(f"💱 美元/人民币: {gm['usd_cny']}")
    if gm.get("usd_jpy"):
        parts.append(f"💱 美元/日元: {gm['usd_jpy']}")
    if gm.get("euro_usd"):
        parts.append(f"💱 欧元/美元: {gm['euro_usd']}")
    return "\n".join(parts) if parts else "*暂无数据*"


def _build_bond_section_card(gm: dict, macro: dict) -> str:
    """债维度"""
    parts = []
    if gm.get("us_10y_bond"):
        parts.append(f"🇺🇸 10Y: {gm['us_10y_bond']}%")
    if gm.get("us_2y_bond"):
        parts.append(f"🇺🇸 2Y: {gm['us_2y_bond']}%")
    if gm.get("us_10y_bond") and gm.get("us_2y_bond"):
        try:
            spread = float(gm['us_10y_bond']) - float(gm['us_2y_bond'])
            flag = "⚠️" if spread < 0 else "✅"
            parts.append(f"利差: {spread:+.2f}% {flag}")
        except Exception:
            pass
    lpr_1y = macro.get("lpr_1y")
    if lpr_1y:
        lpr_5y = macro.get("lpr_5y", "-")
        parts.append(f"🇨🇳 LPR: 1Y {lpr_1y}% / 5Y {lpr_5y}%")
    shibor = macro.get("shibor_7d")
    if shibor:
        parts.append(f"银行间7天拆借利率: {shibor}%")
    return "\n".join(parts) if parts else "*暂无数据*"


def _build_g_section_card(gm: dict, crypto: dict, north: dict, comparison: dict, monetary: dict) -> str:
    """G 维度"""
    parts = []
    if gm.get("vix"):
        v = float(gm['vix'])
        vix_flag = "😱恐慌" if v > 25 else "😌平静" if v < 15 else "➖正常"
        parts.append(f"📊 VIX: {gm['vix']} {vix_flag}")
    if gm.get("bdi"):
        parts.append(f"🚢 BDI: {gm['bdi']}")
    if crypto.get("btc_price"):
        btc_chg = crypto.get("btc_change", 0) or 0
        icon = "🟢" if btc_chg >= 0 else "🔴"
        parts.append(f"{icon} BTC: {crypto['btc_price']} ({_fmt_pct(btc_chg)})")
    if crypto.get("eth_price"):
        eth_chg = crypto.get("eth_change", 0) or 0
        icon = "🟢" if eth_chg >= 0 else "🔴"
        parts.append(f"{icon} ETH: {crypto['eth_price']} ({_fmt_pct(eth_chg)})")
    net = north.get("net_flow")
    if net is not None and abs(net) > 0.01:
        direction = "流入" if net >= 0 else "流出"
        parts.append(f"💹 北向{direction}{abs(net):.1f}亿")
    if monetary.get("rrr_current"):
        parts.append(f"🏦 存准率: {monetary['rrr_current']}%")
    if monetary.get("social_finance_growth"):
        parts.append(f"📊 社融增量: {monetary['social_finance_growth']}")
    comp_summary = comparison.get("summary", "")
    if comp_summary:
        parts.append(f"🌐 跨市场: {comp_summary}")
    return "\n".join(parts) if parts else "*暂无数据*"


def _build_us_section_card(us_market: dict) -> str:
    """美股"""
    if not us_market:
        return ""
    indices = us_market.get("indices", [])
    top_stocks = us_market.get("top_stocks", [])
    parts = []
    if indices:
        idx_lines = []
        for idx in indices:
            name = idx.get("name", "")
            val = idx.get("value", 0)
            pct = idx.get("change_pct", 0)
            icon = "🟢" if pct >= 0 else "🔴"
            idx_lines.append(f"{icon} {name}: {val:.2f} ({_fmt_pct(pct)})")
        parts.append("**美股指数**\n" + "\n".join(idx_lines))
    if top_stocks:
        stock_lines = []
        for s in top_stocks[:5]:
            pct = s.get("change_pct", 0)
            icon = "🟢" if pct >= 0 else "🔴"
            stock_lines.append(f"{icon} {s['name']} ({_fmt_pct(pct)})")
        parts.append("**热门个股**\n" + "\n".join(stock_lines))
    return "\n\n".join(parts) if parts else "*暂无数据*"


def _build_monetary_section_card(monetary: dict) -> str:
    """货币政策量化"""
    if not monetary:
        return ""
    parts = []
    if monetary.get("m2_growth"):
        parts.append(f"📈 M2 同比: {monetary['m2_growth']}")
    if monetary.get("social_finance_growth"):
        parts.append(f"📊 社融增量: {monetary['social_finance_growth']}")
    if monetary.get("rrr_current"):
        parts.append(f"🏦 存准率: {monetary['rrr_current']}")
    return "\n".join(parts) if parts else "*暂无数据*"


def _build_etf_section_card(etf: dict) -> str:
    """ETF 动向"""
    if not etf:
        return ""
    broad = etf.get("broad_based", [])
    industry = etf.get("industry", [])
    parts = []
    if broad:
        b_lines = [f"{'🟢' if e.get('change_pct', 0) >= 0 else '🔴'} {e['name']} {_fmt_pct(e.get('change_pct', 0))}"
                   for e in broad[:5]]
        parts.append("**宽基ETF**\n" + "\n".join(b_lines))
    if industry:
        i_lines = [f"{'🟢' if e.get('change_pct', 0) >= 0 else '🔴'} {e['name']} {_fmt_pct(e.get('change_pct', 0))}"
                   for e in industry[:5]]
        parts.append("**行业ETF**\n" + "\n".join(i_lines))
    return "\n\n".join(parts) if parts else "*暂无数据*"


def _build_leading_section_card(leading: dict) -> str:
    """龙头企业"""
    if not leading:
        return ""
    headlines = leading.get("headlines", [])[:5]
    if not headlines:
        return ""
    lines = []
    for h in headlines:
        pct = h.get("change_pct", 0)
        lines.append(f"{'🟢' if pct >= 0 else '🔴'} **{h['name']}** {_fmt_pct(pct)} 市值{h.get('market_cap', '')}")
    return "\n".join(lines)


def _build_bse_section_card(bse: dict) -> str:
    """北证市场"""
    if not bse:
        return ""
    indices = bse.get("indices", [])
    if not indices:
        return ""
    lines = []
    for idx in indices:
        pct = idx.get("change_pct", 0)
        val = idx.get("value", 0)
        icon = "🟢" if pct >= 0 else "🔴"
        lines.append(f"{icon} {idx['name']}: {val:.2f} ({_fmt_pct(pct)})")
    headlines = bse.get("leading", {}).get("headlines", [])[:3]
    if headlines:
        lines.append("**北证龙头**")
        for h in headlines:
            pct = h.get("change_pct", 0)
            lines.append(f"{'🟢' if pct >= 0 else '🔴'} {h['name']} ({_fmt_pct(pct)})")
    return "\n".join(lines)


def build_strategy_signals_card(signals_data: dict, version: str = "opening") -> dict:
    """构建策略信号卡片（轻量版本，用于 09:15 开盘推送）。

    Args:
        signals_data: 策略适配器返回的完整数据 {"symbols": {...}, "date": "...", "total_symbols": N}
        version: 版本名称 (opening/early/morning/noon/close)

    Returns:
        飞书卡片 dict
    """
    import math as _math
    report_date = datetime.now().strftime("%Y-%m-%d")
    symbols = signals_data.get("symbols", {})
    total_stocks = signals_data.get("total_symbols", 0)

    # 构建内容
    sections = []

    # ── 策略信号头 ──
    header_lines = ["## 🎯 自选股策略信号"]
    header_lines.append(f"📅 更新: {signals_data.get('date', report_date)}")
    sections.append("\n".join(header_lines))

    # ── 全局摘要：统计所有股票的买卖信号 ──
    total_buy = 0
    total_sell = 0
    for sym, data in symbols.items():
        if "error" in data:
            continue
        total_buy += data.get("buy_count", 0)
        total_sell += data.get("sell_count", 0)

    if total_buy > 0 or total_sell > 0:
        net_direction = total_buy - total_sell
        if net_direction > 0:
            senti_icon = "🟢"
            senti_text = "偏多"
        elif net_direction < 0:
            senti_icon = "🔴"
            senti_text = "偏空"
        else:
            senti_icon = "➖"
            senti_text = "中性"
        summary_line = f"📊 **{total_buy}策略看多 vs {total_sell}策略看空 → {senti_icon}{senti_text}**"
        sections.append(summary_line)
    else:
        sections.append("📊 **暂无策略信号**")
    sections.append("")

    # ── 逐只股票展示（简洁模式）──
    for sym, data in symbols.items():
        if "error" in data:
            sections.append(f"**{data.get('stock_name', sym)}** ({sym}) — ❌ {data['error']}")
            continue

        stock_name = data.get("stock_name", sym)
        price = data.get("price", 0)
        change_pct = data.get("change_pct", 0)
        change_icon = "🟢" if change_pct >= 0 else "🔴"
        buy_n = data.get("buy_count", 0)
        sell_n = data.get("sell_count", 0)

        stock_lines = [f"**{stock_name}** ({sym})"]
        stock_lines.append(f"{change_icon} {price:.2f} ({change_pct:+.2f}%)  🟢买入{buy_n}  🔴卖出{sell_n}")

        # 无明确信号：买入=0 且 卖出=0
        if buy_n == 0 and sell_n == 0:
            stock_lines.append("  ⚪ **无明确信号**")
        else:
            # 买入信号详情（简洁：策略名 + 强度条 在同一行）
            for sig in data.get("buy_signals", [])[:5]:
                strength = sig.get("signal_strength", 0)
                bar = "▓" * min(int(strength * 10), 10) + "░" * (10 - min(int(strength * 10), 10))
                stock_lines.append(f"  🟢 {sig['strategy_name']} {bar} {strength:.0%}")

            # 卖出信号详情
            for sig in data.get("sell_signals", [])[:5]:
                strength = sig.get("signal_strength", 0)
                bar = "▓" * min(int(strength * 10), 10) + "░" * (10 - min(int(strength * 10), 10))
                stock_lines.append(f"  🔴 {sig['strategy_name']} {bar} {strength:.0%}")

        # 综合判断（基于净信号）
        net = buy_n - sell_n
        if net > 2:
            stock_lines.append("  ✅ **综合: 偏多**")
        elif net < -2:
            stock_lines.append("  ⚠️ **综合: 偏空**")
        else:
            stock_lines.append("  ➖ **综合: 中性**")

        sections.append("\n".join(stock_lines))

    # ── 页脚 ──
    version_labels = {"opening": "开盘信号", "early": "隔夜", "morning": "早盘", "noon": "午间", "close": "收盘"}
    v_label = version_labels.get(version, version)
    footer = (
        "---\n"
        f"📊 共扫描 {total_stocks} 只股票 | {len(symbols)} 项有数据\n"
        f"📌 v2.0 | {v_label} | 基于 18 个核心策略\n"
        "⚠️ 不构成投资建议"
    )
    sections.append(footer)

    card_text = "\n\n".join(sections)
    card_text = card_text.replace("None", "暂无数据")

    title_text = f"🎯 {report_date} 自选股策略信号（{v_label}）"
    return {
        "header": {
            "template": "indigo",
            "title": {"tag": "plain_text", "content": title_text},
        },
        "elements": [{"tag": "markdown", "content": card_text}],
    }


def build_alert_card(alerts: list[dict]) -> dict:
    items = []
    for a in alerts:
        icon = "🔴" if a["level"] == "danger" else "🟡"
        items.append(f"{icon} **{a.get('title', '')}**\n{a.get('content', '')}")
    content_text = "\n\n".join(items) if items else "*暂无异动*"
    return {
        "header": {
            "template": "red",
            "title": {"tag": "plain_text", "content": "🚨 异动提醒"},
        },
        "elements": [{"tag": "markdown", "content": content_text}],
    }


def build_detail_card(data: dict) -> dict:
    """五维框架日报详情卡片（v2.0）。"""
    report_date = data.get("report_date", "")
    version = data.get("version", "")
    market = data.get("market", {})
    macro = data.get("macro", {})
    north = data.get("north_flow", {})
    etf = data.get("etf", {})
    leading = data.get("leading", {})
    global_m = data.get("global_macro", {})
    bse = data.get("bse", {})
    us_market = data.get("us_market", {})
    crypto = data.get("crypto", {})
    futures = data.get("futures", {})
    monetary = data.get("monetary", {})
    comparison = data.get("comparison", {})
    commentary = data.get("master_commentary", "")
    dim_analysis = data.get("five_dimension_analysis", "")
    alerts = data.get("alerts", [])
    update_time = get_update_timestamp()

    sections = []

    # 0. 异动提醒（置顶）
    if alerts:
        alert_lines = []
        for a in alerts[:5]:
            icon = "🔴" if a.get("level") == "danger" else "🟡"
            alert_lines.append(f"{icon} **{a.get('title', '异动')}**：{a.get('content', '')}")
        sections.append("## 🚨 异动提醒\n" + "\n".join(alert_lines))

    # 1. A 股核心指数
    sections.append(_build_index_section(market))

    # 2. 五维矩阵
    sections.append(
        "## 🏛️ 五维矩阵\n"
        f"**金**\n{_build_gold_section_card(global_m)}\n\n"
        f"**油**\n{_build_oil_section_card(global_m, futures)}\n\n"
        f"**汇**\n{_build_fx_section_card(global_m)}\n\n"
        f"**债**\n{_build_bond_section_card(global_m, macro)}\n\n"
        f"**G**\n{_build_g_section_card(global_m, crypto, north, comparison, monetary)}"
    )

    # 3. 美股
    us_text = _build_us_section_card(us_market)
    if us_text:
        sections.append("## 🇺🇸 美股\n" + us_text)

    # 4. 货币政策量化
    mon_text = _build_monetary_section_card(monetary)
    if mon_text:
        sections.append("## 🏦 货币政策\n" + mon_text)

    # 5. ETF / 龙头 / 北证
    etf_text = _build_etf_section_card(etf)
    lead_text = _build_leading_section_card(leading)
    bse_text = _build_bse_section_card(bse)
    extra_parts = []
    if etf_text:
        extra_parts.append(etf_text)
    if lead_text:
        extra_parts.append(lead_text)
    if bse_text:
        extra_parts.append(bse_text)
    if extra_parts:
        sections.append("## 📊 市场扫描\n\n".join(extra_parts))

    # 6. 跨市场比价
    comp_summary = comparison.get("summary", "")
    if comp_summary:
        sections.append("## 🌐 跨市场比较\n" + comp_summary)

    # 7. 策略信号（MakingMoney 注入）
    strategy_signals = data.get("strategy_signals", {})
    if strategy_signals:
        signal_lines = []
        for sym, sig_data in strategy_signals.items():
            sigs = sig_data.get("signals", [])
            name = sig_data.get("name", sym)
            price = sig_data.get("price", 0)
            change_pct = sig_data.get("change_pct", 0)
            icon = "🟢" if change_pct >= 0 else "🔴"
            buy_count = sum(1 for s in sigs if s.get("signal", 0) > 0)
            sell_count = sum(1 for s in sigs if s.get("signal", 0) < 0)
            signal_lines.append(f"{icon} **{name}** ({sym}) {price:.2f} ({change_pct:+.2f}%)  🟢{buy_count}  🔴{sell_count}")
            # 显示前3个信号详情
            for s in sigs[:3]:
                action_icon = "🟢" if s.get("signal", 0) > 0 else "🔴"
                strength = s.get("signal_strength", 0)
                bar = "▓" * min(int(strength * 10), 10) + "░" * (10 - min(int(strength * 10), 10))
                signal_lines.append(f"  {action_icon} {s['strategy']} {bar} {strength:.0%}")
        sections.append("## 🎯 策略信号\n" + "\n".join(signal_lines))

    # 8. 宏观数据
    macro_parts = []
    if macro.get("cpi"):
        macro_parts.append(f"居民消费价格(CPI): {macro['cpi']}")
    if macro.get("ppi"):
        macro_parts.append(f"工业品出厂价(PPI): {macro['ppi']}")
    if macro.get("pmi"):
        macro_parts.append(f"采购经理指数(PMI): {macro['pmi']}")
    if macro.get("m2"):
        macro_parts.append(f"M2: {macro['m2']}")
    if macro_parts:
        sections.append("## 📋 宏观数据\n" + " | ".join(macro_parts))

    # 8. 大师兄解读
    if commentary:
        sections.append("## 💡 大师兄解读\n" + commentary)

    # 9. 五维专项分析
    if dim_analysis and dim_analysis not in commentary:
        sections.append("## 🔍 五维深度分析\n" + dim_analysis)

    # 10. 帮助信息 / 页脚
    footer = (
        "---\n"
        f"📈 数据更新: {update_time}\n"
        f"📌 v2.0 | 收盘 | 金油汇债G五维框架\n"
        "⚠️ 不构成投资建议"
    )
    sections.append(footer)

    # 清理卡片中的英文残留
    card_text = "\n\n".join(sections)
    card_text = card_text.replace("None", "暂无数据")
    card_text = card_text.replace("null", "暂无数据")
    card_text = card_text.replace("True", "是")
    card_text = card_text.replace("False", "否")
    sections = card_text.split("\n\n")

    title_text = f"📊 {report_date} 日报详情{' ' + version if version else ''}"
    # 版本名英文→中文
    version_labels = {"close": "收盘", "morning": "早盘", "noon": "午间", "early": "隔夜"}
    v_label = version_labels.get(version, version)
    title_text = f"📊 {report_date} 日报详情（{v_label}）"
    if not data.get("is_trading_day", True):
        title_text += " 🏖️ 非交易日"
    return {
        "header": {
            "template": "turquoise",
            "title": {"tag": "plain_text", "content": title_text},
        },
        "elements": [{"tag": "markdown", "content": "\n\n".join(sections)}],
    }
