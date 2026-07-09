@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"

set "PACKAGE_DIR=dist\paper-scraper-ui-windows"
if not exist "dist" mkdir "dist" || exit /b 1
if exist "%PACKAGE_DIR%" (
    rmdir /S /Q "%PACKAGE_DIR%"
    if exist "%PACKAGE_DIR%" (
        echo [ERROR] Failed to remove stale package directory: %PACKAGE_DIR%
        exit /b 1
    )
)
mkdir "%PACKAGE_DIR%" || exit /b 1

call :copy_required "paper_scraper_ui.py" "%PACKAGE_DIR%\" || exit /b 1
call :copy_required "start_paper_scraper_ui.bat" "%PACKAGE_DIR%\" || exit /b 1
call :copy_required "sd_scraper.py" "%PACKAGE_DIR%\" || exit /b 1
call :copy_required "sd_scraper_en.py" "%PACKAGE_DIR%\" || exit /b 1
call :copy_required "sd_supplements.py" "%PACKAGE_DIR%\" || exit /b 1
call :copy_required "sd_institutional_skill.py" "%PACKAGE_DIR%\" || exit /b 1
call :copy_required "student_handoff.py" "%PACKAGE_DIR%\" || exit /b 1
call :copy_required "paper_skill.py" "%PACKAGE_DIR%\" || exit /b 1
call :copy_required "doi_batch_utils.py" "%PACKAGE_DIR%\" || exit /b 1
call :copy_required "windows_paths.py" "%PACKAGE_DIR%\" || exit /b 1
call :copy_required "requirements.txt" "%PACKAGE_DIR%\" || exit /b 1
call :copy_required "LICENSE" "%PACKAGE_DIR%\" || exit /b 1
call :copy_required "NOTICE" "%PACKAGE_DIR%\" || exit /b 1
call :copy_required "README.md" "%PACKAGE_DIR%\" || exit /b 1
call :copy_required "README_zh.md" "%PACKAGE_DIR%\" || exit /b 1
call :copy_required "WINDOWS_UI_README.md" "%PACKAGE_DIR%\" || exit /b 1
call :copy_required "MANUAL_QA.md" "%PACKAGE_DIR%\" || exit /b 1
call :copy_required "install_codex_skills.ps1" "%PACKAGE_DIR%\" || exit /b 1
call :copy_optional "如何导出机构Cookie.md" "%PACKAGE_DIR%\" || exit /b 1

call :robocopy_required "paper_automation" "%PACKAGE_DIR%\paper_automation" || exit /b 1
if not exist "%PACKAGE_DIR%\docs" mkdir "%PACKAGE_DIR%\docs" || exit /b 1
call :copy_required "docs\sciencedirect_skill_beginner_guide.md" "%PACKAGE_DIR%\docs\" || exit /b 1
call :robocopy_required "skills" "%PACKAGE_DIR%\skills" || exit /b 1
call :verify_required "%PACKAGE_DIR%\sd_supplements.py" || exit /b 1
call :verify_required "%PACKAGE_DIR%\skills\sciencedirect-doi-download\references" || exit /b 1
call :verify_required "%PACKAGE_DIR%\skills\sciencedirect-doi-download\references\beginner-workflow.md" || exit /b 1
call :verify_required "%PACKAGE_DIR%\skills\sciencedirect-doi-download\references\failure-reasons.md" || exit /b 1

echo Package created:
echo   %CD%\%PACKAGE_DIR%
echo.
echo On another Windows computer, create a venv and install requirements first:
echo   python -m venv .venv
echo   .venv\Scripts\python.exe -m pip install -r requirements.txt
echo   start_paper_scraper_ui.bat
echo.
echo Optional Codex skill install:
echo   powershell -ExecutionPolicy Bypass -File install_codex_skills.ps1
endlocal & exit /b 0

:copy_required
if not exist "%~1" (
    echo [ERROR] Missing required file: %~1
    exit /b 1
)
copy /Y "%~1" "%~2" >nul
if errorlevel 1 (
    echo [ERROR] Failed to copy required file: %~1
    exit /b 1
)
exit /b 0

:copy_optional
if not exist "%~1" exit /b 0
copy /Y "%~1" "%~2" >nul
if errorlevel 1 (
    echo [ERROR] Failed to copy optional file: %~1
    exit /b 1
)
exit /b 0

:robocopy_required
if not exist "%~1" (
    echo [ERROR] Missing required directory: %~1
    exit /b 1
)
robocopy "%~1" "%~2" /E /XD "__pycache__" /XF "*.pyc" >nul
set "ROBOCOPY_EXIT=%ERRORLEVEL%"
if %ROBOCOPY_EXIT% GEQ 8 (
    echo [ERROR] Robocopy failed for required directory: %~1
    exit /b %ROBOCOPY_EXIT%
)
exit /b 0

:verify_required
if not exist "%~1" (
    echo [ERROR] Missing packaged required path: %~1
    exit /b 1
)
exit /b 0
