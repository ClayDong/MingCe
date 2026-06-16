
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from qlib_vnpy_platform.config import load_config, get_config
from qlib_vnpy_platform.core.main_engine import MainEngine

load_config()

print("=" * 60)
print("测试: 默认配置和监控列表")
print("=" * 60)

config = get_config()
print("\n1. 配置内容:")
print(f"   trading.default_symbol: {config.get('trading', {}).get('default_symbol', 'NOT FOUND')}")
print(f"   watchlist.default_stocks: {config.get('watchlist', {}).get('default_stocks', 'NOT FOUND')}")

print("\n2. 初始化 MainEngine...")
engine = MainEngine()

print(f"\n3. 监控列表内容: {engine._watch_list}")

print(f"\n4. 默认股票是否在列表中: {'SZ002594' in engine._watch_list}")

print("\n" + "=" * 60)
