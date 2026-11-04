@echo off
chcp 65001 >nul
setlocal

REM ============================================================
REM  SkillForge 一键启动脚本（Windows）
REM  双击运行：先扫描技能，再启动 Web 看板，最后自动打开浏览器
REM ============================================================

cd /d "%~dp0"

REM 1. 检查 Python
where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.11 或更高版本
    echo        下载地址：https://www.python.org/downloads/
    pause
    exit /b 1
)

REM 2. 确认产物存在
if not exist "dist\sfx.pyz" (
    echo [提示] 未找到 dist\sfx.pyz，正在重新构建...
    python scripts\build.pyz.py
    if errorlevel 1 (
        echo [错误] 构建失败
        pause
        exit /b 1
    )
)

REM 3. 扫描技能入库
echo [1/2] 正在扫描本机技能目录...
python dist\sfx.pyz scan >nul 2>nul

REM 4. 启动 Web 看板
echo [2/2] 正在启动看板 http://127.0.0.1:7788/
echo.
echo 看板已启动，浏览器将自动打开。
echo 关闭此窗口即可停止服务。
echo.
start "" http://127.0.0.1:7788/
python dist\sfx.pyz serve

endlocal
