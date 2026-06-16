
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from qlib_vnpy_platform.config import load_config
from qlib_vnpy_platform.core.main_engine import MainEngine

load_config()
print("=== 测试开始 ===")

engine = MainEngine()
print(f"Engine 监控列表: {engine._watch_list}")

print(f"Scheduler status watch_list: {engine.scheduler.status['watch_list']}")

assert engine._watch_list == engine.scheduler.status['watch_list'], "Scheduler status 没有正确返回 engine 的监控列表！"

print("✅ 测试通过！Scheduler.status 现在正确返回 engine._watch_list 了！")
