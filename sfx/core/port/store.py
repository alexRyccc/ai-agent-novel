"""端口协议（依赖倒置，ARCH §4.2 / NFR-09）。

``core`` 层只依赖这些 ``Protocol``，**不依赖任何具体数据库**。
SQLite → 服务端库的切换只需替换 ``infra/`` 下的实现，``core`` 零改动（FR-29 / NFR-06）。

为什么用 ``typing.Protocol`` 而不是 ABC
--------------------------------------
结构化子类型（duck typing）不需要实现类显式继承，也就不需要 ``core`` 去 import
``infra``——依赖方向被物理切断（NFR-09）。

性能注意
--------
本模块会被 import 到 ``typing``（约 +10~30ms）。``sfx match`` 热路径**不 import 它**；
它由架构测试 ``tests/test_arch_imports.py`` 与 IDE 静态检查消费。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from sfx.core.model.event import CallEvent, Session
from sfx.core.model.skill import Skill


@runtime_checkable
class SkillRepoPort(Protocol):
    """skill 持久化端口。"""

    def find_key(self, source_root: str, dir_path: str) -> tuple[str, str] | None:
        """按来源根 + 目录定位已有记录，返回 ``(id, content_hash)``。"""
        ...

    def upsert(self, skill: Skill) -> str:
        """插入或更新，返回 ``added`` / ``updated`` / ``unchanged``。"""
        ...

    def list_active(self) -> list[Skill]:
        """列出全部启用中的 skill（**不含正文**）。"""
        ...

    def count(self, status: str | None = None) -> int:
        """计数。"""
        ...

    def commit(self) -> None:
        """提交事务。"""
        ...


@runtime_checkable
class EventRepoPort(Protocol):
    """埋点持久化端口。"""

    def insert_session(self, session: Session) -> None:
        """写入会话记录。"""
        ...

    def insert_events(self, events: list[CallEvent]) -> None:
        """批量写入调用事件。"""
        ...

    def history_scores(self) -> dict[str, float]:
        """history 信号；不可用时返回空字典。"""
        ...

    def commit(self) -> None:
        """提交事务。"""
        ...


@runtime_checkable
class StorePort(Protocol):
    """聚合根：一次业务操作所需的所有 Repository。"""

    def skills(self) -> SkillRepoPort:
        """skill 仓储。"""
        ...

    def events(self) -> EventRepoPort:
        """埋点仓储。"""
        ...

    def close(self) -> None:
        """释放连接。"""
        ...
