@echo off
chcp 65001 >nul
cd /d "%~dp0"
git fetch origin
git checkout origin/claude/company-research-skill-ZRmF0 -- output
echo.
echo [1/2] GitHub sync complete.
xcopy /E /I /Y "output" "G:\マイドライブ\Claude\転職\output"
echo [2/2] Copied to Google Drive.
pause
