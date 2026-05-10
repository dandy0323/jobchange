@echo off
chcp 65001 >nul
cd /d "%~dp0"
git fetch origin
git checkout origin/claude/company-research-skill-ZRmF0 -- output
echo.
echo output folder updated successfully.
pause
