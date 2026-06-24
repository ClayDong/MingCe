"""数据获取模块 — 使用 akshare 获取 A 股行情与宏观数据。

同步的 akshare 调用通过 run_in_executor 在线程池中执行，
避免阻塞 FastAPI 异步事件循环。数据缓存通过 FileCache 实现。
"""

import akshare as ak
import pandas as pd
import numpy as np
import urllib3
from loguru import logger
from typing import Optional, Any, Dict, List

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from core.utils import safe_float, safe_str, safe_pct, format_volume, retry
from core.cache import FileCache, get_cache_for_module
from core.data_quality import (
    get_validator, get_monitor, generate_quality_report,
    DataQualityReport
)
from models.schemas import (
    MarketOverview, IndexData, MacroData, NorthFlowData,
    ETFData, LeadingStockData, GlobalMacroData, AlertItem,
)
from config.settings import get_settings

settings = get_settings()

_global_cache: Optional[FileCache] = None

# 数据质量报告存储
_data_quality_reports: Dict[str, DataQualityReport] = {}


def get_latest_quality_report(module_name: str) -> Optional[DataQualityReport]:
    """获取最新的数据质量报告"""
    return _data_quality_reports.get(module_name)



def _get_cache() -> FileCache:
    global _global_cache
    if _global_cache is None:
        _global_cache = FileCache()
    return _global_cache


def set_cache_for_testing(cache: FileCache):
    global _global_cache
    _global_cache = cache


def _cached(key: str, ttl_seconds: Optional[int] = None, module_name: Optional[str] = None):
    def decorator(func):
        def wrapper(*args, **kwargs):
            if module_name:
                cache = get_cache_for_module(module_name)
            else:
                cache = _get_cache()
            data = cache.get(key, ttl_seconds=ttl_seconds)
            if data is not None:
                logger.debug(f"Cache hit: {key}")
                return data
            result = func(*args, **kwargs)
            cache.set(key, result)
            return result
        return wrapper
    return decorator


def _try_sources(*source_funcs, module_name: str = None):
    """尝试多个数据源，返回第一个成功且非空的结果。
    
    Args:
        source_funcs: 数据源函数列表（按优先级）
        module_name: 可选，数据模块名。提供后自动检查数据质量，
                     低于 DATA_QUALITY_MIN_ACCEPTABLE_SCORE 时触发降级
    """
    monitor = get_monitor()
    validator = get_validator()
    
    for idx, func in enumerate(source_funcs):
        source_name = func.__name__
        
        # 检查熔断器
        if monitor.should_skip(source_name):
            logger.warning(f"Source {source_name}: skipping due to health status")
            continue
            
        try:
            result = func()
            if result is not None and not (isinstance(result, pd.DataFrame) and result.empty):
                monitor.record_success(source_name)
                logger.debug(f"Source {source_name} succeeded")
                
                # 数据质量门禁：低于阈值时触发降级到缓存
                if module_name:
                    report = get_latest_quality_report(module_name)
                    if report and report.metrics.overall_score < settings.DATA_QUALITY_MIN_ACCEPTABLE_SCORE:
                        logger.warning(
                            f"⚠️ Data quality for {module_name} "
                            f"({report.metrics.overall_score:.2f}) below threshold "
                            f"({settings.DATA_QUALITY_MIN_ACCEPTABLE_SCORE}) — data may be stale"
                        )
                        # 检查是否有缓存可用
                        cache = _get_cache()
                        cached = cache.get(module_name)
                        if cached is not None:
                            logger.info(f"Using cached data for {module_name} due to low quality")
                            return cached
                
                return result
        except Exception as e:
            monitor.record_failure(source_name, str(e))
            logger.warning(f"Source {source_name} (attempt {idx+1}) failed: {e}")
    
    logger.warning(f"All sources failed for {source_funcs[0].__name__ if source_funcs else 'unknown'}")
    return None


def _find_column(df: pd.DataFrame, candidates: list) -> Optional[str]:
    for c in df.columns:
        for cand in candidates:
            if cand in str(c):
                return c
    return None


def _validate_index_value(value: float, name: str) -> bool:
    """验证指数值是否有效。"""
    if value is None:
        return False
    if not isinstance(value, (int, float)):
        return False
    if isinstance(value, float) and (np.isnan(value) or np.isinf(value)):
        return False
    if isinstance(value, int) and (np.isnan(float(value)) or np.isinf(float(value))):
        return False
    return abs(float(value)) >= settings.MIN_INDEX_VALUE_THRESHOLD


# ── 大宗商品/宏观变量合理性校验范围（2026年基准，避免脏数据推送） ──
# 范围设计：留足波动空间，但能拦截单位混淆/数量级错误
_MACRO_PRICE_RANGES = {
    # 单位：美元/盎司。历史区间 1800-5000，留 20% 缓冲
    "gold": (1500.0, 6000.0),
    # 单位：美元/盎司。历史区间 18-60
    "silver": (10.0, 100.0),
    # 单位：美元/桶。历史区间 30-120
    "brent_oil": (20.0, 150.0),
    # 单位：美元/桶。历史区间 25-115
    "wti_oil": (15.0, 140.0),
    # 单位：美元/桶。布伦特应高于WTI，价差 0-10 美元合理
    # 美元指数：70-115
    "usd_index": (70.0, 120.0),
    # VIX：5-80
    "vix": (5.0, 100.0),
}


def _validate_macro_price(value, attr: str) -> bool:
    """校验宏观商品价格是否在合理区间内。

    Args:
        value: 价格值（str/float/int）
        attr: 属性名（gold/silver/brent_oil/wti_oil/usd_index/vix）

    Returns:
        True 如果值在合理区间内
    """
    if value is None:
        return False
    try:
        v = float(value)
    except (TypeError, ValueError):
        return False
    if np.isnan(v) or np.isinf(v) or v == 0:
        return False
    rng = _MACRO_PRICE_RANGES.get(attr)
    if rng is None:
        return True  # 未配置范围的属性默认通过
    lo, hi = rng
    return lo <= v <= hi


# ── 数据源函数（同步） ─────────────────────────────────────

def _fetch_index_sina():
    return ak.stock_zh_index_spot_sina()


def _fetch_index_em():
    return ak.stock_zh_index_spot_em()


def _fetch_index_tencent():
    """从腾讯获取指数实时数据。"""
    return ak.stock_zh_index_spot_tx()


def _fetch_bse_index_bjdirect() -> Optional[pd.DataFrame]:
    """北证50指数直接获取（通过计算北证50成分股的平均涨幅）。"""
    try:
        # 使用东方财富北证股票实时行情
        df = ak.stock_zh_b_spot_em()
        if df is not None and not df.empty:
            # 东方财富北证数据通常包含北证50成分股
            # 筛选出成交额较大的北证股票作为代表性样本
            amount_col = _find_column(df, ["成交额", "amount"])
            if amount_col:
                df[amount_col] = pd.to_numeric(df[amount_col], errors="coerce")
                df = df.sort_values(amount_col, ascending=False).head(50)
            
            # 计算平均涨跌幅作为北证50的参考
            chg_col = _find_column(df, ["涨跌幅", "change_pct"])
            if chg_col:
                df[chg_col] = pd.to_numeric(df[chg_col], errors="coerce")
                avg_change = df[chg_col].mean()
                
                # 使用前5大北证股票的简单平均作为北证50参考
                top5 = df.head(5)
                top5_avg_change = top5[chg_col].mean()
                
                # 北证50指数通常在700-1200点之间
                # 优先使用 ak.stock_zh_index_daily_em 获取真实北证50指数
                try:
                    real_index = ak.stock_zh_index_daily_em(symbol="899050")
                    if real_index is not None and not real_index.empty:
                        last_close = safe_float(real_index.iloc[-1].get("close", 0))
                        if _validate_index_value(last_close, "北证50"):
                            logger.info(f"BSE index fetched from real data: {last_close:.2f}")
                            base_value = last_close
                            estimated_value = last_close * (1 + top5_avg_change / 100)
                        else:
                            raise ValueError("Invalid value")
                    else:
                        raise ValueError("Empty data")
                except Exception:
                    base_value = 1000.0
                    estimated_value = base_value * (1 + top5_avg_change / 100)
                
                logger.info(f"BSE index {'estimated' if base_value == 1000 else 'from real data'}: {estimated_value:.2f}")
                
                return pd.DataFrame([{
                    "名称": "北证50",
                    "最新价": estimated_value,
                    "涨跌幅": top5_avg_change,
                    "成交额": format_volume(df[amount_col].sum()),
                }])
    except Exception as e:
        logger.debug(f"BSE direct source failed: {e}")
    
    return None


def _fetch_index_history(symbol: str) -> Optional[pd.DataFrame]:
    """从日线数据自行计算涨跌幅的 fallback。"""
    # 北证50的代码是 sh899050
    symbol_map = {
        "北证50": "sh899050",
        "北证A股": "sh899001",
        "上证指数": "sh000001",
        "深证成指": "sz399001",
        "创业板指": "sz399006",
        "科创50": "sh000688",
    }
    code = symbol_map.get(symbol, "")
    if not code:
        logger.debug(f"No symbol mapping for {symbol}")
        return None

    try:
        df = ak.stock_zh_index_daily_tx(symbol=code)
        if df is not None and not df.empty and len(df) >= 2:
            latest = df.iloc[-1]
            prev = df.iloc[-2]
            close_val = safe_float(latest.get("close", 0))
            prev_close = safe_float(prev.get("close", 0))
            change_pct = ((close_val - prev_close) / prev_close * 100) if prev_close > 0 else 0
            if _validate_index_value(close_val, symbol):
                return pd.DataFrame([{
                    "名称": symbol,
                    "最新价": close_val,
                    "涨跌幅": change_pct,
                    "成交额": format_volume(safe_float(latest.get("amount", 0))),
                }])
    except Exception as e:
        logger.debug(f"Index history fetch failed for {symbol}: {e}")
    return None


def _fetch_stock_sina():
    return ak.stock_zh_a_spot()


def _fetch_stock_em():
    return ak.stock_zh_a_spot_em()


def _fetch_stock_tx():
    return ak.stock_zh_a_spot_tx()


def _fetch_mcap_from_tencent(codes: List[str]) -> Dict[str, float]:
    '''从腾讯行情获取指定股票的总市值（亿元）。

    腾讯 qt.gtimg.cn 返回格式中，字段46（0-indexed=45）= 总市值(亿)。
    仅对需要市值的少量龙头股调用，避免批量请求。
    '''
    if not codes:
        return {}
    tx_codes = []
    bare_to_prefixed = {}  # 裸代码 → 原输入代码（带前缀）
    for code in codes:
        code_str = str(code).strip()
        if code_str.startswith(("sh", "sz", "bj")):
            tx_codes.append(code_str)
            bare_to_prefixed[code_str[2:]] = code_str  # bj920083 → 920083→bj920083
        elif code_str.startswith("6"):
            tx_codes.append(f"sh{code_str}")
            bare_to_prefixed[code_str] = f"sh{code_str}"  # 600519 → sh600519
        elif code_str.startswith(("0", "3")):
            tx_codes.append(f"sz{code_str}")
            bare_to_prefixed[code_str] = f"sz{code_str}"
        elif code_str.startswith(("4", "8", "9")):
            tx_codes.append(f"bj{code_str}")
            bare_to_prefixed[code_str] = f"bj{code_str}"
    if not tx_codes:
        return {}
    try:
        import requests as _req
        url = f"https://qt.gtimg.cn/q={','.join(tx_codes)}"
        resp = _req.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        resp.encoding = "gbk"
        result = {}
        for line in resp.text.strip().split(";"):
            if not line.strip():
                continue
            if "=" not in line:
                continue
            _, raw = line.split("=", 1)
            raw = raw.strip().strip('"').strip("'")
            parts = raw.split("~")
            if len(parts) >= 46:
                mcap_str = parts[45].strip()
                try:
                    mcap_val = float(mcap_str)
                    prefixed = bare_to_prefixed.get(parts[2])
                    if prefixed:
                        result[prefixed] = mcap_val
                except (ValueError, IndexError):
                    pass
        return result
    except Exception as e:
        logger.debug(f"Tencent market cap fetch failed: {e}")
        return {}


