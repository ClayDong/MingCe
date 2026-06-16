#!/usr/bin/env python3
"""
策略可视化分析报告生成器
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
import numpy as np
from datetime import datetime
from qlib_vnpy_platform.core.strategies import list_strategies, get_strategy

def generate_comprehensive_report():
    """生成综合分析报告"""
    print("\n" + "="*80)
    print("🎯 QLib+VNPY 量化交易平台 - 策略综合分析报告")
    print("="*80)
    
    print(f"\n📅 报告生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    all_strategies = list_strategies()
    
    print(f"\n📊 策略库概览")
    print(f"   总策略数量: {len(all_strategies)}")
    
    categories = {
        '职业操盘手策略': [],
        '技术指标策略': [],
        '趋势跟踪策略': [],
        '均值回归策略': [],
        '波动率策略': []
    }
    
    for strat in all_strategies:
        name = strat['name']
        key = strat['key']
        
        if key in ['sentiment_cycle', 'sector_rotation', 'prosperity', 'band_operation', 
                   'value_investment', 'dragon_head']:
            categories['职业操盘手策略'].append(name)
        elif key in ['ma_cross', 'rsi', 'macd', 'kdj', 'ma_alignment']:
            categories['技术指标策略'].append(name)
        elif key in ['momentum', 'trend_following', 'turtle']:
            categories['趋势跟踪策略'].append(name)
        elif key in ['bollinger', 'volatility_breakout', 'mean_reversion']:
            categories['均值回归策略'].append(name)
        else:
            categories['波动率策略'].append(name)
    
    print(f"\n📈 策略分类:")
    for category, strategies in categories.items():
        if strategies:
            print(f"\n   🔹 {category} ({len(strategies)}个):")
            for strat in strategies:
                print(f"      • {strat}")
    
    print(f"\n{'='*80}")
    print("📋 职业操盘手核心策略详解")
    print('='*80)
    
    pro_strategies = [
        {
            'name': '情绪周期策略',
            'key': 'sentiment_cycle',
            'category': '游资策略',
            'principle': '根据市场情绪周期进行交易',
            'buy_condition': '情绪冰点（恐惧）',
            'sell_condition': '情绪高潮（贪婪）',
            'risk_level': '⭐⭐⭐⭐',
            'suitable_market': '短线交易、波动市'
        },
        {
            'name': '行业轮动策略',
            'key': 'sector_rotation',
            'category': '机构策略',
            'principle': '模拟行业轮动周期',
            'buy_condition': '低估值 + 动量启动',
            'sell_condition': '估值偏高或动量衰竭',
            'risk_level': '⭐⭐⭐',
            'suitable_market': '行业轮动行情、中线'
        },
        {
            'name': '景气度投资策略',
            'key': 'prosperity',
            'category': '私募策略',
            'principle': '投资于高景气行业',
            'buy_condition': '行业高增长 + 订单饱满',
            'sell_condition': '景气度下降',
            'risk_level': '⭐⭐⭐',
            'suitable_market': '成长股、中线布局'
        },
        {
            'name': '波段操作策略',
            'key': 'band_operation',
            'category': '私募策略',
            'principle': '低吸高抛，回调买突破卖',
            'buy_condition': '价格触及波段低点',
            'sell_condition': '价格触及波段高点',
            'risk_level': '⭐⭐',
            'suitable_market': '震荡市、中线波段'
        },
        {
            'name': '价值投资策略',
            'key': 'value_investment',
            'category': '机构策略',
            'principle': '长期持有优质股票',
            'buy_condition': 'ROE高 + 分红稳定 + 低估值',
            'sell_condition': '基本面恶化或估值过高',
            'risk_level': '⭐',
            'suitable_market': '长线投资、稳健型'
        },
        {
            'name': '龙头战法',
            'key': 'dragon_head',
            'category': '游资策略',
            'principle': '只做最强龙头',
            'buy_condition': '涨停突破确认',
            'sell_condition': '快进快出，不隔夜',
            'risk_level': '⭐⭐⭐⭐⭐',
            'suitable_market': '热点题材、短线暴利'
        }
    ]
    
    for strat in pro_strategies:
        print(f"\n🔸 {strat['name']} ({strat['category']})")
        print(f"   核心理念: {strat['principle']}")
        print(f"   买入条件: {strat['buy_condition']}")
        print(f"   卖出条件: {strat['sell_condition']}")
        print(f"   风险等级: {strat['risk_level']}")
        print(f"   适用市场: {strat['suitable_market']}")
    
    print(f"\n{'='*80}")
    print("💡 策略选择建议")
    print('='*80)
    
    recommendations = [
        {
            'style': '稳健型投资者',
            'recommendation': '价值投资(50%) + 波段操作(30%) + 现金(20%)',
            'expected_return': '8-12%/年',
            'risk': '低',
            'strategies': ['value_investment', 'band_operation']
        },
        {
            'style': '平衡型投资者',
            'recommendation': '景气度投资(30%) + 行业轮动(25%) + 波段操作(20%) + 现金(25%)',
            'expected_return': '12-20%/年',
            'risk': '中',
            'strategies': ['prosperity', 'sector_rotation', 'band_operation']
        },
        {
            'style': '激进型投资者',
            'recommendation': '龙头战法(10%) + 情绪周期(20%) + 动量策略(30%) + 现金(40%)',
            'expected_return': '20-50%/年',
            'risk': '高',
            'strategies': ['dragon_head', 'sentiment_cycle', 'momentum']
        }
    ]
    
    for rec in recommendations:
        print(f"\n🎯 {rec['style']}")
        print(f"   推荐配置: {rec['recommendation']}")
        print(f"   预期收益: {rec['expected_return']}")
        print(f"   风险等级: {rec['risk']}")
    
    print(f"\n{'='*80}")
    print("⚠️ 风险控制要点")
    print('='*80)
    
    risk_controls = [
        '永远不满仓、不加杠杆',
        '单只股票不超过总资金 10%',
        '止损必须执行：10%-20% 无条件砍',
        '不追高、不炒题材、不赌消息',
        '不频繁交易、一年操作不超过 10 次',
        '预留 10%-20% 现金仓位',
        '根据市场环境调整策略配置'
    ]
    
    for i, control in enumerate(risk_controls, 1):
        print(f"   {i}. {control}")
    
    print(f"\n{'='*80}")
    print("📚 策略学习路径")
    print('='*80)
    
    learning_path = [
        ('基础阶段', 'MA交叉、RSI、MACD', '1-2周'),
        ('进阶阶段', '布林带、动量、波段操作', '2-4周'),
        ('高级阶段', '行业轮动、景气度投资', '1-2个月'),
        ('大师阶段', '情绪周期、龙头战法、价值投资', '3-6个月')
    ]
    
    for stage, strategies, time in learning_path:
        print(f"   📖 {stage}: {strategies} (预计时间: {time})")
    
    print(f"\n{'='*80}")
    print("🚀 下一步行动计划")
    print('='*80)
    
    actions = [
        '1. 使用真实数据进行回测验证',
        '2. 根据回测结果优化策略参数',
        '3. 在模拟环境中进行实盘测试',
        '4. 逐步实盘，从小仓位开始',
        '5. 记录交易日志，定期复盘',
        '6. 根据市场反馈持续优化策略'
    ]
    
    for action in actions:
        print(f"   ✅ {action}")
    
    print(f"\n{'='*80}")
    print("📞 技术支持")
    print('='*80)
    
    print(f"   • 回测脚本: backtest_pro_strategies.py")
    print(f"   • 参数优化: optimize_strategy_params.py")
    print(f"   • 实盘模拟: simulated_trading.py")
    print(f"   • 策略测试: test_pro_trategies.py")
    print(f"   • Web API: http://localhost:5000")
    
    print(f"\n{'='*80}")
    print("✅ 报告生成完成")
    print('='*80)
    print(f"\n📁 相关文件位置:")
    print(f"   • 策略代码: qlib_vnpy_platform/core/strategies.py")
    print(f"   • 回测脚本: backtest_pro_strategies.py")
    print(f"   • 优化脚本: optimize_strategy_params.py")
    print(f"   • 模拟系统: simulated_trading.py")
    print(f"   • 使用指南: 职业操盘手策略使用指南.md")
    
    return all_strategies

if __name__ == "__main__":
    strategies = generate_comprehensive_report()
    print(f"\n📊 当前平台共有 {len(strategies)} 个策略")
