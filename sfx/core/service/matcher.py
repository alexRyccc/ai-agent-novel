"""多信号加权匹配（ARCH §7.2 / WS-2 W2-3）。

WS 阶段只做 **S1：关键词 + 同义词词典 + 标签加权**（§7.2.1 的 P0 基线），
不做 BM25（§12.6.2 明确推迟）。

**C-1 前置约束（ARCH §12.6.2.1）**
---------------------------------
``weights.history`` 必须**可配置为 0**，且置 0 后**按剩余权重比例摊还**。
这条必须做，因为 Tier B 下没有自动埋点数据，history 信号恒为 0。

实现上是**纯配置驱动**的：不为任何 Tier 写分支代码。规则只有一条——
**权重在"当前可用"的信号之间重新归一化**：

1. 配置权重 ``<= 0`` 的信号被剔除（``history`` 置 0 就是这么生效的）；
2. 运行时判定为"不可用"的信号被剔除（WS 的 ``semantic`` 恒不可用；
   ``history`` 在库里没有 ``load`` 事件时不可用）；
3. 剩下的权重按 ``w_i / Σw`` 摊还到 1.0，再加权求和。

于是"history=0"与"history 无数据"走的是**同一条代码路径**，
Tier A/B/C 三种宿主结论下都零返工。

**S1.1 打分模型（W2-3 修复：排序质量）**
----------------------------------------
原 S1 有三处结构性缺陷，导致"泛化词刷分、稀有词被淹没"：

1. **没有 IDF**：``ui``（十几个技能都有）与 ``对比度``（只有 1 个技能有）
   命中一次得分相同，泛化词靠"铺得多"取胜。
2. **同义词在两个信号里折扣不一致**：``_keyword_signal`` 按
   ``SYNONYM_HIT_WEIGHT=0.7`` 折算，``_tag_signal`` 却按 1.0 全额计分。
3. **标签信号用 ``hits / len(tags)`` 归一**：标签越少越容易拿高分，
   这奖励的是"元数据写得少"，与技能质量无关。

S1.1 的四条规则（全部在 :func:`match` 内按次计算，保持**纯函数语义**：

- **IDF 词权重**：``df(term)`` = 候选集内触发词/标签含该词（归一化、小写）的
  技能数；``idf(term) = ln((N+1)/(df+1)) + 1``，并封顶 :data:`IDF_CAP`。
  命中计分由"累加 1"改为"累加 idf"，单次命中最多贡献 :data:`IDF_CAP`，
  防止一个极稀有词单独把分数顶满。
- **一个查询词只贡献一次**：同义词扩展会把 1 个查询词映射到多个兄弟词
  （例如 ``报错`` → ``异常`` / ``错误处理``），若逐个累加，**一个泛化词就能
  刷出两份分**。因此按"来源查询词"分组，每组只取最高 IDF 的那次命中。
- **同义词统一折扣**：两个信号都按 :data:`SYNONYM_HIT_WEIGHT` 折算，
  保证"原词命中 > 同义词命中"的排序直觉处处成立。
- **同一套饱和度归一**：两个信号都用 ``min(1.0, 加权和 / KEYWORD_FULL_HITS)``，
  不再用 ``len(tags)`` 做分母；单信号满分（1.0）依然可达，C-1 的摊还契约不变。

纯函数的代价与底线：IDF 的文档频率每个调用内现算（N=33 时约 400 次 dict 自增，
微秒级），**不落盘、不跨调用缓存**，``match()`` 签名与参数位置保持不变
（``history`` / ``synonyms`` 按位置被测试与 CLI 调用）。
"""

from __future__ import annotations

import json
import math
import os

from sfx.core.model.skill import Skill
from sfx.infra import pathx