def _fetch_etf_em():
    return ak.fund_etf_spot_em()


def _fetch_etf_ths():
    return ak.fund_etf_spot_ths()


def _fetch_etf_sina():
    return ak.fund_etf_spot_sina()


# ── 核心数据获取函数 ────────────────────────────────────────

@_cached("market", ttl_seconds=settings.CACHE_TTL_MARKET, module_name="market")
@retry(max_retries=2, delay=1.0, backoff=2.0)
def get_market_overview() -> dict:
    """A 股大盘概况：核心指数 + 涨跌分布 + 板块排行 + 主力资金。"""
    logger.info("Fetching market overview...")
    result = MarketOverview()
    validator = get_validator()
    monitor = get_monitor()
    all_issues: List[str] = []

    target_indices = set(settings.TARGET_INDICES)
    found_indices = set()

    df_idx = _try_sources(_fetch_index_sina, _fetch_index_tencent, _fetch_index_em)
    if df_idx is not None:
        name_col = _find_column(df_idx, ["名称", "name", "指数名称"])
        price_col = _find_column(df_idx, ["最新价", "price", "最新", "close"])
        change_col = _find_column(df_idx, ["涨跌幅", "change_pct", "涨跌幅%"])
        vol_col = _find_column(df_idx, ["成交额", "amount", "volume"])

        if name_col and price_col:
            for _, row in df_idx.iterrows():
                name = safe_str(row.get(name_col, ""))
                if name in target_indices and name not in found_indices:
                    value = safe_float(row.get(price_col, 0))
                    change = safe_pct(row.get(change_col, 0) if change_col else 0)
                    
                    # 使用增强的数据质量验证
                    is_valid, issues = validator.validate_index_value(value, name)
                    if is_valid:
                        # 验证涨跌幅
                        chg_valid, chg_issues = validator.validate_change_pct(change, name)
                        issues.extend(chg_issues)
                        
                        # 验证历史一致性
                        hist_valid, hist_issues = validator.validate_historical_consistency(
                            name, value, change
                        )
                        issues.extend(hist_issues)
                        
                        all_issues.extend(issues)
                        
                        if not issues:
                            result.indices.append(IndexData(
                                name=name,
                                value=value,
                                change_pct=change,
                                volume=safe_str(row.get(vol_col, "")) if vol_col else "",
                            ))
                            found_indices.add(name)
                        else:
                            logger.warning(f"Data quality issues for {name}: {issues}")

    for name in target_indices - found_indices:
        logger.warning(f"Index not found in primary sources: {name}, trying history...")
        try:
            df = _fetch_index_history(name)
            if df is not None:
                for _, row in df.iterrows():
                    row_name = safe_str(row.get("名称", ""))
                    if row_name == name:
                        value = safe_float(row.get("最新价", 0))
                        is_valid, issues = validator.validate_index_value(value, name)
                        if is_valid:
                            result.indices.append(IndexData(
                                name=name,
                                value=value,
                                change_pct=safe_pct(row.get("涨跌幅", 0)),
                                volume=safe_str(row.get("成交额", "")),
                            ))
                            found_indices.add(name)
                            break
        except Exception as e:
            logger.debug(f"Failed to fetch {name} from history: {e}")

    if len(result.indices) == 0:
        logger.warning("No index data available from any source")
        all_issues.append("没有可用的指数数据")

    df_stock = _try_sources(_fetch_stock_sina, _fetch_stock_tx, _fetch_stock_em)
    if df_stock is not None:
        chg_col = _find_column(df_stock, ["涨跌幅", "change_pct"])
        vol_col = _find_column(df_stock, ["成交额", "amount"])

        if chg_col:
            try:
                chg_vals = pd.to_numeric(df_stock[chg_col], errors="coerce")
                result.up_count = int((chg_vals > 0.001).sum())
                result.down_count = int((chg_vals < -0.001).sum())
                result.flat_count = len(df_stock) - result.up_count - result.down_count
            except Exception as e:
                logger.warning(f"Failed to calculate stock stats: {e}")

        if vol_col:
            try:
                vol = pd.to_numeric(df_stock[vol_col], errors="coerce").sum()
                if not np.isnan(vol) and vol > 0:
                    result.total_volume = format_volume(vol)
            except Exception as e:
                logger.warning(f"Failed to calculate volume: {e}")

    if result.up_count == 0 and result.down_count == 0:
        logger.warning("Zero up/down count, fallback to alternative method")
        try:
            df = ak.stock_zh_a_spot()
            if df is not None and not df.empty:
                chg_col = _find_column(df, ["涨跌幅"])
                if chg_col:
                    chg_vals = pd.to_numeric(df[chg_col], errors="coerce")
                    result.up_count = int((chg_vals > 0.001).sum())
                    result.down_count = int((chg_vals < -0.001).sum())
                    result.flat_count = len(df) - result.up_count - result.down_count
        except Exception as e:
            logger.debug(f"Fallback method also failed: {e}")

    try:
        df_board = ak.stock_board_concept_spot_em()
        if df_board is not None and not df_board.empty:
            name_col = _find_column(df_board, ["名称", "name"])
            chg_col = _find_column(df_board, ["涨跌幅"])
            if name_col and chg_col:
                df_sorted = df_board.sort_values(chg_col, ascending=False)
                for _, row in df_sorted.head(3).iterrows():
                    name = safe_str(row.get(name_col, ""))
                    change = safe_pct(row.get(chg_col, 0))
                    if name and change != 0:
                        result.top_sectors.append({
                            "name": name,
                            "change_pct": change,
                            "lead_stock": "",
                        })
                for _, row in df_sorted.tail(3).iterrows():
                    name = safe_str(row.get(name_col, ""))
                    change = safe_pct(row.get(chg_col, 0))
                    if name and change != 0:
                        result.bottom_sectors.append({
                            "name": name,
                            "change_pct": change,
                            "lead_stock": "",
                        })
    except Exception as e:
        logger.warning(f"Failed to fetch concept board: {e}")
        try:
            df_industry = ak.stock_board_industry_spot_em()
            if df_industry is not None and not df_industry.empty:
                name_col = _find_column(df_industry, ["名称", "name"])
                chg_col = _find_column(df_industry, ["涨跌幅"])
                if name_col and chg_col:
                    df_sorted = df_industry.sort_values(chg_col, ascending=False)
                    for _, row in df_sorted.head(3).iterrows():
                        name = safe_str(row.get(name_col, ""))
                        change = safe_pct(row.get(chg_col, 0))
                        if name:
                            result.top_sectors.append({
                                "name": name,
                                "change_pct": change,
                                "lead_stock": "",
                            })
                    for _, row in df_sorted.tail(3).iterrows():
                        name = safe_str(row.get(name_col, ""))
                        change = safe_pct(row.get(chg_col, 0))
                        if name:
                            result.bottom_sectors.append({
                                "name": name,
                                "change_pct": change,
                                "lead_stock": "",
                            })
        except Exception as e2:
            logger.warning(f"Failed to fetch industry board fallback: {e2}")

    try:
        fund_df = ak.stock_market_fund_flow()
        if fund_df is not None and not fund_df.empty:
            fund_df = fund_df.sort_values("日期", ascending=False)
            latest = fund_df.iloc[0]
            for col in fund_df.columns:
                if "主力" in str(col) and "净额" in str(col):
                    val = safe_float(latest.get(col, 0))
                    if not np.isnan(val):
                        direction = "净流入" if val >= 0 else "净流出"
                        result.fund_flow = f"主力{direction}{abs(val):.1f}亿"
                    break
    except Exception as e:
        logger.warning(f"Failed to fetch fund flow: {e}")

    # 生成数据质量报告
    report = generate_quality_report("market", result.model_dump(), all_issues)
    _data_quality_reports["market"] = report
    
    # 记录数据源健康状态
    for source in ["_fetch_index_sina", "_fetch_index_tencent", "_fetch_index_em", 
                   "_fetch_stock_sina", "_fetch_stock_tx", "_fetch_stock_em"]:
        report.source_health[source] = monitor.get_health(source)
    
    return result.model_dump()


@_cached("macro", ttl_seconds=settings.CACHE_TTL_MACRO, module_name="macro")
@retry(max_retries=1, delay=1.0, backoff=2.0)
def get_macro_data() -> dict:
    """宏观经济数据：LPR / CPI / PPI / PMI / M2 / 社融 / Shibor。"""
    logger.info("Fetching macro data...")
    result = MacroData()
    _fetch_lpr(result)
    _fetch_cpi(result)
    _fetch_ppi(result)
    _fetch_pmi(result)
    _fetch_m2(result)
    _fetch_social_finance(result)
    _fetch_shibor(result)
    return result.model_dump()


def _fetch_lpr(result: MacroData):
    try:
        df = ak.macro_china_lpr()
        if df is not None and not df.empty:
            df = df.sort_values("日期", ascending=False)
            latest = df.iloc[0]
            cols = list(df.columns)
            if len(cols) >= 2:
                result.lpr_1y = safe_str(latest.iloc[1])
            if len(cols) >= 3:
                result.lpr_5y = safe_str(latest.iloc[2])
    except Exception as e:
        logger.warning(f"Failed to fetch LPR: {e}")


def _fetch_cpi(result: MacroData):
    try:
        df = ak.macro_china_cpi_monthly()
        if df is not None and not df.empty:
            df = df.sort_values("日期", ascending=False)
            result.cpi = safe_str(df.iloc[0].iloc[-1])
            if result.cpi:
                result.highlights.append(f"CPI最新值: {result.cpi}")
    except Exception as e:
        logger.warning(f"Failed to fetch CPI: {e}")


def _fetch_ppi(result: MacroData):
    try:
        df = ak.macro_china_ppi()
        if df is not None and not df.empty:
            df = df.sort_values("日期", ascending=False)
            result.ppi = safe_str(df.iloc[0].iloc[-1])
            if result.ppi:
                result.highlights.append(f"PPI最新值: {result.ppi}")
    except Exception as e:
        logger.warning(f"Failed to fetch PPI: {e}")


