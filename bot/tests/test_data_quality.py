"""数据质量保障模块测试"""
import unittest
import numpy as np
from datetime import datetime

from core.data_quality import (
    DataQualityValidator, DataSourceMonitor, DataQualityMetrics,
    DataQualityReport, DataQualityLevel, DataSourceHealth,
    get_validator, get_monitor, generate_quality_report
)


class TestDataQualityValidator(unittest.TestCase):
    """数据质量验证器测试"""
    
    def setUp(self):
        self.validator = DataQualityValidator()
    
    def test_validate_index_value_normal(self):
        """测试正常的指数值验证"""
        is_valid, issues = self.validator.validate_index_value(3200.0, "上证指数")
        self.assertTrue(is_valid)
        self.assertEqual(len(issues), 0)
    
    def test_validate_index_value_none(self):
        """测试空值验证"""
        is_valid, issues = self.validator.validate_index_value(None, "上证指数")
        self.assertFalse(is_valid)
        self.assertGreater(len(issues), 0)
    
    def test_validate_index_value_nan(self):
        """测试NaN值验证"""
        is_valid, issues = self.validator.validate_index_value(np.nan, "上证指数")
        self.assertFalse(is_valid)
        self.assertGreater(len(issues), 0)
    
    def test_validate_index_value_too_small(self):
        """测试过小的指数值验证"""
        is_valid, issues = self.validator.validate_index_value(10.0, "上证指数")
        self.assertFalse(is_valid)
        self.assertGreater(len(issues), 0)
    
    def test_validate_index_value_out_of_range(self):
        """测试超出历史范围的指数值"""
        is_valid, issues = self.validator.validate_index_value(6000.0, "上证指数")
        self.assertTrue(is_valid)  # 仍然认为有效，但给出警告
        self.assertGreater(len(issues), 0)
    
    def test_validate_change_pct_normal(self):
        """测试正常的涨跌幅验证"""
        is_valid, issues = self.validator.validate_change_pct(2.5, "上证指数")
        self.assertTrue(is_valid)
        self.assertEqual(len(issues), 0)
    
    def test_validate_change_pct_extreme(self):
        """测试极端涨跌幅验证"""
        is_valid, issues = self.validator.validate_change_pct(25.0, "上证指数")
        self.assertTrue(is_valid)
        self.assertGreater(len(issues), 0)
    
    def test_validate_change_pct_none(self):
        """测试空涨跌幅验证"""
        is_valid, issues = self.validator.validate_change_pct(None, "上证指数")
        self.assertTrue(is_valid)  # None视为有效（可选字段）
    
    def test_validate_volume_normal(self):
        """测试正常的成交额验证"""
        is_valid, issues = self.validator.validate_volume(5000.0, "上证指数")
        self.assertTrue(is_valid)
        self.assertEqual(len(issues), 0)
    
    def test_validate_volume_negative(self):
        """测试负成交额验证"""
        is_valid, issues = self.validator.validate_volume(-100.0, "上证指数")
        self.assertFalse(is_valid)
        self.assertGreater(len(issues), 0)
    
    def test_validate_north_flow_normal(self):
        """测试正常的北向资金验证"""
        is_valid, issues = self.validator.validate_north_flow(50.0, 30.0, 20.0)
        self.assertTrue(is_valid)
        self.assertEqual(len(issues), 0)
    
    def test_validate_north_flow_inconsistent(self):
        """测试不一致的北向资金验证"""
        is_valid, issues = self.validator.validate_north_flow(60.0, 30.0, 20.0)
        self.assertTrue(is_valid)
        self.assertGreater(len(issues), 0)
    
    def test_validate_north_flow_extreme(self):
        """测试极端北向资金验证"""
        is_valid, issues = self.validator.validate_north_flow(350.0, 200.0, 150.0)
        self.assertTrue(is_valid)
        self.assertGreater(len(issues), 0)
    
    def test_check_data_completeness_full(self):
        """测试完全完整的数据完整性检查"""
        data = {"a": 1, "b": 2, "c": 3}
        required = ["a", "b", "c"]
        completeness, missing = self.validator.check_data_completeness(data, required)
        self.assertEqual(completeness, 1.0)
        self.assertEqual(len(missing), 0)
    
    def test_check_data_completeness_partial(self):
        """测试部分完整的数据完整性检查"""
        data = {"a": 1, "c": 3}
        required = ["a", "b", "c"]
        completeness, missing = self.validator.check_data_completeness(data, required)
        self.assertAlmostEqual(completeness, 0.666, places=2)
        self.assertEqual(len(missing), 1)
    
    def test_validate_historical_consistency(self):
        """测试历史一致性验证"""
        # 第一次验证，没有历史数据
        is_valid, issues = self.validator.validate_historical_consistency("测试指数", 3200.0, 1.0)
        self.assertTrue(is_valid)
        
        # 添加一些历史数据
        for _ in range(5):
            self.validator.validate_historical_consistency("测试指数", 3200.0, 0.5)
        
        # 验证异常值
        is_valid, issues = self.validator.validate_historical_consistency("测试指数", 5000.0, 10.0)
        self.assertTrue(is_valid)
        self.assertGreater(len(issues), 0)


