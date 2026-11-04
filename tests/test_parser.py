"""SKILL.md 解析单测（ARCH WS-2 W2-2 / §12.6.2.1 C-2）。

重点验证 **C-2**：``summary`` 必须被抽取，且**缺失时有兜底**
（取 ``description`` 前 40 字 + ``元数据待补全`` 标记、``summary_fallback=True``）。
这条如果不做，Tier B 阶段要回头改 parser 并重扫全部 skill。
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from sfx.core.service import parser as skill_parser  # noqa: E402

NOW = "2026-10-29T11:35:22Z"


def _write(directory: str, name: str, content: str) -> str:
    path = os.path.join(directory, name)
    os.makedirs(path, exist_ok=True)
    entry = os.path.join(path, "SKILL.md")
    with open(entry, "w", encoding="utf-8") as handle:
        handle.write(content)
    return entry


class TestSummaryExtraction(unittest.TestCase):
    """C-2：summary 抽取与缺失兜底。"""

    def test_explicit_summary_is_used(self) -> None:
        """front-matter 里写了 summary 就直接用，且 ``summary_fallback=False``。"""
        with tempfile.TemporaryDirectory() as tmp:
            entry = _write(
                tmp, "with-summary",
                "---\nname: A\ndescription: 描述\nsummary: 明确摘要\n---\n正文\n",
            )
            skill, warnings = skill_parser.parse_skill_file(entry, tmp, NOW)
        self.assertEqual(skill.summary, "明确摘要")
        self.assertFalse(skill.summary_fallback)
        self.assertEqual(warnings, [])

    def test_missing_summary_falls_back_to_description(self) -> None:
        """缺 summary → 取 description 前 40 字 + ``元数据待补全`` + ``summary_fallback=True``。"""
        long_description = "内部下单接口的字段命名与错误码规范，适用于所有写接口与读接口"
        with tempfile.TemporaryDirectory() as tmp:
            entry = _write(
                tmp, "no-summary",
                f"---\nname: A\ndescription: {long_description}\n---\n正文\n",
            )
            skill, warnings = skill_parser.parse_skill_file(entry, tmp, NOW)
        self.assertTrue(skill.summary_fallback)
        self.assertIn("元数据待补全", skill.summary)
        self.assertTrue(skill.summary.startswith(long_description[:40]))
        reasons = [str(item["reason"]) for item in warnings]
        self.assertIn("summary_missing_fallback", reasons)

    def test_fallback_uses_name_when_no_description(self) -> None:
        """连 description 都没有时，用 name 兜底，不能产出空摘要。"""
        with tempfile.TemporaryDirectory() as tmp:
            entry = _write(tmp, "bare", "---\nname: 光秃秃的技能\n---\n正文\n")
            skill, _ = skill_parser.parse_skill_file(entry, tmp, NOW)
        self.assertTrue(skill.summary_fallback)
        self.assertIn("光秃秃的技能", skill.summary)
        self.assertIn("元数据待补全", skill.summary)

    def test_no_frontmatter_at_all(self) -> None:
        """完全没有 front-matter 也必须入库（summary 走兜底）。"""
        with tempfile.TemporaryDirectory() as tmp:
            entry = _write(tmp, "plain", "# 纯 Markdown\n\n没有元数据\n")
            skill, _ = skill_parser.parse_skill_file(entry, tmp, NOW)
        self.assertEqual(skill.name, "plain")  # 回退到目录名
        self.assertTrue(skill.summary_fallback)


class TestMetadataExtraction(unittest.TestCase):
    """元数据抽取。"""

    def test_triggers_and_tags(self) -> None:
        """触发词来自 triggers / keywords，并自动包含 skill 名。"""
        with tempfile.TemporaryDirectory() as tmp:
            entry = _write(
                tmp, "meta",
                "---\n"
                "name: 重构助手\n"
                "description: d\n"
                "summary: s\n"
                "triggers:\n  - 重构\n  - refactor\n"
                "keywords: [代码整理]\n"
                "tags:\n  - 后端\n"
                "version: 3\n"
                "author: someone\n"
                "---\n正文\n",
            )
            skill, _ = skill_parser.parse_skill_file(entry, tmp, NOW)
        self.assertIn("重构", skill.triggers)
        self.assertIn("refactor", skill.triggers)
        self.assertIn("代码整理", skill.triggers)
        self.assertIn("重构助手", skill.triggers)
        self.assertEqual(skill.tags, ("后端",))
        self.assertEqual(skill.version, 3)
        self.assertEqual(skill.author, "someone")

    def test_content_hash_and_size(self) -> None:
        """内容 hash 与字节数用于增量判定。"""
        with tempfile.TemporaryDirectory() as tmp:
            entry = _write(tmp, "h", "---\nname: H\n---\n正文内容\n")
            first, _ = skill_parser.parse_skill_file(entry, tmp, NOW)
            with open(entry, "a", encoding="utf-8") as handle:
                handle.write("追加一行\n")
            second, _ = skill_parser.parse_skill_file(entry, tmp, NOW)
            self.assertNotEqual(first.content_hash, second.content_hash)
            # body_bytes 必须是**文件真实字节数**（Windows 上可能含 CRLF，不能按字符数算）
            self.assertEqual(second.body_bytes, os.path.getsize(entry))
            self.assertGreater(second.body_bytes, first.body_bytes)

    def test_slug_is_generated(self) -> None:
        """中文名也能生成非空 slug。"""
        with tempfile.TemporaryDirectory() as tmp:
            entry = _write(tmp, "slug", "---\nname: 内部规范 Checker\n---\n正文\n")
            skill, _ = skill_parser.parse_skill_file(entry, tmp, NOW)
        self.assertTrue(skill.slug)
        self.assertNotIn(skill.slug, (".", ".."))

    def test_broken_yaml_raises_parse_error_with_line(self) -> None:
        """结构不可恢复 → ``ParseError`` 带行号（由 scanner 转为 skip）。"""
        with tempfile.TemporaryDirectory() as tmp:
            entry = _write(tmp, "bad", "---\nname: X\n这行没有冒号\n---\n正文\n")
            with self.assertRaises(skill_parser.ParseError) as ctx:
                skill_parser.parse_skill_file(entry, tmp, NOW)
        self.assertEqual(ctx.exception.line_no, 3)

    def test_block_scalar_degrades_not_raises(self) -> None:
        """块标量是"合法但超出子集" → 继续入库，不抛异常（§2.2.3）。"""
        with tempfile.TemporaryDirectory() as tmp:
            entry = _write(
                tmp, "blockscalar",
                "---\nname: B\ndescription: d\nsummary: s\nnotes: |\n  第一行\n  第二行\n---\n正文\n",
            )
            skill, warnings = skill_parser.parse_skill_file(entry, tmp, NOW)
        self.assertEqual(skill.name, "B")
        self.assertTrue(any(str(item["reason"]) == "block_scalar" for item in warnings))


class TestScannerIntegration(unittest.TestCase):
    """scanner 行为（目录不存在 / 去重 / 坏文件跳过）。"""

    def test_iter_skips_missing_and_noise_dirs(self) -> None:
        """不存在/不可读的目录静默跳过；噪音目录不下钻。"""
        from sfx.core.service import scanner

        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "node_modules", "x"), exist_ok=True)
            _write(os.path.join(tmp, "node_modules", "x"), "SKILL.md", "---\nname: N\n---\n正文\n")
            good = _write(tmp, "good", "---\nname: G\n---\n正文\n")
            found = scanner.iter_skill_dirs(tmp, 6)
        self.assertEqual(found, [good])

    def test_root_itself_can_be_a_skill(self) -> None:
        """来源根自身含 SKILL.md 时也应被识别。"""
        from sfx.core.service import scanner

        with tempfile.TemporaryDirectory() as tmp:
            entry = os.path.join(tmp, "SKILL.md")
            with open(entry, "w", encoding="utf-8") as handle:
                handle.write("---\nname: R\n---\n正文\n")
            found = scanner.iter_skill_dirs(tmp, 6)
        self.assertEqual(len(found), 1)


if __name__ == "__main__":
    unittest.main()
