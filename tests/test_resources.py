"""包内资源访问层单测（ARCH §2.3.3 / P-2）。

必须同时覆盖**两种运行形态**：源码目录形态与 zipapp 形态。
zipapp 形态的验证方式是真的起一个子进程跑 ``dist/sfx.pyz doctor``
（``importlib.resources`` 在 zip 内的行为只有真跑才知道）。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from sfx import _res  # noqa: E402

PYZ = os.path.join(ROOT, "dist", "sfx.pyz")


class TestResourceLayer(unittest.TestCase):
    """``_res`` 资源读取。"""

    def test_read_synonyms(self) -> None:
        """能读到同义词词典（源码目录形态）。"""
        text = _res.read_text("synonyms.txt")
        self.assertIn("重构", text)

    def test_read_migration_sql(self) -> None:
        """能读到子目录下的迁移 SQL。"""
        sql = _res.read_text("migrations/0001_init.sql")
        self.assertIn("CREATE TABLE IF NOT EXISTS skills", sql)

    def test_exists(self) -> None:
        """``exists`` 对存在/不存在资源给出正确判定。"""
        self.assertTrue(_res.exists("synonyms.txt"))
        self.assertFalse(_res.exists("no-such-file.txt"))

    def test_missing_resource_raises(self) -> None:
        """读取不存在的资源抛 ``OSError``，由调用方降级。"""
        with self.assertRaises(OSError):
            _res.read_text("no-such-file.txt")

    def test_lazy_import(self) -> None:
        """``importlib.resources`` 必须**不在模块顶层**导入（P-2，实测 +205ms）。

        用 AST 判定而不是搜源码文本：模块 docstring 里必然提到这个名字，
        文本搜索会产生假阳性。
        """
        import ast

        with open(os.path.join(ROOT, "sfx", "_res.py"), "r", encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        top_level: list[str] = []
        for node in tree.body:
            if isinstance(node, ast.Import):
                top_level.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                top_level.append(node.module)
        self.assertEqual(
            [name for name in top_level if name.startswith("importlib")], [],
            "_res.py 顶层不得 import importlib（必须在函数体内延迟导入）",
        )

    @unittest.skipUnless(os.path.isfile(PYZ), "需要先执行 python scripts/build.pyz.py")
    def test_zipapp_form_can_read_resources(self) -> None:
        """zipapp 形态下资源同样可用（真起子进程跑一次 scan 验证）。

        ``scan`` 一定会走 ``migrator.migrate`` → 必然读 ``_data/migrations/0001_init.sql``。
        在 zipapp 里这个文件位于 zip 内部，普通 ``open()`` 取不到；
        能跑通就证明 ``importlib.resources`` 路径在 zipapp 下真的可用（P-2）。
        """
        import tempfile

        env = dict(os.environ)
        for key in list(env):
            if key.startswith("PYTHON"):
                del env[key]
        with tempfile.TemporaryDirectory() as tmp:
            env["SFX_HOME"] = os.path.join(tmp, "home")
            env["SFX_ROOTS"] = os.path.join(ROOT, "tests", "testdata", "skills")
            result = subprocess.run(
                [sys.executable, PYZ, "scan"],
                cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8",
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"], payload)
        self.assertGreaterEqual(payload["data"]["added"], 1)


if __name__ == "__main__":
    unittest.main()
