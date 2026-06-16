"""独立测试运行器 — 运行所有测试。"""
import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import unittest, tempfile

os.environ['CACHE_DIR'] = tempfile.mkdtemp()
os.environ['SQLITE_DB_PATH'] = os.environ['CACHE_DIR'] + '/test.db'
os.environ['DEBUG'] = 'true'

from tests.test_utils import TestSafeFloat, TestSafeStr, TestSafePct, TestFormatPct, TestFormatVolume
from tests.test_schemas import TestIndexData, TestMarketOverview, TestDailyReportData, TestAlertItem, TestIsTradingDay, TestBuildMarketSummary
from tests.test_cache import TestFileCache
from tests.test_llm import TestCleanResponse
from tests.test_feishu import TestFmtPct, TestTruncate, TestChatIdValid, TestBuildSummaryCard, TestBuildDetailCard, TestBuildAlertCard, TestDetectAlerts

loader = unittest.TestLoader()
suite = unittest.TestSuite()
for tc in [TestSafeFloat, TestSafeStr, TestSafePct, TestFormatPct, TestFormatVolume,
           TestIndexData, TestMarketOverview, TestDailyReportData, TestAlertItem, TestIsTradingDay, TestBuildMarketSummary,
           TestFileCache, TestCleanResponse,
           TestFmtPct, TestTruncate, TestChatIdValid, TestBuildSummaryCard, TestBuildDetailCard, TestBuildAlertCard, TestDetectAlerts]:
    suite.addTests(loader.loadTestsFromTestCase(tc))

runner = unittest.TextTestRunner(verbosity=2)
result = runner.run(suite)
print(f"\n{'='*50}\nTotal: {result.testsRun}, Failures: {len(result.failures)}, Errors: {len(result.errors)}")
sys.exit(0 if result.wasSuccessful() else 1)
