"""``sfx serve`` —— 启动一个零依赖的本地 Web 看板（ARCH §3.2 T04 的最小可用形态）。

约束（严格遵循）
----------------
- **纯标准库**：``http.server`` + ``sqlite3``，零第三方依赖（§9.2）；
- **默认只监听 127.0.0.1**，非回环必须显式 ``--host 0.0.0.0``（NFR-04：禁止无鉴权监听 0.0.0.0）；
- 这是**本地单机看板**，不含团队服务端、账号、审核（那些是 M2）。

页面
----
- ``/``         —— 主看板（skill 列表 + 统计 + 匹配试玩），单文件内嵌 CSS/JS（零 CDN，断网可用）；
- ``/api/skills``—— 返回 skill 列表 JSON；
- ``/api/match`` —— 匹配试玩（POST，body 为任务文本）；
- ``/api/stats`` —— 统计信息。

安全性说明：本版本**不做账号鉴权**（那是 FR-30，M2 团队版才需要）。
本看板只读 + 匹配试玩，不暴露任何写操作；数据来自本机 SQLite。
"""

from __future__ import annotations

import json
import os

from sfx import _boot
from sfx import _errors as errors
from sfx.cli import dispatch

# 注意：``http.server`` / ``socketserver`` 是重量级 stdlib（实测 +177ms），
# 一律在 :func:`run` 内延迟导入（P-1 纪律）。本模块顶层只允许 import 轻量模块。
# ``Envelope`` 这里用不到（serve 是长驻服务，不返回信封），也不导入。

ALLOWED_FLAGS: frozenset[str] = frozenset({
    "host", "port", "open", "json", "human",
})

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 7788
#: 低于这个样本量不对外展示采比率（PRD M-3：N<5 显示"数据不足"）
MIN_SAMPLE = 5


# ---------------------------------------------------------------------------
# 页面渲染（单文件 HTML，内嵌 CSS/JS，零 CDN）
# ---------------------------------------------------------------------------
_TEMPLATE_NAME = "index_template.html"
_template_cache: str | None = None


def _load_template() -> str:
    """读取 HTML 模板（走包内资源，兼容 zipapp 形态）。"""
    global _template_cache
    if _template_cache is None:
        from sfx import _res  # 延迟导入：serve 非热路径，这里付一次 +205ms 可接受

        _template_cache = _res.read_text(_TEMPLATE_NAME)
    return _template_cache


def _inline_json(value) -> str:
    """把对象序列化成可安全内联进 ``<script>`` 的 JSON。

    ``json.dumps`` 不转义 ``<``：只要某个 skill 的摘要里出现 ``</script>``，
    浏览器的脚本块就会在那里被截断，页面直接白屏（且是技能作者可控的输入）。
    把 ``<`` 统一转成 ``\\u003c`` 是最省事也最彻底的合规做法 —— JSON 语义不变
    （``\\u003c`` 解析回来仍是 ``<``），但不可能再闭合标签，``<!--`` 也一并失效。
    """
    return json.dumps(value, ensure_ascii=False).replace("<", "\\u003c")


def _render_index(skills: list[dict], stats: dict) -> str:
    """渲染主看板 HTML。

    两次 ``replace`` 都带 ``count=1``：模板里每个占位符只应出现一次，
    限制替换次数可以防止**注入内容里恰好含有占位符字面量**时被二次替换。
    """
    template = _load_template()
    # 先 stats 后 skills：stats 是纯服务端数字，不会被技能文本污染。
    template = template.replace("__STATS__", _inline_json(stats), 1)
    return template.replace("__SKILLS__", _inline_json(skills), 1)


def _load_skills(cfg) -> list[dict]:
    """读取 active skill 列表，转成页面友好的字典。"""
    from sfx.infra import pathx
    from sfx.infra.sqlite import migrator, skill_repo
    from sfx.infra.sqlite import open as sqlite_open

    conn = sqlite_open.open_db(pathx.db_path(cfg.home))
    try:
        migrator.migrate(conn, _boot.now_rfc3339())
        repo = skill_repo.SkillRepo(conn)
        skills = repo.list_active()
        out = []
        for s in skills:
            out.append({
                "id": s.id,
                "name": s.name,
                "slug": s.slug,
                "summary": s.summary,
                "summary_fallback": s.summary_fallback,
                "version": s.version,
                "author": s.author,
                "tags": list(s.tags),
                "triggers": list(s.triggers),
                "path": s.entry_path,
            })
        return out
    finally:
        sqlite_open.close_db(conn)


