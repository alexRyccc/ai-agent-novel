# SkillForge 安装脚本（Windows / PowerShell 5.1+，系统自带，无需额外依赖）
#
# 用法：powershell -ExecutionPolicy Bypass -File scripts/install.ps1
#
# 三条硬约束（ARCH §2.3.4 / §10.1）：
#   1. 安装步骤 <= 2 条命令（本脚本 + sfx init 之类的一次跑通）
#   2. **绝不设置 PYTHONPATH** —— 实测本机 PYTHONPATH 会让裸启动从 64.3ms 放大到
#      423ms，是冷启动头号杀手。所以这里只做 PATH 追加，不碰任何 PYTHON* 变量。
#   3. 前置依赖只有 Python 3.11+；缺失时明确指引，不做静默失败。
#
# 卸载：scripts/uninstall.ps1（或直接删安装目录 + 数据目录）

[CmdletBinding()]
param(
    [string]$Source = (Join-Path $PSScriptRoot "..\dist\sfx.pyz"),
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA "Programs\sfx")
)

$ErrorActionPreference = "Stop"

function Write-Step([string]$Message) {
    Write-Host "[install] $Message"
}

function Find-Python {
    # 优先 py -3（Windows Python 启动器），回退 python / python3
    $candidates = @("py", "python", "python3")
    foreach ($name in $candidates) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if (-not $cmd) { continue }
        try {
            if ($name -eq "py") {
                $output = & py -3 -c "import sys;print(sys.version_info[:2] >= (3,11))" 2>$null
                $version = & py -3 -c "import sys;print('.'.join(map(str,sys.version_info[:3])))" 2>$null
            } else {
                $output = & $name -c "import sys;print(sys.version_info[:2] >= (3,11))" 2>$null
                $version = & $name -c "import sys;print('.'.join(map(str,sys.version_info[:3])))" 2>$null
            }
        } catch {
            continue
        }
        if ($output -eq "True") {
            return @{ Launcher = $name; Version = $version }
        }
        if ($version) {
            Write-Step "发现 Python $version，但版本低于 3.11，继续查找其它解释器..."
        }
    }
    return $null
}

# ---- 1. 检测 Python ----
$python = Find-Python
if (-not $python) {
    Write-Host "[install] 未找到 Python 3.11+。" -ForegroundColor Red
    Write-Host "          请从内网共享盘安装离线 Python 包，或访问 python.org 下载。"
    Write-Host "          安装时勾选 'Add python.exe to PATH'，然后重跑本脚本。"
    exit 5
}
Write-Step "Python $($python.Version)（启动器：$($python.Launcher)）"

# ---- 2. 拷贝 sfx.pyz ----
$sourceFull = (Resolve-Path -LiteralPath $Source -ErrorAction SilentlyContinue).Path
if (-not $sourceFull) {
    Write-Host "[install] 找不到产物：$Source" -ForegroundColor Red
    Write-Host "          请先运行：python scripts\build.pyz.py"
    exit 5
}
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
Copy-Item -LiteralPath $sourceFull -Destination (Join-Path $InstallDir "sfx.pyz") -Force
Write-Step "已安装到 $InstallDir\sfx.pyz"

# ---- 3. 写 sfx.cmd 包装（Windows 无 shebang 机制，必须包装）----
$launcher = $python.Launcher
if ($launcher -eq "py") {
    $launchLine = '@py -3 "%~dp0sfx.pyz" %*'
} else {
    $launchLine = "@`"$launcher`" `"%~dp0sfx.pyz`" %*"
}
$cmdPath = Join-Path $InstallDir "sfx.cmd"
Set-Content -LiteralPath $cmdPath -Value $launchLine -Encoding ASCII
Write-Step "已写入包装 $cmdPath"

# ---- 4. 追加到用户 PATH（不修改系统 PATH，不需要管理员）----
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($userPath -and ($userPath -split ";") -contains $InstallDir) {
    Write-Step "PATH 已包含 $InstallDir，跳过"
} else {
    $newPath = if ($userPath) { "$userPath;$InstallDir" } else { $InstallDir }
    [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
    Write-Step "已追加到用户 PATH（新开一个终端生效）"
}

Write-Host ""
Write-Host "安装完成。请新开一个终端，然后运行：" -ForegroundColor Green
Write-Host "    sfx doctor"
Write-Host ""
