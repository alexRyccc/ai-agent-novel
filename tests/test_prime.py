"""``sfx prime`` 的单元测试：指令块的自包含性契约。

关注点（ARCH §7.4 自包含性检查）：
- 命中时：指令块必须包含任务原文 + 每个命中 skill 的绝对路径；
- 未命中时：指令块必须包含"不要编造"的兜底句；
- **指令块里绝不出现要求执行命令的措辞**（Tier C 前提）。
"""

from __future__ import annotations

import unittest

from sfx.cli.cmd_prime import build_prime_prompt


class TestBuildPrimePrompt(unittest.TestCase):
    def test_hit_includes_paths_and_task(self) -> None:
        cards = [
            {
                "skill_id": "s1",
                "name": "pixel-asset-forge",
                "summary": "生成像素素材",
                "path": r"C:\Users\me\.workbuddy\skills\pixel-asset-forge\SKILL.md",
                "score": 0.8,
                "reason": "命中",
            }
        ]
        text = build_prime_prompt("生成一个像素角色", cards)
        self.assertIn("生成一个像素角色", text)
        self.assertIn("pixel-asset-forge", text)
        self.assertIn("SKILL.md", text)

    def test_miss_includes_no_fabricate_guard(self) -> None:
        text = build_prime_prompt("写工作总结", [])
        self.assertIn("不要编造", text)

    def test_never_asks_to_execute_commands(self) -> None:
        """指令块不得要求 Metis 执行任何终端命令（Tier C 前提）。"""
        cards = [
            {
                "skill_id": "s1",
                "name": "demo",
                "summary": "x",
                "path": "/a/b/SKILL.md",
                "score": 0.8,
                "reason": "命中",
            }
        ]
        text = build_prime_prompt("任务", cards)
        forbidden = ("执行", "运行命令", "sfx ", "terminal", "shell", "bash")
        lowered = text.lower()
        for word in forbidden:
            self.assertNotIn(word.lower(), lowered, f"指令块不应出现 {word!r}")


if __name__ == "__main__":
    unittest.main()