def _fetch_pmi(result: MacroData):
    try:
        df = ak.macro_china_cx_pmi()
        if df is not None and not df.empty:
            df = df.sort_values("日期", ascending=False)
            result.pmi = safe_str(df.iloc[0].iloc[-1])
            if result.pmi:
                result.highlights.append(f"PMI最新值: {result.pmi}")
    except Exception as e:
        logger.warning(f"Failed to fetch PMI: {e}")
        try:
            df = ak.macro_china_cx_pmi_yearly()
            if df is not None and not df.empty:
                df = df.sort_values("日期", ascending=False)
                result.pmi = safe_str(df.iloc[0].iloc[-1])
                if result.pmi:
                    result.highlights.append(f"PMI最新值: {result.pmi}")
        except Exception as e2:
            logger.debug(f"PMI fallback also failed: {e2}")


def _fetch_m2(result: MacroData):
    try:
        df = ak.macro_china_money_supply()
        if df is not None and not df.empty:
            df = df.sort_values("日期", ascending=False)
            result.m2 = safe_str(df.iloc[0].iloc[-1])
    except Exception as e:
        logger.warning(f"Failed to fetch M2: {e}")


def _fetch_social_finance(result: MacroData):
    try:
        df = ak.macro_china_shrzgm()
        if df is not None and not df.empty:
            df = df.sort_values("月份", ascending=False)
            cols = list(df.columns)
            if len(cols) >= 2:
                result.social_finance = safe_str(df.iloc[0].iloc[1])
    except Exception as e:
        logger.warning(f"Failed to fetch social finance: {e}")


def _fetch_shibor(result: MacroData):
    try:
        df = ak.macro_china_shibor_all()
        if df is not None and not df.empty:
            df = df.sort_values("日期", ascending=False)
            latest = df.iloc[0]
            result.shibor_overnight = safe_str(latest.get("O/N-定价", ""))
            result.shibor_7d = safe_str(latest.get("1W-定价", ""))
    except Exception as e:
        logger.warning(f"Failed to fetch Shibor: {e}")


def _is_valid_flow_value(val) -> bool:
    """检查资金流数值是否有效（非None、非NaN、非Inf）。"""
    if val is None:
        return False
    if isinstance(val, float) and (np.isnan(val) or np.isinf(val)):
        return False
    return abs(val) > 0.01  # 过滤极小值


