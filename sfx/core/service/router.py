"""精简路由卡构造（ARCH §3.2）——**严禁塞正文**。

为什么要有这一层
----------------
路由卡是要被 Metis 读进上下文的。一个 skill 正文动辄几千 token，
Top3 全塞进去就是几万 token，**直接把上下文挤爆**（R-14）。
所以"路由卡字段集合"必须是**冻结的、可断言的**：只有元数据 + 绝对路径，
宿主拿到路径后自己 ``Read`` 正文（NN-4）。

本模块用 ``ROUTE_CARD_FIELDS`` + :func:`assert_route_card` 做 golden 断言，
任何往里加字段的改动都会在测试里失败——这是把设计约束固化成代码的方式。
"""

from __future__ import annotations

from sfx.core.service.matcher import MatchResult

#: 路由卡的**冻结字段集合**（ARCH §5.2 ``sfx match`` 契约）
ROUTE_CARD_FIELDS: tuple[str, ...] = (
    "skill_id",
    "name",
    "summary",
    "path",
    "score",
    "reason",
)

#: 明令禁止出现在路由卡里的键（正文 / 大字段 / 内部字段）
FORBIDDEN_CARD_KEYS: frozenset[str] = frozenset({
    "body", "content", "text", "markdown", "raw", "source",
    "description", "triggers", "tags", "triggers_json", "tags_json",
    "dir_path", "source_root", "body_bytes", "content_hash",
})

#: 单个字段的长度硬上限：summary/reason 失控同样会挤爆上下文
MAX_SUMMARY_CHARS = 200
MAX_REASON_CHARS = 200


def build_route_card(results: list[MatchResult]) -> list[dict[str, object]]:
    """把匹配结果转成路由卡（只含冻结字段，且路径为原生绝对路径）。"""
    cards: list[dict[str, object]] = []
    for result in results:
        cards.append(
            {
                "skill_id": result.skill_id,
                "name": result.name,
                "summary": _clip(result.summary, MAX_SUMMARY_CHARS),
                "path": result.path,
                "score": result.score,
                "reason": _clip(result.reason, MAX_REASON_CHARS),
            }
        )
    assert_route_card(cards)
    return cards


def assert_route_card(cards: list[dict[str, object]]) -> None:
    """校验路由卡：**字段集合必须与冻结集合完全一致，且不含任何禁止键**。

    Raises:
        ValueError: 违规（测试里应直接失败，生产里由顶层兜底转成 ``E_INTERNAL``）。
    """
    for card in cards:
        keys = set(card.keys())
        if keys != set(ROUTE_CARD_FIELDS):
            missing = sorted(set(ROUTE_CARD_FIELDS) - keys)
            extra = sorted(keys - set(ROUTE_CARD_FIELDS))
            raise ValueError(f"路由卡字段集合不符：缺少={missing} 多余={extra}")
        leaked = keys & FORBIDDEN_CARD_KEYS
        if leaked:
            raise ValueError(f"路由卡泄漏了禁止字段：{sorted(leaked)}")
        path = str(card.get("path", ""))
        if path.startswith("~"):
            raise ValueError("路由卡路径禁止使用 ~（NN-4：必须是宿主可直接打开的绝对路径）")


def _clip(text: str, limit: int) -> str:
    """截断超长文本（避免单个字段把上下文撑爆）。"""
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def build_match_data(
    session_id: str,
    results: list[MatchResult],
    threshold: float,
    engine_version: str,
) -> dict[str, object]:
    """构造 ``sfx match`` 的 ``data`` 负载（ARCH §5.2）。"""
    return {
        "session_id": session_id,
        "matched": build_route_card(results),
        "match_count": len(results),
        "threshold": threshold,
        "engine_version": engine_version,
    }
