"""SKILL.md 解析：front-matter + 正文元数据抽取（ARCH §3.2 / WS-2 W2-2）。

本模块是 scanner 的"单文件"处理单元：**一个文件解析失败绝不中断整体扫描**
（ARCH §2.2.3 / FR-02）。

**C-2 前置约束（ARCH §12.6.2.1）**
---------------------------------
``parser`` 必须抽取 ``summary`` 并**实现缺失兜底**：
缺失时取 ``description`` 前 40 字并追加 ``元数据待补全`` 标记，同时置
``summary_fallback=True``。原因：Tier B 的路由索引"摘要"列复用同一字段，
若 WS-2 不抽，Tier B 阶段要回头改 parser **并重扫全部 skill**（0.1 人日 → 数小时返工）。
"""

from __future__ import annotations

import hashlib
import os

from sfx import _frontmatter as fm
from sfx import _ids
from sfx.core.model.skill import STATUS_ACTIVE, Skill
from sfx.infra import pathx

#: 兜底摘要截取长度（ARCH §12.6.2.1 C-2 明确规定"前 40 字"）
SUMMARY_FALLBACK_CHARS = 40
#: 兜底标记文本
SUMMARY_FALLBACK_TAG = " 元数据待补全"

#: front-matter 里可承载触发词的字段名（按优先级；允许不同团队写法）
TRIGGER_FIELDS = ("triggers", "keywords", "trigger", "keyword")
#: front-matter 里承载标签的字段名
TAG_FIELDS = ("tags", "tag", "categories", "category")


class ParseError(Exception):
    """单文件解析失败（结构不可恢复 / IO 错误）。由 scanner 转为 skip 记录。"""

    __slots__ = ("line_no", "reason")

    def __init__(self, reason: str, line_no: int = 0) -> None:
        super().__init__(reason)
        self.reason = reason
        self.line_no = line_no


def slugify(text: str) -> str:
    """生成 URL/slug 安全的标识。

    中文保留（``str.isalnum()`` 对 CJK 返回 True），其余字符折叠为 ``-``。
    空结果由调用方兜底。
    """
    out: list[str] = []
    pending_dash = False
    for ch in text.strip().lower():
        if ch.isalnum():
            out.append(ch)
            pending_dash = False
        elif not pending_dash:
            out.append("-")
            pending_dash = True
    return "".join(out).strip("-")


def _as_str_list(value: object) -> tuple[str, ...]:
    """把 front-matter 里的列表/标量统一成字符串元组。"""
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        items = [str(item).strip() for item in value if str(item).strip()]
    else:
        text = str(value).strip()
        items = [part.strip() for part in text.split(",") if part.strip()]
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return tuple(ordered)


def _as_int(value: object, default: int) -> int:
    """宽松转 int。"""
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return default


def _first_str(fields: dict[str, object], keys: tuple[str, ...]) -> str:
    """按顺序取第一个非空字符串字段。"""
    for key in keys:
        value = fields.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _raw_snippet(raw_fields: dict[str, str], key: str, limit: int) -> str:
    """从降级保留的原文里抠出可读片段（首行是 ``key: |``，跳过它）。

    真实世界的 SKILL.md 大量使用折叠块标量（``description: >-``）写长描述，
    解析器会按 §2.2.3 降级为 raw。此时仍能从中取出前若干字符用于摘要兜底，
    比让 summary 退化成"只有 skill 名"要有用得多。
    """
    raw = raw_fields.get(key) or ""
    lines = raw.splitlines()[1:]
    text = " ".join(line.strip() for line in lines if line.strip())
    return text[:limit].strip()


def read_text(path: str) -> tuple[str, bytes]:
    """读取 SKILL.md 原文。

    Returns:
        ``(文本, 原始字节)``。文本用于解析，字节用于 hash 与体积统计。

    Raises:
        ParseError: 文件不存在 / 无权限 / 编码异常。
    """
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
    except OSError as exc:
        raise ParseError(f"无法读取文件：{exc.strerror or exc}") from exc
    try:
        return raw.decode("utf-8"), raw
    except UnicodeDecodeError:
        # 编码坏了也不能丢掉整个 skill：用 replacement 解码，正文仍可入库
        return raw.decode("utf-8", errors="replace"), raw


