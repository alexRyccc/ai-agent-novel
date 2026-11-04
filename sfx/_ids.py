"""手写 UUIDv7 与轻量哈希（ARCH §2.1 / §10.5）。

为什么不用 stdlib ``uuid``
--------------------------
1. stdlib ``uuid`` 只有 v4（随机），**不具备时间有序性**，而 ARCH §10.5 要求
   "时间有序，适合游标分页"；
2. 实测 ``import uuid`` 增量 +31.4ms（ARCH §2.1），在 ``sfx match`` 热路径上是纯浪费。

UUIDv7 布局（RFC 9562）
----------------------
::

     0                   1                   2                   3
     00000000-0000-7000-8000-000000000000
     |------| |--| |--| |--| |----------|
     unix_ts_ms(48) ver(4) rand_a(12) var(2) rand_b(62)

高位 48 bit 是毫秒时间戳，因此**按字典序排序 == 按时间排序**，这正是索引需要的性质。

为什么还要一个 FNV-1a
---------------------
``sessions.task_hash`` 需要一个**跨进程稳定**的摘要（ARCH §10.3 禁止日志/库里存
任务正文）。内置的 ``hash()`` 每次进程随机加盐，不可用；``hashlib`` 实测 +53.8ms，
为一个 32bit 摘要付 53ms 不划算。故手写 FNV-1a（确定性、零导入、对短文本足够）。
"""

from __future__ import annotations

import os
import time

#: FNV-1a 32 位参数
_FNV_OFFSET = 0x811C9DC5
_FNV_PRIME = 0x01000193
_MASK32 = 0xFFFFFFFF

#: 单调递增状态：同一毫秒内靠 ``counter`` 递增，保证**进程内严格有序**。
#: （RFC 9562 允许 rand_a 用计数器替代随机数；我们两者结合：
#:   毫秒变化时 counter 重新随机化 → 跨进程仍不碰撞，
#:   毫秒不变时 counter 递增 → 同一进程内字典序严格递增。）
_state = {"last_ms": 0, "counter": 0}


def uuid7() -> str:
    """生成一个新的 UUIDv7 字符串（小写，带连字符，36 字符）。

    性质：
      - **时间有序**：高 48 bit 是毫秒时间戳，跨毫秒天然递增；
      - **同毫秒内也递增**：``rand_a`` 位置放单调递增计数器（RFC 9562 允许的变体）；
      - 跨进程唯一：低位 62 bit 与计数器的初值来自 ``os.urandom``。

    线程安全说明：本函数**假定单线程调用**（CLI 内所有 ID 都在主线程生成）。
    若将来引入并发写入，需在此加一把锁——目前加锁的收益低于它引入的 import 成本。
    """
    ms = time.time_ns() // 1_000_000
    if ms == _state["last_ms"]:
        _state["counter"] += 1
        if _state["counter"] > 0x0FFF:
            # 同一毫秒内 4096 个已用完：等下一毫秒，绝不重复
            while ms == _state["last_ms"]:
                time.sleep(0.0002)
                ms = time.time_ns() // 1_000_000
            _state["last_ms"] = ms
            _state["counter"] = int.from_bytes(os.urandom(2), "big") & 0x0FFF
    else:
        _state["last_ms"] = ms
        _state["counter"] = int.from_bytes(os.urandom(2), "big") & 0x0FFF

    rand_a = _state["counter"] & 0x0FFF
    rand_b = int.from_bytes(os.urandom(8), "big") & ((1 << 62) - 1)
    value = (
        ((ms & ((1 << 48) - 1)) << 80)
        | (0x7 << 76)
        | (rand_a << 64)
        | (0x2 << 62)
        | rand_b
    )
    # 手工拼 8-4-4-4-12，等价于 uuid 的标准文本形式
    hexs = f"{value:032x}"
    return "-".join(
        (hexs[0:8], hexs[8:12], hexs[12:16], hexs[16:20], hexs[20:32])
    )


def fnv1a_hex(text: str) -> str:
    """计算字符串的 FNV-1a 32 位摘要，返回 8 位小写十六进制。

    注意：这是**非加密**哈希，仅用于日志/库里的去重与关联，绝不用于口令或签名。
    """
    h = _FNV_OFFSET
    for ch in text:
        h ^= ord(ch)
        h = (h * _FNV_PRIME) & _MASK32
    return f"{h:08x}"
