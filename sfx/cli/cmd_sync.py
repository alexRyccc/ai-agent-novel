"""``sfx sync`` —— 生成/更新约定文件（AGENTS.md / agent.md），让 Metis 能自动调用 skill。

这是 SkillForge 的 **P0 主链路**（对应架构 Tier A/B 的"约定文件通道"，WS-3 的
最小可用形态）。

机制
----
1. 读取已入库的 active skill；
2. 生成一份**技能路由索引**（名字 / 摘要 / 触发词 / 绝对路径），**绝不塞正文**；
3. 把索引 + 一段"你是路由器"的指令写进约定文件，用锚点标记隔离：
   ``<!-- SKILLFORGE:BEGIN -->`` ... ``<!-- SKILLFORGE:END -->``；
4. 约定文件里**锚点块之外**的内容（用户手写的其它规范）**原样保留**。

Metis 每次对话读到这个文件后，遇到任务会按索引选最匹配的 skill，
读取它的 SKILL.md 并执行——无需任何 API 集成。

安全性（ARCH §12.9）
--------------------
约定文件会被写入项目根目录（可能是 Git 工作区）。为避免把本机绝对路径
与内部规范清单外泄进 Git，本命令：
- 若检测到目标文件已被 Git 跟踪 → **默认拒绝写入**，给出换名/共存/接管三条出路；
- 若在 Git 工作区但文件未被跟踪 → 自动写入 ``.git/info/exclude`` 本地隔离。

（注：本 Walking Skeleton 版本先实现"生成 + 锚点幂等 + Git 跟踪检测拒绝"，
   .git/info/exclude 自动写入与三条出路的交互式选择留待后续细化。）
"""

from __future__ import annotations

import os

from sfx import _boot
from sfx import _errors as errors
from sfx.cli import dispatch
from sfx.core.model.envelope import Envelope

ALLOWED_FLAGS: frozenset[str] = frozenset({
    "file", "output", "stdout", "json", "human",
})

#: 默认约定文件名（Metis 常见的几种；--file 可覆盖）
DEFAULT_FILENAMES = ("AGENTS.md", "agent.md", "CLAUDE.md", ".cursorrules")

ANCHOR_BEGIN = "<!-- SKILLFORGE:BEGIN -->"
ANCHOR_END = "<!-- SKILLFORGE:END -->"


# ---------------------------------------------------------------------------
# 路由索引与指令块渲染
# ---------------------------------------------------------------------------
def _render_index(skills: list[dict]) -> str:
    """把 skill 列表渲染成紧凑的 Markdown 路由索引（不含正文）。"""
    lines: list[str] = []
    lines.append("## 技能路由索引（由 SkillForge 自动生成，请勿手改本块）")
    lines.append("")
    lines.append("| 技能 | 摘要 | 触发词 | 定义文件路径 |")
    lines.append("| --- | --- | --- | --- |")
    for s in skills:
        name = (s.get("name") or "").replace("|", "\\|")
        summary = (s.get("summary") or "").replace("|", "\\|").replace("\n", " ")
        if len(summary) > 60:
            summary = summary[:59] + "…"
        triggers = "、".join((s.get("triggers") or [])[:5]).replace("|", "\\|")
        path = (s.get("path") or "").replace("|", "\\|")
        lines.append(f"| {name} | {summary} | {triggers} | {path} |")
    return "\n".join(lines)


def _render_block(skills: list[dict]) -> str:
    """渲染完整的锚点块：指令 + 索引。"""
    lines: list[str] = []
    lines.append(ANCHOR_BEGIN)
    lines.append("")
    lines.append("你是运行在本项目的 AI 助手。请遵循下面的技能路由规则：")
    lines.append("")
    lines.append("1. 收到用户任务后，先对照下方「技能路由索引」，判断最匹配的一个技能。")
    lines.append("2. 用你的文件读取能力，打开该技能对应的「定义文件路径」，完整阅读并严格遵循其中的规则、工作流与产出规范。")
    lines.append("3. 如果没有任何技能匹配，就用你的通用能力直接完成任务，不要编造不存在的技能或文件。")
    lines.append("4. 上面列出的路径是本机绝对路径，请直接读取，不要臆测或改写。")
    lines.append("")
    lines.append(_render_index(skills))
    lines.append("")
    lines.append(ANCHOR_END)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 文件读写（幂等 + Git 跟踪检测）
