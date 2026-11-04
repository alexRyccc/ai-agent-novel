"""CLI 端到端单测（ARCH §5.2 / NFR-07 NN-2）。

全部通过**真实子进程**验证，覆盖验收标准 2/3/5/6/9：
  - stdout 恒为**恰好一行**合法 JSON；
  - 重复扫描不产生重复记录；
  - 人为注入异常时 stdout 仍是一行 JSON、退出码 4、堆栈只进日志；
  - 中文输出为 UTF-8 字节；
  - ``doctor`` 能正确打印数据目录。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

TESTDATA_SKILLS = os.path.join(ROOT, "tests", "testdata", "skills")
PYZ = os.path.join(ROOT, "dist", "sfx.pyz")


def clean_env() -> dict[str, str]:
    """清除 ``PYTHON*``（模拟干净目标机，且避免本机 shim 拖慢测试）。"""
    env = dict(os.environ)
    for key in list(env):
        if key.startswith("PYTHON"):
            del env[key]
    return env


def run_sfx(args: list[str], home: str, roots: str = "", cwd: str = ROOT) -> subprocess.CompletedProcess:
    """以子进程跑一次 ``sfx``（源码目录形态）。"""
    env = clean_env()
    env["SFX_HOME"] = home
    if roots:
        env["SFX_ROOTS"] = roots
    return subprocess.run(
        [sys.executable, "-m", "sfx"] + args,
        cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8",
    )


def one_json(result: subprocess.CompletedProcess) -> dict:
    """断言 stdout 恰好一行且是合法 JSON，并返回解析结果。"""
    lines = result.stdout.strip().splitlines()
    assert len(lines) == 1, f"stdout 不是恰好一行：{result.stdout!r}"
    return json.loads(lines[0])


class TestMetaCommands(unittest.TestCase):
    """``--help`` / ``--version``（§5.2 明确豁免"一行 JSON"的元命令）。"""

    def test_version(self) -> None:
        """``--version`` 退出码 0 且有输出。"""
        result = run_sfx(["--version"], tempfile.gettempdir())
        self.assertEqual(result.returncode, 0)
        self.assertIn("sfx", result.stdout)

    def test_help(self) -> None:
        """``--help`` 退出码 0 且列出三个命令。"""
        result = run_sfx(["--help"], tempfile.gettempdir())
        self.assertEqual(result.returncode, 0)
        for name in ("scan", "match", "doctor"):
            self.assertIn(name, result.stdout)

    def test_unknown_command_is_usage_error(self) -> None:
        """未知命令 → 退出码 2 + 一行 JSON + ``E_USAGE``。"""
        result = run_sfx(["nosuchcmd"], tempfile.gettempdir())
        self.assertEqual(result.returncode, 2)
        payload = one_json(result)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["code"], "E_USAGE")


class TestScan(unittest.TestCase):
    """``sfx scan``。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.home = os.path.join(self._tmp.name, "home")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_scan_finds_skills_and_reports_broken_one(self) -> None:
        """扫到正常 skill；坏 YAML 被跳过并报出行号（FR-02），整体扫描不受影响。"""
        result = run_sfx(["scan"], self.home, roots=TESTDATA_SKILLS)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = one_json(result)
        self.assertTrue(payload["ok"], payload)
        data = payload["data"]
        self.assertEqual(data["added"], 1)
        self.assertEqual(data["scanned_dirs"], 2)
        self.assertEqual(len(data["skipped_errors"]), 1)
        self.assertEqual(data["skipped_errors"][0]["line"], 3)

    def test_rescan_produces_no_duplicates(self) -> None:
        """**重复扫描不产生重复记录**（FR-01 / 验收标准 2）。"""
        first = run_sfx(["scan"], self.home, roots=TESTDATA_SKILLS)
        self.assertEqual(first.returncode, 0)
        self.assertEqual(one_json(first)["data"]["added"], 1)

        second = run_sfx(["scan"], self.home, roots=TESTDATA_SKILLS)
        payload = one_json(second)
        self.assertEqual(payload["data"]["added"], 0)
        self.assertEqual(payload["data"]["updated"], 0)
        self.assertEqual(payload["data"]["unchanged"], 1)
        self.assertEqual(payload["data"]["skills_total"], 1)

        third = run_sfx(["scan"], self.home, roots=TESTDATA_SKILLS)
        self.assertEqual(one_json(third)["data"]["skills_total"], 1)

    def test_missing_root_is_not_an_error(self) -> None:
        """来源目录不存在就跳过，不报错。"""
        result = run_sfx(["scan"], self.home, roots=os.path.join(self._tmp.name, "nope"))
        self.assertEqual(result.returncode, 0)
        payload = one_json(result)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["data"]["scanned_dirs"], 0)
        self.assertEqual(payload["data"]["skipped_errors"], [])
        self.assertIn("nope", str(payload["data"]["roots_missing"]))

    def test_unknown_flag_is_usage_error(self) -> None:
        """未认识的 flag → 退出码 2。"""
        result = run_sfx(["scan", "--nope"], self.home, roots=TESTDATA_SKILLS)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(one_json(result)["code"], "E_USAGE")


