@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

set PACKAGE_DIR=dist\paper-scraper-ui-windows
if not exist "dist" mkdir "dist"
if not exist "%PACKAGE_DIR%" mkdir "%PACKAGE_DIR%"

copy /Y "paper_scraper_ui.py" "%PACKAGE_DIR%\" >nul
copy /Y "start_paper_scraper_ui.bat" "%PACKAGE_DIR%\" >nul
copy /Y "sd_scraper.py" "%PACKAGE_DIR%\" >nul
copy /Y "windows_paths.py" "%PACKAGE_DIR%\" >nul
copy /Y "requirements.txt" "%PACKAGE_DIR%\" >nul
copy /Y "WINDOWS_UI_README.md" "%PACKAGE_DIR%\" >nul

echo Package created:
echo   %CD%\%PACKAGE_DIR%
echo.
echo On another Windows computer, create a venv and install requirements first:
echo   python -m venv .venv
echo   .venv\Scripts\python.exe -m pip install -r requirements.txt
echo   start_paper_scraper_ui.bat
endlocal
