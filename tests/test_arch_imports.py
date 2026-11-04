"""架构纪律测试：分层依赖方向与顶层 import 白名单（ARCH §1.2 / §2.4 P-1 / P-2）。

这是把"架构约束"固化成可执行断言的地方。违反任何一条都应该让 CI 失败：
  - **P-1 import 纪律**：重量级 stdlib（``http.server`` / ``importlib.resources`` /
    ``secrets`` / ``socketserver`` / ``string`` / ``argparse`` / ``uuid``）
    **绝不能出现在模块顶层**——实测它们的导入成本是 55~205ms，
    出现在 ``sfx match`` 热路径上会直接击穿 NFR-05 的 300ms 红线。
  - **P-2 资源访问层**：任何模块都不得用 ``open()`` 读 ``_data/`` 下的包内资源
    （zipapp 里根本没有独立文件路径，只能经 ``sfx/_res.py``）。
  - **NFR-09 分层**：``core/`` 不得出现 SQL 字面量，也不得 import ``infra`` / ``cli``。
"""

from __future__ import annotations

import ast
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

SFX_DIR = os.path.join(ROOT, "sfx")

#: 禁止出现在**模块顶层**的重量级 stdlib（ARCH §2.1 实测开销）
FORBIDDEN_TOPLEVEL = frozenset({
    "importlib.resources", "http.server", "socketserver", "secrets", "string",
    "argparse", "uuid", "zipfile", "requests", "yaml",
})

#: SQL 关键字（``core/`` 层不得出现，D-4）
SQL_LITERAL_MARKERS = ("SELECT ", "INSERT INTO ", "UPDATE ", "DELETE FROM ", "CREATE TABLE ")


def _iter_python_files(root: str):
    """遍历包内所有 ``*.py``（跳过构建产物）。"""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in ("__pycache__", "build", "dist")]
        for filename in sorted(filenames):
            if filename.endswith(".py"):
                yield os.path.join(dirpath, filename)


def _parse(path: str):
    """读取并解析一个源文件。"""
    with open(path, "r", encoding="utf-8") as handle:
        return ast.parse(handle.read(), filename=path)


def _toplevel_module_names(tree) -> list[str]:
    """收集模块顶层（非函数/类体内）的 import 目标模块名。"""
    names: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                names.append(node.module)
    return names


def _relative(path: str) -> str:
    return os.path.relpath(path, ROOT).replace("\\", "/")


class TestImportDiscipline(unittest.TestCase):
    """P-1：顶层 import 纪律。"""

    def test_no_heavy_stdlib_at_module_top_level(self) -> None:
        """重量级模块只允许在函数体内延迟导入。"""
        offenders: list[str] = []
        for path in _iter_python_files(SFX_DIR):
            tree = _parse(path)
            for name in _toplevel_module_names(tree):
                top = name.split(".")[0]
                if name in FORBIDDEN_TOPLEVEL or top in {"yaml", "requests"}:
                    offenders.append(f"{_relative(path)}: {name}")
        self.assertEqual(offenders, [], "违反 P-1（顶层重量级 import）：\n" + "\n".join(offenders))

    def test_importlib_resources_is_never_toplevel(self) -> None:
        """``importlib.resources`` 实测 +205ms，必须延迟导入（P-2）。"""
        offenders: list[str] = []
        for path in _iter_python_files(SFX_DIR):
            tree = _parse(path)
            for name in _toplevel_module_names(tree):
                if name.startswith("importlib"):
                    offenders.append(f"{_relative(path)}: {name}")
        self.assertEqual(offenders, [], "\n".join(offenders))

    def test_main_module_has_name_guard(self) -> None:
        """``__main__.py`` 必须有 ``if __name__ == "__main__"`` 守卫（zipapp 坑 2）。"""
        path = os.path.join(SFX_DIR, "__main__.py")
        tree = _parse(path)
        guarded = False
        for node in tree.body:
            if not isinstance(node, ast.If):
                continue
            test = node.test
            if (
                isinstance(test, ast.Compare)
                and isinstance(test.left, ast.Name)
                and test.left.id == "__name__"
            ):
                guarded = True
        self.assertTrue(guarded, "__main__.py 缺少 __name__ 守卫，会导致 stdout 出现两行 JSON")

    def test_main_does_not_call_main_bare(self) -> None:
        """模块末尾不得出现裸 ``main()`` 调用。"""
        path = os.path.join(SFX_DIR, "__main__.py")
        tree = _parse(path)
        for node in tree.body:
            self.assertFalse(
                isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name)
                and node.value.func.id == "main",
                "__main__.py 不得在模块顶层裸调用 main()",
            )


