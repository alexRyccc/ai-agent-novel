"""路由卡 golden 断言（ARCH §5.2 / NN-4）。

**路由卡绝不能包含 skill 正文**——这是防上下文爆炸的硬要求。
本测试把这个约束固化成可执行断言：字段集合必须与冻结集合**完全一致**，
多一个字段、少一个字段、混进 ``body`` / ``description`` 都会失败。
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from sfx.core.service import router  # noqa: E402
from sfx.core.service.matcher import MatchResult  # noqa: E402


def _result() -> MatchResult:
    return MatchResult(
        skill_id="0199-xxxx",
        name="内部下单接口规范",
        slug="order-api",
        summary="下单接口的内部规范（字段/错误码/幂等）",
        # 用 tempfile.gettempdir() 保证带盘符：Windows 的 ``os.path.isabs``
        # 对"\abs\..."这类无盘符路径判定为 False（NN-4 要求的是"宿主能直接打开"的路径）
        path=os.path.join(tempfile.gettempdir(), "order-api", "SKILL.md"),
        score=0.8123,
        reason="命中触发词 下单/订单；标签命中 2/3",
    )


class TestRouteCard(unittest.TestCase):
    """路由卡字段集合。"""

    def test_field_set_is_exactly_frozen(self) -> None:
        """字段集合必须与 ``ROUTE_CARD_FIELDS`` 完全一致。"""
        cards = router.build_route_card([_result()])
        self.assertEqual(len(cards), 1)
        self.assertEqual(tuple(cards[0].keys()), router.ROUTE_CARD_FIELDS)

    def test_no_body_in_card(self) -> None:
        """序列化后的路由卡里不得出现任何正文/大字段键。"""
        cards = router.build_route_card([_result()])
        text = str(cards[0])
        for forbidden in ("body", "content", "text", "description", "triggers_json"):
            self.assertNotIn(forbidden, text)

    def test_path_is_absolute_not_tilde(self) -> None:
        """路径必须是宿主可直接打开的绝对路径（NN-4：禁止 ``~``）。"""
        cards = router.build_route_card([_result()])
        self.assertTrue(os.path.isabs(cards[0]["path"]))
        self.assertFalse(str(cards[0]["path"]).startswith("~"))

    def test_assert_rejects_extra_field(self) -> None:
        """多一个字段（哪怕是 body）必须被断言拦下。"""
        card = {
            "skill_id": "a", "name": "b", "summary": "c",
            "path": "/x/SKILL.md", "score": 0.5, "reason": "r",
            "body": "这里是正文，绝对不能出现",
        }
        with self.assertRaises(ValueError):
            router.assert_route_card([card])

    def test_assert_rejects_tilde_path(self) -> None:
        """``~`` 路径必须被拦下。"""
        card = {
            "skill_id": "a", "name": "b", "summary": "c",
            "path": "~/skills/x/SKILL.md", "score": 0.5, "reason": "r",
        }
        with self.assertRaises(ValueError):
            router.assert_route_card([card])

    def test_long_fields_are_clipped(self) -> None:
        """超长 summary / reason 会被截断，避免单字段把上下文撑爆。"""
        result = _result()
        result.summary = "很长的摘要" * 100
        result.reason = "很长的理由" * 100
        card = router.build_route_card([result])[0]
        self.assertLessEqual(len(card["summary"]), router.MAX_SUMMARY_CHARS)
        self.assertLessEqual(len(card["reason"]), router.MAX_REASON_CHARS)


class TestMatchData(unittest.TestCase):
    """``sfx match`` 的 ``data`` 负载。"""

    def test_contains_session_id_and_matched(self) -> None:
        """必须包含 ``session_id``；无命中时 ``matched`` 为空数组而非 null。"""
        data = router.build_match_data("session-1", [], 0.35, "rule+dict+v1")
        self.assertEqual(data["session_id"], "session-1")
        self.assertEqual(data["matched"], [])
        self.assertEqual(data["match_count"], 0)
        self.assertEqual(data["threshold"], 0.35)
        self.assertEqual(data["engine_version"], "rule+dict+v1")

    def test_matched_items_are_route_cards(self) -> None:
        """``matched`` 的每一项都是合规路由卡。"""
        data = router.build_match_data("session-1", [_result()], 0.35, "rule+dict+v1")
        self.assertEqual(len(data["matched"]), 1)
        self.assertEqual(tuple(data["matched"][0].keys()), router.ROUTE_CARD_FIELDS)


if __name__ == "__main__":
    unittest.main()
