"""matcher 单测（ARCH §7.2 / §12.6.2.1 C-1）。

重点验证 **C-1**：``weights.history`` 置 0（或 history 信号不可用）时，
权重必须**按剩余比例摊还**，而不是"直接少一截分数"。
"""

from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from sfx.core.model.skill import Skill  # noqa: E402
from sfx.core.service import matcher  # noqa: E402
from sfx.infra import conf  # noqa: E402


class _Cfg:
    """matcher 只需要 threshold / top_n / weight()，这里给一个最小替身。"""

    def __init__(self, weights: dict[str, float], threshold: float = 0.0, top_n: int = 10) -> None:
        self.weights = weights
        self.threshold = threshold
        self.top_n = top_n

    def weight(self, name: str) -> float:
        return float(self.weights.get(name, 0.0))


def _skill(skill_id: str, name: str, triggers: tuple[str, ...], tags: tuple[str, ...]) -> Skill:
    return Skill(
        id=skill_id, name=name, slug=name, summary=f"{name} 的摘要",
        entry_path=f"/abs/path/{name}/SKILL.md",
        triggers=triggers, tags=tags,
    )


class TestWeightRedistribution(unittest.TestCase):
    """C-1：权重摊还。"""

    def test_history_zero_redistributes_to_others(self) -> None:
        """history=0 时，剩余权重必须摊还到 1.0（否则所有分数都会凭空少 15%）。"""
        cfg = _Cfg({"keyword": 0.40, "tag": 0.20, "semantic": 0.25, "history": 0.0})
        skills = [_skill("s1", "重构", ("重构", "数据库"), ("数据库",))]
        results = matcher.match("帮我重构数据库", skills, cfg, history={}, synonyms={})
        self.assertEqual(len(results), 1)
        # WS 下 semantic 恒不可用，故只在 keyword + tag 之间摊还：0.4/0.6 与 0.2/0.6。
        # keyword = 2 个触发词命中 / 3 = 0.667（N=1 时 idf 恰为 1.0，与旧公式一致）
        # tag     = 1 个标签命中 / 3 = 0.333
        #   —— S1.1 起标签信号改用与关键词**同一套**归一（分母 KEYWORD_FULL_HITS=3），
        #      不再用 len(tags)=1 做分母（旧值 1.0）。理由：len(tags) 做分母等于
        #      "标签写得越少越容易得高分"，奖励的是元数据缺失，不是匹配质量。
        expected = (0.4 / 0.6) * (2 / 3.0) + (0.2 / 0.6) * (1 / 3.0)
        self.assertAlmostEqual(results[0].score, round(expected, 4), places=4)

    def test_history_zero_is_not_a_hard_cut(self) -> None:
        """history 置 0 后，单信号满分仍能拿到 1.0（不是被硬截断到 0.85）。"""
        cfg = _Cfg({"keyword": 1.0, "tag": 0.0, "semantic": 0.0, "history": 0.0})
        skills = [_skill("s1", "重构", ("重构", "数据库", "性能"), ())]
        results = matcher.match("重构数据库性能", skills, cfg, history={}, synonyms={})
        self.assertAlmostEqual(results[0].score, 1.0, places=4)

    def test_history_unavailable_when_no_events(self) -> None:
        """history 无数据时与"权重置 0"走同一条路径（Tier B 下零返工）。"""
        cfg = _Cfg({"keyword": 0.40, "tag": 0.20, "semantic": 0.25, "history": 0.15})
        skills = [_skill("s1", "重构", ("重构", "数据库"), ("后端",))]
        without_history = matcher.match("帮我重构数据库", skills, cfg, history={}, synonyms={})
        cfg_zero = _Cfg({"keyword": 0.40, "tag": 0.20, "semantic": 0.25, "history": 0.0})
        with_zero_weight = matcher.match("帮我重构数据库", skills, cfg_zero, history={}, synonyms={})
        self.assertAlmostEqual(without_history[0].score, with_zero_weight[0].score, places=6)

    def test_tag_signal_unavailable_without_any_tags(self) -> None:
        """所有 skill 都没有标签时，tag 信号不可用 → 权重摊还给 keyword。"""
        cfg = _Cfg({"keyword": 0.40, "tag": 0.20, "semantic": 0.25, "history": 0.15})
        skills = [_skill("s1", "重构", ("重构", "数据库", "性能"), ())]
        results = matcher.match("重构数据库性能", skills, cfg, history={}, synonyms={})
        self.assertAlmostEqual(results[0].score, 1.0, places=4)

    def test_history_signal_used_when_available(self) -> None:
        """有 load 埋点时 history 参与加权（与置 0 时结果不同）。"""
        cfg = _Cfg({"keyword": 0.50, "tag": 0.0, "semantic": 0.0, "history": 0.50})
        skills = [_skill("s1", "重构", ("重构", "数据库", "性能"), ())]
        results = matcher.match(
            "重构数据库性能", skills, cfg, history={"s1": 1.0}, synonyms={}
        )
        self.assertAlmostEqual(results[0].score, 1.0, places=4)
        results_zero = matcher.match(
            "重构数据库性能", skills, cfg, history={"s1": 0.0}, synonyms={}
        )
        self.assertAlmostEqual(results_zero[0].score, 0.5, places=4)