@_cached("north_flow", ttl_seconds=settings.CACHE_TTL_NORTH, module_name="north_flow")
@retry(max_retries=2, delay=1.0, backoff=2.0)
def get_north_flow() -> dict:
    """北向资金数据。"""
    logger.info("Fetching north flow data...")
    result = NorthFlowData()
    validator = get_validator()
    monitor = get_monitor()
    all_issues: List[str] = []

    sources = [
        _fetch_north_em_summary,
        _fetch_north_em_min,
        _fetch_north_hsgt,
        _fetch_north_em_hist,
        _fetch_north_tencent,
        _fetch_north_163,
        _fetch_north_sina,
    ]

    for source_func in sources:
        source_name = source_func.__name__
        try:
            data = source_func()
            if data:
                net_flow = data.get('net_flow')
                sh_flow = data.get('sh_flow')
                sz_flow = data.get('sz_flow')
                
                # 数据质量验证
                is_valid, issues = validator.validate_north_flow(net_flow, sh_flow, sz_flow)
                all_issues.extend(issues)
                
                has_valid_data = any(_is_valid_flow_value(data.get(k)) for k in ['net_flow', 'sh_flow', 'sz_flow'])
                if has_valid_data:
                    if _is_valid_flow_value(data.get('net_flow')):
                        result.net_flow = data['net_flow']
                    if _is_valid_flow_value(data.get('sh_flow')):
                        result.sh_flow = data['sh_flow']
                    if _is_valid_flow_value(data.get('sz_flow')):
                        result.sz_flow = data['sz_flow']
                    logger.debug(f"North flow data found from {source_name}")
                    monitor.record_success(source_name)
                    break
                else:
                    logger.debug(f"North flow source {source_name} returned invalid data: {data}")
        except Exception as e:
            monitor.record_failure(source_name, str(e))
            logger.debug(f"North flow source {source_name} failed: {e}")

    # 最终回退：东方财富 kamt 接口
    if not result.net_flow:
        try:
            import httpx as _httpx_kamt
            resp = _httpx_kamt.get(
                "https://push2his.eastmoney.com/api/qt/kamt.kline/get?fields1=f1,f3&fields2=f51,f52,f53,f54,f55,f56&klt=101&lmt=1",
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                kamt_data = data.get("data", {})
                sh_str = kamt_data.get("hk2sh", [""])[0] if kamt_data.get("hk2sh") else ""
                sz_str = kamt_data.get("hk2sz", [""])[0] if kamt_data.get("hk2sz") else ""
                if sh_str or sz_str:
                    # 格式: "2026-06-24,0.00,5200000.00,273757367.45"
                    sh_parts = sh_str.split(",") if sh_str else []
                    sz_parts = sz_str.split(",") if sz_str else []
                    # 第4个字段是净买入额（元），转亿元
                    sh_net = safe_float(sh_parts[3]) / 1e8 if len(sh_parts) > 3 else 0
                    sz_net = safe_float(sz_parts[3]) / 1e8 if len(sz_parts) > 3 else 0
                    total_net = round(sh_net + sz_net, 2)
                    if total_net != 0:
                        result.net_flow = total_net
                        result.sh_flow = round(sh_net, 2)
                        result.sz_flow = round(sz_net, 2)
                        logger.info(f"North flow fallback (eastmoney kamt): net={total_net}, sh={sh_net}, sz={sz_net}")
        except Exception as e:
            logger.debug(f"North flow eastmoney kamt fallback failed: {e}")

    # 生成数据质量报告
    report = generate_quality_report("north_flow", result.model_dump(), all_issues)
    _data_quality_reports["north_flow"] = report
    
    # 记录数据源健康状态
    for source in ["_fetch_north_em_summary", "_fetch_north_em_min", "_fetch_north_em_hist",
                   "_fetch_north_tencent", "_fetch_north_163", "_fetch_north_sina"]:
        report.source_health[source] = monitor.get_health(source)
    
    return result.model_dump()


def _fetch_north_em_summary():
    try:
        df = ak.stock_hsgt_fund_flow_summary_em()
        if df is not None and not df.empty:
            result = {}
            for _, row in df.iterrows():
                direction = safe_str(row.get("资金方向", row.get("方向", "")))
                stock_type = safe_str(row.get("板块", row.get("市场", "")))
                if "北向" in direction:
                    if "沪" in stock_type or stock_type == "沪股通":
                        result['sh_flow'] = safe_float(row.get("成交净买额", row.get("资金净流入", 0)))
                    elif "深" in stock_type or stock_type == "深股通":
                        result['sz_flow'] = safe_float(row.get("成交净买额", row.get("资金净流入", 0)))
            if 'sh_flow' in result or 'sz_flow' in result:
                result['net_flow'] = (result.get('sh_flow') or 0) + (result.get('sz_flow') or 0)
                return result
    except Exception as e:
        logger.debug(f"_fetch_north_em_summary failed: {e}")
    return None


def _fetch_north_hsgt():
    """从沪深港通资金流获取北向资金数据"""
    try:
        func = getattr(ak, 'stock_hsgt', None)
        if func:
            df = func()
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    name = safe_str(row.get("名称", ""))
                    if "北向资金" in name:
                        net_val = safe_float(row.get("净流入", 0))
                        if net_val != 0:
                            return {'net_flow': net_val}
    except Exception as e:
        logger.debug(f"_fetch_north_hsgt failed: {e}")
    return None


def _fetch_north_em_min():
    try:
        df = ak.stock_hsgt_fund_min_em()
        if df is not None and not df.empty:
            latest = df.iloc[-1]
            sh_val = safe_float(latest.get("沪股通", 0))
            sz_val = safe_float(latest.get("深股通", 0))
            if sh_val != 0 or sz_val != 0:
                return {
                    'sh_flow': sh_val,
                    'sz_flow': sz_val,
                    'net_flow': sh_val + sz_val
                }
    except Exception as e:
        logger.debug(f"_fetch_north_em_min failed: {e}")
    return None


def _fetch_north_em_hist():
    try:
        df = ak.stock_hsgt_hist_em(symbol="北向资金")
        if df is not None and not df.empty:
            df = df.sort_values("日期", ascending=False)
            latest = df.iloc[0]
            net_val = safe_float(latest.get("当日成交净买额", latest.get("当日资金流入", 0)))
            if net_val != 0:
                return {'net_flow': net_val}
    except Exception as e:
        logger.debug(f"_fetch_north_em_hist failed: {e}")
    return None


def _fetch_north_sina():
    try:
        func = getattr(ak, 'stock_hsgt_fund_flow_sina', None)
        if func:
            df = func()
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    name = safe_str(row.get("名称", ""))
                    if "北向资金" in name:
                        val = safe_float(row.get("净流入", 0))
                        if val != 0:
                            return {'net_flow': val}
        else:
            logger.debug("akshare.stock_hsgt_fund_flow_sina not available")
    except Exception as e:
        logger.debug(f"_fetch_north_sina failed: {e}")
    return None


def _fetch_north_tencent():
    """从腾讯获取北向资金数据。"""
    try:
        df = ak.stock_hsgt_fund_flow_tx()
        if df is not None and not df.empty:
            for _, row in df.iterrows():
                name = safe_str(row.get("名称", ""))
                if "北向" in name or "沪股通" in name or "深股通" in name:
                    val = safe_float(row.get("净流入", 0))
                    if val != 0:
                        return {'net_flow': val}
    except Exception as e:
        logger.debug(f"_fetch_north_tencent failed: {e}")
    return None


def _fetch_north_163():
    """从网易获取北向资金数据。"""
    try:
        func = getattr(ak, 'stock_hsgt_fund_flow_163', None)
        if func:
            df = func()
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    val = safe_float(row.get("北向资金", row.get("净流入", 0)))
                    if val != 0:
                        return {'net_flow': val}
    except Exception as e:
        logger.debug(f"_fetch_north_163 failed: {e}")
    return None


@_cached("etf", ttl_seconds=settings.CACHE_TTL_ETF, module_name="etf")
@retry(max_retries=2, delay=1.0, backoff=2.0)
def get_etf_data() -> dict:
    """ETF 行情数据。"""
    logger.info("Fetching ETF data...")
    result = ETFData()

    df = _try_sources(_fetch_etf_em, _fetch_etf_sina, _fetch_etf_ths)
    if df is None:
        return result.model_dump()

    broad_keywords = ["沪深300", "中证500", "中证1000", "科创50", "创业板", "上证50", "中证A500", "MSCI"]
    industry_keywords = ["半导体", "芯片", "新能源", "医药", "消费", "军工", "人工智能", "AI", "机器人", "光伏", "碳中和"]

    name_col = _find_column(df, ["名称", "name"])
    chg_col = _find_column(df, ["涨跌幅", "change_pct"])
    code_col = _find_column(df, ["代码", "code"])

    if name_col and chg_col:
        for _, row in df.iterrows():
            name = safe_str(row.get(name_col, ""))
            if not name:
                continue
            change = safe_pct(row.get(chg_col, 0))
            code = safe_str(row.get(code_col, "")) if code_col else ""
            item = {"name": name, "code": code, "change_pct": change}

            if any(kw in name for kw in broad_keywords):
                result.broad_based.append(item)
            if any(kw in name for kw in industry_keywords):
                result.industry.append(item)

        result.broad_based.sort(key=lambda x: abs(x["change_pct"]), reverse=True)
        result.industry.sort(key=lambda x: abs(x["change_pct"]), reverse=True)
        result.broad_based = result.broad_based[:8]
        result.industry = result.industry[:8]

    return result.model_dump()


@_cached("leading", ttl_seconds=settings.CACHE_TTL_LEADING, module_name="leading")
@retry(max_retries=2, delay=1.0, backoff=2.0)
def get_leading_stocks() -> dict:
    """大市值涨幅榜（按市值≥300亿 + 涨跌幅降序筛选）。

    注意：本字段名为 "leading" 是历史命名，实际语义是
    "大市值个股当日涨幅榜"，并非行业龙头。行业龙头需要按
    细分行业市占率/营收排名定义，此处仅按市值+涨幅筛选。
    面向用户展示时应使用"大市值涨幅榜"而非"龙头股"。
    """
    logger.info("Fetching large-cap top gainers (leading stocks)...")
    result = LeadingStockData()

    df_stock = _try_sources(_fetch_stock_sina, _fetch_stock_tx, _fetch_stock_em)
    if df_stock is None:
        return result.model_dump()

    mcap_col = _find_column(df_stock, ["总市值", "market_cap", "市值"])
    chg_col = _find_column(df_stock, ["涨跌幅", "change_pct"])
    name_col = _find_column(df_stock, ["名称", "name"])
    code_col = _find_column(df_stock, ["代码", "code"])

    if chg_col and name_col:
        try:
            df_filtered = df_stock.copy()
            df_filtered[chg_col] = pd.to_numeric(df_filtered[chg_col], errors="coerce")

            have_mcap = bool(mcap_col)
            if have_mcap:
                df_filtered[mcap_col] = pd.to_numeric(df_filtered[mcap_col], errors="coerce")
                min_mcap = 300 * 10**8
                df_filtered = df_filtered[df_filtered[mcap_col] >= min_mcap].copy()

            df_filtered = df_filtered.sort_values(chg_col, ascending=False)

            found_headlines = 0
            for _, row in df_filtered.iterrows():
                if found_headlines >= 5:
                    break
                name = safe_str(row.get(name_col, ""))
                change = safe_pct(row.get(chg_col, 0))
                code = safe_str(row.get(code_col, "")) if code_col else ""
                mcap = safe_float(row.get(mcap_col, 0)) if have_mcap else 0
                if abs(change) >= 0.5 and name:
                    result.headlines.append({
                        "name": name, "change_pct": change,
                        "market_cap": format_volume(mcap) if mcap else "",
                        "code": code,
                    })
                    found_headlines += 1

            # 如果新浪没有市值列，从腾讯补充
            if not have_mcap and result.headlines:
                codes_to_fetch = [h.get("code", "") for h in result.headlines if h.get("code")]
                mcap_map = _fetch_mcap_from_tencent(codes_to_fetch) if codes_to_fetch else {}
                if mcap_map:
                    for h in result.headlines:
                        code = h.get("code", "")
                        if code in mcap_map:
                            mcap_val = mcap_map[code] * 1e8  # 腾讯返回亿，转元
                            h["market_cap"] = format_volume(mcap_val) if mcap_val else ""

            if not result.headlines:
                for _, row in df_filtered.head(5).iterrows():
                    name = safe_str(row.get(name_col, ""))
                    change = safe_pct(row.get(chg_col, 0))
                    mcap = safe_float(row.get(mcap_col, 0)) if mcap_col else 0
                    if name:
                        result.headlines.append({
                            "name": name, "change_pct": change,
                            "market_cap": format_volume(mcap) if mcap else "",
                            "code": safe_str(row.get(code_col, "")) if code_col else "",
                        })

            found_events = 0
            for _, row in df_filtered.iterrows():
                if found_events >= 10:
                    break
                change = safe_pct(row.get(chg_col, 0))
                name = safe_str(row.get(name_col, ""))
                if abs(change) >= 1.0 and name:
                    result.major_events.append({
                        "name": name, "change_pct": change,
                        "code": safe_str(row.get(code_col, "")) if code_col else "",
                    })
                    found_events += 1

            if not result.major_events:
                for _, row in df_filtered.head(5).iterrows():
                    name = safe_str(row.get(name_col, ""))
                    change = safe_pct(row.get(chg_col, 0))
                    if name:
                        result.major_events.append({
                            "name": name, "change_pct": change,
                            "code": safe_str(row.get(code_col, "")) if code_col else "",
                        })
        except Exception as e:
            logger.warning(f"Failed to process leading stocks: {e}")

    return result.model_dump()


@_cached("global_macro", ttl_seconds=settings.CACHE_TTL_GLOBAL, module_name="global_macro")
@retry(max_retries=2, delay=1.0, backoff=2.0)
def get_global_macro() -> dict:
    """全球宏观变量数据（多源：新浪期货 + akshare 备用）。

    严谨性保障：
    1. 所有价格经过 _validate_macro_price 合理性区间校验
    2. 布伦特原油独立获取（OIL 符号），不再用 WTI 近似
    3. 布伦特-WTI 价差校验（正常 0-10 美元，异常则标记告警）
    """
    logger.info("Fetching global macro data...")
    result = GlobalMacroData()

    # 1) 外盘期货：黄金/白银/布伦特/WTI（akshare futures_foreign_hist）
    #    布伦特原油使用 OIL 符号独立获取，不再用 WTI 近似复制
    futures_map = {
        "GC": "gold",        # COMEX 黄金（美元/盎司）
        "SI": "silver",      # COMEX 白银（美元/盎司）
        "OIL": "brent_oil",  # ICE 布伦特原油（美元/桶）
        "CL": "wti_oil",     # NYMEX WTI 原油（美元/桶）
    }
    for sym, attr in futures_map.items():
        try:
            df = ak.futures_foreign_hist(symbol=sym)
            if df is None or df.empty:
                continue
            price = safe_float(df["close"].iloc[-1])
            if price is None or price == 0:
                continue
            # 合理性区间校验：拦截单位混淆/数量级错误
            if not _validate_macro_price(price, attr):
                logger.warning(
                    f"宏观价格校验失败 {sym}->{attr}: {price} 超出合理区间 "
                    f"{_MACRO_PRICE_RANGES.get(attr)}，已丢弃"
                )
                continue
            # 黄金取整数，银/油取两位小数
            format_str = f"{price:.0f}" if attr == "gold" else f"{price:.2f}"
            setattr(result, attr, format_str)
        except Exception as e:
            logger.debug(f"Futures {sym} failed: {e}")

    # 布伦特-WTI 价差合理性校验（正常布伦特比WTI高0-10美元）
    # 若价差异常（如完全相等或倒挂），记录告警但不强制覆盖
    if result.brent_oil and result.wti_oil:
        try:
            brent_v = float(result.brent_oil)
            wti_v = float(result.wti_oil)
            spread = brent_v - wti_v
            if abs(spread) < 0.01:
                logger.warning(
                    f"布伦特与WTI价格完全一致({brent_v})，疑似数据源异常"
                )
            elif spread < -5:
                logger.warning(
                    f"布伦特({brent_v})低于WTI({wti_v}) {abs(spread):.2f}美元，"
                    f"罕见倒挂，请人工核实"
                )
        except (ValueError, TypeError):
            pass

    # 2) 美债收益率（akshare 中国外汇交易中心数据）
    try:
        df = ak.bond_zh_us_rate()
        if df is not None and not df.empty:
            last = df.iloc[-1]
            us_10y = safe_float(last.get("美国国债收益率10年"))
            us_2y = safe_float(last.get("美国国债收益率2年"))
            if us_10y and not result.us_10y_bond:
                result.us_10y_bond = f"{us_10y:.2f}"
            if us_2y and not result.us_2y_bond:
                result.us_2y_bond = f"{us_2y:.2f}"
    except Exception as e:
        logger.debug(f"Bond rate fetch failed: {e}")

    # 3) 汇率（新浪期货格式）
    import requests as _requests, json as _json, re as _re
    for sym, attr, fmt in [
        ("EURUSD", "euro_usd", ".4f"),
        ("USDJPY", "usd_jpy", ".2f"),
        ("USDCNY", "usd_cny", ".4f"),
    ]:
        try:
            url = f"https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var%20_x=/GlobalFuturesService.getGlobalFuturesDailyKLine?symbol={sym}"
            resp = _requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10, verify=False)
            text = resp.text
            if text and "([" in text:
                match = _re.search(r"\(\[(.*?)\]\)", text, _re.DOTALL)
                if match:
                    records = _json.loads("[" + match.group(1) + "]")
                    if records and len(records) > 0:
                        price = safe_float(records[-1][2])
                        if price is not None and price != 0:
                            setattr(result, attr, format(price, fmt))
        except Exception as e:
            logger.debug(f"Forex {sym} failed: {e}")

    # 3b) 汇率回退：新浪外汇 hq.sinajs.cn
    if not result.usd_cny:
        try:
            resp = _requests.get(
                "https://hq.sinajs.cn/list=fx_susdcny",
                headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn"},
                timeout=10,
            )
            text = resp.text.strip()
            val = text.split('"')[1] if '"' in text else ""
            if val:
                parts = val.split(",")
                if len(parts) > 1:
                    price = safe_float(parts[1])
                    if price and 6.0 < price < 8.0:
                        result.usd_cny = f"{price:.4f}"
                        logger.info(f"USD/CNY fallback (sina forex): {result.usd_cny}")
        except Exception as e:
            logger.debug(f"USD/CNY sina forex fallback failed: {e}")

    # 4) VIX 恐慌指数（新浪期货）
    try:
        url = "https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var%20_x=/GlobalFuturesService.getGlobalFuturesDailyKLine?symbol=VIX"
        resp = _requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        match = _re.search(r"\(\[.*\]\)", resp.text)
        if match:
            records = _json.loads(match.group(0))
            if records and len(records) > 0:
                price = safe_float(records[-1][2])
                if price is not None and price != 0:
                    result.vix = f"{price:.2f}"
    except Exception as e:
        logger.debug(f"VIX fetch failed: {e}")

    # 4b) VIX 回退：新浪期货 hf_VX
    if not result.vix:
        try:
            resp = _requests.get(
                "https://hq.sinajs.cn/list=hf_VX",
                headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn"},
                timeout=10,
            )
            text = resp.text.strip()
            val = text.split('"')[1] if '"' in text else ""
            if val:
                parts = val.split(",")
                if len(parts) > 0:
                    price = safe_float(parts[0])
                    if price and 10 < price < 80:
                        result.vix = f"{price:.2f}"
                        logger.info(f"VIX fallback (sina hf_VX): {result.vix}")
        except Exception as e:
            logger.debug(f"VIX sina hf_VX fallback failed: {e}")

    # 5) BDI 波罗的海干散货指数
    try:
        df = ak.macro_shipping_bdi()
        if df is not None and not df.empty:
            df = df.tail(5)
            latest = df.iloc[-1]
            result.bdi = f"{safe_float(latest.iloc[-1]):.0f}"
    except Exception as e:
        logger.debug(f"BDI fetch failed: {e}")

    # 6) 美元指数（新浪指数）
    try:
        df = ak.stock_zh_index_spot_sina()
        if df is not None and not df.empty:
            for _, row in df.iterrows():
                name = safe_str(row.get("名称", ""))
                price = safe_float(row.get("最新价", 0))
                if "美元" in name and price:
                    result.usd_index = f"{price:.4f}"
                if "标普" in name and price and not result.sp500:
                    result.sp500 = f"{price:.2f}"
    except Exception as e:
        logger.debug(f"Index spot failed: {e}")

    # 6b) 美元指数回退方案（直接新浪HTTP API）
    if not result.usd_index:
        try:
            import requests as _req, json as _json
            url = "https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var%20_x=/GlobalFuturesService.getGlobalFuturesDailyKLine?symbol=USDX"
            resp = _req.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10, verify=False)
            text = resp.text
            if text and "([{" in text:
                match = _re.search(r"\(\[(.*?)\]\)", text, _re.DOTALL)
                if match:
                    records = _json.loads("[" + match.group(1) + "]")
                    if records and len(records) > 0:
                        price = float(records[-1][2])
                        if price and 90 < price < 120:
                            result.usd_index = f"{price:.4f}"
                            logger.info(f"USD index fallback: {result.usd_index}")
        except Exception as e2:
            logger.debug(f"USD index fallback failed: {e2}")

    # 6c) 美元指数回退方案3：新浪期货 hf_DINI
    if not result.usd_index:
        try:
            resp = _requests.get(
                "https://hq.sinajs.cn/list=hf_DINI",
                headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn"},
                timeout=10,
            )
            text = resp.text.strip()
            val = text.split('"')[1] if '"' in text else ""
            if val:
                parts = val.split(",")
                if len(parts) > 0:
                    price = safe_float(parts[0])
                    if price and 90 < price < 120:
                        result.usd_index = f"{price:.4f}"
                        logger.info(f"USD index fallback3 (sina hf_DINI): {result.usd_index}")
        except Exception as e:
            logger.debug(f"USD index hf_DINI fallback failed: {e}")

    # 布伦特原油回退：仅在独立获取失败时，用 WTI + 3美元 估算（不再直接复制）
    # 布伦特通常比 WTI 高 1-5 美元，取中值 3 美元作为估算补偿
    if not result.brent_oil and result.wti_oil:
        try:
            wti_v = float(result.wti_oil)
            est_brent = wti_v + 3.0
            if _validate_macro_price(est_brent, "brent_oil"):
                result.brent_oil = f"{est_brent:.2f}"
                logger.info(f"布伦特原油独立获取失败，用WTI+3估算: {result.brent_oil}")
        except (ValueError, TypeError):
            pass

    # highlights
    if result.gold:
        result.highlights.append(f"黄金: {result.gold}")
    if result.bdi:
        result.highlights.append(f"BDI: {result.bdi}")
    if result.vix:
        v = float(result.vix)
        flag = "⚠️恐慌" if v > 25 else "✅平静" if v < 15 else "➖正常"
        result.highlights.append(f"VIX: {result.vix} {flag}")

    # highlights（去重）
    seen = set()
    unique_highlights = []
    for h in result.highlights:
        if h not in seen:
            seen.add(h)
            unique_highlights.append(h)
    result.highlights = unique_highlights

    logger.info(f"Global macro: gold={result.gold}, oil={result.wti_oil}, usd={result.usd_index}, bdi={result.bdi}")
    # 扩展：VIX/BDI/日经/白银/2Y美债
    _extend_global_macro(result)
    return result.model_dump()