class TestDataSourceMonitor(unittest.TestCase):
    """数据源监控器测试"""
    
    def setUp(self):
        self.monitor = DataSourceMonitor()
    
    def test_record_success(self):
        """测试记录成功"""
        self.monitor.record_success("test_source")
        stats = self.monitor.source_stats["test_source"]
        self.assertEqual(stats["success_count"], 1)
        self.assertEqual(stats["consecutive_failures"], 0)
    
    def test_record_failure(self):
        """测试记录失败"""
        self.monitor.record_failure("test_source", "test error")
        stats = self.monitor.source_stats["test_source"]
        self.assertEqual(stats["failure_count"], 1)
        self.assertEqual(stats["consecutive_failures"], 1)
        self.assertEqual(stats["last_error"], "test error")
    
    def test_get_health_unknown(self):
        """测试获取未知数据源健康状态"""
        health = self.monitor.get_health("unknown_source")
        self.assertEqual(health, DataSourceHealth.UNKNOWN)
    
    def test_get_health_healthy(self):
        """测试获取健康的数据源状态"""
        self.monitor.record_success("healthy_source")
        health = self.monitor.get_health("healthy_source")
        self.assertEqual(health, DataSourceHealth.HEALTHY)
    
    def test_get_health_degraded(self):
        """测试获取降级的数据源状态"""
        for _ in range(3):
            self.monitor.record_success("degraded_source")
        for _ in range(2):
            self.monitor.record_failure("degraded_source", "error")
        health = self.monitor.get_health("degraded_source")
        self.assertEqual(health, DataSourceHealth.DEGRADED)
    
    def test_get_health_failed(self):
        """测试获取失败的数据源状态"""
        for _ in range(4):
            self.monitor.record_failure("failed_source", "error")
        health = self.monitor.get_health("failed_source")
        self.assertEqual(health, DataSourceHealth.FAILED)
    
    def test_should_skip(self):
        """测试是否应该跳过数据源"""
        self.assertFalse(self.monitor.should_skip("new_source"))
        
        for _ in range(4):
            self.monitor.record_failure("failed_source", "error")
        self.assertTrue(self.monitor.should_skip("failed_source"))
    
    def test_reset(self):
        """测试重置监控"""
        self.monitor.record_success("test_source")
        self.monitor.record_failure("test_source", "error")
        self.monitor.reset("test_source")
        
        stats = self.monitor.source_stats["test_source"]
        self.assertEqual(stats["success_count"], 0)
        self.assertEqual(stats["failure_count"], 0)


class TestDataQualityMetrics(unittest.TestCase):
    """数据质量指标测试"""
    
    def test_default_metrics(self):
        """测试默认指标"""
        metrics = DataQualityMetrics()
        self.assertEqual(metrics.completeness, 1.0)
        self.assertEqual(metrics.accuracy, 1.0)
        self.assertEqual(metrics.consistency, 1.0)
        self.assertEqual(metrics.timeliness, 1.0)
        self.assertEqual(metrics.validity, 1.0)
    
    def test_overall_score(self):
        """测试综合评分计算"""
        metrics = DataQualityMetrics(
            completeness=0.9,
            accuracy=0.8,
            consistency=0.7,
            timeliness=0.6,
            validity=0.5
        )
        expected_score = (0.9 * 0.25 + 0.8 * 0.25 + 0.7 * 0.2 + 0.6 * 0.15 + 0.5 * 0.15)
        self.assertAlmostEqual(metrics.overall_score, expected_score, places=4)
    
    def test_level_excellent(self):
        """测试优秀等级"""
        metrics = DataQualityMetrics(
            completeness=0.98,
            accuracy=0.98,
            consistency=0.98,
            timeliness=0.98,
            validity=0.98
        )
        self.assertEqual(metrics.level, DataQualityLevel.EXCELLENT)
    
    def test_level_warning(self):
        """测试警告等级"""
        metrics = DataQualityMetrics(
            completeness=0.6,
            accuracy=0.6,
            consistency=0.6,
            timeliness=0.6,
            validity=0.6
        )
        self.assertEqual(metrics.level, DataQualityLevel.WARNING)
    
    def test_level_critical(self):
        """测试严重等级"""
        metrics = DataQualityMetrics(
            completeness=0.3,
            accuracy=0.3,
            consistency=0.3,
            timeliness=0.3,
            validity=0.3
        )
        self.assertEqual(metrics.level, DataQualityLevel.CRITICAL)


class TestDataQualityReport(unittest.TestCase):
    """数据质量报告测试"""
    
    def test_create_report(self):
        """测试创建报告"""
        report = DataQualityReport(
            module_name="test_module",
            issues=["test issue"],
            recommendations=["test recommendation"]
        )
        self.assertEqual(report.module_name, "test_module")
        self.assertEqual(len(report.issues), 1)
        self.assertEqual(len(report.recommendations), 1)
    
    def test_to_dict(self):
        """测试转换为字典"""
        report = DataQualityReport(
            module_name="test_module",
            issues=["test issue"]
        )
        report_dict = report.to_dict()
        self.assertIn("module_name", report_dict)
        self.assertIn("timestamp", report_dict)
        self.assertIn("metrics", report_dict)
        self.assertIn("issues", report_dict)


class TestGlobalInstances(unittest.TestCase):
    """全局单例测试"""
    
    def test_get_validator(self):
        """测试获取验证器"""
        validator1 = get_validator()
        validator2 = get_validator()
        self.assertIs(validator1, validator2)
    
    def test_get_monitor(self):
        """测试获取监控器"""
        monitor1 = get_monitor()
        monitor2 = get_monitor()
        self.assertIs(monitor1, monitor2)
    
    def test_generate_quality_report(self):
        """测试生成质量报告"""
        report = generate_quality_report("test_module", {}, [])
        self.assertIsInstance(report, DataQualityReport)
        self.assertEqual(report.module_name, "test_module")
        self.assertEqual(report.metrics.level, DataQualityLevel.EXCELLENT)
    
    def test_generate_quality_report_with_issues(self):
        """测试带问题的质量报告生成"""
        report = generate_quality_report("test_module", {}, ["问题1", "问题2"])
        self.assertEqual(len(report.issues), 2)
        self.assertLess(report.metrics.overall_score, 1.0)


if __name__ == "__main__":
    unittest.main()
