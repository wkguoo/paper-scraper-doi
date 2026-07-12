@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

set "PY_EXE=.venv\Scripts\python.exe"

if not exist "%PY_EXE%" (
    echo [初始化] 未检测到 .venv，正在创建本地 Python 环境...
    where python >nul 2>nul
    if errorlevel 1 (
        echo [错误] 找不到 Python。请先安装 Python 3.11 或更新 PATH。
        pause
        exit /b 1
    )
    python -m venv .venv
    if errorlevel 1 goto install_failed
)

"%PY_EXE%" -c "import curl_cffi, browser_cookie3, openpyxl, websocket" >nul 2>nul
if errorlevel 1 (
    echo [初始化] 正在安装或修复依赖，请稍候...
    "%PY_EXE%" -m pip install --upgrade pip
    if errorlevel 1 goto install_failed
    "%PY_EXE%" -m pip install -r requirements.txt
    if errorlevel 1 goto install_failed
)

echo.
echo [提示] 默认入口：UI「统一批次（推荐）」= paper_batch.py
echo [提示] 其它页签与 sd_scraper / paper_skill 仅为兼容路径。
echo.
"%PY_EXE%" "paper_scraper_ui.py"
if errorlevel 1 (
    echo.
    echo [错误] 图形界面异常退出。请把上方错误信息发给维护者排查。
    pause
    exit /b 1
)

endlocal
exit /b 0

:install_failed
echo.
echo [错误] 环境初始化或依赖安装失败。请检查网络、Python 安装和 requirements.txt。
pause
exit /b 1
