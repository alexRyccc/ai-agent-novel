#!/usr/bin/env python3
"""通过 api.github.com 推送整个本地仓库树到远程分支。

用途：当 github.com 主域名不通、只有 api.github.com 可达时，
用 Git Data API（blob -> tree -> commit -> update ref）完成推送。

零依赖，仅用标准库。用法：

    GITHUB_TOKEN=xxx python scripts/git_push_via_api.py \
        --owner alexRyccc --repo ai-agent-novel --branch main --message "..."

可选：
    --dry-run   只打印将要上传的文件，不发写请求
    --force     强制覆盖分支（默认 True，因为要覆盖已有内容）
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

API = "https://api.github.com"
TIMEOUT = 60


class ApiError(RuntimeError):
    pass


def _request(method: str, path: str, token: str, payload: dict | None = None) -> dict:
    url = path if path.startswith("http") else API + path
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", "skillforge-push")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body.strip() else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise ApiError(f"{method} {url} -> {exc.code}\n{detail}") from None


def _tracked_files() -> list[str]:
    """取 git 跟踪的文件列表。

    用 -z（NUL 分隔）拿原始字节，再显式按 UTF-8 解码，
    避免 core.quotepath 把中文名转成 "\\351\\241..." 这种转义串。
    """
    raw = subprocess.run(
        ["git", "-c", "core.quotepath=false", "ls-files", "-z"],
        capture_output=True, check=True,
    ).stdout
    return [part.decode("utf-8") for part in raw.split(b"\0") if part]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--owner", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--branch", default="main")
    parser.add_argument("--message", default="push via api")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token and not args.dry_run:
        print("缺少环境变量 GITHUB_TOKEN", file=sys.stderr)
        return 2

    files = _tracked_files()
    if not files:
        print("git ls-files 为空，没东西可推", file=sys.stderr)
        return 2
    print(f"待上传文件：{len(files)} 个")

    if args.dry_run:
        for name in files:
            print(f"  {name}")
        return 0

    repo_path = f"/repos/{args.owner}/{args.repo}"

    # 0) 权限自检：拿不到 push 权限就早点失败，别浪费 117 个请求
    info = _request("GET", repo_path, token)
    perms = info.get("permissions", {})
    print(f"仓库：{info.get('full_name')}  默认分支：{info.get('default_branch')}")
    print(f"权限：{perms}")
    if not perms.get("push"):
        print(
            "当前 token 没有写权限（push=false）。需要 Contents: Read and write。",
            file=sys.stderr,
        )
        return 3

    # 1) 逐个建 blob
    entries = []
    for index, name in enumerate(files, 1):
        with open(name, "rb") as handle:
            raw = handle.read()
        encoded = base64.b64encode(raw).decode("ascii")
        blob = _request(
            "POST", f"{repo_path}/git/blobs", token,
            {"content": encoded, "encoding": "base64"},
        )
        entries.append({"path": name, "mode": "100644", "type": "blob", "sha": blob["sha"]})
        print(f"  [{index}/{len(files)}] {name}")

    # 2) 建 tree（只含本次文件，因此旧 Java 工程文件会被自然移除）
    tree = _request(
        "POST", f"{repo_path}/git/trees", token,
        {"tree": entries},
    )

    # 3) 找父提交
    parents: list[str] = []
    try:
        ref = _request("GET", f"{repo_path}/git/ref/heads/{args.branch}", token)
        parents = [ref["object"]["sha"]]
        print(f"父提交：{parents[0]}")
    except ApiError as exc:
        if "-> 404" not in str(exc):
            raise
        print("远程分支不存在，将新建")

    # 4) 建提交
    commit_payload: dict = {"message": args.message, "tree": tree["sha"]}
    if parents:
        commit_payload["parents"] = parents
    commit = _request("POST", f"{repo_path}/git/commits", token, commit_payload)
    print(f"新提交：{commit['sha']}")

    # 5) 更新引用（force 覆盖）
    _request(
        "PATCH", f"{repo_path}/git/refs/heads/{args.branch}", token,
        {"sha": commit["sha"], "force": True},
    )
    print(f"已更新 refs/heads/{args.branch} -> {commit['sha']}")
    print(f"https://github.com/{args.owner}/{args.repo}/commit/{commit['sha']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