class TestMatch(unittest.TestCase):
    """``sfx match``。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.home = os.path.join(self._tmp.name, "home")
        run_sfx(["scan"], self.home, roots=TESTDATA_SKILLS)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_match_returns_exactly_one_line(self) -> None:
        """验收标准 3：``sfx match "<任务描述>"`` 返回**恰好一行** JSON。"""
        result = run_sfx(["match", "--task", "帮我看下下单接口的规范"], self.home)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = one_json(result)
        self.assertTrue(payload["ok"])
        self.assertIn("session_id", payload["data"])
        self.assertGreaterEqual(payload["data"]["match_count"], 1)

    def test_positional_task_form(self) -> None:
        """位置参数形式 ``sfx match "<描述>"`` 同样可用。"""
        result = run_sfx(["match", "下单 订单 幂等"], self.home)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = one_json(result)
        self.assertGreaterEqual(payload["data"]["match_count"], 1)

    def test_route_card_shape(self) -> None:
        """路由卡只含冻结字段，且路径为绝对路径。"""
        result = run_sfx(["match", "--task", "下单接口规范"], self.home)
        payload = one_json(result)
        card = payload["data"]["matched"][0]
        self.assertEqual(
            tuple(sorted(card.keys())),
            tuple(sorted(["skill_id", "name", "summary", "path", "score", "reason"])),
        )
        self.assertTrue(os.path.isabs(card["path"]))
        self.assertNotIn("body", card)

    def test_empty_match_still_returns_session_id(self) -> None:
        """无命中：``ok=true``、``matched=[]``、仍有 ``session_id``、退出码 0。"""
        result = run_sfx(["match", "--task", "完全不相关的火星文任务"], self.home)
        self.assertEqual(result.returncode, 0)
        payload = one_json(result)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["data"]["matched"], [])
        self.assertTrue(payload["data"]["session_id"])
        self.assertEqual(payload["code"], "EMPTY_MATCH")

    def test_missing_task_is_usage_error(self) -> None:
        """缺 ``--task`` → 退出码 2。"""
        result = run_sfx(["match"], self.home)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(one_json(result)["code"], "E_USAGE")

    def test_elapsed_ms_present(self) -> None:
        """信封与 data 都带 ``elapsed_ms``，且是非负整数。"""
        result = run_sfx(["match", "--task", "下单"], self.home)
        payload = one_json(result)
        self.assertIsInstance(payload["elapsed_ms"], int)
        self.assertGreaterEqual(payload["elapsed_ms"], 0)


class TestPanicFallback(unittest.TestCase):
    """NFR-07：任何异常下 stdout 仍是一行 JSON，堆栈只进日志（验收标准 5）。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.home = os.path.join(self._tmp.name, "home")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_panic_keeps_one_line_json_and_exit_code_4(self) -> None:
        """人为注入 ``RuntimeError``：一行 JSON、退出码 4、无堆栈、日志有堆栈。"""
        script = (
            "import io, sys\n"
            # 子进程 stdout 默认是 GBK（干净 Windows 环境的真实情况），
            # 这里模拟真实场景：先重编码为 UTF-8 再回写，便于父进程按 UTF-8 解码。
            "sys.stdout.reconfigure(encoding='utf-8', newline='\\n')\n"
            f"sys.path.insert(0, {ROOT!r})\n"
            "import sfx.__main__ as m\n"
            "import sfx.cli.dispatch as d\n"
            "def boom(argv):\n"
            "    raise RuntimeError('人为注入的异常')\n"
            "d.run = boom\n"
            "buf = io.StringIO()\n"
            "real = sys.stdout\n"
            "sys.stdout = buf\n"
            "try:\n"
            "    m.main()\n"
            "    rc = 0\n"
            "except SystemExit as exc:\n"
            "    rc = exc.code\n"
            "sys.stdout = real\n"
            "real.write(buf.getvalue())\n"
            "real.flush()\n"
            "sys.exit(rc)\n"
        )
        env = clean_env()
        env["SFX_HOME"] = self.home
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8",
        )
        self.assertEqual(result.returncode, 4, result.stderr)
        payload = one_json(result)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["code"], "E_INTERNAL")
        self.assertIsNone(payload["data"])
        # 堆栈与源码位置绝不能出现在 stdout（E-3）；
        # 异常类型名出现在 message 里是**有意**的（用户报障时能说清是哪个异常），
        # 但它既不是堆栈也不含代码路径，不算"panic 外泄"。
        self.assertNotIn("Traceback", result.stdout)
        self.assertNotIn("sfx\\", result.stdout)
        self.assertNotIn(".py", result.stdout)

        # 但必须出现在日志文件里
        log_file = os.path.join(self.home, "logs", "sfx.log")
        self.assertTrue(os.path.isfile(log_file), "日志文件应被创建")
        with open(log_file, "r", encoding="utf-8") as handle:
            content = handle.read()
        self.assertIn("RuntimeError", content)
        self.assertIn("Traceback", content)


