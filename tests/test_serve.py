"""``sfx serve`` 渲染层测试（只测与安全相关的契约，不做 DOM 断言）。

这里守的是一条**输入可控**的边界：技能摘要来自团队提交的 SKILL.md，
属于不受信任内容。它被内联进 ``<script>`` 时若原样保留 ``<``，
一个 ``</script>`` 就能截断脚本块、白屏，甚至注入任意 JS。
"""

from __future__ import annotations

import unittest

from sfx.cli import cmd_serve

MALICIOUS = '正常摘要</script><img src=x onerror="alert(1)">'


class TestInlineJson(unittest.TestCase):
    def test_escapes_left_angle(self):
        out = cmd_serve._inline_json({"s": MALICIOUS})
        self.assertNotIn("<", out)
        self.assertIn("\\u003c", out)

    def test_roundtrip_preserves_value(self):
        import json

        payload = {"s": MALICIOUS, "n": 3, "zh": "中文"}
        self.assertEqual(json.loads(cmd_serve._inline_json(payload)), payload)

    def test_keeps_non_ascii_readable(self):
        # ensure_ascii=False 是刻意保留的：中文直接可读，便于人工排查页面数据
        self.assertIn("中文", cmd_serve._inline_json({"s": "中文"}))


class TestRenderIndex(unittest.TestCase):
    def test_no_injected_script_tag(self):
        skills = [{"slug": "evil", "summary": MALICIOUS, "tags": []}]
        baseline = cmd_serve._load_template().count("</script>")
        html = cmd_serve._render_index(skills, {"total": 1, "active": 1})
        # 注入内容不得新增 script 结束标签（模板自身有几个就还是几个）
        self.assertEqual(html.count("</script>"), baseline)
        self.assertNotIn("<img src=x", html)

    def test_placeholders_fully_replaced(self):
        html = cmd_serve._render_index([], {"total": 0, "active": 0})
        self.assertNotIn("__SKILLS__", html)
        self.assertNotIn("__STATS__", html)

    def test_placeholder_literal_in_data_is_not_replaced(self):
        # 技能摘要里恰好含占位符字面量时，不能被当作模板占位符二次替换
        skills = [{"slug": "x", "summary": "__SKILLS__ __STATS__"}]
        html = cmd_serve._render_index(skills, {"total": 1, "active": 1})
        self.assertIn("__SKILLS__ __STATS__", html)


if __name__ == "__main__":
    unittest.main()


class TestBuildScores(unittest.TestCase):
    """分数表的语义测试：核心是"没有数据"不能被算成"0 分"。"""

    def test_insufficient_sample_returns_none_not_zero(self):
        out = cmd_serve._build_scores({"a": {"shown": 2, "loaded": 0}})
        self.assertIsNone(out["a"]["load_rate"])
        self.assertEqual(out["a"]["n"], 2)

    def test_enough_sample_returns_rate(self):
        out = cmd_serve._build_scores({"a": {"shown": 10, "loaded": 3}})
        self.assertAlmostEqual(out["a"]["load_rate"], 0.3, places=4)

    def test_zero_loads_with_enough_sample_is_real_zero(self):
        # 推荐 10 次、一次没被采纳 —— 这才是真的 0 分，必须与"无数据"区分
        out = cmd_serve._build_scores({"a": {"shown": 10, "loaded": 0}})
        self.assertEqual(out["a"]["load_rate"], 0.0)

    def test_rate_is_capped(self):
        out = cmd_serve._build_scores({"a": {"shown": 5, "loaded": 9}})
        self.assertEqual(out["a"]["load_rate"], 1.0)

    def test_min_sample_is_respected(self):
        out = cmd_serve._build_scores({"a": {"shown": 5, "loaded": 1}}, min_sample=50)
        self.assertIsNone(out["a"]["load_rate"])

    def test_empty_counts(self):
        self.assertEqual(cmd_serve._build_scores({}), {})

    def test_min_sample_is_a_contract_for_the_ui(self):
        # 页面不该硬编码 5，由接口告知，两边必须一致
        self.assertIsInstance(cmd_serve.MIN_SAMPLE, int)
        self.assertEqual(cmd_serve.MIN_SAMPLE, 5)
