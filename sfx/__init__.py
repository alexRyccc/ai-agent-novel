"""SkillForge 主包（CLI 名 ``sfx``）。

约束（ARCH §2.4 P-1）
--------------------
本模块位于 ``sfx match`` 热路径的导入链最顶端，**只允许 import 极轻量的东西**。
这里只放版本号常量，任何重量级 stdlib 模块（``json`` / ``sqlite3`` /
``importlib.resources`` / ``http.server`` / ``argparse`` 等）一律禁止在此导入。

Python 要求：>= 3.11（ARCH §9.4）。
"""

from __future__ import annotations

#: CLI / 引擎版本号，写入统一信封的 ``engine_version`` 之外的元信息
__version__ = "0.3.0"

#: 包内资源目录名（ARCH §3.1）。只能通过 ``sfx._res`` 读取。
DATA_DIR = "_data"

#: Walking Skeleton 阶段的匹配引擎标识。
#: 正式版目标是 ``rule+bm25+v1``（ARCH §7.2.2），但 WS-2 明确不做 BM25（§12.6.2），
#: 因此这里如实上报 ``rule+dict+v1``（关键词 + 同义词词典），避免"报一个还没实现的引擎"。
ENGINE_VERSION = "rule+dict+v1"

#: 统一信封的 Schema 标识（ARCH §5.1，冻结）
ENVELOPE_SCHEMA = "sfx.v1"