# ---------------------------------------------------------------------------
def _is_git_tracked(path: str) -> bool:
    """判断文件是否已被 Git 跟踪（用 ``git ls-files``）。非 Git 环境返回 False。"""
    import subprocess

    try:
        proc = subprocess.run(
            ["git", "ls-files", "--error-unmatch", os.path.basename(path)],
            cwd=os.path.dirname(path) or ".",
            capture_output=True,
            text=True,
            timeout=5,
        )
        return proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired, FileNotFoundError):
        return False


def _sync_file(path: str, block: str) -> tuple[str, bool]:
    """把 block 幂等地写入文件（锚点块外原样保留）。

    Returns:
        ``(状态, 是否新增了块)``，状态为 ``created`` / ``updated`` / ``unchanged``。
    """
    begin = ANCHOR_BEGIN
    end = ANCHOR_END

    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as handle:
            original = handle.read()
    else:
        original = ""

    if begin in original and end in original:
        # 已有块：只替换锚点之间的内容
        pre = original[: original.index(begin)]
        post = original[original.index(end) + len(end):]
        new_content = pre + block + post
        changed = new_content != original
        status = "updated" if changed else "unchanged"
    else:
        # 无块：追加到文件末尾（保留原有内容，补一个换行分隔）
        sep = "" if not original or original.endswith("\n") else "\n"
        new_content = original + (sep + "\n" if original and not original.endswith("\n\n") else "\n") + block + "\n"
        changed = True
        status = "created" if not original else "updated"

    if changed:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(new_content)
    return status, changed


def _write_skillforge_block(filepath: str, block: str) -> tuple[str, bool]:
    """写块，并在 Git 跟踪时拒绝。"""
    if _is_git_tracked(filepath):
        raise errors.SfxError(
            errors.E_CONV_TRACKED_BY_GIT,
            f"目标文件 {filepath} 已被 Git 跟踪，为避免把本机路径/内部规范外泄进版本库，拒绝写入",
            {"file": filepath},
            "三条出路：① 换一个未被跟踪的文件名（--file 指定）；② 手动取消跟踪后重试（git rm --cached）；③ 若确实要提交，请改用 sfx prime 逐次粘贴",
        )
    return _sync_file(filepath, block)


# ---------------------------------------------------------------------------
# 命令入口
# ---------------------------------------------------------------------------
def run(cfg, logger, opts: dict[str, object], positional: list[str]) -> Envelope:
    """生成约定文件。"""
    dispatch.reject_unknown(opts, ALLOWED_FLAGS, "sync")

    from sfx.infra import pathx
    from sfx.infra.sqlite import migrator, skill_repo
    from sfx.infra.sqlite import open as sqlite_open

    conn = sqlite_open.open_db(pathx.db_path(cfg.home))
    try:
        migrator.migrate(conn, _boot.now_rfc3339())
        skills = skill_repo.SkillRepo(conn).list_active()
        skill_dicts = [
            {
                "name": s.name,
                "summary": s.summary,
                "triggers": list(s.triggers),
                "path": s.entry_path,
            }
            for s in skills
        ]
    finally:
        sqlite_open.close_db(conn)

    block = _render_block(skill_dicts)

    # 输出到 stdout（--stdout）还是文件（默认）
    if dispatch.opt_bool(opts, "stdout"):
        data = {"block": block, "skills": len(skill_dicts)}
        return Envelope.success(data=data, code=errors.OK, elapsed_ms=_boot.elapsed_ms())

    # 决定目标文件名
    filename = dispatch.opt_str(opts, "file") or dispatch.opt_str(opts, "output")
    written: list[dict] = []

    if filename:
        filepath = os.path.abspath(filename)
        status, _ = _write_skillforge_block(filepath, block)
        written.append({"file": filepath, "status": status})
    else:
        # 默认：写第一个存在的候选文件；都不存在则写 agent.md
        cwd = os.getcwd()
        for name in DEFAULT_FILENAMES:
            candidate = os.path.join(cwd, name)
            if os.path.exists(candidate):
                filepath = candidate
                break
        else:
            filepath = os.path.join(cwd, "agent.md")

        status, _ = _write_skillforge_block(filepath, block)
        written.append({"file": filepath, "status": status})

    data = {
        "written": written,
        "skills": len(skill_dicts),
        "hint": "在 Metis 中打开该项目，它应自动读取该约定文件并按索引调用 skill",
    }
    return Envelope.success(data=data, code=errors.OK, elapsed_ms=_boot.elapsed_ms())
