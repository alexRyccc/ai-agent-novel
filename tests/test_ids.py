"""手写 UUIDv7 与 FNV-1a 单测（ARCH §2.1 / §10.5）。

UUIDv7 的关键性质是**时间有序**：按字符串字典序排序 == 按生成时间排序。
这条性质是索引与游标分页的基础，必须用测试钉住。
"""

from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from sfx import _ids  # noqa: E402


class TestUuid7(unittest.TestCase):
    """UUIDv7。"""

    def test_format(self) -> None:
        """标准 8-4-4-4-12 形式，全小写十六进制。"""
        value = _ids.uuid7()
        self.assertEqual(len(value), 36)
        parts = value.split("-")
        self.assertEqual([len(part) for part in parts], [8, 4, 4, 4, 12])
        for part in parts:
            self.assertTrue(all(ch in "0123456789abcdef" for ch in part))

    def test_version_and_variant_nibbles(self) -> None:
        """第 13 个十六进制字符必须是 ``7``（version），第 17 个必须是 8/9/a/b（variant）。"""
        for _ in range(50):
            value = _ids.uuid7()
            self.assertEqual(value[14], "7")
            self.assertIn(value[19], "89ab")

    def test_time_ordering(self) -> None:
        """连续生成的 id 按字典序递增（时间有序性）。"""
        values = [_ids.uuid7() for _ in range(500)]
        self.assertEqual(values, sorted(values))

    def test_uniqueness(self) -> None:
        """同一毫秒内也不重复（随机数部分足够宽）。"""
        values = {_ids.uuid7() for _ in range(2000)}
        self.assertEqual(len(values), 2000)

    def test_high_bits_carry_unix_ms(self) -> None:
        """高 48 bit 必须是当前的 Unix 毫秒时间戳（误差 < 5s）。"""
        import time

        value = _ids.uuid7()
        embedded = int(value.replace("-", "")[:12], 16)
        now_ms = time.time_ns() // 1_000_000
        self.assertLess(abs(embedded - now_ms), 5000)


class TestFnv1a(unittest.TestCase):
    """FNV-1a 摘要（用于 ``sessions.task_hash``）。"""

    def test_deterministic_across_calls(self) -> None:
        """同一输入恒定同一输出（跨进程稳定，不能用内置 ``hash()``）。"""
        self.assertEqual(_ids.fnv1a_hex("内部下单接口规范"), _ids.fnv1a_hex("内部下单接口规范"))

    def test_different_inputs_differ(self) -> None:
        """不同输入应产生不同摘要（至少对常见短文本）。"""
        self.assertNotEqual(_ids.fnv1a_hex("重构数据库"), _ids.fnv1a_hex("重构数据库访问层"))
        self.assertNotEqual(_ids.fnv1a_hex("a"), _ids.fnv1a_hex("b"))

    def test_shape(self) -> None:
        """8 位小写十六进制。"""
        value = _ids.fnv1a_hex("")
        self.assertEqual(len(value), 8)
        self.assertTrue(all(ch in "0123456789abcdef" for ch in value))


if __name__ == "__main__":
    unittest.main()
