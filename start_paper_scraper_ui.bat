@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" "paper_scraper_ui.py"
) else (
    python "paper_scraper_ui.py"
)

endlocal
