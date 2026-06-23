"""炒股的智慧深度分析模块测试。"""

import pytest
from services.wisdom_analyzer import (
    _detect_wisdom_triggers,
    build_wisdom_card,
)


class TestDetectWisdomTriggers:
    """触发条件检测测试。"""

    def test_no_triggers_on_calm_market(self):
        """平静市场不应触发深度分析。"""
        calm_data = {
            "market": {"indices": [{"change_pct": 0.1}, {"change_pct": -0.05}]},
            "macro": {"gold_silver_ratio": 75},
            "north_flow": {"net_buy": 10},
            "global_macro": {"vix": 15},
            "shipping": {"bdi": 1500},
            "leading_stocks": [],
        }
        triggers = _detect_wisdom_triggers(calm_data)
        assert not triggers.get("trigger_reasons")

    def test_two_different_triggers_activate(self):
        """2个不同类别的触发条件应启动深度分析。"""
        data = {
            "market": {"indices": [{"name": "深证成指", "change_pct": -3.5}]},
            "macro": {},
            "north_flow": {},
            "global_macro": {"bdi": 300},
            "shipping": {"bdi": 300},
            "leading_stocks": [],
        }
        triggers = _detect_wisdom_triggers(data)
        # philosophy_trigger(指数大跌) + cycle_trigger(BDI<500) = 2个不同类别
        assert triggers.get("philosophy_trigger") is True
        assert triggers.get("cycle_trigger") is True
        assert len(triggers.get("trigger_reasons", [])) >= 2

    def test_single_trigger_not_enough(self):
        """仅1个触发条件不应启动深度分析。"""
        data = {
            "market": {"indices": [{"name": "深证成指", "change_pct": -3.5}]},
            "macro": {},
            "north_flow": {},
            "global_macro": {},
            "shipping": {},
            "leading_stocks": [],
        }
        triggers = _detect_wisdom_triggers(data)
        # 单一触发类别，不满足>=2的要求
        assert not triggers.get("trigger_reasons")

    def test_same_category_two_signals_not_enough(self):
        """同一类别内2个信号（如BDI+VIX）不算2个触发条件。"""
        data = {
            "market": {"indices": []},
            "macro": {},
            "north_flow": {},
            "global_macro": {"bdi": 300, "vix": 30},
            "shipping": {"bdi": 300},
            "leading_stocks": [],
        }
        triggers = _detect_wisdom_triggers(data)
        # BDI和VIX都属于cycle_trigger，只有1个类别
        assert not triggers.get("trigger_reasons")


class TestBuildWisdomCard:
    """飞书卡片构建测试。"""

    def test_basic_card_structure(self):
        """基本卡片应包含 header 和 elements。"""
        card = build_wisdom_card("测试分析内容", {})
        assert "header" in card
        assert "elements" in card
        assert card["header"]["template"] == "purple"

    def test_long_content_truncation(self):
        """超长内容应被截断到 8000 字符。"""
        long_text = "测试内容。" * 2000
        card = build_wisdom_card(long_text, {})
        content = card["elements"][0]["content"]
        assert len(content) <= 8000 + 200
