#!/usr/bin/env bash
# SkillForge 安装脚本（Linux / macOS）
#
# 用法：bash scripts/install.sh
#
# 硬约束（ARCH §2.3.4 / §10.1）：
#   1. **绝不设置 PYTHONPATH** —— 实测会把裸启动从 64.3ms 放大到 423ms。
#      本脚本不 export 任何 PYTHON* 变量。
#   2. 前置依赖只有 Python 3.11+（zipapp 自带 shebang，可直接执行）。
#
# 卸载：rm -f ~/.local/bin/sfx && rm -rf "${XDG_DATA_HOME:-$HOME/.local/share}/sfx"

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE="${SCRIPT_DIR}/../dist/sfx.pyz"
BIN_DIR="${HOME}/.local/bin"

step() { printf '[install] %s\n' "$1"; }

# ---- 1. 检测 Python ----
PYTHON_BIN=""
for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
        if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info[:2] >= (3, 11) else 1)' >/dev/null 2>&1; then
            PYTHON_BIN="$candidate"
            break
        else
            step "发现 $candidate 但版本低于 3.11，继续查找..."
        fi
    fi
done
if [[ -z "$PYTHON_BIN" ]]; then
    printf '[install] 未找到 Python 3.11+。请先安装后重试。\n' >&2
    exit 5
fi
step "Python：$PYTHON_BIN $("$PYTHON_BIN" -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')"

if [[ ! -f "$SOURCE" ]]; then
    printf '[install] 找不到产物：%s\n' "$SOURCE" >&2
    printf '           请先运行：python3 scripts/build.pyz.py\n' >&2
    exit 5
fi

# ---- 2. 安装（zipapp 自带 shebang，拷过去即可执行）----
mkdir -p "$BIN_DIR"
install -m 0755 "$SOURCE" "${BIN_DIR}/sfx"
step "已安装到 ${BIN_DIR}/sfx"

# ---- 3. PATH 提示（不自动改 shell 配置，避免污染用户环境）----
case ":${PATH}:" in
    *":${BIN_DIR}:"*) step "PATH 已包含 ${BIN_DIR}" ;;
    *) step "请把下面一行加入你的 shell 配置（~/.bashrc 或 ~/.zshrc）："
       printf '    export PATH="%s:$PATH"\n' "$BIN_DIR" ;;
esac

printf '\n安装完成。重新加载 shell 后运行：\n    sfx doctor\n\n'
