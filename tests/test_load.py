"""``sfx load`` 的集成测试：采纳上报必须真的进库、真的能被统计。

这条链路的特殊性在于它**跨进程**：``match`` 写 session 与 match 事件，
``load`` 要把采纳挂回最近那次会话，``serve`` 再从同一张表里读出采纳率。
只做单元测试会漏掉"写进去了但 join 不上"这类问题，所以这里全部用子进程跑真 CLI。
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from tests.test_cli import TESTDATA_SKILLS, one_json, run_sfx  # noqa: E402


class TestLoad(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.home = os.path.join(self._tmp.name, "home")
        run_sfx(["scan"], self.home, roots=TESTDATA_SKILLS)
        self.slug = self._first_slug()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # ---------------- 夹具 ----------------
    def _first_slug(self) -> str:
        result = run_sfx(["match", "--task", "下单 订单 幂等"], self.home)
        payload = one_json(result)
        cards = payload["data"]["matched"]
        self.assertTrue(cards, "测试数据里至少应有 1 个可匹配的 skill")
        return self._slug_of(cards[0]["skill_id"])

    def _slug_of(self, skill_id: str) -> str:
        result = run_sfx(["match", "--task", "下单"], self.home)
        for card in one_json(result)["data"]["matched"]:
            if card["skill_id"] == skill_id:
                return os.path.basename(os.path.dirname(card["path"]))
        return ""

    def _scores(self) -> dict:
        # 直接用同一份 db 起一次 serve 太重，这里读库等价物：用 doctor 之外的
        # 公开入口 —— load 的回显本身就带累计值，故不再单独开服务。
        return {}

    # ---------------- 用例 ----------------
    def test_records_against_latest_match_session(self) -> None:
        """采纳必须挂到最近一次 match 的会话上，否则漏斗对不上。"""
        match_payload = one_json(run_sfx(["match", "--task", "下单 订单"], self.home))
        session_id = match_payload["data"]["session_id"]

        result = run_sfx(["load", self.slug, "--note", "试用"], self.home)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = one_json(result)
        self.assertTrue(payload["ok"])
        # 用目录名也能定位到同一个技能（slug 可能被去重改名，目录名是用户唯一看得见的东西）
        self.assertEqual(payload["data"]["skill_id"], match_payload["data"]["matched"][0]["skill_id"])
        self.assertTrue(payload["data"]["slug"])
        self.assertEqual(payload["data"]["session_id"], session_id)
        self.assertEqual(payload["data"]["loaded"], 1)
        self.assertIsNone(payload["data"]["load_rate"], "样本不足时不得给出比率")

    def test_positional_and_flag_forms_agree(self) -> None:
        a = one_json(run_sfx(["load", self.slug], self.home))
        b = one_json(run_sfx(["load", "--skill", self.slug], self.home))
        self.assertEqual(a["data"]["skill_id"], b["data"]["skill_id"])
        self.assertEqual(b["data"]["loaded"], 2, "两次上报都应计数，不做幂等去重")

    def test_without_prior_match_warns_but_still_records(self) -> None:
        """没跑过 match 就 load：要给 warning，但这条采纳不能丢。"""
        tmp = tempfile.TemporaryDirectory()
        try:
            home = os.path.join(tmp.name, "home")
            run_sfx(["scan"], home, roots=TESTDATA_SKILLS)
            result = run_sfx(["load", self.slug], home)
            payload = one_json(result)
            self.assertTrue(payload["ok"])
            self.assertIn("no_prior_match_session", payload["warnings"])
            self.assertEqual(payload["data"]["loaded"], 1)
        finally:
            tmp.cleanup()

    def test_unknown_skill_is_not_found(self) -> None:
        result = run_sfx(["load", "definitely-not-a-skill-xyz"], self.home)
        payload = one_json(result)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["code"], "E_NOT_FOUND")

    def test_empty_needle_is_usage_error(self) -> None:
        result = run_sfx(["load"], self.home)
        payload = one_json(result)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["code"], "E_USAGE")

    def test_history_signal_starts_flowing_after_load(self) -> None:
        """load 一次之后，matcher 的 history 信号从"不可用"变为"可用"。

        这是"闭环"的技术含义：没有 load 时 ``history_scores()`` 返回空字典，
        matcher 把 history 权重摊还掉；有 load 之后它开始参与打分。
        """
        from sfx.infra import pathx
        from sfx.infra.sqlite import event_repo
        from sfx.infra.sqlite import open as sqlite_open

        conn = sqlite_open.open_db(pathx.db_path(self.home))
        try:
            before = event_repo.EventRepo(conn).history_scores()
        finally:
            sqlite_open.close_db(conn)
        self.assertEqual(before, {}, "还没有 load 时 history 信号必须不可用")

        run_sfx(["load", self.slug], self.home)

        conn = sqlite_open.open_db(pathx.db_path(self.home))
        try:
            after = event_repo.EventRepo(conn).history_scores()
        finally:
            sqlite_open.close_db(conn)
        self.assertTrue(after, "上报采纳后 history 信号应可用")
        self.assertTrue(all(0.0 <= v <= 1.0 for v in after.values()))


class TestRepairIds(unittest.TestCase):
    """空主键历史数据必须被修回来 —— 否则那些技能永远 join 不上埋点。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.home = os.path.join(self._tmp.name, "home")
        run_sfx(["scan"], self.home, roots=TESTDATA_SKILLS)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_scan_repairs_empty_id(self) -> None:
        from sfx.infra import pathx
        from sfx.infra.sqlite import open as sqlite_open

        conn = sqlite_open.open_db(pathx.db_path(self.home))
        try:
            conn.execute("UPDATE skills SET id = '' WHERE rowid = (SELECT MIN(rowid) FROM skills)")
            conn.commit()
        finally:
            sqlite_open.close_db(conn)

        result = run_sfx(["scan"], self.home, roots=TESTDATA_SKILLS)
        payload = one_json(result)
        self.assertEqual(payload["data"]["repaired_ids"], 1)

        conn = sqlite_open.open_db(pathx.db_path(self.home))
        try:
            bad = conn.execute(
                "SELECT COUNT(*) FROM skills WHERE id IS NULL OR length(id) <> 36"
            ).fetchone()[0]
        finally:
            sqlite_open.close_db(conn)
        self.assertEqual(bad, 0)

    def test_second_scan_repairs_nothing(self) -> None:
        payload = one_json(run_sfx(["scan"], self.home, roots=TESTDATA_SKILLS))
        self.assertEqual(payload["data"]["repaired_ids"], 0)


if __name__ == "__main__":
    unittest.main()
