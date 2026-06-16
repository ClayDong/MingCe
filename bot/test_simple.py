#!/usr/bin/env python3
"""简单测试"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("Hello! Testing imports...")

try:
    from services.data_fetcher import get_market_overview
    print("✓ Import get_market_overview ok")

    market = get_market_overview()
    print(f"✓ get_market_overview returned: {type(market)}")
    print(f"  indices: {len(market.get('indices', []))}")
    for idx in market.get('indices', []):
        print(f"  - {idx['name']}: value={idx.get('value')}, change={idx.get('change_pct')}%")

except Exception as e:
    print(f"✗ Error: {e}")
    import traceback
    traceback.print_exc()
