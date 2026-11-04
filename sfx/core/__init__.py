"""L0 内核：领域模型、端口协议、业务服务（ARCH §1.2 / NFR-09）。

依赖方向：``core`` **不得** import ``adapter`` / ``cli``；
持久化一律经 ``core.port`` 的 Protocol，SQL 只出现在 ``infra``。
"""

from __future__ import annotations
