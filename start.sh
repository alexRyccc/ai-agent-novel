#!/usr/bin/env bash
# ============================================================
#  SkillForge 一键启动脚本（Linux / macOS）
#  用法：./start.sh
# ============================================================
set -euo pipefail

cd "$(dirname "$0")"

# 1. 检查 Python
if ! command -v python3 >/dev/null 2>&1; then
    echo "[错误] 未找到 python3，请先安装 Python 3.11 或更高版本"
    exit 1
fi

# 2. 确认产物存在
if [ ! -f "dist/sfx.pyz" ]; then
    echo "[提示] 未找到 dist/sfx.pyz，正在重新构建..."
    python3 scripts/build.pyz.py
fi

# 3. 扫描技能入库
echo "[1/2] 正在扫描本机技能目录..."
python3 dist/sfx.pyz scan >/dev/null 2>&1 || true

# 4. 启动 Web 看板
echo "[2/2] 正在启动看板 http://127.0.0.1:7788/"
echo "关闭（Ctrl+C）即可停止服务。"
python3 dist/sfx.pyz serve
