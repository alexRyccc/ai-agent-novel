"""front-matter 解析器单测（ARCH §2.2）。

最重要的断言是 **round-trip 恒等**：解析后不经任何修改直接 ``dump()``，
必须与原文**字节相等**。这条同时保证：
  - 不会把 ``key: value`` 写成 ``key: "value"``；
  - 不会重排字段、不会吃掉注释；
  - 行级 patch 的基础是成立的。
"""

from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from sfx import _frontmatter as fm  # noqa: E402

GOOD_SKILL = os.path.join(ROOT, "tests", "testdata", "skills", "order-api", "SKILL.md")
BROKEN_SKILL = os.path.join(ROOT, "tests", "testdata", "skills", "broken-yaml", "SKILL.md")


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


class TestRoundTrip(unittest.TestCase):
    """round-trip 恒等（ARCH §2.2.5 验收断言）。"""

    def test_real_skill_file_is_byte_identical(self) -> None:
        """真实 SKILL.md：``parse(text).dump() == text``。"""
        text = _read(GOOD_SKILL)
        doc = fm.parse_document(text)
        self.assertEqual(doc.dump(), text)

    def test_various_line_endings_and_shapes(self) -> None:
        """LF / CRLF / 无尾换行 / 无 front-matter 四种形态都必须恒等。"""
        samples = [
            "---\nname: a\n---\n正文\n",
            "---\r\nname: a\r\ntags:\r\n  - x\r\n---\r\n正文\r\n",
            "---\nname: a\n---\n正文（无尾换行）",
            "没有 front-matter 的纯 Markdown\n第二行\n",
            "",
            "---\n---\n空 front-matter\n",
            "\ufeff---\nname: 带 BOM\n---\n正文\n",
        ]
        for text in samples:
            with self.subTest(text=text[:24]):
                doc = fm.parse_document(text)
                self.assertEqual(doc.dump(), text)

    def test_comments_and_blank_lines_preserved(self) -> None:
        """注释与空行必须逐字保留。"""
        text = "---\n# 注释一\n\nname: a\n\n# 注释二\nversion: 2\n---\n正文\n"
        doc = fm.parse_document(text)
        self.assertEqual(doc.dump(), text)
        self.assertEqual(doc.fields.get("name"), "a")
        self.assertEqual(doc.fields.get("version"), 2)


class TestSyntaxSubset(unittest.TestCase):
    """语法子集与类型推断（ARCH §2.2.2）。"""

    def test_scalar_types(self) -> None:
        """bool / int / float / 字符串的类型推断。"""
        text = (
            "---\n"
            "enabled: true\n"
            "disabled: no\n"
            "version: 3\n"
            "ratio: 0.35\n"
            "plain: 内部规范\n"
            "single: '单引号'\n"
            "double: \"双引号 \\\"转义\\\"\"\n"
            "with_comment: 值 # 这是行尾注释\n"
            "---\n正文\n"
        )
        doc = fm.parse_document(text)
        self.assertIs(doc.fields["enabled"], True)
        self.assertIs(doc.fields["disabled"], False)
        self.assertEqual(doc.fields["version"], 3)
        self.assertEqual(doc.fields["ratio"], 0.35)
        self.assertEqual(doc.fields["plain"], "内部规范")
        self.assertEqual(doc.fields["single"], "单引号")
        self.assertEqual(doc.fields["double"], '双引号 "转义"')
        self.assertEqual(doc.fields["with_comment"], "值")

    def test_block_list_and_inline_list(self) -> None:
        """块列表与行内列表。"""
        text = "---\ntags:\n  - alpha\n  - beta\nkeys: [x, y]\n---\n正文\n"
        doc = fm.parse_document(text)
        self.assertEqual(doc.fields["tags"], ["alpha", "beta"])
        self.assertEqual(doc.fields["keys"], ["x", "y"])

    def test_nested_mapping(self) -> None:
        """嵌套映射（config.yaml 需要两层以上，见模块 docstring 的扩展说明）。"""
        text = (
            "---\n"
            "engine:\n"
            "  threshold: 0.35\n"
            "  weights:\n"
            "    keyword: 0.4\n"
            "---\n正文\n"
        )
        doc = fm.parse_document(text)
        self.assertEqual(doc.fields["engine"]["threshold"], 0.35)
        self.assertEqual(doc.fields["engine"]["weights"]["keyword"], 0.4)
        # 扁平路径便于配置读取
        self.assertEqual(doc.fields["engine.weights.keyword"], 0.4)


