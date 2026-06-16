#!/usr/bin/env python3
"""快速诊断脚本 - 不需要交互"""
import sys
import json
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from loguru import logger
import pandas as pd

from services.data_fetcher import (
    get_market_overview, get_macro_data, get_north_flow,
    get_etf_data, get_leading_stocks, get_global_macro,
)
from core.cache import FileCache


def print_section(title, char="="):
    print(f"\n{char * 60}")
    print(f"  {title}")
    print(f"{char * 60}")


def main():
    print_section("快速数据获取诊断", char="#")
    
    # 清除缓存
    print("🗑️  清除缓存...")
    cache = FileCache()
    cache.clear()
    print("✅ 缓存已清除")
    
    results = {}
    
    # 诊断各模块
    print_section("1. 市场概况数据")
    try:
        data = get_market_overview()
        print(f"✅ 成功")
        print(f"   指数: {len(data.get('indices', []))}个")
        for idx in data.get('indices', []):
            print(f"     {idx['name']}: {idx.get('value')} ({idx.get('change_pct')}%)")
        print(f"   涨跌: {data.get('up_count')}涨 / {data.get('down_count')}跌")
        print(f"   成交额: {data.get('total_volume')}")
        print(f"   板块: {len(data.get('top_sectors', []))}最强 / {len(data.get('bottom_sectors', []))}最弱")
        results['market'] = True
    except Exception as e:
        logger.exception(f"❌ 失败: {e}")
        results['market'] = False
    
    print_section("2. 宏观经济数据")
    try:
        data = get_macro_data()
        print(f"✅ 成功")
        fields = ['cpi', 'ppi', 'pmi', 'lpr_1y', 'lpr_5y', 'shibor_7d']
        for f in fields:
            val = data.get(f)
            status = "有数据" if val else "无数据"
            print(f"   {f}: {val} ({status})")
        print(f"   Highlights: {len(data.get('highlights', []))}个")
        results['macro'] = True
    except Exception as e:
        logger.exception(f"❌ 失败: {e}")
        results['macro'] = False
    
    print_section("3. 北向资金数据")
    try:
        data = get_north_flow()
        print(f"✅ 成功")
        print(f"   净流入: {data.get('net_flow')}")
        print(f"   沪股通: {data.get('sh_flow')}")
        print(f"   深股通: {data.get('sz_flow')}")
        print(f"   加仓板块: {len(data.get('top_industries_buy', []))}")
        print(f"   重仓个股: {len(data.get('top_stocks_buy', []))}")
        results['north'] = True
    except Exception as e:
        logger.exception(f"❌ 失败: {e}")
        results['north'] = False
    
    print_section("4. ETF数据")
    try:
        data = get_etf_data()
        print(f"✅ 成功")
        print(f"   宽基ETF: {len(data.get('broad_based', []))}个")
        print(f"   行业ETF: {len(data.get('industry', []))}个")
        for e in data.get('broad_based', [])[:3]:
            print(f"     {e.get('name')}: {e.get('change_pct')}%")
        results['etf'] = True
    except Exception as e:
        logger.exception(f"❌ 失败: {e}")
        results['etf'] = False
    
    print_section("5. 龙头企业数据")
    try:
        data = get_leading_stocks()
        print(f"✅ 成功")
        print(f"   头条: {len(data.get('headlines', []))}个")
        print(f"   重大事件: {len(data.get('major_events', []))}个")
        for h in data.get('headlines', [])[:3]:
            print(f"     {h.get('name')}: {h.get('change_pct')}%")
        results['leading'] = True
    except Exception as e:
        logger.exception(f"❌ 失败: {e}")
        results['leading'] = False
    
    print_section("6. 全球宏观数据")
    try:
        data = get_global_macro()
        print(f"✅ 成功")
        print(f"   原油: {data.get('brent_oil')}")
        print(f"   黄金: {data.get('gold')}")
        print(f"   美元指数: {data.get('usd_index')}")
        print(f"   USD/CNY: {data.get('usd_cny')}")
        results['global'] = True
    except Exception as e:
        logger.exception(f"❌ 失败: {e}")
        results['global'] = False
    
    # 汇总
    print_section("诊断结果汇总", char="#")
    success = sum(1 for v in results.values() if v)
    total = len(results)
    print(f"总模块数: {total}")
    print(f"成功: {success}")
    print(f"失败: {total - success}")
    for name, ok in results.items():
        status = "✅" if ok else "❌"
        print(f"  {status} {name}")
    
    return 0 if success == total else 1


if __name__ == "__main__":
    exit(main())