#: 关键词信号达到 1.0 所需的加权命中数（>=3 个"满权重"命中即满分）
KEYWORD_FULL_HITS = 3.0
#: 同义词命中的折算系数（比直接命中略低，保留"原词优先"的排序直觉）
SYNONYM_HIT_WEIGHT = 0.7
#: 单次命中允许的最大 IDF 权重（稀有词不得单独把信号顶满）
IDF_CAP = 2.0
#: 语料内查不到的 term 的兜底 IDF（中性权重，等价于"未知词按普通词算"）
IDF_FLOOR = 1.0
#: 归一化术语时折叠成空格的分隔符（让 ``spring-boot`` 与 ``Spring Boot`` 等价）
_SEPARATORS: tuple[str, ...] = ("-", "_", "/", "\\", "·")

SYNONYM_RESOURCE = "synonyms.txt"
SYNONYM_CACHE_NAME = "synonyms.json"
#: 缓存格式版本。**缓存结构变更时 +1**（词典内容变更不必改这里，见
#: :func:`_dictionary_fingerprint`：词典文件自己的 mtime/size 会进指纹）。
SYNONYM_CACHE_VERSION = 2


class MatchResult:
    """一条匹配结果。

    注意：**这里没有 body / content 字段**——路由卡不得包含 skill 正文
    （防上下文爆炸），字段集合由 ``core.service.router`` 的 golden 断言守住。

    （不用 ``@dataclass`` 的理由见 :class:`~sfx.core.model.skill.Skill`：
      ``dataclasses`` 实测 +38.6ms，热路径付不起。）
    """

    __slots__ = ("skill_id", "name", "slug", "summary", "path", "score", "reason")

    def __init__(
        self,
        skill_id: str = "",
        name: str = "",
        slug: str = "",
        summary: str = "",
        path: str = "",
        score: float = 0.0,
        reason: str = "",
    ) -> None:
        self.skill_id = skill_id
        self.name = name
        self.slug = slug
        self.summary = summary
        self.path = path
        self.score = score
        self.reason = reason


