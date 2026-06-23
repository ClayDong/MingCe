"""日报生成与推送编排 — v2.0 五维框架。

按「金油汇债G」五维框架重组：
- 金：黄金 + 白银
- 油：布伦特 + WTI + 国内商品期货
- 汇：美元指数 + 主要汇率篮子
- 债：美债收益率 + Shibor + LPR
- G：衍生品(VIX/BDI) + 加密货币 + 北向资金 + 跨市场比价

新增数据源：美股 / 加密货币 / 国内期货 / 货币政策量化 / 跨市场比价
"""

import asyncio
import json
import zlib
import base64
from datetime import date, datetime, timedelta
from loguru import logger

from core.database import get_db
from services.data_fetcher import (
    get_market_overview, get_macro_data, get_north_flow,
    get_etf_data, get_leading_stocks, get_global_macro, get_bse_data, detect_alerts,
    get_us_market, get_crypto_data, get_futures_data,
    get_monetary_data, get_intraday_comparison, _extend_alerts,
)
from services.llm_service import generate_commentary, generate_five_dimension_analysis
from services.feishu_service import (
    send_error_notification, build_detail_card,
    build_alert_card, send_card_message,
)
from config.settings import get_settings

settings = get_settings()
TRADING_DAYS = (0, 1, 2, 3, 4)

# 交易日检测：使用 chinesecalendar（自动更新至2027+）替代硬编码节假日
try:
    from chinese_calendar import is_holiday as _is_chinese_holiday
except ImportError:
    # 降级：仅周末判断
    _is_chinese_holiday = None
    logger.warning("chinesecalendar 未安装，仅靠周末判断交易日")

# 去重存储
_sent_reports = {}
_SEND_COOLDOWN_MINUTES = 10


def _is_trading_day() -> bool:
    today = date.today()
    # 周末
    if today.weekday() not in TRADING_DAYS:
        return False
    # 中国法定节假日
    if _is_chinese_holiday and _is_chinese_holiday(today):
        return False
    return True


# ═══════════════════════════════════════════════════════
# 五维市场摘要构建
# ═══════════════════════════════════════════════════════

def _build_gold_section(gm: dict) -> str:
    """维度一：金 — 黄金 + 白银"""
    parts = ["【金】"]
    if gm.get("gold"):
        parts.append(f"黄金: {gm['gold']}美元/盎司")
    if gm.get("silver"):
        parts.append(f"白银: {gm['silver']}美元/盎司")
    if gm.get("gold") and gm.get("silver"):
        try:
            ratio = float(gm['gold']) / float(gm['silver'])
            parts.append(f"金银比: {ratio:.1f}")
        except (ValueError, ZeroDivisionError):
            pass
    return "\n".join(parts) if len(parts) > 1 else ""


def _build_oil_section(gm: dict, futures: dict) -> str:
    """维度二：油 — 布伦特 + WTI + 国内商品期货"""
    parts = ["【油】"]
    if gm.get("brent_oil"):
        parts.append(f"布伦特原油: {gm['brent_oil']}美元/桶")
    if gm.get("wti_oil"):
        parts.append(f"WTI: {gm['wti_oil']}美元/桶")
    # 国内商品期货
    futures_items = futures.get("items", [])
    if futures_items:
        items_str = []
        for item in futures_items[:6]:
            chg = item.get("change_pct", 0) or 0
            icon = "🟢" if chg >= 0 else "🔴"
            items_str.append(f"{icon}{item['name']} {item.get('price', '')} {chg:+.2f}%")
        parts.append("期货: " + " | ".join(items_str))
    return "\n".join(parts) if len(parts) > 1 else ""


def _build_fx_section(gm: dict) -> str:
    """维度三：汇 — 美元指数 + 主要汇率篮子"""
    parts = ["【汇】"]
    if gm.get("usd_index"):
        parts.append(f"美元指数: {gm['usd_index']}")
    if gm.get("usd_cny"):
        parts.append(f"美元/人民币: {gm['usd_cny']}")
    if gm.get("usd_jpy"):
        parts.append(f"美元/日元: {gm['usd_jpy']}")
    if gm.get("euro_usd"):
        parts.append(f"欧元/美元: {gm['euro_usd']}")
    return "\n".join(parts) if len(parts) > 1 else ""