def parse_skill_file(
    entry_path: str, source_root: str, now_text: str
) -> tuple[Skill, list[dict[str, object]]]:
    """解析一个 SKILL.md 文件，产出 :class:`Skill` 元数据。

    Args:
        entry_path: SKILL.md 的绝对路径。
        source_root: 该 skill 所属的来源根（用于唯一性判定）。
        now_text: RFC3339 UTC 时间戳（应用层生成，D-5）。

    Returns:
        ``(skill, warnings)``。

    Raises:
        ParseError: front-matter 结构不可恢复（带行号）或文件不可读。
            调用方按 FR-02 跳过该文件，整体扫描继续。
    """
    text, raw = read_text(entry_path)
    try:
        doc = fm.parse_document(text)
    except fm.FrontMatterError as exc:
        raise ParseError(exc.message, exc.line_no) from exc

    warnings: list[dict[str, object]] = []
    for item in doc.warnings:
        warnings.append(
            {
                "path": entry_path,
                "line": item.get("line", 0),
                "key": str(item.get("key", "")),
                "reason": str(item.get("reason", "")),
            }
        )

    dir_path = os.path.dirname(entry_path)
    dir_name = os.path.basename(dir_path) or "skill"
    fields = doc.fields

    raw_name = fields.get("name")
    name = str(raw_name).strip() if raw_name not in (None, "") else dir_name
    if not name:
        name = dir_name

    # 真实 SKILL.md 里 description 常被写成折叠块标量（``>-``）而降级为 raw，
    # 因此按“解析值 → 中文/英文变体 → raw 片段”的顺序多级兜底。
    description = _first_str(fields, ("description", "description_zh", "description_en"))
    if not description:
        description = _raw_snippet(doc.raw_fields, "description", 240)

    # ---- C-2：summary 抽取与缺失兜底 ----
    raw_summary = fields.get("summary")
    summary_fallback = False
    if isinstance(raw_summary, str) and raw_summary.strip():
        summary = raw_summary.strip()
    else:
        base = description[:SUMMARY_FALLBACK_CHARS].strip()
        if not base:
            base = name[:SUMMARY_FALLBACK_CHARS]
        summary = f"{base}{SUMMARY_FALLBACK_TAG}" if base else SUMMARY_FALLBACK_TAG.strip()
        summary_fallback = True
        warnings.append(
            {
                "path": entry_path,
                "line": 0,
                "key": "summary",
                "reason": "summary_missing_fallback",
            }
        )

    # ---- 触发词与标签 ----
    tags: list[str] = []
    for field_name in TAG_FIELDS:
        tags.extend(_as_str_list(fields.get(field_name)))

    trigger_pool: list[str] = []
    for field_name in TRIGGER_FIELDS:
        trigger_pool.extend(_as_str_list(fields.get(field_name)))
    # 标签与展示名**本质上就是关键词**。WS 阶段没有 BM25（§12.6.2），
    # 把它们并入触发词池能显著提升真实 SKILL.md 的召回——
    # 实测本机大量 skill 只写了 tags，不写 triggers，不并进来几乎匹配不到任何东西。
    trigger_pool.extend(tags)
    display_name = _first_str(fields, ("display_name", "title", "display_name_zh"))
    if display_name:
        trigger_pool.append(display_name)
    if name:
        trigger_pool.append(name)  # skill 名本身就是最强的触发词

    seen_trigger: set[str] = set()
    triggers: list[str] = []
    for word in trigger_pool:
        if word and word not in seen_trigger:
            seen_trigger.add(word)
            triggers.append(word)

    slug = slugify(name) or f"skill-{hashlib.sha256(raw).hexdigest()[:6]}"
    content_hash = hashlib.sha256(raw).hexdigest()

    skill = Skill(
        # 主键一律 uuidv7（D-3：禁止 AUTOINCREMENT，且时间有序便于游标分页）
        id=_ids.uuid7(),
        name=name,
        slug=slug,
        summary=summary,
        description=description,
        source_root=source_root,
        dir_path=dir_path,
        # 对外路径一律走 pathx.native()：确保是**操作系统原生分隔符**的绝对路径，
        # 便于 Metis 直接拿去 Read（ARCH §10.1 规则 3 / NN-4）。
        entry_path=pathx.native(entry_path),
        author=str(fields.get("author") or "").strip(),
        version=_as_int(fields.get("version"), 1),
        status=STATUS_ACTIVE,
        content_hash=content_hash,
        body_bytes=len(raw),
        triggers=tuple(triggers),
        tags=tuple(tags),
        summary_fallback=summary_fallback,
        created_at=now_text,
        updated_at=now_text,
        last_scanned_at=now_text,
    )
    return skill, warnings