# --------------------------------------------------------------------------
# 同义词词典
# --------------------------------------------------------------------------
def parse_synonym_groups(text: str) -> list[tuple[str, ...]]:
    """解析同义词词典文本。

    格式：一行一组，``标准词=同义词1,同义词2``；``#`` 开头为注释。
    分隔符同时兼容半角/全角逗号与顿号。
    """
    groups: list[tuple[str, ...]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        left, right = line.split("=", 1)
        terms: list[str] = []
        for chunk in right.replace("，", ",").replace("、", ",").split(","):
            term = chunk.strip()
            if term:
                terms.append(term)
        canonical = left.strip()
        if canonical:
            terms.insert(0, canonical)
        if len(terms) >= 2:
            groups.append(tuple(terms))
    return groups


def build_synonym_map(groups: list[tuple[str, ...]]) -> dict[str, tuple[str, ...]]:
    """把分组表展开成 ``词 -> 同组其它词`` 的查表结构。

    只展开**一层**：``a=b,c`` 得到 ``a->{b,c}``、``b->{a,c}``、``c->{a,b}``，
    不做传递闭包。一个词若出现在多个分组里，其兄弟集合是各组的并集
    （例如 ``可观测性`` 同时属于"日志"与"监控"两组）。
    """
    table: dict[str, tuple[str, ...]] = {}
    for group in groups:
        for index, term in enumerate(group):
            key = term.lower()
            siblings = tuple(other for pos, other in enumerate(group) if pos != index)
            merged = set(table.get(key, ())) | set(siblings)
            table[key] = tuple(sorted(merged))
    return table


def _dictionary_fingerprint() -> str:
    """返回包内词典文件的廉价指纹 ``"mtime_ns:size"``；取不到时返回 ``""``。

    为什么需要：``<home>/cache/synonyms.json`` 一旦生成就会**永远赢过**
    包内资源，于是"词典是纯数据文件、改它不需要改代码"就成了空话——
    改完不生效，而且没有任何提示（这个坑在本轮修复中真实发生过一次）。

    成本控制：这里只做一次 ``os.stat``（微秒级），**绝不**去
    ``importlib.resources`` 读文件（那是 +205ms）。zipapp 形态下
    ``sfx/__init__.py`` 位于 zip 内部、``os.stat`` 必然失败，于是返回 ``""``
    且两侧一致——打包产物里的词典本来就是冻结的，由版本号兜底即可。
    """
    package_dir = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    try:
        info = os.stat(os.path.join(package_dir, "_data", SYNONYM_RESOURCE))
    except OSError:
        return ""
    return f"{info.st_mtime_ns}:{info.st_size}"


def _read_cache(cache_path: str, fingerprint: str) -> list[tuple[str, ...]] | None:
    """读取同义词缓存（``json`` 已在热路径加载，读缓存几乎零成本）。

    指纹不匹配说明包内词典已被改动，按"缓存未命中"处理，下次写回时刷新。
    """
    if not os.path.isfile(cache_path):
        return None
    try:
        with open(cache_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("v") != SYNONYM_CACHE_VERSION:
        return None
    if str(data.get("fp", "")) != fingerprint:
        return None
    raw_groups = data.get("groups")
    if not isinstance(raw_groups, list):
        return None
    return [tuple(str(term) for term in group) for group in raw_groups if isinstance(group, list)]


def _write_cache(cache_path: str, groups: list[tuple[str, ...]], fingerprint: str) -> None:
    """写同义词缓存（失败无所谓：最坏情况是下次再读一次包内资源）。"""
    try:
        pathx.ensure_parent(cache_path)
        with open(cache_path, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "v": SYNONYM_CACHE_VERSION,
                    "fp": fingerprint,
                    "groups": [list(g) for g in groups],
                },
                handle, ensure_ascii=False,
            )
    except OSError:
        pass


def _read_groups_from_resource() -> list[tuple[str, ...]]:
    """直接从包内资源读词典（会付 ``importlib.resources`` 的 +205ms，只在冷路径调）。"""
    from sfx import _res  # 延迟导入：+205ms，只在缓存未命中/强制刷新时付

    return parse_synonym_groups(_res.read_text(SYNONYM_RESOURCE))


def load_synonyms(
    home: str, logger, refresh: bool = False
) -> tuple[dict[str, tuple[str, ...]], list[str]]:
    """加载同义词词典，优先走磁盘缓存。

    为什么要缓存：词典在包内 ``_data/`` 里，读取必须过 ``importlib.resources``
    （实测 +205ms）。``sfx match`` 是热路径，不能每次都付。
    因此 ``sfx scan``（非热路径）会把词典展开成 ``<home>/cache/synonyms.json``，
    ``match`` 只读这个 JSON（``open`` + ``json``，≈1ms）。

    Args:
        home: 数据根目录。
        logger: 日志器。
        refresh: ``True`` 时**忽略现有缓存、以包内资源为准重写缓存**。
            这正是"词典是纯数据文件，改它不需要改代码"能成立的机制：
            ``sfx scan`` 走 ``refresh=True`` 刷新缓存，``sfx match`` 只读缓存。
            否则缓存一旦生成就永远比词典旧，改词典会"看起来毫无效果"。

    Returns:
        ``(查表字典, 降级说明列表)``。词典不可用时返回空字典 + 一条 warning，
        **绝不抛异常**（§7.2.3 降级链：永不失败）。
    """
    cache_path = os.path.join(pathx.cache_dir(home), SYNONYM_CACHE_NAME)
    fingerprint = _dictionary_fingerprint()
    groups = None if refresh else _read_cache(cache_path, fingerprint)
    if groups is None:
        try:
            groups = _read_groups_from_resource()
            _write_cache(cache_path, groups, fingerprint)
        except Exception as exc:  # noqa: BLE001 - 资源层任何异常都降级
            logger.warn("matcher", "synonyms_unavailable", reason=type(exc).__name__)
            fallback = _read_cache(cache_path, fingerprint)
            if fallback is None:
                return {}, [f"同义词词典不可用（{type(exc).__name__}），已降级为纯关键词匹配"]
            return build_synonym_map(fallback), []
    return build_synonym_map(groups), []


def warm_synonym_cache(home: str, logger) -> bool:
    """由 ``sfx scan`` 调用：**以包内资源为准**重建同义词缓存。

    与 :func:`load_synonyms` 的区别是 ``refresh=True``——scan 是非热路径，
    付得起 ``importlib.resources`` 的 +205ms，换来"改了 ``synonyms.txt``，
    跑一次 scan 就生效"的可维护性。
    """
    try:
        table, _ = load_synonyms(home, logger, refresh=True)
        return bool(table)
    except Exception:  # noqa: BLE001
        return False


# --------------------------------------------------------------------------
# 术语归一化与 IDF
# --------------------------------------------------------------------------
def _norm_term(text: str) -> str:
    """归一化术语：小写 + 分隔符折叠成空格 + 折叠连续空白。

    ``spring-boot`` / ``Spring Boot`` / ``spring_boot`` 归一化后都是
    ``"spring boot"``，避免"技能里写连字符、查询里打空格"这种纯格式差异
    造成的漏命中（实测它曾让 ``帮我写一个 Spring Boot 接口`` 丢掉唯一强信号）。
    """
    value = text.strip().lower()
    if not value:
        return ""
    for separator in _SEPARATORS:
        if separator in value:
            value = value.replace(separator, " ")
    return " ".join(value.split())


def _idf_of(term: str, idf: dict[str, float]) -> float:
    """取一个词的 IDF 权重（语料内没有的词按 :data:`IDF_FLOOR` 处理）。"""
    return idf.get(term, IDF_FLOOR)


def _build_idf(skills: list[Skill]) -> dict[str, float]:
    """按**当前候选集**计算每个词的 IDF 权重。

    ``df(term)`` = 触发词或标签**归一化后等于** term 的技能数（同一技能内
    重复出现只算一次；匹配阶段用的是子串包含，``df`` 这里用的是整词相等——
    查 idf 时用的正是"命中的那个文档词"，两者口径一致）；
    ``idf(term) = ln((N+1)/(df+1)) + 1``，再封顶 :data:`IDF_CAP`。

    为什么用 ``+1`` 平滑：本机语料只有几十个技能，``df=1`` 时裸 ``log(N/df)``
    会给出过高的权重，一次命中就能顶满分；平滑后 ``df=N`` 时 idf 恰为 1.0，
    即"全库都有的词"退化成中性权重，与老公式量级对齐（阈值 ``0.22`` 不必重标）。

    Args:
        skills: 候选 skill 列表（同一批就是"文档集"）。

    Returns:
        ``{归一化词: idf 权重}``。
    """
    total = len(skills)
    if total <= 0:
        return {}
    df: dict[str, int] = {}
    for skill in skills:
        seen: set[str] = set()
        for raw in skill.triggers:
            term = _norm_term(raw)
            if term:
                seen.add(term)
        for raw in skill.tags:
            term = _norm_term(raw)
            if term:
                seen.add(term)
        for term in seen:
            df[term] = df.get(term, 0) + 1
    idf: dict[str, float] = {}
    for term, count in df.items():
        value = math.log((total + 1) / (count + 1)) + 1.0
        idf[term] = value if value < IDF_CAP else IDF_CAP
    return idf


# --------------------------------------------------------------------------
# 信号计算
# --------------------------------------------------------------------------
def _expand_task(task_norm: str, synonyms: dict[str, tuple[str, ...]]) -> dict[str, str]:
    """用同义词词典把任务描述里出现的词扩展成 ``兄弟词 -> 来源词``。

    **只扩展一层**：只在任务里**原样出现**的词上做一次同组替换，扩展出来的
    兄弟词不会再被拿去继续扩展（无传递闭包），避免"措辞漂移越扩越远"。

    Args:
        task_norm: 归一化后的任务描述。
        synonyms: ``build_synonym_map`` 的输出。

    Returns:
        ``{扩展词: 任务里触发它的那个词}``。来源词用于"一个查询词只贡献一次"
        的去重（见 :func:`_keyword_signal`）。
    """
    extra: dict[str, str] = {}
    if not synonyms:
        return extra
    for raw_term, siblings in synonyms.items():
        term = _norm_term(raw_term)
        if not term or term not in task_norm:
            continue
        for raw_sibling in siblings:
            sibling = _norm_term(raw_sibling)
            if not sibling or sibling in task_norm:
                # 已经是直命中的词不该再按同义词折扣计一次
                continue
            if sibling not in extra:
                extra[sibling] = term
    return extra


def _collect_hits(
    terms: tuple[str, ...], task_norm: str, extra: dict[str, str], idf: dict[str, float]
) -> tuple[float, list[str], list[dict[str, object]]]:
    """命中收集（关键词与标签信号共用同一套规则）。

    Args:
        terms: 该技能的触发词或标签。
        task_norm: 归一化后的任务描述。
        extra: :func:`_expand_task` 的输出。
        idf: :func:`_build_idf` 的输出。

    Returns:
        ``(加权命中总和, 命中的原始术语列表, 同义词命中明细)``。加权和的算法是
        **按来源查询词分组取最大值再求和**：

        - 直命中得 ``idf``，同义词命中得 ``idf * SYNONYM_HIT_WEIGHT``；
        - 同一个来源查询词无论命中多少兄弟词，只取最高分的那一次。

        第二条是为了防"一个泛化词刷多份分"：``报错`` 会同时扩展出
        ``异常`` 与 ``错误处理``，若逐个累加，仅凭一个词就能把
        "异常处理"技能刷到接近满分，从而压过真正匹配 ``SpotBugs`` 的技能。

        去重按"命中种类 + 来源"分组：直命中记在 ``("d", 词)`` 下，同义词命中
        记在 ``("s", 来源词)`` 下。两者必须分开——``设计系统`` 既是
        ``ui-design-tokens`` 的直命中词，又扩展出 ``design-tokens``，
        这两份分来自**不同证据**，理应都算。
    """
    best_by_source: dict[tuple[str, str], float] = {}
    ordered: list[tuple[float, str]] = []
    synonym_hits: list[dict[str, object]] = []
    for term in terms:
        word = _norm_term(term)
        if not word:
            continue
        if word in task_norm:
            weight = _idf_of(word, idf)
            source = ("d", word)
        elif word in extra:
            weight = _idf_of(word, idf) * SYNONYM_HIT_WEIGHT
            source = ("s", extra[word])
            synonym_hits.append(
                {"query": extra[word], "matched": term, "discount": SYNONYM_HIT_WEIGHT}
            )
        else:
            continue
        ordered.append((weight, term))
        if weight > best_by_source.get(source, 0.0):
            best_by_source[source] = weight
    total = 0.0
    for value in best_by_source.values():
        total += value
    # 证据本身按权重降序：给宿主看的 reason 必须**先报最能区分的那几个词**，
    # 否则会出现"命中触发词 ui/组件"这种"全是泛化词、看不出为什么"的解释。
    ordered.sort(key=lambda item: -item[0])
    return total, [name for _, name in ordered], synonym_hits


def _saturate(total: float) -> float:
    """把加权命中和压到 ``0~1``（``KEYWORD_FULL_HITS`` 个满权重命中即满分）。"""
    score = total / KEYWORD_FULL_HITS
    if score > 1.0:
        return 1.0
    if score < 0.0:
        return 0.0
    return score


def _keyword_signal(
    triggers: tuple[str, ...], task_norm: str, extra: dict[str, str], idf: dict[str, float]
) -> tuple[float, float, list[str], list[dict[str, object]]]:
    """关键词信号：``(0~1 分数, 加权命中和, 命中的触发词, 同义词命中明细)``。"""
    total, matched, synonym_hits = _collect_hits(triggers, task_norm, extra, idf)
    return _saturate(total), total, matched, synonym_hits


def _tag_signal(
    tags: tuple[str, ...], task_norm: str, extra: dict[str, str], idf: dict[str, float]
) -> tuple[float, float, list[str], list[dict[str, object]]]:
    """标签信号：``(0~1 分数, 加权命中和, 命中的标签, 同义词命中明细)``。无标签时全零。

    归一化分母与关键词信号**一致**（``KEYWORD_FULL_HITS``），不再用
    ``len(tags)``：标签少的技能不该因为"分母小"而更容易得高分。
    """
    if not tags:
        return 0.0, 0.0, [], []
    total, matched, synonym_hits = _collect_hits(tags, task_norm, extra, idf)
    return _saturate(total), total, matched, synonym_hits


def _normalize(weights: dict[str, float]) -> dict[str, float]:
    """把权重按总和摊还到 1.0（这就是 C-1 要求的"按比例摊还"）。"""
    total = sum(weights.values())
    if total <= 0:
        return {}
    return {name: value / total for name, value in weights.items()}


def _score_all(
    task: str,
    skills: list[Skill],
    cfg,
    history: dict[str, float] | None = None,
    synonyms: dict[str, tuple[str, ...]] | None = None,
) -> tuple[list[MatchResult], list[dict[str, object]]]:
    """共享打分主循环：返回 ``(results, explain)``。

    与 :func:`match` 同源——分数、排序、阈值、``top_n`` 完全一致（纯函数语义），
    额外为每条命中收集可解释信息。``results`` 已应用置信度标注；``explain``
    与 ``results`` 一一对应。
    """
    history = history or {}
    synonyms = synonyms or {}
    task_norm = _norm_term(task)
    extra = _expand_task(task_norm, synonyms)
    # IDF 按本次候选集现算：不落盘、不跨调用缓存，match() 仍是纯函数。
    idf = _build_idf(skills)

    # ---- 判定各信号是否可用（纯数据驱动，无 Tier 分支）----
    tag_available = any(skill.tags for skill in skills)
    semantic_available = False  # WS-2 不做 BM25（§12.6.2）
    history_available = bool(history)

    available = {
        "keyword": True,
        "tag": tag_available,
        "semantic": semantic_available,
        "history": history_available,
    }
    active_weights = {
        name: cfg.weight(name)
        for name in ("keyword", "tag", "semantic", "history")
        if available[name] and cfg.weight(name) > 0
    }
    norm = _normalize(active_weights)

    # (展示分数, 未截断的加权命中和, slug, skill_id, 结果, 解释)
    # 第 2 个字段只用于**并列时的决胜**：两个技能都被顶到 1.0（信号饱和）时，
    # 「实际命中更强」的那个应该排前面，而不是靠 slug 字典序碰运气。
    ranked: list[tuple[float, float, str, str, MatchResult, dict[str, object]]] = []
    for skill in skills:
        signals: dict[str, float] = {}
        reason_parts: list[str] = []
        signal_total = 0.0
        synonym_hits: list[dict[str, object]] = []

        keyword_score, keyword_hits, matched_keywords, kw_syn = _keyword_signal(
            skill.triggers, task_norm, extra, idf
        )
        signals["keyword"] = keyword_score
        signal_total += keyword_hits
        synonym_hits.extend(kw_syn)
        if matched_keywords:
            shown = "/".join(matched_keywords[:3])
            reason_parts.append(f"命中触发词 {shown}")

        matched_tags: list[str] = []
        if tag_available:
            tag_score, tag_hits, matched_tags, tag_syn = _tag_signal(
                skill.tags, task_norm, extra, idf
            )
            signals["tag"] = tag_score
            signal_total += tag_hits
            synonym_hits.extend(tag_syn)
            if matched_tags:
                reason_parts.append(f"标签命中 {len(matched_tags)}/{len(skill.tags)}")

        if history_available:
            rate = float(history.get(skill.id, 0.0))
            signals["history"] = rate
            if rate > 0:
                reason_parts.append(f"历史采纳率 {rate:.2f}")

        if not norm:
            score = 0.0
        else:
            score = sum(norm[name] * signals.get(name, 0.0) for name in norm)
        if score > 1.0:
            score = 1.0
        if score < 0.0:
            score = 0.0

        if score < cfg.threshold:
            continue

        result = MatchResult(
            skill_id=skill.id,
            name=skill.name,
            slug=skill.slug,
            summary=skill.summary,
            path=skill.display_path(),
            score=round(score, 4),
            reason="；".join(reason_parts) if reason_parts else "弱匹配",
        )

        # IDF 只列本次实际命中的词（原始术语 → 权重）
        idf_hits: dict[str, float] = {}
        for raw in matched_keywords + matched_tags:
            word = _norm_term(raw)
            if word:
                idf_hits[raw] = _idf_of(word, idf)

        detail: dict[str, object] = {
            "skill_id": skill.id,
            "name": skill.name,
            "score": result.score,
            "signals": {name: signals[name] for name in norm},
            "weights": dict(active_weights),
            "matched_keywords": matched_keywords,
            "matched_tags": matched_tags,
            "synonym_hits": synonym_hits,
            "idf": idf_hits,
        }
        ranked.append(
            (result.score, signal_total, result.slug, result.skill_id, result, detail)
        )

    # 排序必须稳定：同分时按 slug 再按 id，避免每次结果顺序抖动（R-17）
    ranked.sort(key=lambda item: (-item[0], -item[1], item[2], item[3]))
    _apply_confidence(ranked)

    top = ranked[: max(1, int(cfg.top_n))]
    return [item[4] for item in top], [item[5] for item in top]


def _apply_confidence(
    ranked: list[tuple[float, float, str, str, MatchResult, dict[str, object]]],
) -> None:
    """排序后为每条命中标注置信度等级，并把并列提示追加到第一名 reason 末尾。

    纯展示，不改分数：
    - ``score >= 0.8`` → 高；``0.5 <= score < 0.8`` → 中；``< 0.5`` → 低；
    - 第一名与第二名分差 < 0.05 时，第一名 reason 末尾追加并列提示。
    """
    if not ranked:
        return
    top_score = ranked[0][0]
    second_score = ranked[1][0] if len(ranked) > 1 else None
    for index, item in enumerate(ranked):
        result = item[4]
        if result.score >= 0.8:
            level = "高"
        elif result.score >= 0.5:
            level = "中"
        else:
            level = "低"
        suffix = ""
        if index == 0 and second_score is not None and (top_score - second_score) < 0.05:
            suffix = f"（存在并列候选，分差 {top_score - second_score:.2f}）"
        result.reason = f"[{level}] {result.reason}{suffix}"


def match(
    task: str,
    skills: list[Skill],
    cfg,
    history: dict[str, float] | None = None,
    synonyms: dict[str, tuple[str, ...]] | None = None,
) -> list[MatchResult]:
    """对一批 skill 打分并排序（与改造前分数完全一致）。

    Args:
        task: 任务描述原文（**只在内存中使用，不写库、不写日志**）。
        skills: 候选 skill（``status='active'``）。
        cfg: :class:`~sfx.infra.conf.Config`。
        history: ``{skill_id: 0~1}``；``None`` 或空字典表示"信号不可用"。
        synonyms: 同义词查表字典；``None`` 视为空。

    Returns:
        降序排列的 :class:`MatchResult` 列表（已应用 ``top_n`` 与 ``threshold``）。
    """
    results, _ = _score_all(task, skills, cfg, history, synonyms)
    return results


def match_explain(
    task: str,
    skills: list[Skill],
    cfg,
    history: dict[str, float] | None = None,
    synonyms: dict[str, tuple[str, ...]] | None = None,
) -> tuple[list[MatchResult], list[dict[str, object]]]:
    """与 :func:`match` 同源打分，额外返回每条命中的可解释信息。

    Returns:
        ``(results, explain)``。``explain[i]`` 与 ``results[i]`` 一一对应，字段：
        ``skill_id`` / ``name`` / ``score`` / ``signals`` / ``weights`` /
        ``matched_keywords`` / ``matched_tags`` / ``synonym_hits`` / ``idf``。
    """
    return _score_all(task, skills, cfg, history, synonyms)