def _build_scores(counts: dict, min_sample: int = MIN_SAMPLE) -> dict:
    """把原始计数换算成看板用的分数表（纯函数，便于单测）。

    ``load_rate`` 在样本不足时返回 ``None`` 而**不是 0.0``——
    0.0 会被界面读成"采纳率 0%，这技能很差"，而事实是"还没有数据"。
    PRD 的 M-3 要求这种情况显示"数据不足"：一个技能被推荐 1 次、还没人用它，
    和推荐了 200 次、没人用它，是完全不同的两件事，不能给同一个数字。
    """
    scores: dict[str, dict] = {}
    for skill_id, slot in counts.items():
        shown = int(slot.get("shown", 0))
        loaded = int(slot.get("loaded", 0))
        rate = None
        if shown >= min_sample:
            rate = round(min(1.0, loaded / float(shown)), 4)
        scores[str(skill_id)] = {
            "shown": shown,
            "loaded": loaded,
            "feedback": int(slot.get("feedback", 0)),
            "load_rate": rate,
            "n": shown,
        }
    return scores


def _load_scores(cfg) -> dict:
    """读取看板分数表（真实埋点，无数据时给空表，绝不编造）。"""
    from sfx.infra import pathx
    from sfx.infra.sqlite import event_repo, migrator, skill_repo
    from sfx.infra.sqlite import open as sqlite_open

    conn = sqlite_open.open_db(pathx.db_path(cfg.home))
    try:
        migrator.migrate(conn, _boot.now_rfc3339())
        # 只统计仍然存在的 skill：删掉的技能残留事件不该继续出现在页面上
        alive = {s.id for s in skill_repo.SkillRepo(conn).list_active()}
        counts = event_repo.EventRepo(conn).scoreboard()
        return {
            "min_sample": MIN_SAMPLE,
            "scores": _build_scores({k: v for k, v in counts.items() if k in alive}),
        }
    finally:
        sqlite_open.close_db(conn)


def _load_stats(cfg) -> dict:
    from sfx.infra import pathx
    from sfx.infra.sqlite import migrator, skill_repo
    from sfx.infra.sqlite import open as sqlite_open

    conn = sqlite_open.open_db(pathx.db_path(cfg.home))
    try:
        migrator.migrate(conn, _boot.now_rfc3339())
        repo = skill_repo.SkillRepo(conn)
        total = repo.count(None)
        active = repo.count("active")
        return {
            "total": total,
            "active": active,
            "last_scanned_at": repo.last_scanned_at(),
        }
    finally:
        sqlite_open.close_db(conn)


def _do_match(cfg, task: str) -> tuple[list[dict], list[dict]]:
    from sfx.core.service import matcher, router
    from sfx.infra import pathx
    from sfx.infra.sqlite import event_repo, migrator, skill_repo
    from sfx.infra.sqlite import open as sqlite_open

    conn = sqlite_open.open_db(pathx.db_path(cfg.home))
    try:
        migrator.migrate(conn, _boot.now_rfc3339())
        skills = skill_repo.SkillRepo(conn).list_active()
        history = event_repo.EventRepo(conn).history_scores()
        results, explain = matcher.match_explain(task, skills, cfg, history, None)
        return router.build_route_card(results), explain
    finally:
        sqlite_open.close_db(conn)


# ---------------------------------------------------------------------------
# 命令入口
# ---------------------------------------------------------------------------
def _assert_port_free(host: str, port: int) -> None:
    """启动前主动探测端口，被占用时给出可执行的提示。

    为什么不能只依赖 bind 报错：``http.server`` 默认 ``allow_reuse_address = 1``，
    在 Windows 上这等价于 ``SO_REUSEADDR``——**第二个进程能成功绑定同一端口**，
    于是两个服务同时 LISTEN，请求随机落到其中一个（实测本机 7788 上叠了 3 个
    进程，改完代码刷新页面看到的还是旧页面，极其难排查）。Linux 则会正常报
    ``EADDRINUSE``。用一次真实连接探测，把两个平台的差异抹平成同一条错误。
    """
    import socket

    probe_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    try:
        with socket.create_connection((probe_host, int(port)), timeout=0.3):
            pass
    except OSError:
        return  # 连不上 = 端口空闲，正常情况
    raise errors.SfxError(
        errors.E_USAGE,
        f"端口 {port} 已被占用（可能是一个没关掉的看板进程）",
        {"host": host, "port": int(port)},
        f"换一个端口：sfx serve --port {int(port) + 1}；"
        f"或先结束占用进程（Windows：netstat -ano | findstr :{port}）",
    )