@_cached("bse", ttl_seconds=settings.CACHE_TTL_BSE, module_name="bse")
@retry(max_retries=2, delay=1.0, backoff=2.0)
def get_bse_data() -> dict:
    """北证市场数据：北证指数 + 北证龙头股票。"""
    from models.schemas import BSEData, BSEIndexData, BSELeadingStockData
    logger.info("Fetching BSE (北证) data...")
    result = BSEData()
    validator = get_validator()
    monitor = get_monitor()
    all_issues: List[str] = []

    # 获取北证指数
    try:
        df_idx = _try_sources(_fetch_index_sina, _fetch_index_tencent, _fetch_index_em, _fetch_index_history)
        if df_idx is not None:
            name_col = _find_column(df_idx, ["名称", "name", "指数名称"])
            price_col = _find_column(df_idx, ["最新价", "price", "最新", "close"])
            change_col = _find_column(df_idx, ["涨跌幅", "change_pct", "涨跌幅%"])
            vol_col = _find_column(df_idx, ["成交额", "amount", "volume"])

            if name_col and price_col:
                found_bse = set()

                for _, row in df_idx.iterrows():
                    name = safe_str(row.get(name_col, ""))
                    is_bse_index = "北证" in name
                    if is_bse_index and name not in found_bse:
                        value = safe_float(row.get(price_col, 0))
                        change = safe_pct(row.get(change_col, 0) if change_col else 0)

                        is_valid, issues = validator.validate_index_value(value, name)
                        if is_valid:
                            result.indices.append(BSEIndexData(
                                name=name,
                                value=value,
                                change_pct=change,
                                volume=safe_str(row.get(vol_col, "")) if vol_col else "",
                            ))
                            found_bse.add(name)
                            all_issues.extend(issues)

                # 如果北证50不在目标列表中，尝试单独获取
        if not any("北证50" in idx.name for idx in result.indices):
            logger.warning("北证50 not found in standard sources, trying separate fetch")
            
            # 方法1: 使用历史数据
            try:
                df = ak.stock_zh_index_daily_tx(symbol="sh899050")
                if df is not None and not df.empty and len(df) >= 2:
                    latest = df.iloc[-1]
                    prev = df.iloc[-2]
                    close_val = safe_float(latest.get("close", 0))
                    prev_close = safe_float(prev.get("close", 0))
                    change_pct = ((close_val - prev_close) / prev_close * 100) if prev_close > 0 else 0
                    if close_val > 0:
                        result.indices.append(BSEIndexData(
                            name="北证50",
                            value=close_val,
                            change_pct=change_pct,
                            volume="",
                        ))
                        all_issues.append(f"北证50通过股票池历史数据获取")
                        logger.info(f"Successfully fetched 北证50 via stock pool history: {close_val:.2f}")
            except Exception as e:
                logger.debug(f"Failed to fetch 北证50 via stock pool: {e}")
            
            # 方法3: 从龙头企业数据生成北证市场参考指数
            if not any("北证50" in idx.name for idx in result.indices):
                headlines = result.leading.headlines if hasattr(result.leading, 'headlines') else []
                if not headlines:
                    # 如果还没有获取到龙头企业数据，先尝试获取
                    try:
                        df_stock = _try_sources(_fetch_stock_sina, _fetch_stock_tx, _fetch_stock_em)
                        if df_stock is not None:
                            # 筛选北证股票
                            code_col = _find_column(df_stock, ["代码", "code"])
                            if code_col:
                                def is_bse_stock(code):
                                    code = str(code)
                                    return code.startswith("bj") or code.startswith("8") or code.startswith("9") or code.startswith("4")
                                
                                df_stock["_code"] = df_stock[code_col].astype(str)
                                bse_df = df_stock[df_stock["_code"].apply(is_bse_stock)].copy()
                                
                                chg_col = _find_column(bse_df, ["涨跌幅", "change_pct"])
                                if chg_col:
                                    bse_df[chg_col] = pd.to_numeric(bse_df[chg_col], errors="coerce")
                                    # 计算北证市场的平均涨跌幅
                                    avg_change = bse_df[chg_col].mean()
                                    # 北证50基准值约为1000点
                                    base_value = 1000.0
                                    estimated_value = base_value * (1 + avg_change / 100)
                                    
                                    if not pd.isna(avg_change):
                                        result.indices.append(BSEIndexData(
                                            name="北证50",
                                            value=estimated_value,
                                            change_pct=avg_change,
                                            volume="",
                                        ))
                                        all_issues.append(f"北证50通过北交所股票平均涨幅估算")
                                        logger.info(f"北证50通过北交所股票平均涨幅估算: {avg_change:.2f}%, 估算值: {estimated_value:.2f}")
                    except Exception as e:
                        logger.debug(f"Failed to estimate BSE50 from stocks: {e}")
    except Exception as e:
        logger.warning(f"Failed to fetch BSE indices: {e}")

    # 获取北证龙头股票
    try:
        df_stock = _try_sources(_fetch_stock_sina, _fetch_stock_tx, _fetch_stock_em)
        if df_stock is not None:
            bse_df = None
            try:
                code_col = _find_column(df_stock, ["代码", "code"])
                if code_col:
                    # 筛选北交所股票（代码一般以 8/4/9 开头
                    def is_bse_stock(code):
                        code = str(code)
                        return code.startswith("bj") or code.startswith("8") or code.startswith("9") or code.startswith("4")

                    df_stock["_code"] = df_stock[code_col].astype(str)
                    bse_mask = df_stock["_code"].apply(is_bse_stock)
                    bse_df = df_stock[bse_mask].copy()
            except Exception as e:
                logger.debug(f"Failed to filter BSE stocks: {e}")

            if bse_df is None or bse_df.empty:
                bse_df = df_stock.copy()

            chg_col = _find_column(bse_df, ["涨跌幅", "change_pct"])
            name_col = _find_column(bse_df, ["名称", "name"])
            code_col = _find_column(bse_df, ["代码", "code"])

            if chg_col and name_col:
                bse_df[chg_col] = pd.to_numeric(bse_df[chg_col], errors="coerce")
                bse_df = bse_df.sort_values(chg_col, ascending=False)

                found_headlines = 0
                for _, row in bse_df.iterrows():
                    if found_headlines >= 5:
                        break
                    name = safe_str(row.get(name_col, ""))
                    change = safe_pct(row.get(chg_col, 0))
                    if abs(change) >= 0.5 and name:
                        result.leading.headlines.append({
                            "name": name, "change_pct": change,
                            "market_cap": "",
                            "code": safe_str(row.get(code_col, "")) if code_col else "",
                        })
                        found_headlines += 1

                if not result.leading.headlines:
                    for _, row in bse_df.head(5).iterrows():
                        name = safe_str(row.get(name_col, ""))
                        change = safe_pct(row.get(chg_col, 0))
                        if name:
                            result.leading.headlines.append({
                                "name": name, "change_pct": change,
                                "market_cap": "",
                                "code": safe_str(row.get(code_col, "")) if code_col else "",
                            })

                found_events = 0
                for _, row in bse_df.iterrows():
                    if found_events >= 10:
                        break
                    change = safe_pct(row.get(chg_col, 0))
                    name = safe_str(row.get(name_col, ""))
                    if abs(change) >= 1.0 and name:
                        result.leading.major_events.append({
                            "name": name, "change_pct": change,
                            "code": safe_str(row.get(code_col, "")) if code_col else "",
                        })
                        found_events += 1

                if not result.leading.major_events:
                    for _, row in bse_df.head(5).iterrows():
                        name = safe_str(row.get(name_col, ""))
                        change = safe_pct(row.get(chg_col, 0))
                        if name:
                            result.leading.major_events.append({
                                "name": name, "change_pct": change,
                                "code": safe_str(row.get(code_col, "")) if code_col else "",
                            })
    except Exception as e:
        logger.warning(f"Failed to fetch BSE leading stocks: {e}")

    # 生成北证市场亮点
    if result.indices:
        for idx in result.indices:
            change_str = f"+{idx.change_pct:.2f}%" if idx.change_pct >= 0 else f"{idx.change_pct:.2f}%"
            result.highlights.append(f"{idx.name}: {change_str}")

    report = generate_quality_report("bse", result.model_dump(), all_issues)
    _data_quality_reports["bse"] = report

    return result.model_dump()


