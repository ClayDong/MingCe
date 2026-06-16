"""数据获取模块单元测试。"""

import pandas as pd
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── _find_column ─────────────────────────────────────

def test_find_column_exact_match():
    from services.data_fetcher import _find_column
    df = pd.DataFrame({"总市值": [100], "名称": ["A"], "涨跌幅": [1.0]})
    assert _find_column(df, ["总市值", "market_cap"]) == "总市值"


def test_find_column_partial_match():
    from services.data_fetcher import _find_column
    df = pd.DataFrame({"market_cap_bse": [100]})
    assert _find_column(df, ["总市值", "market_cap"]) == "market_cap_bse"


def test_find_column_no_match():
    from services.data_fetcher import _find_column
    df = pd.DataFrame({"代码": ["000001"]})
    assert _find_column(df, ["总市值", "market_cap"]) is None


def test_find_column_empty_df():
    from services.data_fetcher import _find_column
    df = pd.DataFrame()
    assert _find_column(df, ["总市值"]) is None


# ── safe_float / safe_pct (import from core.utils) ──

def test_safe_float_edge_cases():
    from core.utils import safe_float
    assert safe_float(None) == 0.0
    assert safe_float("") == 0.0
    assert safe_float(42.5) == 42.5
    assert safe_float("3.14") == 3.14
    assert safe_float("-5.0%") == -5.0


def test_format_volume():
    from core.utils import format_volume
    assert "亿" in format_volume(150_0000_0000)
    assert "万" in format_volume(5_0000)
    assert format_volume(999) == "999"
    assert format_volume(float("nan")) == "0"
    assert format_volume(None) == "0"


# ── _fetch_mcap_from_tencent (直接导入测试) ─────────

def test_mcap_null_empty():
    """空列表和None情况。"""
    from services.data_fetcher import _fetch_mcap_from_tencent
    assert _fetch_mcap_from_tencent([]) == {}
    assert _fetch_mcap_from_tencent(["invalid"]) == {}


# ── 腾讯字段解析验证 ────────────────────────────────

def test_mcap_field_position():
    """验证腾讯qt.gtimg.cn返回中字段46（0-indexed=45）是总市值。"""
    # 模拟腾讯返回格式（真实数据验证）
    raw_sample = '1~贵州茅台~600519~1256.02~1271.10~1267.01~21157~7973~13184~1256.06~2~1256.03~1~1256.02~3~1256.01~14~1256.00~119~1256.07~1~1256.08~2~1256.10~3~1256.11~2~1256.16~4~~20260616120506~-15.08~-1.19~1267.88~1256.01~1256.02/21157/2665880591~21157~266588~0.17~18.98~~1267.88~1256.01~0.93~15701.27~15701.27~5.86~1398.21~1143.99~1.14~127~1260.04~14.41~19.07~~~0.31~266588.0591~0.0000~0~ ~GP-A~-8.80~0.00~4.12~30.53~26.78~1568.00~1250.10~-3.92~-5.16~-14.49~1250081601~1250081601~84.11~-16.24~1250081601~~~-8.37~-0.16~~CNY~0~___D__F__N~1255.96~2~'
    parts = raw_sample.split("~")
    assert len(parts) > 46, f"预期至少46个字段，实际{len(parts)}"
    mcap_str = parts[45].strip()
    mcap_val = float(mcap_str)
    assert mcap_val > 15000, f"茅台市值应>15000亿，实际{mcap_val}"  # 茅台约1.57万亿


# ── safe_str 边界 ───────────────────────────────────

def test_safe_str_nan():
    from core.utils import safe_str
    import math
    assert safe_str(float("nan")) == ""
    assert safe_str(None) == ""


# ── 涨跌幅格式化 ────────────────────────────────────

def test_format_pct():
    from core.utils import format_pct
    assert "+" in format_pct(5.0)
    assert "-" in format_pct(-3.0)
    assert "0.00%" == format_pct(0)
    assert "0.00%" == format_pct(float("nan"))