def run(cfg, logger, opts: dict[str, object], positional: list[str]) -> None:
    """启动 HTTP 服务（阻塞，直到 Ctrl+C）。

    注意：本命令不是"输出 JSON 后退出"的命令，而是长驻服务，
    因此它**不返回 Envelope**，而是直接 serve；中断时打印一行提示。

    ``http.server`` / ``socketserver`` 在此**延迟导入**（P-1：实测 +177ms，
    绝不放模块顶层）。
    """
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    dispatch.reject_unknown(opts, ALLOWED_FLAGS, "serve")

    host = dispatch.opt_str(opts, "host") or DEFAULT_HOST
    port = dispatch.opt_int(opts, "port") or DEFAULT_PORT

    if host not in ("127.0.0.1", "localhost", "::1") and not dispatch.opt_bool(opts, "open"):
        # NFR-04：非回环必须显式 --open（避免误暴露）
        raise errors.SfxError(
            errors.E_USAGE,
            f"监听非回环地址 {host} 需要显式 --open",
            {"host": host},
            "本地看板默认只监听 127.0.0.1；如确需局域网访问，加 --open",
        )

    # 把 cfg 注入到 handler 类（闭包捕获，避免全局可变状态）
    handler_cfg = cfg

    class Handler(BaseHTTPRequestHandler):
        cfg = handler_cfg

        def log_message(self, *args):  # 关掉默认的 stderr 日志噪音
            pass

        def _send_json(self, obj, status=200):
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _send_html(self, html: str):
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html"):
                try:
                    skills = _load_skills(self.cfg)
                    stats = _load_stats(self.cfg)
                    self._send_html(_render_index(skills, stats))
                except Exception as exc:  # noqa: BLE001
                    self._send_json({"ok": False, "error": str(exc)}, 500)
            elif path == "/api/skills":
                try:
                    self._send_json({"ok": True, "skills": _load_skills(self.cfg)})
                except Exception as exc:  # noqa: BLE001
                    self._send_json({"ok": False, "error": str(exc)}, 500)
            elif path == "/api/stats":
                try:
                    self._send_json({"ok": True, "stats": _load_stats(self.cfg)})
                except Exception as exc:  # noqa: BLE001
                    self._send_json({"ok": False, "error": str(exc)}, 500)
            elif path == "/api/scores":
                try:
                    payload = _load_scores(self.cfg)
                    self._send_json({"ok": True, **payload})
                except Exception as exc:  # noqa: BLE001
                    self._send_json({"ok": False, "error": str(exc)}, 500)
            else:
                self._send_json({"ok": False, "error": "not found"}, 404)

        def do_POST(self):
            path = self.path.split("?", 1)[0]
            if path == "/api/match":
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    raw = self.rfile.read(length).decode("utf-8")
                    body = json.loads(raw) if raw else {}
                    task = str(body.get("task", "")).strip()
                    if not task:
                        self._send_json({"ok": False, "error": "缺少 task"}, 400)
                        return
                    cards, explain = _do_match(self.cfg, task)
                    self._send_json({
                        "ok": True, "matched": cards, "explain": explain,
                        "count": len(cards),
                    })
                except Exception as exc:  # noqa: BLE001
                    self._send_json({"ok": False, "error": str(exc)}, 500)
            else:
                self._send_json({"ok": False, "error": "not found"}, 404)

    _assert_port_free(host, port)
    server = ThreadingHTTPServer((host, int(port)), Handler)

    # 向用户打印启动信息（这是 serve 命令仅有的非 JSON 输出，属长驻服务的合理例外）
    url = f"http://127.0.0.1:{port}/" if host in ("127.0.0.1", "localhost", "::1") else f"http://{host}:{port}/"
    print(f"SkillForge 看板已启动：{url}")
    print("按 Ctrl+C 停止服务")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        print("\n已停止")