class TestUtf8Output(unittest.TestCase):
    """验收标准 6：中文输出必须是 UTF-8 字节。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.home = os.path.join(self._tmp.name, "home")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_doctor_prints_home_and_chinese_as_utf8(self) -> None:
        """``sfx doctor`` 能正确打印数据目录，且中文为 UTF-8 字节（验收标准 9）。"""
        env = clean_env()
        env["SFX_HOME"] = self.home
        result = subprocess.run(
            [sys.executable, "-m", "sfx", "doctor"],
            cwd=ROOT, env=env, capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        raw = result.stdout
        # 必须是 UTF-8 可解码，且含中文字符（uninstall_hint 里必有中文）
        text = raw.decode("utf-8")
        payload = json.loads(text)
        self.assertEqual(payload["data"]["home"], self.home)
        self.assertIn("卸载", text)

    def test_doctor_reports_db_and_counts(self) -> None:
        """doctor 展示 db_path / migrations / skills / events。"""
        run_sfx(["scan"], self.home, roots=TESTDATA_SKILLS)
        result = run_sfx(["doctor"], self.home)
        payload = one_json(result)
        data = payload["data"]
        self.assertTrue(data["db_exists"])
        self.assertIn(1, data["migrations"])
        self.assertEqual(data["skills"], 1)
        self.assertIn("uninstall_hint", data)

    def test_human_flag_emits_indented_json(self) -> None:
        """``--human`` 输出缩进 JSON（仍是合法 JSON，仅用户主动触发）。"""
        result = run_sfx(["doctor", "--human"], self.home)
        self.assertEqual(result.returncode, 0)
        self.assertGreater(len(result.stdout.strip().splitlines()), 1)
        self.assertTrue(json.loads(result.stdout)["ok"])


class TestZipappForm(unittest.TestCase):
    """zipapp 形态（验收标准 1）：源码目录与 zipapp 两种都能跑。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.home = os.path.join(self._tmp.name, "home")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    @unittest.skipUnless(os.path.isfile(PYZ), "需要先执行 python scripts/build.pyz.py")
    def test_pyz_help_and_scan(self) -> None:
        """``python sfx.pyz --help`` 与 ``scan`` 都可用。"""
        env = clean_env()
        env["SFX_HOME"] = self.home
        env["SFX_ROOTS"] = TESTDATA_SKILLS
        result = subprocess.run(
            [sys.executable, PYZ, "--help"],
            cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8",
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("sfx", result.stdout)

        scan = subprocess.run(
            [sys.executable, PYZ, "scan"],
            cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8",
        )
        self.assertEqual(scan.returncode, 0, scan.stdout + scan.stderr)
        self.assertEqual(one_json(scan)["data"]["added"], 1)

    @unittest.skipUnless(os.path.isfile(PYZ), "需要先执行 python scripts/build.pyz.py")
    def test_pyz_exit_codes_match_source_form(self) -> None:
        """zipapp 形态的**退出码**必须与源码形态一致。

        这是一个真实踩过的坑：zipapp 生成的根 ``__main__.py`` 内容是
        ``sfx.__main__.main()``——**返回值被丢弃**。若 ``main()`` 只是
        ``return 2``，zipapp 形态下退出码恒为 0，``E_USAGE``/``E_INTERNAL``
        全部失效，宿主永远以为执行成功。修复方式是让 ``main()`` 自己调
        ``sys.exit``；这个测试把结论钉住，防止回归。
        """
        env = clean_env()
        env["SFX_HOME"] = self.home
        pyz_usage = subprocess.run(
            [sys.executable, PYZ, "scan", "--bogus"],
            cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8",
        )
        src_usage = run_sfx(["scan", "--bogus"], self.home)
        self.assertEqual(pyz_usage.returncode, 2)
        self.assertEqual(src_usage.returncode, 2)
        self.assertEqual(one_json(pyz_usage)["code"], "E_USAGE")
        self.assertEqual(one_json(src_usage)["code"], "E_USAGE")

        pyz_help = subprocess.run(
            [sys.executable, PYZ, "--help"],
            cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8",
        )
        self.assertEqual(pyz_help.returncode, 0)


if __name__ == "__main__":
    unittest.main()