class TestDegradeStrategy(unittest.TestCase):
    """降级策略（ARCH §2.2.3，与 FR-02 对齐）。"""

    def test_block_scalar_degrades_to_raw(self) -> None:
        """块标量 ``|``：合法但超出子集 → 进 ``raw_fields``，不抛异常，继续入库。"""
        doc = fm.parse_document(_read(GOOD_SKILL))
        self.assertTrue(doc.partial, "块标量应把文档标记为 partial")
        self.assertIn("notes", doc.raw_fields)
        self.assertIn("块标量", doc.raw_fields["notes"])
        reasons = [str(item["reason"]) for item in doc.warnings]
        self.assertIn("block_scalar", reasons)
        # 同时验证降级没有影响其它字段
        self.assertEqual(doc.fields["name"], "内部下单接口规范")
        self.assertEqual(doc.fields["version"], 2)

    def test_unsupported_constructs_are_recorded(self) -> None:
        """锚点 / 别名 / 流式映射 / 显式标签 → 记 warning，不抛异常。"""
        text = (
            "---\n"
            "a: &anchor 值\n"
            "b: *anchor\n"
            "c: {x: 1}\n"
            "d: !!str 42\n"
            "---\n正文\n"
        )
        doc = fm.parse_document(text)
        reasons = sorted(str(item["reason"]) for item in doc.warnings)
        self.assertEqual(reasons, ["alias", "anchor", "explicit_tag", "flow_mapping"])
        self.assertTrue(doc.partial)
        self.assertEqual(doc.dump(), text, "降级后仍必须保持 round-trip 恒等")

    def test_structural_error_reports_line_number(self) -> None:
        """结构不可恢复 → 抛 ``FrontMatterError`` 且带 1-based 行号（FR-02）。"""
        with self.assertRaises(fm.FrontMatterError) as ctx:
            fm.parse_document(_read(BROKEN_SKILL))
        self.assertEqual(ctx.exception.line_no, 3)

    def test_top_level_sequence_is_rejected(self) -> None:
        """front-matter 顶层出现列表项 → 结构错误。"""
        with self.assertRaises(fm.FrontMatterError):
            fm.parse_document("---\n- a\n- b\n---\n正文\n")

    def test_bad_indent_is_rejected(self) -> None:
        """缩进无法配对 → 结构错误。"""
        with self.assertRaises(fm.FrontMatterError):
            fm.parse_document("---\nname: a\n    orphan: 1\n---\n正文\n")


class TestLineLevelPatch(unittest.TestCase):
    """行级 patch 回写（ARCH §2.2.5）。"""

    def test_set_value_keeps_style_comments_and_order(self) -> None:
        """改一个字段，只能动那一行：引号风格、注释、字段顺序全部保留。"""
        text = (
            "---\n"
            "# 顶部注释\n"
            "name: '旧名字'\n"
            "version: 2   # 版本号不要乱改\n"
            "enabled: true\n"
            "---\n正文\n"
        )
        doc = fm.parse_document(text)
        doc.set_value("name", "新名字")
        result = doc.dump()
        self.assertEqual(doc.fields["name"], "新名字")
        # 单引号风格保留
        self.assertIn("name: '新名字'", result)
        # 注释、字段顺序、其它行一字不动
        self.assertIn("# 顶部注释", result)
        self.assertIn("version: 2   # 版本号不要乱改", result)
        self.assertIn("enabled: true", result)
        self.assertLess(result.index("name:"), result.index("version:"))
        self.assertLess(result.index("version:"), result.index("enabled:"))

    def test_set_value_on_plain_scalar_stays_plain(self) -> None:
        """原来不带引号，回写后也不得擅自加引号。"""
        doc = fm.parse_document("---\nname: 旧值\n---\n正文\n")
        doc.set_value("name", "新值")
        self.assertIn("name: 新值", doc.dump())
        self.assertNotIn('"', doc.dump())

    def test_append_field_goes_before_closing_fence(self) -> None:
        """新增字段追加到 front-matter 末尾，正文不受影响。"""
        text = "---\nname: a\n---\n正文第一行\n正文第二行\n"
        doc = fm.parse_document(text)
        doc.append_field("summary", "新增摘要")
        result = doc.dump()
        self.assertIn("summary: 新增摘要", result)
        self.assertEqual(result.index("---", 4), result.rindex("---"))
        self.assertTrue(result.endswith("正文第一行\n正文第二行\n"))
        # 追加后仍可继续 patch 已存在的 key
        doc.set_value("name", "b")
        self.assertIn("name: b", doc.dump())

    def test_append_field_creates_fences_when_missing(self) -> None:
        """原本没有 front-matter 时，追加字段会补上一对围栏。"""
        doc = fm.parse_document("纯正文\n")
        doc.append_field("name", "x")
        result = doc.dump()
        self.assertTrue(result.startswith("---\nname: x\n---\n"))
        self.assertTrue(result.endswith("纯正文\n"))


class TestConfigMapping(unittest.TestCase):
    """``config.yaml`` 解析（无围栏的纯映射）。"""

    def test_two_level_nesting(self) -> None:
        """``engine.weights.keyword`` 两层嵌套必须可读（config.yaml 的必需能力）。"""
        text = (
            "version: 1\n"
            "roots:\n"
            "  - ~/.workbuddy/skills\n"
            "  - .cursor/rules\n"
            "engine:\n"
            "  threshold: 0.35\n"
            "  semantic: off\n"
            "  weights:\n"
            "    keyword: 0.40\n"
            "    tag: 0.20\n"
            "    semantic: 0.25\n"
            "    history: 0.00\n"
        )
        data = fm.parse_mapping(text)
        self.assertEqual(data["version"], 1)
        self.assertEqual(data["roots"], ["~/.workbuddy/skills", ".cursor/rules"])
        self.assertEqual(data["engine"]["threshold"], 0.35)
        self.assertEqual(data["engine"]["weights"]["history"], 0.0)

    def test_broken_config_reports_line(self) -> None:
        """坏配置必须报出行号，由调用方转成 ``E_CONFIG``。"""
        with self.assertRaises(fm.FrontMatterError) as ctx:
            fm.parse_mapping("version: 1\n这行没有冒号\n")
        self.assertEqual(ctx.exception.line_no, 2)


if __name__ == "__main__":
    unittest.main()
