"""跨平台路径与配置优先级单测（ARCH §10.1）。"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from sfx.infra import conf, pathx  # noqa: E402


class TestPathx(unittest.TestCase):
    """路径解析。"""

    def test_default_home_is_absolute(self) -> None:
        """平台默认 home 必须是绝对路径。"""
        home = pathx.default_home()
        self.assertTrue(os.path.isabs(home), home)
        self.assertTrue(home.endswith("sfx"), home)

    def test_home_priority_flag_over_env_over_default(self) -> None:
        """``--home`` > ``$SFX_HOME`` > 平台默认。"""
        with tempfile.TemporaryDirectory() as tmp:
            flag_home = os.path.join(tmp, "flag")
            env_home = os.path.join(tmp, "env")
            os.environ["SFX_HOME"] = env_home
            try:
                self.assertEqual(pathx.resolve_home(flag_home), pathx.expand(flag_home))
                self.assertEqual(pathx.resolve_home(None), pathx.expand(env_home))
            finally:
                del os.environ["SFX_HOME"]
            self.assertEqual(pathx.resolve_home(None), pathx.default_home())

    def test_expand_handles_user_and_relative(self) -> None:
        """``~`` 与相对路径都能展开成绝对路径。"""
        self.assertTrue(os.path.isabs(pathx.expand("~")))
        self.assertTrue(os.path.isabs(pathx.expand(".")))

    def test_norm_key_is_case_insensitive_on_windows(self) -> None:
        """唯一性键在 Windows 上大小写不敏感（防止同一目录被记成两条）。"""
        if not pathx.IS_WINDOWS:
            self.skipTest("仅 Windows 上验证大小写不敏感")
        self.assertEqual(pathx.norm_key("C:\\Skills\\A"), pathx.norm_key("c:\\skills\\a"))

    def test_native_uses_os_separator(self) -> None:
        """对外输出使用操作系统原生分隔符。"""
        joined = pathx.native(os.path.join("a", "b"))
        self.assertEqual(joined.count(os.sep), 1)

    def test_derived_paths_under_home(self) -> None:
        """db / log / cache 都落在 home 下。"""
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(pathx.db_path(tmp).startswith(tmp))
            self.assertTrue(pathx.log_path(tmp).startswith(tmp))
            self.assertTrue(pathx.cache_dir(tmp).startswith(tmp))
            self.assertTrue(pathx.db_path(tmp).endswith("sfx.db"))


class TestConfigPriority(unittest.TestCase):
    """配置优先级：flag > env > file > default。"""

    def _fresh_env(self) -> None:
        for key in list(os.environ):
            if key.startswith("SFX_"):
                del os.environ[key]

    def test_defaults_when_nothing_provided(self) -> None:
        """无配置源时用内置默认。"""
        self._fresh_env()
        cfg = conf.load("/tmp/sfx-home", "/nonexistent/config.yaml")
        self.assertEqual(cfg.threshold, conf.DEFAULT_THRESHOLD)
        self.assertEqual(cfg.top_n, conf.DEFAULT_TOP_N)
        self.assertEqual(cfg.roots, conf.DEFAULT_ROOTS)
        self.assertEqual(cfg.sources["threshold"], "default")

    def test_env_overrides_default(self) -> None:
        """环境变量优于默认值。"""
        self._fresh_env()
        os.environ["SFX_THRESHOLD"] = "0.5"
        os.environ["SFX_TOP_N"] = "5"
        try:
            cfg = conf.load("/tmp/sfx-home", "/nonexistent/config.yaml")
        finally:
            self._fresh_env()
        self.assertAlmostEqual(cfg.threshold, 0.5)
        self.assertEqual(cfg.top_n, 5)
        self.assertEqual(cfg.sources["threshold"], "env")

    def test_flag_overrides_env(self) -> None:
        """命令行 flag 优先级最高。"""
        self._fresh_env()
        os.environ["SFX_TOP_N"] = "5"
        try:
            cfg = conf.load("/tmp/sfx-home", "/nonexistent/config.yaml", flags={"top_n": 9})
        finally:
            self._fresh_env()
        self.assertEqual(cfg.top_n, 9)
        self.assertEqual(cfg.sources["top_n"], "flag")

    def test_config_file_overrides_default(self) -> None:
        """配置文件优于默认值，且支持两层嵌套。"""
        self._fresh_env()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "config.yaml")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(
                    "roots:\n"
                    "  - ~/my-skills\n"
                    "engine:\n"
                    "  threshold: 0.42\n"
                    "  top_n: 7\n"
                    "  weights:\n"
                    "    keyword: 0.5\n"
                    "    tag: 0.3\n"
                    "    semantic: 0.0\n"
                    "    history: 0.0\n"
                )
            cfg = conf.load(tmp, path)
        self.assertAlmostEqual(cfg.threshold, 0.42)
        self.assertEqual(cfg.top_n, 7)
        self.assertEqual(cfg.roots, ("~/my-skills",))
        self.assertEqual(cfg.weight("history"), 0.0)
        self.assertEqual(cfg.sources["threshold"], "file")

    def test_broken_config_file_raises_e_config(self) -> None:
        """坏配置文件 → ``E_CONFIG`` 且带行号。"""
        from sfx import _errors as errors

        self._fresh_env()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "config.yaml")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("version: 1\n这行没有冒号\n")
            with self.assertRaises(errors.SfxError) as ctx:
                conf.load(tmp, path)
        self.assertEqual(ctx.exception.code, errors.E_CONFIG)
        self.assertEqual(ctx.exception.details.get("line"), 2)

    def test_history_weight_can_be_zero(self) -> None:
        """C-1：``weights.history`` 必须可以配置为 0。"""
        self._fresh_env()
        os.environ["SFX_WEIGHT_HISTORY"] = "0"
        try:
            cfg = conf.load("/tmp/sfx-home", "/nonexistent/config.yaml")
        finally:
            self._fresh_env()
        self.assertEqual(cfg.weight("history"), 0.0)
        self.assertNotIn("history", cfg.active_signals())


if __name__ == "__main__":
    unittest.main()