class TestResourceDiscipline(unittest.TestCase):
    """P-2：资源只能经 ``_res.py`` 读取。"""

    def test_no_open_on_data_dir(self) -> None:
        """不得出现 ``open(..."_data"...)`` 这类直接读包内资源的写法。

        用 AST 找 ``open()`` 调用并检查其字符串参数，避免把 docstring / 注释里的
        "禁止用 open() 读 _data" 误判为违规（文本搜索会假阳性）。
        """
        offenders: list[str] = []
        for path in _iter_python_files(SFX_DIR):
            tree = _parse(path)
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
                    continue
                if node.func.id != "open":
                    continue
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        if "_data" in arg.value:
                            offenders.append(f"{_relative(path)}:{node.lineno}: {arg.value}")
        self.assertEqual(offenders, [], "\n".join(offenders))

    def test_res_reads_through_importlib_resources(self) -> None:
        """``_res.py`` 必须走 ``importlib.resources``。"""
        path = os.path.join(SFX_DIR, "_res.py")
        with open(path, "r", encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn("importlib.resources", source)
        self.assertIn("files(\"sfx\")", source)


class TestLayering(unittest.TestCase):
    """NFR-09：分层依赖方向。"""

    def test_core_has_no_sql(self) -> None:
        """``core/`` 层不得出现 SQL 字面量（D-4：SQL 只在 ``infra``）。"""
        core_dir = os.path.join(SFX_DIR, "core")
        offenders: list[str] = []
        for path in _iter_python_files(core_dir):
            with open(path, "r", encoding="utf-8") as handle:
                source = handle.read()
            for marker in SQL_LITERAL_MARKERS:
                if marker in source:
                    offenders.append(f"{_relative(path)}: 含 SQL 字面量 {marker!r}")
        self.assertEqual(offenders, [], "\n".join(offenders))

    def test_core_does_not_import_persistence_or_cli(self) -> None:
        """``core/`` 不得依赖持久化实现 / ``cli`` / ``adapter``（依赖倒置，NFR-09）。

        例外（有意保留，见 ``matcher`` / ``scanner`` 的用法）：``sfx.infra.pathx``
        是**纯路径计算**（无 IO、无 SQL、无状态），等价于一个工具函数模块，
        ``core`` 可以依赖它。真正必须隔离的是 ``sfx.infra.sqlite`` / ``logx``，
        因为那才是"换数据库就要改"的部分（FR-29 / NFR-06）。
        """
        forbidden_prefixes = ("sfx.infra.sqlite", "sfx.infra.logx", "sfx.cli", "sfx.adapter")
        core_dir = os.path.join(SFX_DIR, "core")
        offenders: list[str] = []
        for path in _iter_python_files(core_dir):
            tree = _parse(path)
            for node in ast.walk(tree):
                module = ""
                if isinstance(node, ast.Import):
                    module = node.names[0].name if node.names else ""
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    module = node.module or ""
                if module.startswith(forbidden_prefixes):
                    offenders.append(f"{_relative(path)}:{getattr(node, 'lineno', 0)}: {module}")
        self.assertEqual(offenders, [], "\n".join(offenders))

    def test_cli_does_not_import_adapter(self) -> None:
        """``cli/`` 只做协议转换，不得直接依赖 adapter 层。"""
        cli_dir = os.path.join(SFX_DIR, "cli")
        offenders: list[str] = []
        for path in _iter_python_files(cli_dir):
            tree = _parse(path)
            for node in ast.walk(tree):
                module = ""
                if isinstance(node, ast.Import):
                    module = node.names[0].name if node.names else ""
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    module = node.module or ""
                if module.startswith("sfx.adapter"):
                    offenders.append(f"{_relative(path)}:{getattr(node, 'lineno', 0)}: {module}")
        self.assertEqual(offenders, [], "\n".join(offenders))


if __name__ == "__main__":
    unittest.main()
