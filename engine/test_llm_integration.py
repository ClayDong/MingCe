#!/usr/bin/env python3
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from qlib_vnpy_platform.core.llm_analyzer import LLManalyzer

def test_llm_connection():
    print("=" * 80)
    print("测试LLM连接")
    print("=" * 80)

    try:
        analyzer = LLManalyzer()
        print(f"\n✓ LLM Analyzer初始化成功")
        print(f"  模型: {analyzer.get_model_name()}")
        print(f"  API可用: {analyzer.is_available()}")
        print(f"  配置: {analyzer.config}")

        if not analyzer.is_available():
            print("\n✗ LLM API不可用，请检查API Key配置")
            return False

        return True

    except Exception as e:
        print(f"\n✗ LLM Analyzer初始化失败: {e}")
        return False


def test_stock_analysis():
    print("\n" + "=" * 80)
    print("测试股票分析")
    print("=" * 80)

    try:
        analyzer = LLManalyzer()

        if not analyzer.is_available():
            print("跳过测试：LLM不可用")
            return False

        market_data = {
            "price": 250.5,
            "change_pct": 2.5,
            "volume": 50000000,
            "high": 252.0,
            "low": 245.0,
            "open": 248.0,
            "prev_close": 244.5,
            "ma5": 248.5,
            "ma10": 246.2,
            "ma20": 244.8,
            "rsi": 65.5,
            "macd": 2.3,
            "macd_signal": 1.8,
            "boll_upper": 260.0,
            "boll_lower": 235.0,
        }

        news_text = """
        比亚迪官方宣布，5月新能源汽车销量突破20万辆，同比增长150%，
        再创历史新高。同时，公司宣布将在深圳建设新的研发中心，
        预计投资50亿元。受此消息影响，多家券商上调比亚迪目标价。
        """

        print("\n正在调用LLM进行股票分析...")
        result = analyzer.analyze(
            stock_code="SZ002594",
            market_data=market_data,
            news_text=news_text,
            use_thinking=False
        )

        print("\n✓ 分析结果:")
        print(f"  信号: {result.get('signal', 'N/A')}")
        print(f"  置信度: {result.get('confidence', 0):.2f}")
        print(f"  风险等级: {result.get('risk_level', 'N/A')}")
        print(f"  理由: {result.get('reason', 'N/A')}")
        print(f"  目标价: {result.get('target_price', 'N/A')}")
        print(f"  止损价: {result.get('stop_loss', 'N/A')}")
        print(f"  关键因素: {result.get('key_factors', [])}")
        print(f"  模型: {result.get('model', 'N/A')}")
        print(f"  响应时间: {result.get('response_time', 0):.2f}秒")

        return True

    except Exception as e:
        print(f"\n✗ 股票分析测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_news_analysis():
    print("\n" + "=" * 80)
    print("测试新闻舆情分析")
    print("=" * 80)

    try:
        analyzer = LLManalyzer()

        if not analyzer.is_available():
            print("跳过测试：LLM不可用")
            return False

        news_text = """
        比亚迪官方宣布，5月新能源汽车销量突破20万辆，同比增长150%，
        再创历史新高。同时，公司宣布将在深圳建设新的研发中心，
        预计投资50亿元。受此消息影响，多家券商上调比亚迪目标价。
        """

        print("\n正在调用LLM进行新闻分析...")
        result = analyzer.analyze_news(
            news_text=news_text,
            stock_code="SZ002594"
        )

        print("\n✓ 新闻分析结果:")
        print(f"  情感: {result.get('sentiment', 'N/A')}")
        print(f"  影响程度: {result.get('impact_level', 'N/A')}")
        print(f"  影响时长: {result.get('impact_duration', 'N/A')}")
        print(f"  股价影响因子: {result.get('stock_impact_factor', 0):.2f}")
        print(f"  置信度: {result.get('confidence', 0):.2f}")
        print(f"  要点: {result.get('key_points', [])}")
        print(f"  模型: {result.get('model', 'N/A')}")
        print(f"  响应时间: {result.get('response_time', 0):.2f}秒")

        return True

    except Exception as e:
        print(f"\n✗ 新闻分析测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_strategy_advice():
    print("\n" + "=" * 80)
    print("测试策略建议生成")
    print("=" * 80)

    try:
        analyzer = LLManalyzer()

        if not analyzer.is_available():
            print("跳过测试：LLM不可用")
            return False

        regime = {
            "regime": "BULL",
            "trend_strength": 0.75,
            "volatility": 0.15,
        }

        backtest_results = [
            {
                "strategy": {"name": "MACD金叉"},
                "metrics": {
                    "total_return": 0.25,
                    "sharpe_ratio": 1.8,
                    "max_drawdown": 0.08,
                    "win_rate": 0.65,
                    "total_trades": 15,
                },
                "latest_signals": {
                    "next_action": "BUY",
                    "signal_strength": 0.8,
                },
            },
            {
                "strategy": {"name": "RSI超卖"},
                "metrics": {
                    "total_return": 0.18,
                    "sharpe_ratio": 1.5,
                    "max_drawdown": 0.10,
                    "win_rate": 0.60,
                    "total_trades": 20,
                },
                "latest_signals": {
                    "next_action": "BUY",
                    "signal_strength": 0.7,
                },
            },
        ]

        print("\n正在调用LLM生成策略建议...")
        result = analyzer.generate_strategy_advice(
            symbol="SZ002594",
            backtest_results=backtest_results,
            regime=regime
        )

        print("\n✓ 策略建议结果:")
        print(f"  推荐策略: {result.get('recommended_strategy', 'N/A')}")
        print(f"  入场条件: {result.get('entry_condition', 'N/A')}")
        print(f"  出场条件: {result.get('exit_condition', 'N/A')}")
        print(f"  建议仓位: {result.get('position_size', 'N/A')}")
        print(f"  置信度: {result.get('confidence', 0):.2f}")
        print(f"  风险提示: {result.get('risk_warning', 'N/A')}")
        print(f"  理由: {result.get('reasoning', 'N/A')}")

        return True

    except Exception as e:
        print(f"\n✗ 策略建议测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    print("\n" + "=" * 80)
    print("量化交易系统 LLM 集成测试")
    print("=" * 80)

    results = []

    results.append(("LLM连接", test_llm_connection()))

    if results[-1][1]:
        results.append(("股票分析", test_stock_analysis()))
        results.append(("新闻分析", test_news_analysis()))
        results.append(("策略建议", test_strategy_advice()))

    print("\n" + "=" * 80)
    print("测试总结")
    print("=" * 80)

    for name, passed in results:
        status = "✓ 通过" if passed else "✗ 失败"
        print(f"  {name}: {status}")

    all_passed = all(r[1] for r in results)
    print(f"\n总体结果: {'✓ 全部通过' if all_passed else '✗ 部分失败'}")

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