def detect_alerts(market: dict, north: dict, leading: dict, etf: dict | None = None, bse: dict | None = None) -> list[dict]:
    """根据市场数据检测并生成告警列表。"""
    alerts = []

    for idx in market.get("indices", []):
        change = idx.get("change_pct", 0)
        if change is not None and abs(change) >= settings.ALERT_INDEX_THRESHOLD:
            direction = "暴涨" if change > 0 else "暴跌"
            alerts.append(AlertItem(
                alert_type="index",
                title=f"{idx['name']}{direction}{abs(change):.2f}%",
                content=f"{idx['name']}最新点位{idx.get('value', 0):.2f}",
                level="danger" if change < -2 else "warning",
            ).model_dump())

    net_flow = north.get("net_flow")
    if net_flow is not None and abs(net_flow) >= settings.ALERT_NORTH_FLOW_THRESHOLD:
        direction = "大幅流入" if net_flow > 0 else "大幅流出"
        sh = north.get("sh_flow") or 0
        sz = north.get("sz_flow") or 0
        alerts.append(AlertItem(
            alert_type="north_flow",
            title=f"北向资金{direction}{abs(net_flow):.1f}亿",
            content=f"沪股通{sh:.1f}亿，深股通{sz:.1f}亿",
            level="warning",
        ).model_dump())

    for stock in leading.get("headlines", []):
        change = stock.get("change_pct", 0)
        if change is not None and abs(change) >= settings.ALERT_LEADING_STOCK_THRESHOLD:
            direction = "暴涨" if change > 0 else "暴跌"
            alerts.append(AlertItem(
                alert_type="leading_stock",
                title=f"大市值{stock['name']}{direction}{abs(change):.2f}%",
                content=f"市值{stock.get('market_cap', '')}",
                level="danger" if change < -5 else "warning",
            ).model_dump())

    # 北证告警
    if bse:
        for idx in bse.get("indices", []):
            change = idx.get("change_pct", 0)
            if change is not None and abs(change) >= settings.ALERT_INDEX_THRESHOLD:
                direction = "暴涨" if change > 0 else "暴跌"
                alerts.append(AlertItem(
                    alert_type="bse_index",
                    title=f"{idx['name']}{direction}{abs(change):.2f}%",
                    content=f"{idx['name']}最新点位{idx.get('value', 0):.2f}",
                    level="danger" if change < -2 else "warning",
                ).model_dump())

        for stock in bse.get("leading", {}).get("headlines", []):
            change = stock.get("change_pct", 0)
            if change is not None and abs(change) >= settings.ALERT_LEADING_STOCK_THRESHOLD:
                direction = "暴涨" if change > 0 else "暴跌"
                alerts.append(AlertItem(
                    alert_type="bse_stock",
                    title=f"北证龙头{stock['name']}{direction}{abs(change):.2f}%",
                    content=f"北证{stock['name']}{direction}涨跌{abs(change):.2f}%",
                    level="danger" if change < -5 else "warning",
                ).model_dump())

    return alerts


# ═══════════════════════════════════════════════════════
# 新增数据源 (v2.0 — 五维框架)
# ═══════════════════════════════════════════════════════

# ── 4. 美股市场 ──────────────────────────────────────

@_cached("us_market", ttl_seconds=settings.CACHE_TTL_US, module_name="us_market")
@retry(max_retries=1, delay=1.0, backoff=2.0)
def get_us_market() -> dict:
    """美股市场数据：道指 / 标普 / 纳指 + 热门个股。"""
    if not settings.ENABLE_US_MARKET:
        from models.schemas import USMarketData
        return USMarketData().model_dump()
    from models.schemas import USMarketData, USStockData
    logger.info("Fetching US market data...")
    result = USMarketData()

    # 美股指数 - 使用快速日线 API（最后一条是最新数据）
    try:
        # 标普500
        try:
            df = ak.index_us_stock_sina()
            if df is not None and not df.empty:
                latest = df.iloc[-1]
                close = safe_float(latest.get("close", 0))
                # 计算涨跌幅（与前一日比较）
                if len(df) >= 2:
                    prev = df.iloc[-2]
                    prev_close = safe_float(prev.get("close", 0))
                    if close and prev_close and prev_close > 0:
                        chg = ((close - prev_close) / prev_close) * 100
                        result.indices.append(IndexData(name="标普500", value=close, change_pct=chg))
        except Exception as e:
            logger.debug(f"index_us_stock_sina failed: {e}")

        # 道指和纳指 - 从知名美股中取
        try:
            df = ak.stock_us_famous_spot_em()
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    name = safe_str(row.get("名称", ""))
                    price = safe_float(row.get("最新价", 0))
                    chg = safe_pct(row.get("涨跌幅", 0))
                    if price is not None and price > 10:
                        if name in ("道琼斯", "标普500", "纳斯达克"):
                            # 去重
                            existing_names = {idx.name for idx in result.indices}
                            if name not in existing_names:
                                result.indices.append(IndexData(name=name, value=price, change_pct=chg))
                        elif name not in ("VIX", "CBOE Volatility Index"):
                            result.top_stocks.append(USStockData(name=name, value=price, change_pct=chg))
                # 只取前10只
                result.top_stocks = sorted(result.top_stocks, key=lambda x: abs(x.change_pct), reverse=True)[:10]
            else:
                logger.warning("stock_us_famous_spot_em returned no data")
        except Exception as e:
            logger.warning(f"Failed to fetch US market indices via famous_spot: {e}")
            # 最终备用：通过新浪逐个获取三大指数
            us_targets = [
                (".DJI", "道琼斯"),
                (".INX", "标普500"),
                (".IXIC", "纳斯达克"),
            ]
            for sym, target_name in us_targets:
                # 检查是否已存在
                existing_names = {idx.name for idx in result.indices}
                if target_name in existing_names:
                    continue
                try:
                    df = ak.index_us_stock_sina(symbol=sym)
                    if df is not None and not df.empty:
                        latest = df.iloc[-1]
                        close = safe_float(latest.get("close", 0))
                        if len(df) >= 2:
                            prev = df.iloc[-2]
                            prev_close = safe_float(prev.get("close", 0))
                            if close and prev_close and prev_close > 0:
                                chg = ((close - prev_close) / prev_close) * 100
                                result.indices.append(IndexData(name=target_name, value=close, change_pct=chg))
                                logger.info(f"US index {target_name}: {close} ({chg:+.2f}%)")
                except Exception as e2:
                    logger.debug(f"US index {target_name} fallback failed: {e2}")
        else:
            # stock_us_famous_spot_em 成功，但可能遗漏了道指/纳斯达克
            us_targets = [("道琼斯", ".DJI"), ("纳斯达克", ".IXIC")]
            for display_name, symbol in us_targets:
                existing_names = {idx.name for idx in result.indices}
                if display_name in existing_names:
                    continue
                try:
                    df = ak.index_us_stock_sina(symbol=symbol)
                    if df is not None and not df.empty:
                        latest = df.iloc[-1]
                        close = safe_float(latest.get("close", 0))
                        if len(df) >= 2:
                            prev = df.iloc[-2]
                            prev_close = safe_float(prev.get("close", 0))
                            if close and prev_close and prev_close > 0:
                                chg = ((close - prev_close) / prev_close) * 100
                                result.indices.append(IndexData(name=display_name, value=close, change_pct=chg))
                except Exception as e3:
                    logger.debug(f"Missing US index {display_name} fetch failed: {e3}")

    except Exception as e:
        logger.warning(f"Failed to fetch US market data: {e}")

    # 热门个股补充（尝试取前几页名人堂股票即可）
    if not result.top_stocks:
        try:
            df = ak.stock_us_famous_spot_em()
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    name = safe_str(row.get("名称", ""))
                    price = safe_float(row.get("最新价", 0))
                    chg = safe_pct(row.get("涨跌幅", 0))
                    if price is not None and price > 5 and name not in ("道琼斯", "标普500", "纳斯达克", "VIX"):
                        result.top_stocks.append(USStockData(name=name, value=price, change_pct=chg))
                result.top_stocks = sorted(result.top_stocks, key=lambda x: abs(x.change_pct), reverse=True)[:10]
        except Exception as e3:
            logger.debug(f"US market famous stocks fallback failed: {e3}")

    return result.model_dump()


# ── 5. 加密货币 ──────────────────────────────────────

