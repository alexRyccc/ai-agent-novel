"""零第三方依赖断言（ARCH §9.2 / P-5）—— **CI 必跑，违规即构建失败**。

复用 ``scripts/check_deps.py`` 的同一个实现，避免"脚本与测试两套逻辑"。
"""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

SCRIPT = os.path.join(ROOT, "scripts", "check_deps.py")


def _load_script():
    """按文件路径加载 ``check_deps.py``（它没有 ``.py`` 之外的名字约束）。"""
    spec = importlib.util.spec_from_file_location("check_deps_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestZeroDependency(unittest.TestCase):
    """零依赖断言。"""

    def test_sfx_package_has_no_third_party_import(self) -> None:
        """``sfx/`` 包内不得出现任何非标准库 import。"""
        module = _load_script()
        violations = module.find_violations(os.path.join(ROOT, "sfx"))
        self.assertEqual(
            violations, [],
            msg="发现第三方依赖：\n" + "\n".join(f"{p}:{l}: {m}" for p, l, m in violations),
        )

    def test_stdlib_imports_are_not_reported(self) -> None:
        """``import json`` / ``import sqlite3`` 这类标准库**不得误报**（ARCH §9.2 实测项）。"""
        module = _load_script()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "clean.py")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(
                    "from __future__ import annotations\n"
                    "import json\n"
                    "import sqlite3\n"
                    "import os.path\n"
                    "from dataclasses import dataclass\n"
                    "from sfx import _errors\n"
                )
            self.assertEqual(module.find_violations(tmp), [])

    def test_third_party_imports_are_reported(self) -> None:
        """注入 ``yaml`` / ``click`` / ``jinja2`` 必须被准确报出（含行号）。"""
        module = _load_script()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "dirty.py")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(
                    "import json\n"
                    "import yaml\n"
                    "import click\n"
                    "from jinja2 import Template\n"
                )
            violations = module.find_violations(tmp)
            names = sorted(item[2] for item in violations)
            self.assertEqual(names, ["click", "jinja2", "yaml"])
            lines = sorted(item[1] for item in violations)
            self.assertEqual(lines, [2, 3, 4])


if __name__ == "__main__":
    unittest.main()
