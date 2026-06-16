"""
数据质量保障模块测试
"""

import sys
import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "qlib_vnpy_platform"))

from qlib_vnpy_platform.core.data_quality import (
    DataQualityChecker, DataValidator, DataImputer
)


def create_test_data():
    """创建测试数据"""
    dates = pd.date_range(start="2024-01-01", end="2024-12-31", freq="B")
    
    data = {
        "date": dates,
        "open": np.random.uniform(10, 50, len(dates)),
        "high": np.random.uniform(50, 60, len(dates)),
        "low": np.random.uniform(5, 15, len(dates)),
        "close": np.random.uniform(10, 50, len(dates)),
        "volume": np.random.randint(1000000, 10000000, len(dates)),
    }
    
    df = pd.DataFrame(data)
    
    # 确保 high >= low
    df["high"] = df[["open", "close", "high"]].max(axis=1) + np.random.uniform(0, 5, len(df))
    df["low"] = df[["open", "close", "low"]].min(axis=1) - np.random.uniform(0, 5, len(df))
    
    return df


def test_quality_checker():
    """测试数据质量检查器"""
    print("=" * 60)
    print("测试数据质量检查器")
    print("=" * 60)
    
    checker = DataQualityChecker()
    df = create_test_data()
    
    # 测试完整性检查
    result = checker.check_completeness(df, ["date", "close", "volume"])
    print(f"\n✓ 完整性检查: {'通过' if result['passed'] else '失败'}")
    print(f"  - 总行数: {result['total_rows']}")
    print(f"  - 缺失列: {result['missing_columns']}")
    
    # 测试准确性检查
    result = checker.check_accuracy(df)
    print(f"\n✓ 准确性检查: {'通过' if result['passed'] else '失败'}")
    print(f"  - 负数价格: {len(result['negative_prices'])}")
    print(f"  - 零价格: {len(result['zero_prices'])}")
    
    # 测试一致性检查
    result = checker.check_consistency(df)
    print(f"\n✓ 一致性检查: {'通过' if result['passed'] else '失败'}")
    print(f"  - 高低价倒置: {len(result['high_low_inverted'])}")
    
    # 测试时效性检查
    result = checker.check_timeliness(df)
    print(f"\n✓ 时效性检查: {'通过' if result['passed'] else '失败'}")
    print(f"  - 数据陈旧天数: {result['stale_data_days']}")
    
    # 测试重复检查
    result = checker.check_duplicates(df, ["date"])
    print(f"\n✓ 重复检查: {'通过' if result['passed'] else '失败'}")
    print(f"  - 重复记录数: {result['duplicate_count']}")
    
    # 运行完整检查
    print("\n" + "=" * 60)
    print("完整数据质量检查")
    print("=" * 60)
    
    full_result = checker.run_full_check(df, "SZ000001")
    print(f"\n质量评分: {full_result['quality_score']:.1f}/100")
    print(f"总体状态: {'通过' if full_result['overall_passed'] else '失败'}")
    
    if full_result["issues_summary"]:
        print(f"\n发现的问题:")
        for i, issue in enumerate(full_result["issues_summary"][:5], 1):
            print(f"  {i}. {issue}")


def test_data_validator():
    """测试数据验证器"""
    print("\n" + "=" * 60)
    print("测试数据验证器")
    print("=" * 60)
    
    # 测试价格验证
    valid_prices = [12.5, 100.0, 0.01]
    invalid_prices = [-1, 0, 200000]
    
    print("\n价格验证:")
    for price in valid_prices:
        valid, msg = DataValidator.validate_price(price)
        print(f"  {price}: {'✓ 有效' if valid else '✗ 无效'} - {msg or ''}")
    
    for price in invalid_prices:
        valid, msg = DataValidator.validate_price(price)
        print(f"  {price}: {'✓ 有效' if valid else '✗ 无效'} - {msg}")
    
    # 测试成交量验证
    valid_volumes = [100, 1000000, 100000000]
    invalid_volumes = [-100, 2000000000]
    
    print("\n成交量验证:")
    for vol in valid_volumes:
        valid, msg = DataValidator.validate_volume(vol)
        print(f"  {vol}: {'✓ 有效' if valid else '✗ 无效'} - {msg or ''}")
    
    for vol in invalid_volumes:
        valid, msg = DataValidator.validate_volume(vol)
        print(f"  {vol}: {'✓ 有效' if valid else '✗ 无效'} - {msg}")


def test_data_imputer():
    """测试数据填补器"""
    print("\n" + "=" * 60)
    print("测试数据填补器")
    print("=" * 60)
    
    # 创建有缺失值的数据
    df = create_test_data()
    
    # 随机设置一些缺失值
    mask = np.random.random(len(df)) < 0.1
    df_with_na = df.copy()
    for i, row_mask in enumerate(mask):
        if row_mask and i < len(df):
            df_with_na.loc[df_with_na.index[i], "close"] = np.nan
    
    missing_before = df_with_na["close"].isnull().sum()
    print(f"\n填补前缺失值数量: {missing_before}")
    
    # 使用移动平均填补
    df_filled = DataImputer.fill_with_ma(df_with_na, ["close"], window=5)
    missing_after = df_filled["close"].isnull().sum()
    print(f"填补后缺失值数量: {missing_after}")
    
    print(f"\n✓ 填补完成，消除了 {missing_before - missing_after} 个缺失值")


def test_anomaly_detection():
    """测试异常检测"""
    print("\n" + "=" * 60)
    print("测试异常检测")
    print("=" * 60)
    
    checker = DataQualityChecker()
    
    # 创建正常数据
    normal_df = create_test_data()
    
    # 添加异常数据
    anomaly_df = normal_df.copy()
    anomaly_df.loc[50, "high"] = 1000  # 异常高价
    anomaly_df.loc[100, "low"] = -5    # 异常低价
    anomaly_df.loc[150, "volume"] = 0  # 零成交量
    
    # 检查准确性
    result = checker.check_accuracy(anomaly_df)
    print(f"\n异常检测结果:")
    print(f"  - 负数价格: {len(result['negative_prices'])} 个")
    print(f"  - 零价格: {len(result['zero_prices'])} 个")
    
    if result["issues"]:
        print(f"\n发现的问题:")
        for issue in result["issues"]:
            print(f"  • {issue}")


if __name__ == "__main__":
    test_quality_checker()
    test_data_validator()
    test_data_imputer()
    test_anomaly_detection()
    
    print("\n" + "=" * 60)
    print("✅ 所有数据质量测试完成！")
    print("=" * 60)