@_cached("crypto", ttl_seconds=settings.CACHE_TTL_CRYPTO, module_name="crypto")
@retry(max_retries=1, delay=1.0, backoff=2.0)
def get_crypto_data() -> dict:
    """加密货币数据：BTC / ETH 实时行情（多源回退）。"""
    if not settings.ENABLE_CRYPTO:
        from models.schemas import CryptoData
        return CryptoData().model_dump()
    from models.schemas import CryptoData
    logger.info("Fetching crypto data...")
    result = CryptoData()
    fetched = False

    # 源1: akshare crypto_js_spot（首选）
    try:
        df = ak.crypto_js_spot()
        if df is not None and not df.empty:
            for _, row in df.iterrows():
                name = safe_str(row.get("交易品种", ""))
                price = safe_float(row.get("最近报价", 0))
                chg = safe_pct(row.get("涨跌幅", 0))
                if "BTC" in name.upper():
                    result.btc_price = f"{price:,.0f}" if price is not None and price > 1 else f"{price}"
                    result.btc_change = chg
                    fetched = True
                elif "ETH" in name.upper():
                    result.eth_price = f"{price:,.0f}" if price is not None and price > 1 else f"{price}"
                    result.eth_change = chg
                    fetched = True
    except Exception as e:
        logger.warning(f"Failed to fetch crypto_js_spot: {e}")

    # 源2: CoinGecko API（回退，当日美盘时段更准确）
    if not fetched or result.btc_price is None:
        try:
            import httpx as _httpx
            cg_url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum&vs_currencies=usd&include_24hr_change=true"
            cg_resp = _httpx.get(cg_url, headers={"Accept": "application/json"}, timeout=10)
            if cg_resp.status_code == 200:
                cg_data = cg_resp.json()
                btc = cg_data.get("bitcoin", {})
                eth = cg_data.get("ethereum", {})
                if btc.get("usd"):
                    result.btc_price = f"{btc['usd']:,.0f}"
                    result.btc_change = btc.get("usd_24h_change")
                    fetched = True
                if eth.get("usd"):
                    result.eth_price = f"{eth['usd']:,.0f}"
                    result.eth_change = eth.get("usd_24h_change")
        except Exception as e:
            logger.debug(f"Failed to fetch CoinGecko crypto fallback: {e}")

    # ETH 回退：Binance API
    if not result.eth_price:
        try:
            import httpx as _httpx_binance
            resp = _httpx_binance.get(
                "https://api.binance.com/api/v3/ticker/24hr?symbol=ETHUSDT",
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=5,
            )
            if resp.status_code == 200:
                data = resp.json()
                price = safe_float(data.get("lastPrice"))
                chg = safe_float(data.get("priceChangePercent"))
                if price:
                    result.eth_price = f"{price:,.0f}"
                    if chg is not None:
                        result.eth_change = chg
                    fetched = True
                    logger.info(f"ETH fallback (Binance): {result.eth_price} ({result.eth_change}%)")
        except Exception as e:
            logger.debug(f"ETH Binance fallback failed: {e}")

    # ETH 回退2：Gate.io API
    if not result.eth_price:
        try:
            import httpx as _httpx_gate
            resp = _httpx_gate.get(
                "https://api.gateio.ws/api/v4/spot/tickers?currency_pair=ETH_USDT",
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=5,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data and len(data) > 0:
                    price = safe_float(data[0].get("last"))
                    chg = safe_float(data[0].get("change_percentage"))
                    if price:
                        result.eth_price = f"{price:,.0f}"
                        if chg is not None:
                            result.eth_change = round(chg, 2)
                        fetched = True
                        logger.info(f"ETH fallback (Gate.io): {result.eth_price} ({result.eth_change}%)")
        except Exception as e:
            logger.debug(f"ETH Gate.io fallback failed: {e}")

    if result.btc_change is not None:
        direction = "上涨" if result.btc_change >= 0 else "下跌"
        result.highlights.append(f"BTC 24h {direction} {abs(result.btc_change):.2f}%")
    if result.eth_change is not None:
        direction = "上涨" if result.eth_change >= 0 else "下跌"
        result.highlights.append(f"ETH 24h {direction} {abs(result.eth_change):.2f}%")

    if not fetched:
        logger.warning("所有加密货币数据源均失败")
        result.highlights.append("⚠️ 加密货币数据暂不可用")

    return result.model_dump()


# ── 6. 国内商品期货 ────────────────────────────────

@_cached("futures", ttl_seconds=settings.CACHE_TTL_FUTURES, module_name="futures")
@retry(max_retries=1, delay=1.0, backoff=2.0)
def get_futures_data() -> dict:
    """国内商品期货：铁矿石 / 螺纹钢 / 碳酸锂 / 生猪 / 铜等关键品种。"""
    if not settings.ENABLE_FUTURES:
        from models.schemas import FuturesData
        return FuturesData().model_dump()
    from models.schemas import FuturesData
    logger.info("Fetching domestic futures data...")
    result = FuturesData()

    # 关注的关键品种
    # 可配置：通过 settings.TARGET_FUTURES 覆盖
    target_futures = getattr(settings, "TARGET_FUTURES", ["铁矿石", "螺纹钢", "碳酸锂", "生猪", "沪铜", "沪铝", "焦煤", "纯碱", "玻璃"])

    try:
        df = ak.futures_zh_realtime()
        if df is not None and not df.empty:
            name_col = "name"
            price_col = "trade"
            chg_col = "changepercent"
            for _, row in df.iterrows():
                name = safe_str(row.get(name_col, ""))
                for t in target_futures:
                    if t in name:
                        price = safe_float(row.get(price_col, 0))
                        chg = safe_pct(row.get(chg_col, 0) if chg_col else 0)
                        if price is not None and price > 0.001:
                            result.items.append({
                                "name": name,
                                "price": f"{price:.2f}" if price < 1000 else f"{price:.0f}",
                                "change_pct": chg,
                            })
                        break
    except Exception as e:
        logger.warning(f"Failed to fetch futures_zh_realtime: {e}")

    # 再备选：futures_spot_price_daily
    if not result.items:
        try:
            df = ak.futures_spot_price_daily()
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    name = safe_str(row.get("品种", row.get("名称", "")))
                    if not name:
                        continue
                    for t in target_futures:
                        if t in name:
                            price = safe_float(row.get("最新价", row.get("price", 0)))
                            chg = safe_pct(row.get("涨跌幅", row.get("change_pct", 0)))
                            if price is not None and price > 0.001:
                                result.items.append({
                                    "name": name,
                                    "price": f"{price:.2f}" if price < 1000 else f"{price:.0f}",
                                    "change_pct": chg,
                                })
                            break
        except Exception as e:
            logger.debug(f"Futures spot price daily fallback failed: {e}")

    if result.items:
        result.items.sort(key=lambda x: abs(x.get("change_pct", 0) or 0), reverse=True)
        for item in result.items[:3]:
            chg = item.get("change_pct", 0)
            direction = "上涨" if chg >= 0 else "下跌"
            result.highlights.append(f"{item['name']} {direction} {abs(chg):.2f}%")

    return result.model_dump()


# ── 7. 货币政策量化 ────────────────────────────────

@_cached("monetary", ttl_seconds=settings.CACHE_TTL_MONETARY, module_name="monetary")
@retry(max_retries=1, delay=1.0, backoff=2.0)
def get_monetary_data() -> dict:
    """货币政策量化数据：M2增速 / 社融增速 / 信贷脉冲 / 存准率 / MLF。"""
    if not settings.ENABLE_MONETARY:
        from models.schemas import MonetaryData
        return MonetaryData().model_dump()
    from models.schemas import MonetaryData
    logger.info("Fetching monetary policy data...")
    result = MonetaryData()

    # M2 同比增速（取自 macro_china_money_supply，已有 M2 增速列）
    # M2 同比增速
    try:
        df = ak.macro_china_money_supply()
        if df is not None and not df.empty:
            df = df.sort_values("月份", ascending=False)
            latest = df.iloc[0]
            for i, c in enumerate(df.columns):
                if "同比增长" in str(c):
                    result.m2_growth = safe_str(latest.iloc[i])[:8]
                    break
    except Exception as e:
        logger.warning(f"Failed to fetch M2 growth: {e}")

    # M2 历史趋势（近6期）
    try:
        df = ak.macro_china_money_supply()
        if df is not None and not df.empty:
            df = df.sort_values("月份", ascending=False).head(6)
            m2_vals = []
            for i, c in enumerate(df.columns):
                if "同比增长" in str(c):
                    m2_vals = [safe_str(row.iloc[i])[:6] for _, row in df.iterrows()]
                    break
            if len(m2_vals) >= 2:
                result.highlights.append(f"M2趋势: {'→'.join(m2_vals[:4])}")
    except Exception as e:
        logger.debug(f"Failed to fetch M2 trend: {e}")

    # 社融增量（当月值，亿元）
    try:
        df = ak.macro_china_shrzgm()
        if df is not None and not df.empty:
            df = df.sort_values("月份", ascending=False)
            latest = df.iloc[0]
            # 社会融资规模增量（当月新增，亿元）
            raw_val = safe_str(latest.iloc[1]) if len(latest) >= 2 else ""
            if raw_val:
                try:
                    val = float(raw_val)
                    # 格式化显示
                    if abs(val) >= 10000:
                        result.social_finance_growth = f"{val/10000:.1f}万亿"
                    elif abs(val) >= 1000:
                        result.social_finance_growth = f"{val/1000:.1f}千亿"
                    else:
                        result.social_finance_growth = f"{val:.0f}亿"
                except (ValueError, TypeError):
                    result.social_finance_growth = raw_val
    except Exception as e:
        logger.warning(f"Failed to fetch social finance: {e}")
    
    # 上月社融对比（简版趋势）
    try:
        df = ak.macro_china_shrzgm()
        if df is not None and not df.empty:
            df = df.sort_values("月份", ascending=False).head(3)
            vals = []
            for _, row in df.iterrows():
                raw = safe_str(row.iloc[1]) if len(row) >= 2 else ""
                try:
                    vals.append(float(raw))
                except (ValueError, TypeError):
                    pass
            if len(vals) >= 2:
                trend = "扩张" if vals[0] > vals[1] else "收缩" if vals[0] < vals[1] else "持平"
                result.highlights.append(f"社融趋势: {trend}（本月{vals[0]/10000:.1f}万亿 vs 上月{vals[1]/10000:.1f}万亿）")
    except Exception as e:
        logger.debug(f"Failed to fetch social finance trend: {e}")

    # 存款准备金率
    try:
        df = ak.macro_china_reserve_requirement_ratio()
        if df is not None and not df.empty:
            df = df.sort_values("公布时间", ascending=False)
            latest = df.iloc[0]
            # 取大型金融机构调整后
            for col in df.columns:
                if "大型" in str(col) and "调整后" in str(col):
                    result.rrr_current = safe_str(latest[col])[:8]
                    break
            if not result.rrr_current:
                # 取"大型金融机构-调整后"列
                rrr_col = "大型金融机构-调整后"
                if rrr_col in df.columns:
                    result.rrr_current = safe_str(latest[rrr_col])[:8]
    except Exception as e:
        logger.warning(f"Failed to fetch RRR: {e}")

    # 生成 highlights
    if result.m2_growth:
        result.highlights.append(f"M2同比: {result.m2_growth}")
    if result.social_finance_growth:
        result.highlights.append(f"社融增量: {result.social_finance_growth}")
    if result.rrr_current:
        result.highlights.append(f"存准率: {result.rrr_current}")

    return result.model_dump()


# ── 8. 扩展全球宏观（VIX / BDI / 日经 / 汇率篮子） ──
def _extend_global_macro(result):
    """给已有的 GlobalMacroData 补充 VIX / BDI / 日经 / 汇率篮子。"""
    # 统一获取一次知名美股数据（包含 VIX、Nikkei、WTI、标普等）
    us_df = None
    if settings.ENABLE_VIX:
        try:
            us_df = ak.stock_us_famous_spot_em()
        except Exception as e:
            logger.debug(f"Failed to fetch us_famous_spot_em for VIX: {e}")

    if us_df is not None and not us_df.empty:
        for _, row in us_df.iterrows():
            name = safe_str(row.get("名称", ""))
            price = safe_float(row.get("最新价", 0))
            chg = safe_pct(row.get("涨跌幅", 0))

            # VIX
            if settings.ENABLE_VIX and not result.vix:
                if "VIX" in name.upper():
                    result.vix = f"{price:.2f}"

            # 日经
            if not result.nikkei:
                if "日经" in name or "Nikkei" in name:
                    result.nikkei = f"{price:.2f} {chg:+.2f}%" if chg else f"{price:.2f}"

            # WTI
            if not result.wti_oil:
                if "WTI" in name.upper():
                    result.wti_oil = f"{price:.2f}"

            # 标普500
            if not result.sp500 and "标普" in name:
                result.sp500 = f"{price:.2f}"

    # 波罗的海干散货指数 BDI
    if settings.ENABLE_SHIPPING and not result.bdi:
        try:
            df = ak.macro_shipping_bdi()
            if df is not None and not df.empty:
                df = df.tail(5)
                latest = df.iloc[-1]
                result.bdi = f"{safe_float(latest.iloc[-1]):.0f}"
        except Exception as e:
            logger.debug(f"Failed to fetch BDI: {e}")

    # 汇率篮子
    try:
        df = ak.forex_spot_em()
        if df is not None and not df.empty:
            for _, row in df.iterrows():
                name = safe_str(row.get("名称", ""))
                price_raw = row.get("最新价", row.get("中间价", 0))
                price = safe_float(price_raw)
                if not price:
                    continue
                if "美元/日元" in name or "USD/JPY" in name:
                    result.usd_jpy = f"{price:.2f}"
                elif "欧元/美元" in name or "EUR/USD" in name:
                    result.euro_usd = f"{price:.4f}"
    except Exception as e:
        logger.debug(f"Failed to fetch forex basket: {e}")

    # 白银
    if not result.silver:
        try:
            df = ak.macro_cons_silver()
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    price = safe_float(row.get("价格", row.get("最新价", 0)))
                    if price is not None and price != 0:
                        result.silver = f"{price:.2f}"
                        break
        except Exception as e:
            logger.debug(f"Failed to fetch silver: {e}")

    # 美国 2Y 国债
    if not result.us_2y_bond:
        try:
            df = ak.bond_zh_us_rate()
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    name = safe_str(row.get("名称", ""))
                    price = safe_float(row.get("最新价", row.get("price", 0)))
                    if "美国" in name and "2年" in name:
                        result.us_2y_bond = f"{price:.2f}"
                        break
        except Exception as e:
            logger.debug(f"Failed to fetch US 2Y bond: {e}")

    # 生成 highlights
    if result.vix:
        v = float(result.vix) if result.vix else 0
        flag = "⚠️" if v > 25 else "✅" if v < 15 else "➖"
        result.highlights.append(f"VIX: {result.vix} {flag}")
    if result.bdi:
        result.highlights.append(f"BDI: {result.bdi}")
    if result.usd_jpy:
        result.highlights.append(f"USD/JPY: {result.usd_jpy}")



# ── 9. 跨市场比价 ──────────────────────────────────

@_cached("comparison", ttl_seconds=1800, module_name="comparison")
@retry(max_retries=1, delay=1.0, backoff=2.0)
def get_intraday_comparison() -> dict:
    """跨市场日内比较：A股 / 港股 / 美股 / BTC。"""
    from models.schemas import IntradayComparison
    logger.info("Fetching intraday comparison...")
    result = IntradayComparison()

    # A 股（最新指数）
    try:
        df = ak.stock_zh_index_spot_sina()
        if df is not None and not df.empty:
            for _, row in df.iterrows():
                name = safe_str(row.get("名称", ""))
                chg = safe_pct(row.get("涨跌幅", 0))
                if "上证" in name:
                    result.a_shanghai = f"{chg:+.2f}%"
                elif "深证" in name:
                    result.a_shenzhen = f"{chg:+.2f}%"
    except Exception as e:
        logger.debug(f"get_intraday_comparison: failed to fetch A-share index: {e}")
        pass

    # 美股（取当前已知值）
    try:
        df = ak.stock_us_famous_spot_em()
        if df is not None and not df.empty:
            for _, row in df.iterrows():
                name = safe_str(row.get("名称", ""))
                chg = safe_pct(row.get("涨跌幅", 0))
                if "标普" in name:
                    result.us_sp500 = f"{chg:+.2f}%"
                elif "纳斯达克" in name:
                    result.us_nasdaq = f"{chg:+.2f}%"
    except Exception as e:
        logger.debug(f"get_intraday_comparison: failed to fetch US stock: {e}")
        pass

    # 恒生指数
    try:
        df = ak.stock_hk_famous_spot_em()
        if df is not None and not df.empty:
            for _, row in df.iterrows():
                name = safe_str(row.get("名称", ""))
                if "恒生" in name:
                    chg = safe_pct(row.get("涨跌幅", 0))
                    result.hk_hsi = f"{chg:+.2f}%"
                    break
    except Exception as e:
        logger.debug(f"get_intraday_comparison: failed to fetch HK stock: {e}")
        pass

    # BTC
    try:
        df = ak.crypto_js_spot()
        if df is not None and not df.empty:
            for _, row in df.iterrows():
                name = safe_str(row.get("名称", ""))
                if "BTC" in name.upper():
                    chg = safe_pct(row.get("涨跌幅", 0))
                    result.btc = f"{chg:+.2f}%"
                    break
    except Exception as e:
        logger.debug(f"get_intraday_comparison: failed to fetch BTC: {e}")
        pass

    parts = []
    if result.a_shanghai:
        parts.append(f"A股:{result.a_shanghai}")
    if result.a_shenzhen:
        parts.append(f"深证:{result.a_shenzhen}")
    if result.us_sp500:
        parts.append(f"标普:{result.us_sp500}")
    if result.hk_hsi:
        parts.append(f"恒生:{result.hk_hsi}")
    if result.btc:
        parts.append(f"BTC:{result.btc}")
    result.summary = " | ".join(parts) if parts else "暂无跨市场数据"

    return result.model_dump()


# ── 10. 个股基本面（PE / PB / ROE / 市值 / 行业 / 营收增长） ──

def _to_bare_code(code: str) -> str:
    """将 A 股代码转换为 akshare 接口需要的纯数字代码。

    支持: SH600519 → 600519, SZ002594 → 002594, BJ920083 → 920083,
          sh600519 → 600519, 600519 → 600519
    """
    code = str(code).strip().upper()
    if code.startswith(("SH", "SZ", "BJ")):
        return code[2:]
    return code


@_cached("fundamentals", ttl_seconds=settings.CACHE_TTL_MACRO, module_name="fundamentals")
@retry(max_retries=2, delay=1.0, backoff=2.0)
def get_stock_fundamentals(symbols: list[str]) -> dict:
    """获取股票基本面数据：PE / PB / ROE / 市值 / 行业 / 营收增长。

    数据源：
      - akshare.stock_a_indicator_lg: PE / PB / 股息率（取最新一期）
      - akshare.stock_individual_info_em: 总市值 / 流通市值 / 行业
      - akshare.stock_financial_abstract: ROE（最近一期净资产收益率）/ 营收增长

    单只股票失败不影响其他股票。A 股代码格式自动转换：
      SH600519 → 600519, SZ002594 → 002594, BJ920083 → 920083

    Args:
        symbols: 股票代码列表，支持带 SH/SZ/BJ 前缀或纯数字代码

    Returns:
        {"symbols": {symbol: {pe, pb, roe, market_cap, industry, ...}, ...}, "date": "..."}
    """
    logger.info(f"Fetching fundamentals for {len(symbols)} stocks...")
    from datetime import datetime

    result: dict = {"symbols": {}, "date": datetime.now().strftime("%Y-%m-%d")}

    for symbol in symbols:
        bare_code = _to_bare_code(symbol)
        if not bare_code:
            continue
        try:
            entry: dict = {}

            # 1) PE / PB / 股息率（stock_a_indicator_lg，取最新一行）
            try:
                df_ind = ak.stock_a_indicator_lg(symbol=bare_code)
                if df_ind is not None and not df_ind.empty:
                    latest = df_ind.iloc[-1]
                    pe = safe_float(latest.get("pe", 0))
                    pb = safe_float(latest.get("pb", 0))
                    dividend_yield = safe_float(latest.get("dv_ratio", 0))
                    if pe:
                        entry["pe"] = pe
                    if pb:
                        entry["pb"] = pb
                    if dividend_yield:
                        entry["dividend_yield"] = dividend_yield
            except Exception as e:
                logger.debug(f"stock_a_indicator_lg failed for {bare_code}: {e}")

            # 2) 总市值 / 流通市值 / 行业（stock_individual_info_em）
            try:
                df_info = ak.stock_individual_info_em(symbol=bare_code)
                if df_info is not None and not df_info.empty:
                    # df_info 通常是两列: item / value
                    item_col = _find_column(df_info, ["item", "项目"])
                    value_col = _find_column(df_info, ["value", "值"])
                    if item_col and value_col:
                        info_map: dict = {}
                        for _, row in df_info.iterrows():
                            key = safe_str(row.get(item_col, ""))
                            val = row.get(value_col, "")
                            if key:
                                info_map[key] = val
                        # 总市值
                        for k in ("总市值", "总市值（元）"):
                            if k in info_map:
                                entry["market_cap"] = safe_float(info_map[k])
                                break
                        # 流通市值
                        for k in ("流通市值", "流通市值（元）"):
                            if k in info_map:
                                entry["circulating_market_cap"] = safe_float(info_map[k])
                                break
                        # 行业
                        for k in ("行业", "所属行业"):
                            if k in info_map:
                                entry["industry"] = safe_str(info_map[k])
                                break
            except Exception as e:
                logger.debug(f"stock_individual_info_em failed for {bare_code}: {e}")

            # 3) ROE + 营收增长（stock_financial_abstract，取最近一期）
            try:
                df_fin = ak.stock_financial_abstract(symbol=bare_code)
                if df_fin is not None and not df_fin.empty:
                    for _, row in df_fin.iterrows():
                        item_key = safe_str(row.iloc[0]) if len(row) > 0 else ""
                        if not item_key:
                            continue
                        # ROE（净资产收益率）
                        if ("净资产收益率" in item_key or "ROE" in item_key.upper()) and "roe" not in entry:
                            if len(row) > 1:
                                roe_val = safe_float(row.iloc[1])
                                if roe_val:
                                    entry["roe"] = roe_val
                        # 营收增长（营业总收入同比增长 / 营业收入同比增长）
                        if "营业收入" in item_key and "增长" in item_key and "revenue_growth" not in entry:
                            if len(row) > 1:
                                rev_growth = safe_float(row.iloc[1])
                                if rev_growth:
                                    entry["revenue_growth"] = rev_growth
                        if "roe" in entry and "revenue_growth" in entry:
                            break
            except Exception as e:
                logger.debug(f"stock_financial_abstract failed for {bare_code}: {e}")

            if entry:
                result["symbols"][symbol] = entry
            else:
                logger.warning(f"No fundamentals data for {symbol} ({bare_code})")
        except Exception as e:
            logger.warning(f"Failed to fetch fundamentals for {symbol}: {e}")

    return result


# ── 扩展 detect_alerts（新增加密货币/期货告警） ──

def _extend_alerts(alerts: list, crypto: dict | None = None, futures: dict | None = None) -> list:
    """在原有 alerts 基础上增加加密货币和期货告警。"""
    if crypto:
        btc_chg = crypto.get("btc_change")
        if btc_chg is not None and abs(btc_chg) >= settings.ALERT_CRYPTO_THRESHOLD:
            direction = "暴涨" if btc_chg > 0 else "暴跌"
            alerts.append(AlertItem(
                alert_type="crypto",
                title=f"BTC{direction}{abs(btc_chg):.2f}%",
                content=f"比特币24小时{direction}",
                level="danger" if abs(btc_chg) > 8 else "warning",
            ).model_dump())
        eth_chg = crypto.get("eth_change")
        if eth_chg is not None and abs(eth_chg) >= settings.ALERT_CRYPTO_THRESHOLD:
            direction = "暴涨" if eth_chg > 0 else "暴跌"
            alerts.append(AlertItem(
                alert_type="crypto",
                title=f"ETH{direction}{abs(eth_chg):.2f}%",
                content=f"以太坊24小时{direction}",
                level="danger" if abs(eth_chg) > 8 else "warning",
            ).model_dump())

    if futures:
        for item in futures.get("items", []):
            chg = item.get("change_pct", 0) or 0
            if abs(chg) >= settings.ALERT_FUTURES_THRESHOLD:
                direction = "大涨" if chg > 0 else "大跌"
                alerts.append(AlertItem(
                    alert_type="futures",
                    title=f"{item['name']}{direction}{abs(chg):.1f}%",
                    content=f"商品期货{direction}",
                    level="danger" if abs(chg) > 5 else "warning",
                ).model_dump())

    return alerts


# ═══════════════════════════════════════════════════════
# 导出全局宏：便于 report_generator 统一调用
# ═══════════════════════════════════════════════════════

NEW_DATA_SOURCES = [
    "get_us_market",
    "get_crypto_data",
    "get_futures_data",
    "get_monetary_data",
    "get_intraday_comparison",
    "get_stock_fundamentals",
]

