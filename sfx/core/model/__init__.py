"""领域模型（ARCH §2.4 P-6：完整类型标注 + ``__slots__``）。

.. note:: 本包的类刻意**不使用** ``@dataclass``。
    实测 ``import dataclasses`` 会连带拉起 ``inspect``/``ast``/``dis``/``typing``，
    累计 +38.6ms，对 ``sfx match`` 的 300ms 预算（NFR-05）是不可接受的。
    改用显式 ``__slots__`` + 完整类型标注，保留 P-6 的实质；
    详细说明见 :class:`sfx.core.model.skill.Skill` 的 docstring。
"""

from __future__ import annotations
