"""领域对象：Skill（ARCH §4.1 / §4.3 ``skills`` 表）。

约束
----
- 主键 ``id`` 一律 uuidv7 字符串（D-3，禁止 AUTOINCREMENT）。
- ``triggers`` / ``tags`` 在 DB 中以 JSON 文本列存储（``triggers_json`` /
  ``tags_json``），这里对外暴露为元组，避免调用方直接碰 JSON 字符串。
- **不含正文**：Skill 只携带元数据。SKILL.md 正文永远不进内存常驻结构，
  这是"路由卡不得包含正文"（防上下文爆炸）的第一道闸门。
"""

from __future__ import annotations

import json

#: 状态枚举（ARCH §10.4：常量集中，禁止散落字符串字面量）
STATUS_ACTIVE = "active"
STATUS_DISABLED = "disabled"
STATUS_DELETED = "deleted"


class Skill:
    """一个 skill 的元数据记录。

    .. note:: **为什么这里不用 ``@dataclass(slots=True)``**（对 ARCH §2.4 P-6 的有意偏离）

       本机 ``python -X importtime`` 实测：``import dataclasses`` 累计 **38.6ms**——
       它会在模块顶层拉起 ``inspect`` → ``ast`` / ``dis`` / ``typing``。
       ``Skill`` 位于 ``sfx match`` 的热路径上，而 NFR-05 的 p95 预算只有 300ms，
       这 38.6ms 占了 13%，实测足以让 zipapp 形态的 p95 从 272ms 顶到 314ms（超线）。

       改用显式 ``__slots__`` + 完整类型标注后：
         - P-6 的**实质**（无编译期检查 → 靠标注补偿；``slots`` → 内存/属性访问可控）
           完整保留；
         - 只放弃了"少写 ``__init__``"这点样板收益。
       这是"宁可多写 20 行，也要守住冷启动红线"的取舍。
    """

    __slots__ = (
        "id", "name", "slug", "summary", "description", "source_root", "dir_path",
        "entry_path", "author", "version", "status", "content_hash", "body_bytes",
        "triggers", "tags", "summary_fallback",
        "created_at", "updated_at", "last_scanned_at",
    )

    def __init__(
        self,
        id: str = "",
        name: str = "",
        slug: str = "",
        summary: str = "",
        description: str = "",
        source_root: str = "",
        dir_path: str = "",
        entry_path: str = "",
        author: str = "",
        version: int = 1,
        status: str = STATUS_ACTIVE,
        content_hash: str = "",
        body_bytes: int = 0,
        triggers: tuple[str, ...] = (),
        tags: tuple[str, ...] = (),
        summary_fallback: bool = False,
        created_at: str = "",
        updated_at: str = "",
        last_scanned_at: str = "",
    ) -> None:
        self.id = id
        self.name = name
        self.slug = slug
        self.summary = summary
        self.description = description
        self.source_root = source_root
        self.dir_path = dir_path
        self.entry_path = entry_path
        self.author = author
        self.version = version
        self.status = status
        self.content_hash = content_hash
        self.body_bytes = body_bytes
        self.triggers = triggers
        self.tags = tags
        # True 表示 summary 是"缺失兜底"生成的（ARCH §12.6.2.1 **C-2**），
        # Tier B 索引与 Web 页面据此提示"元数据待补全"。
        self.summary_fallback = summary_fallback
        self.created_at = created_at
        self.updated_at = updated_at
        self.last_scanned_at = last_scanned_at

    # ------------------------------------------------------------------
    def display_path(self) -> str:
        """给宿主看的路径：**操作系统原生分隔符的绝对路径**（NN-4，禁止 ``~``）。"""
        return self.entry_path

    def to_row(self) -> tuple:
        """转成 ``skills`` 表的插入/更新参数元组（列顺序与 SQL 一致）。"""
        return (
            self.id,
            self.name,
            self.slug,
            self.summary,
            self.description,
            self.source_root,
            self.dir_path,
            self.entry_path,
            self.author,
            self.version,
            self.status,
            self.content_hash,
            self.body_bytes,
            json.dumps(list(self.triggers), ensure_ascii=False),
            json.dumps(list(self.tags), ensure_ascii=False),
            1 if self.summary_fallback else 0,
            self.created_at,
            self.updated_at,
            self.last_scanned_at,
        )

    @staticmethod
    def from_row(row: tuple) -> "Skill":
        """从 ``skills`` 表的一行还原对象。JSON 列解析失败时退化为「空列表 + 不抛异常」。

        为什么容错：一条 skill 的 tags 写坏了，不该让整个 ``sfx match`` 失败
        （NFR-07 E-2 精神：绝不阻塞 Metis）。
        """
        triggers = _load_json_list(row[13])
        tags = _load_json_list(row[14])
        version = row[9]
        if not isinstance(version, int):
            try:
                version = int(version)
            except (TypeError, ValueError):
                version = 1
        return Skill(
            id=row[0] or "",
            name=row[1] or "",
            slug=row[2] or "",
            summary=row[3] or "",
            description=row[4] or "",
            source_root=row[5] or "",
            dir_path=row[6] or "",
            entry_path=row[7] or "",
            author=row[8] or "",
            version=version,
            status=row[10] or STATUS_ACTIVE,
            content_hash=row[11] or "",
            body_bytes=row[12] or 0,
            triggers=triggers,
            tags=tags,
            summary_fallback=bool(row[15]),
            created_at=row[16] or "",
            updated_at=row[17] or "",
            last_scanned_at=row[18] or "",
        )


def _load_json_list(text: object) -> tuple[str, ...]:
    """解析 JSON 数组列；任何异常都退化为「空元组」而不是抛错。"""
    if not text:
        return ()
    try:
        data = json.loads(str(text))
    except (TypeError, ValueError):
        return ()
    if isinstance(data, list):
        return tuple(str(item) for item in data)
    return ()
