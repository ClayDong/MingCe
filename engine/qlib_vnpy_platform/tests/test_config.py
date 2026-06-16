import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from qlib_vnpy_platform.config import load_config, get_config, PROJECT_ROOT


def test_config_loading():
    config = load_config()
    assert config is not None, "Config should not be None"
    assert "llm" in config, "Config should have llm section"
    assert "data" in config, "Config should have data section"
    assert "risk" in config, "Config should have risk section"
    assert "signal" in config, "Config should have signal section"
    assert "trading" in config, "Config should have trading section"
    print("[PASS] Config loading test")


def test_llm_config():
    config = get_config()["llm"]
    # 只检查存在性，不检查具体值（因为 API Key 可能从 env 来）
    assert "api_key" in config, "LLM config should have api_key"
    assert "base_url" in config, "LLM config should have base_url"
    assert "model" in config, "LLM config should have model"
    print("[PASS] LLM config test (valid structure)")


def test_risk_config():
    config = get_config()["risk"]
    assert config["max_single_position"] == 0.30, "Max single position mismatch"
    assert config["daily_loss_circuit_breaker"] == 0.05, "Circuit breaker mismatch"
    assert config["max_holdings"] == 20, "Max holdings mismatch"
    print("[PASS] Risk config test")


def test_signal_config():
    config = get_config()["signal"]
    assert config["weight_qlib"] == 0.6, "QLib weight mismatch"
    assert config["weight_llm"] == 0.4, "LLM weight mismatch"
    assert config["buy_threshold"] == 0.2, "Buy threshold mismatch"
    assert config["sell_threshold"] == -0.2, "Sell threshold mismatch"
    print("[PASS] Signal config test")


if __name__ == "__main__":
    test_config_loading()
    test_llm_config()
    test_risk_config()
    test_signal_config()
    print("\n=== All config tests passed ===")
