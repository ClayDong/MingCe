"""测试工具函数"""
import unittest
import math
from core.utils import safe_float, safe_str, safe_pct, format_pct, format_volume


class TestSafeFloat(unittest.TestCase):
    def test_normal_float(self):
        self.assertEqual(safe_float("3.14"), 3.14)
        self.assertEqual(safe_float(42.0), 42.0)
        self.assertEqual(safe_float("1,234.56"), 1234.56)

    def test_percent_string(self):
        self.assertEqual(safe_float("+5.2%"), 5.2)
        self.assertEqual(safe_float("-3.14%"), -3.14)

    def test_none_and_empty(self):
        self.assertEqual(safe_float(None), 0.0)
        self.assertEqual(safe_float(""), 0.0)
        self.assertEqual(safe_float("-"), 0.0)

    def test_invalid(self):
        self.assertEqual(safe_float("abc"), 0.0)

    def test_custom_default(self):
        self.assertEqual(safe_float(None, default=1.0), 1.0)


class TestSafeStr(unittest.TestCase):
    def test_normal(self):
        self.assertEqual(safe_str(" hello "), "hello")
        self.assertEqual(safe_str("world"), "world")

    def test_none(self):
        self.assertEqual(safe_str(None), "")

    def test_number(self):
        self.assertEqual(safe_str(123), "123")


class TestSafePct(unittest.TestCase):
    def test_normal(self):
        self.assertEqual(safe_pct(3.14), 3.14)
        self.assertEqual(safe_pct(-2.5), -2.5)

    def test_nan_and_inf(self):
        self.assertEqual(safe_pct(float("nan")), 0.0)
        self.assertEqual(safe_pct(float("inf")), 0.0)

    def test_none(self):
        self.assertEqual(safe_pct(None), 0.0)

    def test_string(self):
        self.assertEqual(safe_pct("5.2"), 5.2)

    def test_invalid(self):
        self.assertEqual(safe_pct("abc"), 0.0)


class TestFormatPct(unittest.TestCase):
    def test_positive(self):
        self.assertEqual(format_pct(3.14), "+3.14%")

    def test_negative(self):
        self.assertEqual(format_pct(-2.5), "-2.50%")

    def test_zero(self):
        self.assertEqual(format_pct(0), "0.00%")

    def test_nan(self):
        self.assertEqual(format_pct(float("nan")), "0.00%")


class TestFormatVolume(unittest.TestCase):
    def test_billion(self):
        self.assertEqual(format_volume(1.5e8), "2亿")

    def test_wan(self):
        self.assertEqual(format_volume(50000), "5万")

    def test_small(self):
        self.assertEqual(format_volume(999), "999")

    def test_nan(self):
        self.assertEqual(format_volume(float("nan")), "0")


if __name__ == "__main__":
    unittest.main()