class TestMatchingBehaviour(unittest.TestCase):
    """基础匹配行为。"""

    def test_threshold_filters(self) -> None:
        """低于阈值的结果不返回。"""
        cfg = _Cfg({"keyword": 1.0, "tag": 0.0, "semantic": 0.0, "history": 0.0}, threshold=0.5)
        skills = [
            _skill("s1", "重构", ("重构", "数据库", "性能"), ()),
            _skill("s2", "文档", ("文档",), ()),
        ]
        results = matcher.match("重构数据库性能", skills, cfg, history={}, synonyms={})
        self.assertEqual([item.skill_id for item in results], ["s1"])

    def test_top_n_limits_result_size(self) -> None:
        """``top_n`` 生效。"""
        cfg = _Cfg({"keyword": 1.0, "tag": 0.0, "semantic": 0.0, "history": 0.0}, top_n=2)
        skills = [_skill(f"s{index}", f"技能{index}", ("重构",), ()) for index in range(5)]
        results = matcher.match("重构", skills, cfg, history={}, synonyms={})
        self.assertEqual(len(results), 2)

    def test_synonym_expansion(self) -> None:
        """同义词命中生效但权重低于直接命中（0.7）。"""
        cfg = _Cfg({"keyword": 1.0, "tag": 0.0, "semantic": 0.0, "history": 0.0})
        skills = [_skill("s1", "重构", ("refactor",), ())]
        synonyms = {"重写": ("refactor", "重构")}
        results = matcher.match("重写这段代码", skills, cfg, history={}, synonyms=synonyms)
        self.assertEqual(len(results), 1)
        self.assertGreater(results[0].score, 0.0)
        self.assertLess(results[0].score, 1.0 / 3.0 + 1e-9)

    def test_sorting_is_deterministic(self) -> None:
        """同分必须稳定排序（R-17：避免每次 sync 结果抖动）。"""
        cfg = _Cfg({"keyword": 1.0, "tag": 0.0, "semantic": 0.0, "history": 0.0}, top_n=10)
        skills = [
            _skill("s2", "b-skill", ("重构",), ()),
            _skill("s1", "a-skill", ("重构",), ()),
        ]
        first = matcher.match("重构", skills, cfg, history={}, synonyms={})
        second = matcher.match("重构", skills, cfg, history={}, synonyms={})
        self.assertEqual([item.skill_id for item in first], ["s1", "s2"])
        self.assertEqual([item.skill_id for item in first], [item.skill_id for item in second])