def _build_bond_section(gm: dict, macro: dict, monetary: dict) -> str:
    """维度四：债 — 美债收益率 + 中国利率"""
    parts = ["【债】"]
    if gm.get("us_10y_bond"):
        parts.append(f"美国10Y: {gm['us_10y_bond']}%")
    if gm.get("us_2y_bond"):
        parts.append(f"美国2Y: {gm['us_2y_bond']}%")
    if gm.get("us_10y_bond") and gm.get("us_2y_bond"):
        try:
            spread = float(gm['us_10y_bond']) - float(gm['us_2y_bond'])
            flag = "⚠️倒挂" if spread < 0 else "✅正常"
            parts.append(f"10Y-2Y利差: {spread:+.2f}% {flag}")
        except (ValueError, TypeError):
            pass
    lpr_1y = macro.get("lpr_1y")
    if lpr_1y:
        lpr_5y = macro.get("lpr_5y", "-")
        parts.append(f"LPR: 1Y {lpr_1y}% / 5Y {lpr_5y}%")
    shibor = macro.get("shibor_7d")
    if shibor:
        parts.append(f"银行间7天拆借: {shibor}%")
    return "\n".join(parts) if len(parts) > 1 else ""


def _build_derivatives_section(gm: dict, crypto: dict, north: dict, comparison: dict, monetary: dict) -> str:
    """维度五：G — VIX/BDI/加密货币/北向资金/跨市场比价"""
    parts = ["【G】"]
    if gm.get("vix"):
        parts.append(f"VIX: {gm['vix']}")
    if gm.get("bdi"):
        parts.append(f"BDI: {gm['bdi']}")
    # 加密货币
    if crypto.get("btc_price"):
        btc_chg = crypto.get("btc_change", 0) or 0
        icon = "🟢" if btc_chg >= 0 else "🔴"
        parts.append(f"{icon}BTC: {crypto['btc_price']} ({btc_chg:+.2f}%)")
    if crypto.get("eth_price"):
        eth_chg = crypto.get("eth_change", 0) or 0
        icon = "🟢" if eth_chg >= 0 else "🔴"
        parts.append(f"{icon}ETH: {crypto['eth_price']} ({eth_chg:+.2f}%)")
    # 北向资金
    net = north.get("net_flow")
    if net is not None and abs(net) > 0.01:
        direction = "流入" if net >= 0 else "流出"
        parts.append(f"北向{direction}{abs(net):.1f}亿")
    # 货币政策量化
    if monetary.get("rrr_current"):
        parts.append(f"存准率: {monetary['rrr_current']}%")
    if monetary.get("social_finance_growth"):
        parts.append(f"社融增量: {monetary['social_finance_growth']}")
    # 跨市场比价摘要
    comp_summary = comparison.get("summary", "")
    if comp_summary:
        parts.append(f"跨市场: {comp_summary}")
    return "\n".join(parts) if len(parts) > 1 else ""


# 数据置信度标签（附加在每个模块后面）
_DATA_CONFIDENCE = {
    "market": "[置信度: 高 · 3源回退 · 缓存TTL 5min]",
    "macro": "[置信度: 高 · 官方发布 · 缓存TTL 12h]",
    "north_flow": "[置信度: 中 · akshare直连 · 缓存TTL 30min]",
    "global_macro": "[置信度: 中 · akshare聚合 · 缓存TTL 1h]",
    "us_market": "[置信度: 中 · 新浪/akshare · 缓存TTL 30min]",
    "crypto": "[置信度: 中 · akshare+CoinGecko双源 · 缓存TTL 15min]",
    "futures": "[置信度: 中 · 国内期货实时 · 缓存TTL 30min]",
    "monetary": "[置信度: 高 · 央行官方数据 · 缓存TTL 12h]",
    "comparison": "[置信度: 中 · 多市场聚合 · 缓存TTL 30min]",
    "etf": "[置信度: 中 · akshare实时 · 缓存TTL 30min]",
    "leading": "[置信度: 低 · 估算值 · 缓存TTL 30min]",
    "bse": "[置信度: 低 · 估算值 · 缓存TTL 30min]",
}


