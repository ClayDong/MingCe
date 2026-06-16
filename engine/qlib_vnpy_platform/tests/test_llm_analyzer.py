import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from qlib_vnpy_platform.config import load_config
from qlib_vnpy_platform.core.llm_analyzer import LLManalyzer


def test_llm_connection():
    load_config()
    analyzer = LLManalyzer()

    result = analyzer.analyze(
        stock_code="SZ000001",
        market_data={
            "price": 12.50,
            "change_pct": 1.23,
            "volume": 50000000,
            "high": 12.80,
            "low": 12.30,
            "open": 12.35,
            "prev_close": 12.35,
            "ma5": 12.20,
            "ma10": 12.00,
            "ma20": 11.80,
            "rsi": 55.3,
            "macd": 0.05,
            "macd_signal": 0.03,
            "boll_upper": 13.0,
            "boll_lower": 11.5,
        },
        news_text="1. [东方财富] 平安银行发布2025年一季报，净利润同比增长5.2%\n2. [公告] 关于回购公司股份的进展公告",
        qlib_pred=0.65,
    )

    assert result is not None, "Result should not be None"
    assert "signal" in result, "Should have signal field"
    assert result["signal"] in ["BUY", "SELL", "HOLD"], f"Invalid signal: {result['signal']}"
    assert "confidence" in result, "Should have confidence field"
    assert 0 <= result["confidence"] <= 1, f"Confidence out of range: {result['confidence']}"
    assert "reason" in result, "Should have reason field"
    assert "risk_level" in result, "Should have risk_level field"

    print(f"[PASS] LLM connection test: signal={result['signal']}, "
          f"confidence={result['confidence']:.2f}, "
          f"risk_level={result['risk_level']}")
    print(f"  Reason: {result['reason']}")
    if result.get("target_price"):
        print(f"  Target: {result['target_price']}, Stop: {result.get('stop_loss')}")


def test_llm_parse_response():
    load_config()
    analyzer = LLManalyzer()

    valid_json = '{"signal": "BUY", "confidence": 0.8, "reason": "技术面看涨", "target_price": 13.5, "stop_loss": 12.0, "risk_level": "LOW", "key_factors": ["MA金叉", "放量上涨"]}'
    result = analyzer._parse_response(valid_json)
    assert result["signal"] == "BUY", "Signal should be BUY"
    assert result["confidence"] == 0.8, "Confidence should be 0.8"
    assert result["risk_level"] == "LOW", "Risk level should be LOW"
    print("[PASS] LLM parse valid JSON test")

    code_block_json = '```json\n{"signal": "SELL", "confidence": 0.6, "reason": "RSI超买"}\n```'
    result = analyzer._parse_response(code_block_json)
    assert result["signal"] == "SELL", "Should parse from code block"
    print("[PASS] LLM parse code block JSON test")

    invalid_json = "This is not JSON at all"
    result = analyzer._parse_response(invalid_json)
    assert result["signal"] == "HOLD", "Should default to HOLD for invalid input"
    print("[PASS] LLM parse invalid input test")


def test_llm_stats():
    load_config()
    analyzer = LLManalyzer()
    stats = analyzer.get_stats()
    assert "total_calls" in stats, "Should have total_calls"
    assert "model" in stats, "Should have model"
    print(f"[PASS] LLM stats test: calls={stats['total_calls']}, model={stats['model']}")


if __name__ == "__main__":
    test_llm_parse_response()
    test_llm_stats()
    test_llm_connection()
    print("\n=== All LLManalyzer tests passed ===")