class TestScoringModel(unittest.TestCase):
    """S1.1 打分模型：IDF / 同义词折扣 / 归一方式 / 术语归一化。

    这几条是"排序质量"的回归闸门——它们的共同背景是：旧公式里
    ``ui``（十几个技能都有）与 ``对比度``（只有 1 个技能有）命中一次得分相同，
    一个泛化词还能靠同义词链刷出多份分。
    """

    def test_idf_downweights_corpus_wide_term(self) -> None:
        """稀有词的单词命中必须高于"全库都有"的词（同为一击）。"""
        cfg = _Cfg({"keyword": 1.0, "tag": 0.0, "semantic": 0.0, "history": 0.0}, threshold=0.1)
        skills = [
            _skill("s1", "通用", ("通用词", "独有词"), ()),
            _skill("s2", "a", ("通用词",), ()),
            _skill("s3", "b", ("通用词",), ()),
        ]
        # df(通用词)=3 → idf=ln(4/4)+1=1.0；df(独有词)=1 → idf=ln(4/2)+1≈1.693
        common = matcher.match("通用词", skills, cfg, history={}, synonyms={})
        rare = matcher.match("独有词", skills, cfg, history={}, synonyms={})
        self.assertEqual(len(rare), 1)
        common_score = {item.skill_id: item.score for item in common}["s1"]
        self.assertGreater(rare[0].score, common_score)
        self.assertAlmostEqual(common_score, round(1.0 / 3.0, 4), places=4)
        self.assertAlmostEqual(rare[0].score, round(1.6931 / 3.0, 4), places=2)

    def test_one_query_word_credits_at_most_one_synonym(self) -> None:
        """一个查询词扩展到多个兄弟词时，只按**最高**那一次计分。

        否则 ``报错`` → ``异常`` + ``错误处理`` 会让"异常处理"技能凭一个词
        拿到 2 份同义词分，压过真正命中 ``SpotBugs`` 的技能。
        """
        cfg = _Cfg({"keyword": 1.0, "tag": 0.0, "semantic": 0.0, "history": 0.0})
        skills = [_skill("s1", "异常", ("异常", "错误处理"), ())]
        synonyms = {"报错": ("异常", "错误处理")}
        results = matcher.match("报错", skills, cfg, history={}, synonyms=synonyms)
        self.assertEqual(len(results), 1)
        # N=1 → idf=1.0；一次同义词命中 = 0.7，再除以 KEYWORD_FULL_HITS=3。
        self.assertAlmostEqual(results[0].score, round(0.7 / 3.0, 4), places=4)

    def test_tag_signal_does_not_reward_fewer_tags(self) -> None:
        """标签数量不同但命中数相同时，分数必须相同（标签少不算优势）。"""
        cfg = _Cfg({"keyword": 0.40, "tag": 0.20, "semantic": 0.0, "history": 0.0})
        skills = [
            _skill("s1", "少标签", ("数据库",), ("数据库",)),
            _skill("s2", "多标签", ("数据库",), ("数据库", "a", "b", "c", "d")),
        ]
        results = matcher.match("数据库", skills, cfg, history={}, synonyms={})
        scores = {item.skill_id: item.score for item in results}
        self.assertAlmostEqual(scores["s1"], scores["s2"], places=6)

    def test_separator_normalisation(self) -> None:
        """``spring-boot`` 与 ``Spring Boot`` 必须等价（纯格式差异不该漏命中）。"""
        cfg = _Cfg({"keyword": 1.0, "tag": 0.0, "semantic": 0.0, "history": 0.0})
        skills = [_skill("s1", "spring", ("spring-boot",), ())]
        results = matcher.match("帮我写一个 Spring Boot 接口", skills, cfg, history={}, synonyms={})
        self.assertEqual(len(results), 1)
        self.assertAlmostEqual(results[0].score, round(1.0 / 3.0, 4), places=4)

    def test_saturation_tie_broken_by_stronger_evidence(self) -> None:
        """两个技能都被顶到 1.0 时，加权命中和更大的排前面（不靠 slug 运气）。"""
        cfg = _Cfg({"keyword": 1.0, "tag": 0.0, "semantic": 0.0, "history": 0.0})
        skills = [
            _skill("s1", "aaa", ("甲", "乙", "丙"), ()),
            _skill("s2", "zzz", ("甲", "乙", "丙", "丁", "戊"), ()),
        ]
        results = matcher.match("甲乙丙丁戊", skills, cfg, history={}, synonyms={})
        # 两个都是 1.0，但 zzz 的加权命中和更高（5 击 vs 3 击）
        self.assertEqual([item.skill_id for item in results], ["s2", "s1"])
        self.assertEqual(results[0].score, results[1].score)


class TestSynonymDictionary(unittest.TestCase):
    """同义词词典解析与缓存。"""

    def test_parse_groups(self) -> None:
        """``标准词=同义1,同义2`` 解析正确，注释行被忽略。"""
        text = "# 注释\n重构=refactor,重写,整理代码\n\n测试=test,单元测试\n"
        groups = matcher.parse_synonym_groups(text)
        self.assertEqual(groups[0], ("重构", "refactor", "重写", "整理代码"))
        self.assertEqual(groups[1], ("测试", "test", "单元测试"))

    def test_build_map_is_symmetric(self) -> None:
        """组内互为同义词。"""
        table = matcher.build_synonym_map([("重构", "refactor")])
        self.assertEqual(set(table["重构"]), {"refactor"})
        self.assertEqual(set(table["refactor"]), {"重构"})

    def test_load_synonyms_degrades_gracefully(self) -> None:
        """资源不可用时返回空词典 + warning，绝不抛异常（§7.2.3 降级链）。"""
        import tempfile
        from sfx.infra.logx import NullLogger

        with tempfile.TemporaryDirectory() as tmp:
            table, warnings = matcher.load_synonyms(tmp, NullLogger())
        # 词典在包内存在，正常应解析出条目；即便失败也必须返回 (dict, list) 而非抛错
        self.assertIsInstance(table, dict)
        self.assertIsInstance(warnings, list)


class TestDefaultConfig(unittest.TestCase):
    """默认配置。"""

    def test_default_weights_sum_to_one(self) -> None:
        """ARCH §7.2.4 的默认权重。"""
        total = sum(conf.DEFAULT_WEIGHTS.values())
        self.assertAlmostEqual(total, 1.0, places=6)
        self.assertEqual(conf.DEFAULT_THRESHOLD, 0.22)
        self.assertEqual(conf.DEFAULT_TOP_N, 3)

    def test_active_signals_excludes_zero_weight(self) -> None:
        """权重为 0 的信号不参与。"""
        cfg = conf.Config(weights={"keyword": 1.0, "tag": 0.0, "semantic": 0.0, "history": 0.0})
        self.assertEqual(cfg.active_signals(), ("keyword",))


if __name__ == "__main__":
    unittest.main()