def _build_market_summary_v2(data: dict) -> str:
    """构建五维市场摘要文本（用于 LLM 分析，含数据置信度标注）。"""
    gm = data.get("global_macro", {})
    market = data.get("market", {})
    north = data.get("north_flow", {})
    macro = data.get("macro", {})
    crypto = data.get("crypto", {})
    futures = data.get("futures", {})
    monetary = data.get("monetary", {})
    comparison = data.get("comparison", {})
    us_market = data.get("us_market", {})
    etf = data.get("etf", {})
    leading = data.get("leading", {})
    bse = data.get("bse", {})

    lines = ["📊 五维市场全景摘要", f"日期: {data.get('report_date', '')}", f"版本: {data.get('version', '')}", f"生成时间: {datetime.now().strftime('%H:%M:%S')}"]
    lines.append("")

    # ═══ A 股核心 ═══
    lines.append("【A股核心】 " + _DATA_CONFIDENCE["market"])
    for idx in market.get("indices", []):
        val = idx.get("value")
        chg = idx.get("change_pct")
        val_str = f"{val:.2f}" if val is not None else "暂无"
        chg_str = f"{chg:+.2f}%" if chg is not None else "暂无"
        lines.append(f"  {idx['name']}: {val_str} ({chg_str})")
    up = market.get("up_count", 0)
    down = market.get("down_count", 0)
    vol = market.get("total_volume", "")
    if up or down:
        lines.append(f"  涨跌: {up}涨/{down}跌  成交: {vol}")
    for s in market.get("top_sectors", [])[:3]:
        lines.append(f"  🔥{s['name']} {s.get('change_pct', 0):+.1f}%")
    for s in market.get("bottom_sectors", [])[:3]:
        lines.append(f"  ❄️{s['name']} {s.get('change_pct', 0):+.1f}%")
    lines.append("")

    # ═══ 五维（含数据置信度标签） ═══
    sections = [
        ("【金】" + " " + _DATA_CONFIDENCE["global_macro"], _build_gold_section(gm=gm)),
        ("【油】" + " " + _DATA_CONFIDENCE["global_macro"], _build_oil_section(gm=gm, futures=futures)),
        ("【汇】" + " " + _DATA_CONFIDENCE["global_macro"], _build_fx_section(gm=gm)),
        ("【债】" + " " + _DATA_CONFIDENCE["global_macro"], _build_bond_section(gm=gm, macro=macro, monetary=monetary)),
        ("【G】" + " " + _DATA_CONFIDENCE["global_macro"], _build_derivatives_section(gm=gm, crypto=crypto, north=north, comparison=comparison, monetary=monetary)),
    ]
    for label, text in sections:
        if text:
            lines.append(label)
            lines.append(text)
            lines.append("")

    # ═══ 美股 ═══
    us_indices = us_market.get("indices", [])
    if us_indices:
        lines.append("【美股】")
        for idx in us_indices:
            us_val = idx.get("value")
            us_chg = idx.get("change_pct")
            us_val_str = f"{us_val:.2f}" if us_val is not None else "暂无"
            us_chg_str = f"{us_chg:+.2f}%" if us_chg is not None else "暂无"
            lines.append(f"  {idx['name']}: {us_val_str} ({us_chg_str})")
        us_stocks = us_market.get("top_stocks", [])
        if us_stocks:
            hot = [f"{s['name']}{s['change_pct']:+.2f}%" for s in us_stocks[:5]]
            lines.append("  热门: " + " | ".join(hot))
        lines.append("")

    # ═══ 宏观数据 ═══
    macro_parts = []
    if macro.get("cpi"):
        macro_parts.append(f"CPI: {macro['cpi']}")
    if macro.get("ppi"):
        macro_parts.append(f"PPI: {macro['ppi']}")
    if macro.get("pmi"):
        macro_parts.append(f"PMI: {macro['pmi']}")
    if macro_parts:
        lines.append("【宏观数据】" + " | ".join(macro_parts))

    # 货币政策
    if monetary.get("m2_growth"):
        lines.append(f"  M2: {monetary['m2_growth']}")
    if monetary.get("social_finance_growth"):
        lines.append(f"  社融: {monetary['social_finance_growth']}")

    # ═══ ETF/大市值涨幅榜/北证 ═══
    etf_high = etf.get("broad_based", [])[:3]
    if etf_high:
        etf_str = [f"{e['name']}{e.get('change_pct', 0):+.2f}%" for e in etf_high]
        lines.append(f"【ETF】{' | '.join(etf_str)}")

    leading_items = leading.get("headlines", [])[:5]
    if leading_items:
        lead_str = [f"{s['name']}{s.get('change_pct', 0):+.2f}%" for s in leading_items[:3]]
        lines.append(f"【大市值涨幅榜】{' | '.join(lead_str)}")

    for idx in bse.get("indices", []):
        p = idx.get("change_pct", 0)
        lines.append(f"【北证】{idx['name']} ({p:+.2f}%)")

    lines.append("")
    lines.append(f"更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    return "\n".join(lines)


async def _save_report_to_db(report_date: str, version: str, data: dict):
    try:
        db = await get_db()
        content = json.dumps(data, ensure_ascii=False, default=str)
        # 压缩内容（如果超过1KB）
        if isinstance(content, str) and len(content) > 1024:
            content = "ZLIB:" + base64.b64encode(zlib.compress(content.encode("utf-8"))).decode("ascii")
        modules = json.dumps(list(data.keys()), ensure_ascii=False)
        await db.execute(
            """INSERT OR REPLACE INTO daily_reports
               (report_date, version, content, modules, status, updated_at)
               VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
            (report_date, version, content, modules, "completed"),
        )
        logger.debug(f"Report saved to DB: {report_date}/{version}")
    except Exception as e:
        logger.error(f"Failed to save report to DB: {e}")


async def generate_daily_report(version: str = "close") -> dict:
    """生成日报数据（五维框架 v2.0）。"""
    logger.info(f"Generating daily report v2.0, version={version}")
    report_date = date.today().isoformat()
    is_trading = _is_trading_day()

    if not is_trading:
        logger.info(f"Non-trading day ({report_date}), fetching available data anyway")

    # 获取各模块数据（异步线程池，避免阻塞事件循环）
    logger.info("Fetching all data modules (v2.0)...")
    _loop = asyncio.get_event_loop()
    market, macro, north, etf, leading, global_m, bse = await asyncio.gather(
        _loop.run_in_executor(None, get_market_overview),
        _loop.run_in_executor(None, get_macro_data),
        _loop.run_in_executor(None, get_north_flow),
        _loop.run_in_executor(None, get_etf_data),
        _loop.run_in_executor(None, get_leading_stocks),
        _loop.run_in_executor(None, get_global_macro),
        _loop.run_in_executor(None, get_bse_data),
    )

    # 新增数据源（异步并行）
    us_market, crypto, futures, monetary, comparison = await asyncio.gather(
        _loop.run_in_executor(None, get_us_market),
        _loop.run_in_executor(None, get_crypto_data),
        _loop.run_in_executor(None, get_futures_data),
        _loop.run_in_executor(None, get_monetary_data),
        _loop.run_in_executor(None, get_intraday_comparison),
    )

    data = {
        "report_date": report_date,
        "version": version,
        "is_trading_day": is_trading,
        "market": market,
        "macro": macro,
        "north_flow": north,
        "etf": etf,
        "leading": leading,
        "global_macro": global_m,
        "bse": bse,
        "us_market": us_market,
        "crypto": crypto,
        "futures": futures,
        "monetary": monetary,
        "comparison": comparison,
    }

    # 生成告警
    alerts = detect_alerts(market, north, leading, etf, bse)
    alerts = _extend_alerts(alerts, crypto, futures)
    data["alerts"] = alerts

    # 构建五维摘要并生成 LLM 解读
    market_summary = _build_market_summary_v2(data)
    # 清理英文残留（仅处理非数据字段中的英文值）
    market_summary = market_summary.replace("close", "收盘")
    market_summary = market_summary.replace("False", "否")
    market_summary = market_summary.replace("True", "是")
    logger.debug(f"Market summary v2.0 for LLM ({len(market_summary)} chars)")

    if market_summary and len(market_summary) > 20:
        try:
            # 自动检测市场上下文，动态加载知识库章节
            from services.llm_service import _detect_market_context
            market_context = _detect_market_context(data)
            commentary = await generate_commentary(market_summary, market_context)
        except Exception as e:
            logger.error(f"Failed to generate LLM commentary: {e}")
            commentary = ""
    else:
        try:
            commentary = await generate_commentary(
                f"今日市场概况（五维框架）:\n"
                f"- 交易日: {'是' if is_trading else '否'}\n"
                f"- 指数: {market.get('indices', [])}\n"
                f"- 北向资金: {north.get('net_flow', '暂无')}亿\n"
                f"- BTC: {crypto.get('btc_price', '暂无')}"
            )
        except Exception as e:
            logger.error(f"Failed to generate fallback commentary: {e}")
            commentary = ""

    if commentary:
        # 如果LLM返回了英文思维链而非正经分析，也走降级
        reasoning_markers = ["Analyze the Request", "Thinking Process", "Self-Correction",
                             "Drafting the", "Search Plan", "Simulating", "Action:"]
        if any(m in commentary for m in reasoning_markers):
            logger.warning("LLM returned reasoning instead of analysis, using template fallback")
            commentary = ""
    
    if not commentary:
        # 生成结构化兜底解读
        fallback_parts = ["📊 今日市场数据摘要"]
        indices = market.get("indices", [])
        if indices:
            idx_lines = []
            for idx in indices:
                v = idx.get("value")
                p = idx.get("change_pct")
                icon = "🟢" if (p or 0) >= 0 else "🔴"
                v_str = f"{v:.2f}" if v is not None else "暂无"
                p_str = f"{p:+.2f}%" if p is not None else "暂无"
                idx_lines.append(f"{icon}{idx['name']}: {v_str} ({p_str})")
            fallback_parts.append("\n".join(idx_lines))

        north_net = north.get("net_flow")
        if north_net is not None and abs(north_net) > 0.01:
            dir_ = "流入" if north_net >= 0 else "流出"
            fallback_parts.append(f"北向资金: {dir_}{abs(north_net):.1f}亿 · 板块方面")

        # 板块轮动
        top_sec = market.get("top_sectors", [])
        bottom_sec = market.get("bottom_sectors", [])
        if top_sec:
            tops = "、".join([f"{s['name']}{s.get('change_pct',0):+.1f}%" for s in top_sec[:2]])
            fallback_parts.append(f"🔥 最强板块: {tops}")
        if bottom_sec:
            bots = "、".join([f"{s['name']}{s.get('change_pct',0):+.1f}%" for s in bottom_sec[:2]])
            fallback_parts.append(f"❄️ 最弱板块: {bots}")

        btc = crypto.get("btc_price")
        btc_chg = crypto.get("btc_change")
        if btc:
            chg_str = f" ({btc_chg:+.2f}%)" if btc_chg else ""
            icon = "🟢" if (btc_chg or 0) >= 0 else "🔴"
            fallback_parts.append(f"{icon}BTC: {btc}{chg_str}")

        m2 = monetary.get("m2_growth")
        if m2:
            fallback_parts.append(f"M2同比: {m2}")

        commentary = "\n\n".join(fallback_parts) if fallback_parts else "📊 数据获取中，请稍后查看。"
        logger.info("LLM commentary unavailable, used template fallback")
    # 清理 commentary 中可能残留的 None 值
    if commentary:
        commentary = commentary.replace("None", "暂无").replace("True", "是").replace("False", "否")
    data["master_commentary"] = commentary

    # 顺便生成五维专项解读
    try:
        dim_analysis = await generate_five_dimension_analysis(data)
        data["five_dimension_analysis"] = dim_analysis
        if data["five_dimension_analysis"]:
            data["five_dimension_analysis"] = data["five_dimension_analysis"].replace("None", "暂无").replace("True", "是").replace("False", "否")
    except Exception as e:
        logger.error(f"Failed to generate five-dimension analysis: {e}")
        data["five_dimension_analysis"] = ""

    # 生成小白模式一句话总结（大白话，便于非专业用户理解）
    try:
        from services.llm_service import generate_beginner_summary
        beginner_summary = await generate_beginner_summary(data)
        if beginner_summary:
            data["beginner_summary"] = beginner_summary
            logger.info(f"Beginner summary generated: {beginner_summary[:50]}")
    except Exception as e:
        logger.error(f"Failed to generate beginner summary: {e}")
        data["beginner_summary"] = ""

    # 炒股的智慧深度分析（触发条件满足时才生成）
    try:
        from services.wisdom_analyzer import generate_wisdom_analysis, _detect_wisdom_triggers
        triggers = _detect_wisdom_triggers(data)
        if triggers.get("triggered"):
            wisdom_analysis = await generate_wisdom_analysis(data)
            if wisdom_analysis:
                data["wisdom_analysis"] = wisdom_analysis
                data["wisdom_triggers"] = triggers
                logger.info(f"Wisdom analysis generated (triggers: {triggers.get('trigger_count', 0)})")
    except Exception as e:
        logger.error(f"Failed to generate wisdom analysis: {e}")

    # 生成自选股+持仓的策略信号
    try:
        from services.portfolio_manager import get_holdings, get_watchlist
        from services.decision_engine import analyze_stock, get_portfolio_summary
        
        # 只扫描自选股+持仓（非交易日也扫描，不限制）
        watchlist = await get_watchlist()
        holdings = await get_holdings()
        
        # 去重合并
        all_symbols = {}
        for h in holdings:
            all_symbols[h["symbol"]] = h["name"]
        for w in watchlist:
            if w["symbol"] not in all_symbols:
                all_symbols[w["symbol"]] = w["name"]
        
        strategy_signals = {}
        for sym, nm in all_symbols.items():
            try:
                result = analyze_stock(sym, nm)
                strategy_signals[sym] = result
            except Exception as e:
                logger.error(f"Strategy scan failed for {sym}: {e}")
        
        data["strategy_signals"] = strategy_signals
        
        # 组合概览
        if holdings:
            portfolio = get_portfolio_summary()
            data["portfolio_summary"] = portfolio
    except Exception as e:
        logger.error(f"Failed to generate strategy signals: {e}")
        data["strategy_signals"] = {}
        data["portfolio_summary"] = {}

    await _save_report_to_db(report_date, version, data)
    logger.info("Daily report v2.0 data generated")
    return data


def _should_send_report(version: str) -> bool:
    report_date = date.today().isoformat()
    key = f"{report_date}_{version}"
    now = datetime.now()
    last_sent = _sent_reports.get(key)
    if last_sent is not None:
        time_diff = (now - last_sent).total_seconds() / 60
        if time_diff < _SEND_COOLDOWN_MINUTES:
            logger.warning(f"Report {version} was sent {time_diff:.1f} minutes ago, skipping")
            return False
    return True


def _mark_report_sent(version: str):
    report_date = date.today().isoformat()
    key = f"{report_date}_{version}"
    _sent_reports[key] = datetime.now()
    cutoff = datetime.now() - timedelta(hours=24)
    keys_to_remove = [k for k, v in _sent_reports.items() if v < cutoff]
    for k in keys_to_remove:
        del _sent_reports[k]


async def push_daily_report(data: dict) -> bool:
    """推送日报到飞书（五维框架卡片）。"""
    chat_id = settings.FEISHU_CHAT_ID
    if not chat_id:
        logger.error("FEISHU_CHAT_ID not configured, cannot push")
        return False

    version = data.get("version", "unknown")

    if not _should_send_report(version):
        logger.info(f"Skipping duplicate report push for version {version}")
        return False

    try:
        # 预先获取信号胜率统计（async），注入到 data 供同步的 build_detail_card 使用
        try:
            from services.signal_tracker import get_signal_tracker
            tracker = get_signal_tracker()
            signal_stats = await tracker.get_accuracy_stats(days=30)
            if signal_stats and signal_stats.get("total_signals", 0) > 0:
                data["signal_accuracy_stats"] = signal_stats
        except Exception as _e:
            logger.debug(f"获取信号胜率统计失败: {_e}")

        detail_card = build_detail_card(data)
        ok = await send_card_message(chat_id, detail_card)

        if ok:
            _mark_report_sent(version)
            logger.info(f"Daily report v2.0 card sent: {ok}")
        return ok
    except Exception as e:
        logger.error(f"Failed to push daily report: {e}")
        await send_error_notification(
            "日报推送失败（v2.0）",
            f"版本: {data.get('version', 'unknown')}\n日期: {data.get('report_date', 'unknown')}\n错误: {e}",
        )
        return False
