#!/usr/bin/env python3
"""诊断数据获取问题"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from loguru import logger
logger.remove()
logger.add(sys.stderr, level="DEBUG")

from services.data_fetcher import (
    get_market_overview, get_macro_data, get_north_flow,
    get_etf_data, get_leading_stocks, get_global_macro,
)

print("=" * 60)
print("📊 开始诊断数据获取...")
print("=" * 60)

print("\n" + "="*60)
print("1️⃣ 获取市场数据...")
print("="*60)
try:
    market = get_market_overview()
    print(f"✅ 市场数据获取成功")
    print(f"   指数: {len(market.get('indices', []))}个")
    for idx in market.get('indices', []):
        print(f"     - {idx['name']}: {idx.get('value')} ({idx.get('change_pct')}%)")
    print(f"   涨跌: {market.get('up_count')}涨/{market.get('down_count')}跌")
    print(f"   成交额: {market.get('total_volume')}")
    print(f"   板块: {len(market.get('top_sectors', []))}个")
except Exception as e:
    print(f"❌ 市场数据获取失败: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "="*60)
print("2️⃣ 获取宏观数据...")
print("="*60)
try:
    macro = get_macro_data()
    print(f"✅ 宏观数据获取成功")
    print(f"   highlights: {len(macro.get('highlights', []))}个")
    for h in macro.get('highlights', []):
        print(f"     - {h}")
except Exception as e:
    print(f"❌ 宏观数据获取失败: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "="*60)
print("3️⃣ 获取北向资金...")
print("="*60)
try:
    north = get_north_flow()
    print(f"✅ 北向资金获取成功")
    print(f"   净流: {north.get('net_flow')}亿")
    print(f"   沪股通: {north.get('sh_flow')}亿")
    print(f"   深股通: {north.get('sz_flow')}亿")
except Exception as e:
    print(f"❌ 北向资金获取失败: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "="*60)
print("4️⃣ 获取ETF数据...")
print("="*60)
try:
    etf = get_etf_data()
    print(f"✅ ETF数据获取成功")
    print(f"   宽基: {len(etf.get('broad_based', []))}个")
    print(f"   行业: {len(etf.get('industry', []))}个")
    print(f"   highlights: {len(etf.get('highlights', []))}个")
except Exception as e:
    print(f"❌ ETF数据获取失败: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "="*60)
print("5️⃣ 获取龙头股数据...")
print("="*60)
try:
    leading = get_leading_stocks()
    print(f"✅ 龙头股数据获取成功")
    print(f"   highlights: {len(leading.get('headlines', []))}个")
except Exception as e:
    print(f"❌ 龙头股数据获取失败: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "="*60)
print("6️⃣ 获取全球宏观...")
print("="*60)
try:
    global_m = get_global_macro()
    print(f"✅ 全球宏观获取成功")
    print(f"   原油: {global_m.get('brent_oil')}")
    print(f"   黄金: {global_m.get('gold')}")
    print(f"   美股: {global_m.get('sp500')}, {global_m.get('nasdaq')}, {global_m.get('dow')}")
except Exception as e:
    print(f"❌ 全球宏观获取失败: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "="*60)
print("✅ 诊断完成")
print("="*60)
