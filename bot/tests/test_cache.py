"""测试缓存模块（使用 unittest，与其他测试保持一致）。"""
import unittest
import tempfile
import os
from core.cache import FileCache


class TestFileCache(unittest.TestCase):
    """FileCache 单元测试。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.cache = FileCache(cache_dir=self.tmpdir, ttl_seconds=3600)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_set_and_get(self):
        self.cache.set("test_key", {"value": 42})
        result = self.cache.get("test_key")
        self.assertEqual(result, {"value": 42})

    def test_get_missing(self):
        result = self.cache.get("nonexistent")
        self.assertIsNone(result)

    def test_get_expired(self):
        self.cache.ttl_seconds = -1
        self.cache.set("test_key", "hello")
        result = self.cache.get("test_key")
        self.assertIsNone(result)

    def test_clear_single_key(self):
        self.cache.set("key1", 1)
        self.cache.set("key2", 2)
        self.cache.clear("key1")
        self.assertIsNone(self.cache.get("key1"))
        self.assertEqual(self.cache.get("key2"), 2)

    def test_clear_all(self):
        self.cache.set("key1", 1)
        self.cache.set("key2", 2)
        self.cache.clear()
        self.assertIsNone(self.cache.get("key1"))
        self.assertIsNone(self.cache.get("key2"))

    def test_empty_value_stored(self):
        """空列表也应被缓存。"""
        self.cache.set("empty_list", [])
        result = self.cache.get("empty_list")
        self.assertIsNotNone(result)
        self.assertEqual(result, [])

    def test_clean_expired(self):
        self.cache.set("old_key", "old_value")
        # 设置一个过期的缓存
        old_cache = FileCache(cache_dir=self.tmpdir, ttl_seconds=-1)
        old_cache.set("old_key2", "old_value2")

        cleaned = self.cache.clean_expired(max_age_hours=0)
        self.assertGreaterEqual(cleaned, 1)


if __name__ == "__main__":
    unittest.main()
