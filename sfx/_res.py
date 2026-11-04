"""包内资源访问层（ARCH §2.3.3 / §2.4 P-2）。

为什么必须有这一层
------------------
zipapp 产物是**一个 zip 文件**。包内资源（迁移 SQL、模板、同义词词典）在
``sfx.pyz`` 里根本没有独立的文件路径，**普通 ``open()`` 必然失败**（zipapp 坑 3）。
唯一可靠入口是 ``importlib.resources``，实测它在"源码目录形态"与"zipapp 形态"
下都能工作。

为什么必须 lazy
--------------
``import importlib.resources`` 实测增量 **+205ms**（本机复测；ARCH §2.1 记录为
+137.7ms，本机更差，因为它会连带拉起 ``zipfile``）。这个代价出现在 ``sfx match``
热路径上是不可接受的，所以：

1. 本模块的 ``import`` 全部写在**函数体内**；
2. 调用方（``infra.sqlite.migrator``）只在"确实需要迁移"时才调用本模块——
   已经迁移过的库完全不付这 205ms；
3. 同义词词典热路径走 ``<home>/cache/synonyms.json``（纯 ``open``+``json``），
   由非热路径的 ``sfx scan`` 预热，见 ``core.service.matcher``。

使用纪律：任何模块都**禁止**用 ``open()`` 读 ``sfx/_data/`` 下的内容。
"""

from __future__ import annotations

_DATA = "_data"


def _resource_path(name: str):
    """返回包内资源的 Path 对象（延迟导入 ``importlib.resources``）。

    Args:
        name: 相对 ``sfx/_data`` 的路径，允许包含 ``/``，如 ``migrations/0001_init.sql``。
    """
    from importlib.resources import files  # 延迟导入：+205ms，绝不放模块顶层

    path = files("sfx") / _DATA
    for part in name.replace("\\", "/").split("/"):
        if part in ("", "."):
            continue
        path = path / part
    return path


def read_text(name: str, encoding: str = "utf-8") -> str:
    """读取包内文本资源。

    Raises:
        OSError: 资源不存在或不可读（调用方负责降级/报错）。
    """
    return _resource_path(name).read_text(encoding=encoding)


def exists(name: str) -> bool:
    """资源是否存在（不读取内容，成本低于 read_text）。"""
    try:
        return _resource_path(name).is_file()
    except (OSError, ValueError, TypeError):
        return False
